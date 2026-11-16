import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta
from types import SimpleNamespace

from tools.market_dashboard.hithink_cli import HithinkError, IndexDailyBar, SectorDefinition, SHANGHAI
from tools.market_dashboard.hithink_store import open_store, migrate_store, store_write_lock
from tools.market_dashboard.hithink_backfill import BackfillBudget, HistoryWindow, backfill_index_history


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.store = open_store(self.root / 'sector-history.sqlite3')
        migrate_store(self.store)
        self.a = SectorDefinition('881001.TI', 'one', 'industry')
        self.b = SectorDefinition('885001.TI', 'two', 'cn_concept')
        self.universe = SimpleNamespace(industries=(self.a,), concepts=(self.b,), version='sector-universe-ths-v1', catalog_digest='test')
        self.window = HistoryWindow('2023-01-01', '2026-11-13')
        self.calls = []
        self.fail = set()
        outer = self
        class Client:
            def index_history(self, code, start, end):
                outer.calls.append(code)
                # Writer lock must be available while provider request is in flight.
                with store_write_lock(outer.root):
                    pass
                if code in outer.fail:
                    raise HithinkError('HITHINK_COMMAND_FAILED')
                n = 251 if code == outer.a.code else 60
                return tuple(IndexDailyBar(code, (datetime(2023, 1, 2) + timedelta(days=i)).date().isoformat(), 1, 2, 1, 2, 10, 20) for i in range(n))
            def index_history_batch(self, *args):
                raise HithinkError('HISTORY_BATCH_INCOMPLETE')
        self.client = Client()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_backfill(self, **kwargs):
        return backfill_index_history(self.client, self.store, self.universe, self.window,
                                      BackfillBudget(min_call_interval=0, **kwargs), state_root=self.root)

    def test_shanghai_window_and_coverage_and_rerun(self):
        self.assertEqual(datetime.fromtimestamp(self.window.start_ms/1000, SHANGHAI).isoformat(), '2023-01-01T00:00:00+08:00')
        report = self.run_backfill()
        self.assertTrue(report.complete)
        self.assertEqual([(r['rows'], r['coverage20'], r['coverage60'], r['coverage250']) for r in report.coverage], [(251, True, True, True), (60, True, True, False)])
        self.assertEqual(self.store.execute('select count(*) from sector_index_daily').fetchone()[0], 311)
        self.assertEqual(self.run_backfill().calls, 0)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual({r[0] for r in self.store.execute("select distinct kind from ingest_runs")}, {'backfill'})

    def test_failure_and_resume(self):
        self.fail.add(self.b.code)
        report = self.run_backfill()
        self.assertFalse(report.complete)
        self.assertEqual(report.coverage[1]['safeErrorCode'], 'HITHINK_COMMAND_FAILED')
        self.fail.clear()
        report = self.run_backfill()
        self.assertTrue(report.complete)
        self.assertEqual(self.calls, [self.a.code, self.b.code, self.b.code])

    def test_budget_stops_before_dispatch(self):
        report = self.run_backfill(max_calls=1)
        self.assertEqual(self.calls, [self.a.code])
        self.assertEqual(report.safe_error_code, 'BACKFILL_CALL_BUDGET')
        self.assertEqual(len(report.coverage), 2)
        self.assertFalse(report.complete)

    def test_single_default_and_explicit_batch_empty_fallback(self):
        report = backfill_index_history(self.client, self.store, self.universe, self.window,
            BackfillBudget(min_call_interval=0), state_root=self.root, batch_validated=True)
        self.assertTrue(report.complete)
        self.assertEqual(report.batch_status, 'HISTORY_BATCH_INCOMPLETE')
        self.assertEqual(self.calls, [self.a.code, self.b.code])

    def test_empty_is_failed_and_retried(self):
        self.client.index_history = lambda *args: ()
        report = self.run_backfill()
        self.assertFalse(report.complete)
        self.assertEqual(report.coverage[0]['safeErrorCode'], 'HISTORY_EMPTY')
        self.assertEqual(self.run_backfill().calls, 2)

    def test_live_preemption_before_dispatch(self):
        report = backfill_index_history(self.client, self.store, self.universe, self.window,
            BackfillBudget(min_call_interval=0), state_root=self.root, should_yield=lambda: True)
        self.assertEqual(self.calls, [])
        self.assertEqual(report.safe_error_code, 'BACKFILL_YIELDED')

    def test_atomic_rollback(self):
        from tools.market_dashboard.hithink_store import commit_index_backfill
        from tools.market_dashboard.hithink_store import replace_catalog
        replace_catalog(self.store, [self.a], observed_at_ms=1)
        bars = [IndexDailyBar(self.a.code, '2023-01-02', 1, 2, 1, 2, 10, 20), IndexDailyBar(self.a.code, '2023-01-03', 1, 2, 1, -1, 10, 20)]
        with self.assertRaises(Exception):
            commit_index_backfill(self.store, bars, run_id='test', started_at_ms=1, finished_at_ms=2, request_count=1)
        self.assertEqual(self.store.execute('select count(*) from sector_index_daily').fetchone()[0], 0)
        self.assertEqual(self.store.execute('select count(*) from ingest_runs').fetchone()[0], 0)

    def test_safe_report(self):
        report = self.run_backfill().safe_summary()
        self.assertEqual(report['coverage']['industryUniverse'], 1)
        self.assertEqual(report['coverage']['conceptUniverse'], 1)
        self.assertNotIn(str(self.root), json.dumps(report))
        self.assertFalse(report['publicReleaseEligible'])

    def test_chunk_interruption_requires_refetch_and_releases_lock(self):
        checks = iter([False, False, True])
        report = backfill_index_history(self.client, self.store, self.universe, self.window,
            BackfillBudget(min_call_interval=0), state_root=self.root,
            should_yield=lambda: next(checks, True))
        self.assertEqual(report.safe_error_code, 'BACKFILL_YIELDED')
        self.assertEqual(report.coverage[0]['rows'], 250)
        self.assertEqual(report.coverage[0]['status'], 'pending')
        self.assertTrue(self.run_backfill().complete)
        self.assertEqual(self.calls.count(self.a.code), 2)
        with store_write_lock(self.root):
            pass

    def test_shared_lock_contention_stops_without_remote_calls(self):
        with store_write_lock(self.root):
            report = self.run_backfill()
        self.assertEqual(report.safe_error_code, 'STORE_BUSY')
        self.assertEqual(self.calls, [])

    def test_metered_adapter_empty_batch_fallback_budget(self):
        from tools.market_dashboard.hithink_cli import HithinkClient
        import subprocess
        actual = []
        def runner(argv):
            actual.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                'ok': True, 'command': 'index.history-batch',
                'meta': {'source': 'remote', 'count': 0, 'truncated': False, 'schema_version': '1'},
                'data': {'item': [], 'interval': '1d', 'adjust': None}}), '')
        client = HithinkClient('/fake/official-cli', runner=runner)
        report = backfill_index_history(client, self.store, self.universe, self.window,
            BackfillBudget(max_calls=1, min_call_interval=0), state_root=self.root, batch_validated=True)
        self.assertEqual(len(actual), 1)
        self.assertEqual(report.calls, 1)
        self.assertEqual(report.safe_error_code, 'BACKFILL_CALL_BUDGET')
        self.assertIs(client.runner, runner)

    def test_runtime_failure_main_emits_safe_error(self):
        from tools.market_dashboard.hithink_backfill import main
        import contextlib
        import io
        output = io.StringIO()
        with patch('tools.market_dashboard.hithink_backfill.store_write_lock', side_effect=RuntimeError('STORE_BUSY')):
            with contextlib.redirect_stdout(output):
                result = main(['--cli', '/fake/official-cli', '--store', str(self.root/'other.sqlite3')])
        self.assertEqual(result, 1)
        self.assertEqual(json.loads(output.getvalue())['safeErrorCode'], 'BACKFILL_FAILED')
