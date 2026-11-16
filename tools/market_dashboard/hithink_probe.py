"""Bounded read-only Hithink capability probe; emits aggregate evidence only.

The initial full run estimate includes one membership per sector, index history,
index snapshots and the measured shared stock snapshot pages. It excludes later
recurring runs. Missing usage metadata is unknown, never zero-cost evidence.
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


class ProbeStopped(HithinkError):
    pass


@dataclass
class ProbeBudget:
    max_calls: int = 50
    max_points: float = 100
    calls: int = field(default=0, init=False)
    points: float = field(default=0, init=False)
    metered_calls: int = field(default=0, init=False)
    largest_charge: float = field(default=0, init=False)

    def __post_init__(self):
        if (type(self.max_calls) is not int or not 1 <= self.max_calls <= 50
                or isinstance(self.max_points, bool)
                or not isinstance(self.max_points, (int, float))
                or not math.isfinite(self.max_points) or not 0 < self.max_points <= 100):
            raise ValueError('INVALID_PROBE_BUDGET')

    def before_call(self):
        if self.calls >= self.max_calls:
            raise ProbeStopped('PROBE_CALL_BUDGET')
        # Reported usage is post-response; reserve at least the largest observed
        # charge. A provider-side tariff ceiling is not available from this CLI.
        if self.points >= self.max_points or (self.largest_charge and
                self.points + self.largest_charge > self.max_points):
            raise ProbeStopped('PROBE_POINT_BUDGET')
        self.calls += 1

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
        if self.points > self.max_points:
            raise ProbeStopped('PROBE_POINT_BUDGET')


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
            'remoteDataAttemptUpperBound': self.budget.calls * 2,
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
            'continueAutomatically': bool(self.complete and not self.error and
                estimate.calls is not None and estimate.calls <= 500 and
                estimate.points is not None and estimate.points <= 100),
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
                or (p['maxCalls'], p['maxPoints'], p['industrySample'], p['conceptSample'],
                    p['expectedIndustries'], p['stockPageSize'], p['fullRunMaxCalls'], p['fullRunMaxPoints'])
                != (50, 100, 10, 20, 90, 1000, 500, 100)):
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


def _metered_runner(runner, budget):
    def invoke(argv):
        budget.before_call()
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
        json.dump(report.safe_summary(), output, allow_nan=False, separators=(',', ':'))
        output.write('\n')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(prog='hithink_probe', description=__doc__)
    parser.add_argument('--cli', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=Path('config/hithink-sector-dashboard.json'))
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--max-calls', type=int, choices=range(1, 26), default=25,
                        help='live logical data calls; reserves one hidden OAuth retry per call')
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text())
        report = run_probe(HithinkClient(args.cli), config, ProbeBudget(max_calls=args.max_calls))
        save_report(args.state_root, report)
        print(json.dumps(report.safe_summary(), allow_nan=False, separators=(',', ':')))
        return 0 if report.complete else 1
    except (ValueError, OSError, subprocess.SubprocessError):
        print(json.dumps({'schemaVersion': 'hithink-sector-probe-v1', 'continueAutomatically': False,
                          'publicReleaseEligible': False, 'safeErrorCode': 'PROBE_FAILED'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
