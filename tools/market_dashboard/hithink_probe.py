"""Bounded read-only Hithink capability probe; emits aggregate evidence only.

The initial full run estimate includes one membership per sector, index history,
index snapshots and the measured shared stock snapshot pages. It excludes later
recurring runs. Under the 2026-11-16 user decision Hithink has no economic
quota gate; point metadata is informational only.
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, time
import json
import math
import os
from pathlib import Path
import subprocess
import time as clock

from tools.market_dashboard.hithink_cli import (
    HithinkClient, HithinkError, SHANGHAI, canonical_date, finite_number, _json_object,
)
from tools.market_dashboard.hithink_store import _private_directory, _private_file


# CLI 0.2.4: three outer nonbatch attempts plus one shared OAuth data
# recovery. Reserve four even for batch commands (a safe overestimate).
CLI_ATTEMPTS_PER_SLICE = 4
CLI_WINDOW_MS = 315576000000  # floor(10 * 365.25 days), inclusive slices


class ProbeStopped(HithinkError):
    pass


@dataclass
class ProbeBudget:
    max_calls: int = 50
    max_elapsed_seconds: float = 120
    min_call_interval: float = 0
    started_at: float = field(default_factory=lambda: clock.monotonic(), init=False)
    last_call_at: float | None = field(default=None, init=False)
    max_remote_attempts: int = 50
    attempts_per_slice: int = CLI_ATTEMPTS_PER_SLICE
    reserved_attempts: int = field(default=0, init=False)
    calls: int = field(default=0, init=False)
    points: float = field(default=0, init=False)
    metered_calls: int = field(default=0, init=False)
    largest_charge: float = field(default=0, init=False)

    def __post_init__(self):
        if (type(self.max_remote_attempts) is not int or not 1 <= self.max_remote_attempts <= 50
                or type(self.attempts_per_slice) is not int or self.attempts_per_slice not in (1, 4)
                or type(self.max_calls) is not int or not 1 <= self.max_calls <= 50
                or not isinstance(self.max_elapsed_seconds, (int, float))
                or not math.isfinite(self.max_elapsed_seconds) or self.max_elapsed_seconds <= 0
                or not isinstance(self.min_call_interval, (int, float))
                or not math.isfinite(self.min_call_interval) or self.min_call_interval < 0):
            raise ValueError('INVALID_PROBE_BUDGET')

    def before_call(self, *, remote_attempts=None):
        remote_attempts = self.attempts_per_slice if remote_attempts is None else remote_attempts
        if type(remote_attempts) is not int or remote_attempts < 1:
            raise ValueError('INVALID_PROBE_BUDGET')
        if self.calls >= self.max_calls:
            raise ProbeStopped('PROBE_CALL_BUDGET')
        if self.reserved_attempts + remote_attempts > self.max_remote_attempts:
            raise ProbeStopped('PROBE_REMOTE_ATTEMPT_BUDGET')
        now = clock.monotonic()
        if now - self.started_at >= self.max_elapsed_seconds:
            raise ProbeStopped('PROBE_TIME_BUDGET')
        delay = (max(0, self.min_call_interval - (now - self.last_call_at))
                 if self.last_call_at is not None else 0)
        if now + delay - self.started_at >= self.max_elapsed_seconds:
            raise ProbeStopped('PROBE_TIME_BUDGET')
        if delay:
            clock.sleep(delay)
        self.last_call_at = clock.monotonic()
        self.calls += 1
        self.reserved_attempts += remote_attempts

    def record_points(self, points):
        if points is None:
            return
        try:
            points = finite_number(points, nonnegative=True)
        except HithinkError:
            raise ProbeStopped('INVALID_POINT_METADATA') from None
        self.points += points
        self.metered_calls += 1
        self.largest_charge = max(self.largest_charge, points)


@dataclass(frozen=True)
class CostEstimate:
    calls: int | None
    points: float | None
    history_calls: int | None
    elapsed_seconds: float | None


@dataclass
class ProbeReport:
    budget: ProbeBudget
    industry_count: int = 0
    concept_count: int = 0
    industry_sample: int = 0
    concept_sample: int = 0
    history_sectors: int = 0
    history_20: int = 0
    history_60: int = 0
    history_250: int = 0
    index_snapshots: int = 0
    stocks: int = 0
    stock_total: int = 0
    stock_pages: int = 0
    batch_supported: bool = False
    batch_status: str = 'NOT_TESTED'
    authorization_status: str = 'unknown'
    public_eligible: bool = False
    elapsed: float = 0
    error: str | None = None
    complete: bool = False

    def safe_summary(self):
        estimate = estimate_full_run(self)
        return {
            'schemaVersion': 'hithink-sector-probe-v1',
            'actualCalls': self.budget.calls,
            'logicalCallLimit': self.budget.max_calls,
            'remoteDataAttemptUpperBound': self.budget.reserved_attempts,
            'actualRemoteDataAttempts': None,
            'remoteAttemptLimit': self.budget.max_remote_attempts,
            'attemptsPerSlice': self.budget.attempts_per_slice,
            'reportedPoints': self.budget.points,
            'pointsKnown': self.budget.calls > 0 and self.budget.metered_calls == self.budget.calls,
            'meteredCalls': self.budget.metered_calls,
            'elapsedSeconds': round(self.elapsed, 3),
            'coverage': {
                'industryUniverse': self.industry_count, 'conceptUniverse': self.concept_count,
                'industrySample': self.industry_sample, 'conceptSample': self.concept_sample,
                'historySectors': self.history_sectors, 'historyAtLeast20': self.history_20,
                'historyAtLeast60': self.history_60, 'historyAtLeast250': self.history_250,
                'indexSnapshots': self.index_snapshots, 'stockSnapshots': self.stocks,
                'stockTotal': self.stock_total,
            },
            'stockSnapshotPages': self.stock_pages,
            'historyBatchSupported': self.batch_supported,
            'historyBatchStatus': self.batch_status,
            'estimatedCalls': estimate.calls, 'estimatedHistoryCalls': estimate.history_calls,
            'estimatedPoints': estimate.points,
            'estimatedElapsedSeconds': estimate.elapsed_seconds,
            'estimateScope': 'initial_history_memberships_and_shared_snapshots',
            'authorizationStatus': self.authorization_status,
            'publicReleaseEligible': self.public_eligible,
            'complete': self.complete, 'safeErrorCode': self.error,
            'economicGateApplied': False,
            'continuationScope': 'private_implementation',
            'requiresCapabilityValidation': not self.complete,
            # Operational probe exhaustion is a partial finding, not an
            # economic veto on later private implementation. Data failures
            # still fail closed; incomplete capabilities remain explicit.
            'continueAutomatically': bool(
                self.industry_count == 90 and self.concept_count >= 20 and self.history_sectors > 0
                and self.error in (None, 'PROBE_CALL_BUDGET', 'PROBE_REMOTE_ATTEMPT_BUDGET', 'PROBE_TIME_BUDGET')),

        }


def estimate_full_run(report) -> CostEstimate:
    total = report.industry_count + report.concept_count
    if not total or not report.history_sectors:
        return CostEstimate(None, None, None, None)
    # A one-code batch does not prove multi-code batching. Even a successful
    # batch probe conservatively estimates single-index history until validated.
    history_calls = total
    calls = 2 + history_calls + total + 1 + report.stock_pages
    points = (round(calls * report.budget.largest_charge, 6)
              if report.budget.calls and report.budget.metered_calls == report.budget.calls else None)
    elapsed = round(calls * report.elapsed / report.budget.calls, 3) if report.budget.calls else None
    return CostEstimate(calls, points, history_calls, elapsed)


def _validate_config(config):
    try:
        p = config['probe']
        if (config['timezone'] != 'Asia/Shanghai' or config['publishEnabled'] is not False
                or config['economicPolicy'] != 'hithink_fee_unrestricted_user_2026-11-16'
                or (p['maxCalls'], p['industrySample'], p['conceptSample'],
                    p['expectedIndustries'], p['stockPageSize']) != (50, 10, 20, 90, 1000)
                or (p['maxRemoteAttempts'], p['remoteAttemptsPerSlice'], p['liveMaxLogicalCalls']) != (50, 4, 12)
                or p['maxElapsedSeconds'] != 120 or p['minCallIntervalSeconds'] != 0.25):
            raise ValueError()
        start, end = canonical_date(p['startDate']), canonical_date(p['endDate'])
        if start > end or end >= datetime.now(SHANGHAI).date():
            raise ValueError()
        auth = config['authorization']
        if auth['status'] not in ('unknown', 'pending', 'denied', 'verified'):
            raise ValueError()
        return p, auth, int(datetime.combine(start, time.min, SHANGHAI).timestamp()*1000), int(datetime.combine(end, time.max, SHANGHAI).timestamp()*1000)
    except (KeyError, TypeError, ValueError):
        raise HithinkError('INVALID_PROBE_CONFIG') from None


def _attempt_reservation(argv, attempts_per_slice):
    command = tuple(argv[1:3])
    if command not in {('index', 'catalog'), ('index', 'history'),
                        ('index', 'history-batch'), ('index', 'snapshot'),
                        ('market', 'snapshot')}:
        raise ProbeStopped('UNSUPPORTED_PROBE_COMMAND')
    slices = 1
    if command == ('index', 'history'):
        try:
            start = int(argv[argv.index('--start-ms') + 1])
            end = int(argv[argv.index('--end-ms') + 1])
            if start < 0 or end < start:
                raise ValueError()
        except (ValueError, IndexError, TypeError):
            raise ProbeStopped('INVALID_PROBE_HISTORY_WINDOW') from None
        # Mirror the CLI's inclusive ten-year slicing conservatively even for
        # index.history, whose current five-year capability does not split.
        # Reserve all slices before the opaque subprocess can dispatch any.
        slices = (end - start) // (CLI_WINDOW_MS + 1) + 1
    return slices * attempts_per_slice


def _metered_runner(runner, budget):
    def invoke(argv):
        budget.before_call(remote_attempts=_attempt_reservation(argv, budget.attempts_per_slice))
        response = runner(argv)
        try:
            raw = json.loads(response.stdout, object_pairs_hook=_json_object)
        except (ValueError, TypeError, UnicodeError):
            budget.record_points(None)
            return response  # strict client emits the safe schema error
        meta = raw.get('meta') if isinstance(raw, dict) else None
        points = meta.pop('points', None) if isinstance(meta, dict) else None
        budget.record_points(points)
        # Usage is consumed by the budget, not silently allowed by Task 1's
        # strict schema. Provider data and other metadata remain untouched.
        return subprocess.CompletedProcess(argv, response.returncode,
                                           json.dumps(raw), '')
    return invoke


def _stock_pages(client, report, page_size):
    seen, offset, total = set(), 0, None
    while True:
        data = client._call('market', 'snapshot', ['--limit', str(page_size), '--offset', str(offset)],
                            ('item', 'timestamp', 'total'))
        report.stock_pages += 1
        observed_total = data['total']
        if (type(observed_total) is not int or observed_total <= 0
                or (total is not None and total != observed_total)
                or len(data['item']) > page_size or not data['item']):
            raise HithinkError()
        total = observed_total
        report.stock_total = total
        if offset == 0 and len(data['item']) <= 100 and total > len(data['item']):
            raise ProbeStopped('SNAPSHOT_100_ROW_PAGING_REJECTED')
        codes = [row.get('thscode') for row in data['item'] if isinstance(row, dict)]
        # Reuse Task 1's strict stock row and envelope normalization offline.
        envelope = {'ok': True, 'command': 'market.snapshot', 'meta': {
            'source': 'remote', 'count': len(data['item']), 'truncated': False, 'schema_version': '1'},
            'data': dict(data, total=len(codes))}
        normalizer = HithinkClient(client.cli_path, runner=lambda argv:
            subprocess.CompletedProcess(argv, 0, json.dumps(envelope), ''))
        rows = normalizer.stock_snapshots(codes)
        if seen.intersection(codes) or offset + len(rows) > total:
            raise HithinkError()
        seen.update(codes)
        report.stocks = len(seen)
        if len(seen) == total:
            return
        if len(rows) < page_size:
            raise HithinkError()
        offset += len(rows)


def run_probe(client, config, budget) -> ProbeReport:
    p, auth, start, end = _validate_config(config)
    report = ProbeReport(budget, authorization_status=auth['status'], public_eligible=bool(
        auth['status'] == 'verified' and auth.get('localNormalizedFeatures') is True
        and auth.get('publicDerivedScores') is True and isinstance(auth.get('evidenceReference'), str)
        and auth['evidenceReference'].strip()))
    original = client.runner
    client.runner = _metered_runner(original, budget)
    started = clock.monotonic()
    try:
        industries = [r for r in client.catalog('industry') if r.code.startswith('881') and r.code.endswith('.TI')]
        concepts = [r for r in client.catalog('cn_concept') if r.code.endswith('.TI')]
        report.industry_count, report.concept_count = len(industries), len(concepts)
        if len(industries) != 90 or len(concepts) < 20:
            raise ProbeStopped('UNIVERSE_COUNT_REJECTED')
        industries = sorted(industries, key=lambda row: row.code)[:10]
        concepts = sorted(concepts, key=lambda row: row.code)[:20]
        sample = industries + concepts
        for definition in sample:
            rows = client.index_history(definition.code, start, end)
            if definition.tag == 'industry':
                report.industry_sample += 1
            else:
                report.concept_sample += 1
            report.history_sectors += bool(rows)
            report.history_20 += len(rows) >= 20
            report.history_60 += len(rows) >= 60
            report.history_250 += len(rows) >= 250
        try:
            batch = client.index_history_batch([sample[0].code], start, end)
            report.batch_supported = bool(batch)
            report.batch_status = 'SUPPORTED_SINGLE_CODE_ONLY' if batch else 'EMPTY'
        except HithinkError as error:
            if error.code != 'HISTORY_BATCH_INCOMPLETE':
                raise
            report.batch_status = error.code
        report.index_snapshots = len(client.index_snapshots([r.code for r in sample]))
        _stock_pages(client, report, p['stockPageSize'])
        report.complete = report.history_20 == 30 and report.index_snapshots == 30 and report.stocks == report.stock_total
        if not report.complete:
            report.error = 'PROBE_COVERAGE_INCOMPLETE'
    except (HithinkError, OSError, subprocess.SubprocessError, TimeoutError, UnicodeError) as error:
        report.error = error.code if isinstance(error, HithinkError) else 'HITHINK_COMMAND_FAILED'
    finally:
        client.runner = original
        report.elapsed = clock.monotonic() - started
    return report


def save_report(state_root, report):
    directory = _private_directory(Path(state_root) / 'market-dashboard-hithink-probe')
    path = directory / 'report.json'
    fd = _private_file(path)
    with os.fdopen(fd, 'w') as output:
        os.ftruncate(output.fileno(), 0)
        json.dump(report.safe_summary(), output, allow_nan=False, separators=(',', ':'))
        output.write('\n')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(prog='hithink_probe', description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('config/hithink-sector-dashboard.json'))
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--max-calls', type=int, choices=range(1, 13), default=12,
                        help='live logical calls; reserves up to four data attempts per history slice')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        report = run_probe(HithinkClient(args.cli), config, ProbeBudget(max_calls=args.max_calls,
            max_remote_attempts=config['probe']['maxRemoteAttempts'],
            attempts_per_slice=config['probe']['remoteAttemptsPerSlice'],
            max_elapsed_seconds=config['probe']['maxElapsedSeconds'],
            min_call_interval=config['probe']['minCallIntervalSeconds']))
        save_report(args.state_root, report)
        print(json.dumps(report.safe_summary(), allow_nan=False, separators=(',', ':')))
        return 0 if report.complete else 1
    except (ValueError, OSError, subprocess.SubprocessError):
        print(json.dumps({'schemaVersion': 'hithink-sector-probe-v1', 'continueAutomatically': False,
                          'publicReleaseEligible': False, 'safeErrorCode': 'PROBE_FAILED'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
