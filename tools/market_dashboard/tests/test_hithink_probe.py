"""Probe tests use real strict normalization with an offline provider boundary."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from tools.market_dashboard import hithink_probe as probe
from tools.market_dashboard.hithink_cli import HithinkClient

FIXTURES = json.loads((Path(__file__).parents[1] / 'fixtures/hithink/responses.json').read_text())


def config():
    return json.loads((Path(__file__).parents[3] / 'config/hithink-sector-dashboard.json').read_text())


class Provider:
    def __init__(self, *, points=None, stock_total=2100, page_cap=None, empty_batch=False):
        self.calls = []
        self.points = points
        self.stock_total = stock_total
        self.page_cap = page_cap
        self.empty_batch = empty_batch

    def __call__(self, argv):
        self.calls.append(argv)
        def option(name):
            return argv[argv.index(name) + 1]
        command = argv[1:3]
        if command == ['index', 'catalog']:
            response = deepcopy(FIXTURES['catalog'])
            tag = option('--tag')
            count, prefix = (90, 881000) if tag == 'industry' else (390, 885000)
            response['data']['item'] = [{'thscode': f'{prefix+i}.TI', 'name': f'{tag}{i}'} for i in range(count)]
        elif command == ['index', 'history']:
            response = deepcopy(FIXTURES['history'])
            response['data']['thscode'] = option('--thscode')
            bar = response['data']['item'][0]
            response['data']['item'] = [dict(bar, date_ms=1794499200000 - i*86400000) for i in range(250)]
        elif command == ['index', 'history-batch']:
            response = deepcopy(FIXTURES['batch'])
            response['data']['item'] = [{'thscode': code, 'timestamp': 1794758400000,
                'item': [] if self.empty_batch else [dict(FIXTURES['history']['data']['item'][0], date_ms=1794499200000)]}
                for code in option('--thscodes').split(',')]
        elif command == ['index', 'snapshot']:
            response = deepcopy(FIXTURES['index'])
            row = response['data']['item'][0]
            codes = option('--thscodes').split(',')
            response['data']['item'] = [dict(row, thscode=code, ticker=code[:6]) for code in codes]
            response['data']['total'] = len(codes)
        elif command == ['market', 'snapshot']:
            response = deepcopy(FIXTURES['stock'])
            start, limit = int(option('--offset')), int(option('--limit'))
            limit = min(limit, self.page_cap or limit)
            row = response['data']['item'][0]
            response['data']['item'] = [dict(row, thscode=f'{i:06}.SZ', ticker=f'{i:06}')
                for i in range(start, min(start+limit, self.stock_total))]
            response['data']['total'] = self.stock_total
        else:
            raise AssertionError(command)
        response['meta']['count'] = len(response['data']['item'])
        if self.points is not None:
            response['meta']['points'] = self.points
        return subprocess.CompletedProcess(argv, 0, json.dumps(response), 'secret stderr')


class ProbeTests(unittest.TestCase):
    def run_probe(self, provider=None, settings=None, budget=None):
        provider = provider or Provider()
        client = HithinkClient('/opt/hithink-finance', runner=provider)
        report = probe.run_probe(client, settings or config(), budget or probe.ProbeBudget(attempts_per_slice=1))
        self.assertIs(client.runner, provider)
        return report, provider

    def test_call_exhaustion_stops_before_call_51(self):
        budget = probe.ProbeBudget(attempts_per_slice=1)
        for _ in range(50):
            budget.before_call()
            budget.record_points(None)
        with self.assertRaisesRegex(probe.ProbeStopped, 'PROBE_CALL_BUDGET'):
            budget.before_call()
        self.assertEqual(budget.calls, 50)

    def test_reported_points_are_informational_even_above_previous_cap(self):
        report, provider = self.run_probe(Provider(points=50))
        summary = report.safe_summary()
        self.assertGreater(summary['reportedPoints'], 100)
        self.assertGreater(len(provider.calls), 2)
        self.assertTrue(summary['continueAutomatically'])

    def test_missing_points_do_not_block_private_continuation(self):
        summary = self.run_probe()[0].safe_summary()
        self.assertIsNone(summary['estimatedPoints'])
        self.assertFalse(summary['pointsKnown'])
        self.assertTrue(summary['continueAutomatically'])
        self.assertFalse(summary['publicReleaseEligible'])

    def test_samples_are_ten_industries_and_twenty_concepts(self):
        summary = self.run_probe()[0].safe_summary()
        self.assertEqual(summary['coverage']['industrySample'], 10)
        self.assertEqual(summary['coverage']['conceptSample'], 20)
        self.assertEqual(summary['coverage']['historySectors'], 30)
        self.assertEqual(summary['coverage']['historyAtLeast250'], 30)
        self.assertLessEqual(summary['actualCalls'], 50)

    def test_full_market_paging_uses_offsets_and_total(self):
        report, provider = self.run_probe()
        pages = [a for a in provider.calls if a[1:3] == ['market', 'snapshot']]
        self.assertEqual([int(a[a.index('--offset')+1]) for a in pages], [0, 1000, 2000])
        self.assertEqual(report.safe_summary()['coverage']['stockSnapshots'], 2100)
        self.assertEqual(report.safe_summary()['stockSnapshotPages'], 3)

    def test_hundred_row_paging_rejected_without_fanout(self):
        report, provider = self.run_probe(Provider(stock_total=5600, page_cap=100))
        summary = report.safe_summary()
        self.assertEqual(summary['safeErrorCode'], 'SNAPSHOT_100_ROW_PAGING_REJECTED')
        self.assertFalse(summary['continueAutomatically'])
        self.assertEqual(len([a for a in provider.calls if a[1:3] == ['market', 'snapshot']]), 1)

    def test_empty_batch_detected_and_single_history_remains_valid(self):
        summary = self.run_probe(Provider(empty_batch=True))[0].safe_summary()
        self.assertFalse(summary['historyBatchSupported'])
        self.assertEqual(summary['historyBatchStatus'], 'HISTORY_BATCH_INCOMPLETE')
        self.assertEqual(summary['coverage']['historySectors'], 30)
        self.assertEqual(summary['estimatedHistoryCalls'], 480)

    def test_non_verified_authorization_blocks_public_eligibility(self):
        for status in ('unknown', 'pending', 'denied'):
            settings = config()
            settings['authorization']['status'] = status
            summary = self.run_probe(settings=settings)[0].safe_summary()
            self.assertFalse(summary['publicReleaseEligible'])
            self.assertEqual(summary['authorizationStatus'], status)

    def test_verified_status_requires_both_scopes_and_evidence(self):
        settings = config()
        settings['authorization'].update(status='verified')
        self.assertFalse(self.run_probe(settings=settings)[0].safe_summary()['publicReleaseEligible'])
        settings['authorization'].update(localNormalizedFeatures=True, publicDerivedScores=True,
                                         evidenceReference='provider-contract-2026')
        self.assertTrue(self.run_probe(settings=settings)[0].safe_summary()['publicReleaseEligible'])

    def test_estimate_includes_memberships_without_economic_500_call_stop(self):
        report, _ = self.run_probe(Provider(empty_batch=True))
        estimate = probe.estimate_full_run(report)
        self.assertGreater(estimate.calls, 500)
        self.assertTrue(report.safe_summary()['continueAutomatically'])

    def test_known_points_over_100_do_not_block_automatic_continuation(self):
        summary = self.run_probe(Provider(points=1))[0].safe_summary()
        self.assertGreater(summary['estimatedPoints'], 100)
        self.assertTrue(summary['continueAutomatically'])

    def test_caps_cannot_be_raised_or_invalid_values_supplied(self):
        for kwargs in ({'max_calls': 51}, {'max_remote_attempts': 51}, {'max_calls': True}, {'max_remote_attempts': 0}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                probe.ProbeBudget(**kwargs)

    def test_small_budget_counts_batch_cross_checks(self):
        report, provider = self.run_probe(Provider(empty_batch=True), budget=probe.ProbeBudget(max_calls=33, attempts_per_slice=1))
        self.assertEqual(len(provider.calls), 33)
        self.assertEqual(report.safe_summary()['safeErrorCode'], 'PROBE_CALL_BUDGET')

    def test_duplicate_stock_pages_fail_closed(self):
        provider = Provider()
        def repeated(argv):
            if argv[1:3] == ['market', 'snapshot']:
                argv = list(argv)
                argv[argv.index('--offset')+1] = '0'
            return provider(argv)
        summary = self.run_probe(repeated)[0].safe_summary()
        self.assertEqual(summary['safeErrorCode'], 'INVALID_HITHINK_RESPONSE')

    def test_safe_summary_and_private_write_never_store_rows_or_paths(self):
        report, _ = self.run_probe()
        with tempfile.TemporaryDirectory() as temporary:
            target = probe.save_report(Path(temporary).resolve(), report)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            data = json.loads(target.read_text())
            self.assertEqual(data, report.safe_summary())
            encoded = target.read_text()
            for sensitive in ('stderr', 'thscode', '/opt', '881000', 'industry0', 'item'):
                self.assertNotIn(sensitive, encoded)
            self.assertEqual(list(Path(temporary).rglob('*.sqlite3')), [])

    def test_completed_process_like_runner_needs_only_stdout_and_returncode(self):
        from types import SimpleNamespace
        provider = Provider()
        def minimal(argv):
            response = provider(argv)
            return SimpleNamespace(stdout=response.stdout, returncode=response.returncode)
        summary = self.run_probe(minimal)[0].safe_summary()
        self.assertTrue(summary['complete'])

    def test_installed_cli_camelcase_metadata_is_normalized_strictly(self):
        provider = Provider()
        def installed(argv):
            result = provider(argv)
            raw = json.loads(result.stdout)
            raw['meta']['schemaVersion'] = raw['meta'].pop('schema_version')
            raw['meta']['requestId'] = 'private-request'
            return subprocess.CompletedProcess(argv, 0, json.dumps(raw), '')
        summary = self.run_probe(installed)[0].safe_summary()
        self.assertTrue(summary['complete'])
        self.assertNotIn('private-request', json.dumps(summary))

    def test_live_entry_point_reserves_four_attempts_and_caps_logical_calls_at_12(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from unittest.mock import patch
        provider = Provider()
        with tempfile.TemporaryDirectory() as temporary:
            output = StringIO()
            with patch.object(probe, 'HithinkClient', return_value=HithinkClient('/opt/hithink-finance', runner=provider)), redirect_stdout(output):
                result = probe.main(['--cli', '/opt/hithink-finance', '--state-root', str(Path(temporary).resolve()), '--max-calls', '12'])
            self.assertEqual(result, 1)
            self.assertEqual(len(provider.calls), 12)
            self.assertEqual(json.loads(output.getvalue())['remoteDataAttemptUpperBound'], 48)
            summary = json.loads(output.getvalue())
            self.assertTrue(summary['continueAutomatically'])
            self.assertFalse(summary['complete'])

    def test_remote_attempt_budget_stops_before_thirteenth_four_attempt_command(self):
        provider = Provider()
        budget = probe.ProbeBudget(attempts_per_slice=4)
        summary = self.run_probe(provider, budget=budget)[0].safe_summary()
        self.assertEqual(len(provider.calls), 12)
        self.assertEqual(summary['remoteDataAttemptUpperBound'], 48)
        self.assertIsNone(summary['actualRemoteDataAttempts'])
        self.assertEqual(summary['safeErrorCode'], 'PROBE_REMOTE_ATTEMPT_BUDGET')
        self.assertTrue(summary['continueAutomatically'])
        self.assertFalse(summary['complete'])
        self.assertTrue(summary['requiresCapabilityValidation'])

    def test_history_window_splits_reserve_each_slice_before_dispatch(self):
        provider = Provider()
        budget = probe.ProbeBudget(attempts_per_slice=4)
        for _ in range(10):
            budget.before_call(remote_attempts=4)
        runner = probe._metered_runner(provider, budget)
        # More than one ten-year slice: eight reserved data attempts.
        argv = ['/opt/hithink', 'index', 'history', '--thscode', '881000.TI',
                '--start-ms', '0', '--end-ms', str(315576000000 + 1)]
        runner(argv)
        self.assertEqual(budget.reserved_attempts, 48)
        with self.assertRaisesRegex(probe.ProbeStopped, 'PROBE_REMOTE_ATTEMPT_BUDGET'):
            runner(argv)
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(budget.calls, 11)

    def test_point_of_dispatch_rejects_unknown_commands_before_remote_call(self):
        provider = Provider()
        budget = probe.ProbeBudget(attempts_per_slice=4)
        with self.assertRaisesRegex(probe.ProbeStopped, 'UNSUPPORTED_PROBE_COMMAND'):
            probe._metered_runner(provider, budget)(['/opt/hithink', 'fund', 'nav'])
        self.assertEqual(provider.calls, [])
        self.assertEqual(budget.calls, 0)

    def test_rewriting_shorter_report_leaves_exactly_one_valid_json_document(self):
        report = probe.ProbeReport(probe.ProbeBudget())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            report.error = 'X' * 10000
            target = probe.save_report(root, report)
            report.error = None
            probe.save_report(root, report)
            self.assertEqual(json.loads(target.read_text()), report.safe_summary())
            self.assertLess(target.stat().st_size, 10000)
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_elapsed_operational_deadline_stops_before_dispatch(self):
        from unittest.mock import patch
        with patch.object(probe.clock, 'monotonic', return_value=0):
            budget = probe.ProbeBudget(max_elapsed_seconds=120)
        with patch.object(probe.clock, 'monotonic', return_value=121):
            with self.assertRaisesRegex(probe.ProbeStopped, 'PROBE_TIME_BUDGET'):
                budget.before_call()
        self.assertEqual(budget.calls, 0)

    def test_wrapper_dispatches_probe_without_production_job_or_logs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            import os
            result = subprocess.run(['bash', 'ops/macos/run-market-dashboard.sh', '--hithink-probe', '--help'],
                capture_output=True, text=True, env=dict(os.environ, MARKET_DASHBOARD_PROJECT_ROOT=str(root)))
            self.assertEqual(result.returncode, 0)
            self.assertIn('hithink_probe', result.stdout)
            self.assertFalse((root / 'logs').exists())
            self.assertFalse((root / 'state').exists())


if __name__ == '__main__':
    unittest.main()
