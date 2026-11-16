"""Private, resumable Hithink index history ingestion; no scores or publication.

Single-index requests are the default until batch capability has been verified.
All real CLI requests (including adapter fallback requests) are budgeted by the
runner. The budget is operational, independent of Hithink's fee-free policy.
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, time
import hashlib
import json
from pathlib import Path
import subprocess
import sqlite3
import time as clock

from .hithink_cli import HithinkClient, HithinkError, SHANGHAI, canonical_date
from .hithink_probe import ProbeBudget, ProbeStopped, _metered_runner
from .hithink_store import (open_store, migrate_store, store_write_lock, replace_catalog,
    commit_index_backfill, record_ingest_run, _private_directory, _private_file)
from .hithink_universe import build_universe, load_catalog_fixture


@dataclass
class BackfillBudget(ProbeBudget):
    max_calls: int = 10000
    max_remote_attempts: int = 40000
    max_elapsed_seconds: float = 7200
    min_call_interval: float = 0.25

    def __post_init__(self):
        # Reuse the tested probe dispatch accounting, relaxing only its initial
        # probe-specific 50-attempt envelope for the authorized full backfill.
        import math
        if (type(self.max_calls) is not int or not 1 <= self.max_calls <= 10000
                or type(self.max_remote_attempts) is not int or not 1 <= self.max_remote_attempts <= 40000
                or self.attempts_per_slice not in (1, 4)
                or any(type(v) not in (int, float) or not math.isfinite(v) or v < 0
                       for v in (self.max_elapsed_seconds, self.min_call_interval))
                or self.max_elapsed_seconds <= 0):
            raise ValueError('INVALID_BACKFILL_BUDGET')

    def before_call(self, **kwargs):
        try:
            return super().before_call(**kwargs)
        except ProbeStopped as error:
            raise ProbeStopped(error.code.replace('PROBE_', 'BACKFILL_')) from None


@dataclass(frozen=True)
class HistoryWindow:
    start: str
    end: str

    def __post_init__(self):
        start, end = canonical_date(self.start), canonical_date(self.end)
        if start > end or end >= datetime.now(SHANGHAI).date():
            raise ValueError('INVALID_BACKFILL_WINDOW')

    @property
    def start_ms(self):
        return int(datetime.combine(canonical_date(self.start), time.min, SHANGHAI).timestamp()*1000)

    @property
    def end_ms(self):
        return int(datetime.combine(canonical_date(self.end), time.max, SHANGHAI).timestamp()*1000)


@dataclass
class BackfillReport:
    coverage: list = field(default_factory=list)
    calls: int = 0
    reserved_attempts: int = 0
    elapsed: float = 0
    safe_error_code: str | None = None
    batch_status: str = 'SINGLE_INDEX_DEFAULT'
    complete: bool = False

    def safe_summary(self):
        rows = self.coverage
        return {'schemaVersion': 'hithink-index-backfill-v1', 'complete': self.complete,
            'actualCalls': self.calls, 'remoteDataAttemptUpperBound': self.reserved_attempts,
            'elapsedSeconds': round(self.elapsed, 3), 'safeErrorCode': self.safe_error_code,
            'historyBatchStatus': self.batch_status, 'economicGateApplied': False,
            'publicReleaseEligible': False, 'coverage': {
                'industryUniverse': sum(r['tag'] == 'industry' for r in rows),
                'conceptUniverse': sum(r['tag'] == 'cn_concept' for r in rows),
                'successfulSectors': sum(r['status'] == 'complete' for r in rows),
                **{f'historyAtLeast{n}': sum(r[f'coverage{n}'] for r in rows) for n in (20, 60, 250)}},
            'sectors': rows}


def _checkpoint_id(universe, window, code):
    digest = hashlib.sha256(f'{universe.version}|{universe.catalog_digest}|{window.start}|{window.end}|{code}'.encode()).hexdigest()
    return 'index-backfill:' + digest


def _coverage(store, sector, window, checkpoint):
    row = store.execute('SELECT count(*),min(market_date),max(market_date) FROM sector_index_daily '
                        'WHERE sector_id=? AND market_date BETWEEN ? AND ?',
                        (sector.code, window.start, window.end)).fetchone()
    run = store.execute('SELECT coverage,safe_error_code FROM ingest_runs WHERE run_id=?', (checkpoint,)).fetchone()
    complete = bool(run and run['coverage'] == 1 and run['safe_error_code'] is None)
    return {'code': sector.code, 'tag': sector.tag, 'rows': row[0], 'firstDate': row[1], 'lastDate': row[2],
        'status': 'complete' if complete else ('failed' if run else 'pending'),
        'safeErrorCode': run['safe_error_code'] if run else None,
        **{f'coverage{n}': row[0] >= n for n in (20, 60, 250)}}


def backfill_index_history(client, store, universe, window, budget, *, state_root=None,
                           batch_validated=False, should_yield=None, progress=None):
    """Resume exact catalog/window checkpoints; release shared lock per 250 rows.

    ``should_yield`` lets the live producer preempt at dispatch/chunk boundaries.
    Remote work never holds the writer lock. STORE_BUSY leaves work resumable.
    """
    if state_root is None:
        state_root = Path(store.execute('PRAGMA database_list').fetchone()[2]).parent
    state_root = Path(state_root)
    sectors = tuple(universe.industries) + tuple(universe.concepts)
    report = BackfillReport()
    began = clock.monotonic()
    calls_before = budget.calls
    attempts_before = budget.reserved_attempts
    original = getattr(client, 'runner', None)
    if original is not None:
        client.runner = _metered_runner(original, budget)
    def request(method, *args):
        if original is None:
            budget.before_call()
        return method(*args)
    def yield_if_needed():
        if should_yield and should_yield():
            raise ProbeStopped('BACKFILL_YIELDED')
    try:
        with store_write_lock(state_root):
            replace_catalog(store, sectors, catalog_version=universe.version,
                            observed_at_ms=int(clock.time()*1000))
        for sector in sectors:
            checkpoint = _checkpoint_id(universe, window, sector.code)
            existing = _coverage(store, sector, window, checkpoint)
            if existing['status'] == 'complete':
                continue
            yield_if_needed()
            started = int(clock.time()*1000)
            count_before = budget.calls
            try:
                if batch_validated:
                    try:
                        rows = request(client.index_history_batch, [sector.code], window.start_ms, window.end_ms)
                    except HithinkError as error:
                        if error.code != 'HISTORY_BATCH_INCOMPLETE':
                            raise
                        report.batch_status = error.code
                        batch_validated = False
                        rows = request(client.index_history, sector.code, window.start_ms, window.end_ms)
                else:
                    rows = request(client.index_history, sector.code, window.start_ms, window.end_ms)
                if not rows:
                    raise HithinkError('HISTORY_EMPTY')
                # The strict adapter guarantees dates/identity; retain checks at
                # this boundary for injectable clients and prevent foreign rows.
                if any(r.code != sector.code or not window.start <= r.date <= window.end for r in rows):
                    raise HithinkError('INVALID_HISTORY_ROWS')
                for offset in range(0, len(rows), 250):
                    yield_if_needed()
                    with store_write_lock(state_root):
                        commit_index_backfill(store, rows[offset:offset+250],
                            run_id=checkpoint if offset+250 >= len(rows) else None,
                            started_at_ms=started, finished_at_ms=int(clock.time()*1000),
                            request_count=budget.calls-count_before, catalog_version=universe.version)
            except ProbeStopped:
                raise
            except HithinkError as error:
                with store_write_lock(state_root):
                    record_ingest_run(store, run_id=checkpoint, started_at_ms=started,
                        finished_at_ms=int(clock.time()*1000), request_count=budget.calls-count_before,
                        coverage=0, safe_error_code=error.code)
            if progress:
                progress(_coverage(store, sector, window, checkpoint))
    except ProbeStopped as error:
        report.safe_error_code = error.code
    except RuntimeError as error:
        if str(error) != 'STORE_BUSY':
            raise
        report.safe_error_code = 'STORE_BUSY'
    finally:
        if original is not None:
            client.runner = original
        report.calls = budget.calls-calls_before
        report.reserved_attempts = budget.reserved_attempts-attempts_before
        report.elapsed = clock.monotonic()-began
        report.coverage = [_coverage(store, sector, window, _checkpoint_id(universe, window, sector.code)) for sector in sectors]
        report.complete = bool(report.coverage) and all(r['status'] == 'complete' for r in report.coverage)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--store', type=Path, default=Path('data/market-dashboard/sector-history.sqlite3'))
    parser.add_argument('--state-root', type=Path)
    parser.add_argument('--config', type=Path, default=Path('config/hithink-sector-dashboard.json'))
    parser.add_argument('--start-date')
    parser.add_argument('--end-date')
    parser.add_argument('--max-calls', type=int, default=10000)
    parser.add_argument('--max-elapsed-seconds', type=float, default=7200)
    parser.add_argument('--min-call-interval', type=float, default=0.25)
    args = parser.parse_args(argv)
    store = None
    try:
        config = json.loads(args.config.read_text())
        if config['economicPolicy'] != 'hithink_fee_unrestricted_user_2026-11-16' or config['publishEnabled'] is not False:
            raise ValueError('INVALID_PRIVATE_BACKFILL_CONFIG')
        window = HistoryWindow(args.start_date or config['probe']['startDate'], args.end_date or config['probe']['endDate'])
        budget = BackfillBudget(max_calls=args.max_calls, max_elapsed_seconds=args.max_elapsed_seconds,
                                min_call_interval=args.min_call_interval)
        fixtures = Path(__file__).parent / 'fixtures' / 'hithink'
        universe = build_universe(load_catalog_fixture(fixtures/'catalog-industry.json'),
            load_catalog_fixture(fixtures/'catalog-concept.json'), json.loads(Path('config/hithink-core-concepts.json').read_text()))
        root = args.state_root or args.store.parent
        with store_write_lock(root):
            store = open_store(args.store)
            migrate_store(store)
        report = backfill_index_history(HithinkClient(args.cli), store, universe, window, budget, state_root=root,
            should_yield=lambda: (root/'hithink-live-priority').exists())
        directory = _private_directory(root/'hithink-index-backfill')
        import os
        with os.fdopen(_private_file(directory/'report.json'), 'w') as output:
            output.truncate(0)
            json.dump(report.safe_summary(), output, allow_nan=False)
            output.write('\n')
        print(json.dumps(report.safe_summary(), allow_nan=False))
        return 0 if report.complete else 1
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error, HithinkError, subprocess.SubprocessError):
        print(json.dumps({'schemaVersion': 'hithink-index-backfill-v1', 'complete': False,
                          'publicReleaseEligible': False, 'safeErrorCode': 'BACKFILL_FAILED'}))
        return 1
    finally:
        if store is not None:
            store.close()


if __name__ == '__main__':
    raise SystemExit(main())
