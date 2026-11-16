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
        self.calendar = []
        day = datetime(2023, 1, 2)
        while len(self.calendar) < 300:
            if day.weekday() < 5:
                self.calendar.append(day.date().isoformat())
            day += timedelta(days=1)
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
                return tuple(IndexDailyBar(code, outer.calendar[i], 1, 2, 1, 2, 10, 20) for i in range(n))
            def index_history_batch(self, *args):
                raise HithinkError('HISTORY_BATCH_INCOMPLETE')
        self.client = Client()

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def run_backfill(self, **kwargs):
        return backfill_index_history(self.client, self.store, self.universe, self.window,
                                      BackfillBudget(min_call_interval=0, **kwargs), state_root=self.root, trading_dates=self.calendar)

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
            BackfillBudget(min_call_interval=0), state_root=self.root, batch_validated=True, trading_dates=self.calendar)
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
            BackfillBudget(min_call_interval=0), state_root=self.root, should_yield=lambda: True, trading_dates=self.calendar)
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
        checks = lambda: self.store.execute('select count(*) from sector_index_daily').fetchone()[0] >= 250
        report = backfill_index_history(self.client, self.store, self.universe, self.window,
            BackfillBudget(min_call_interval=0), state_root=self.root,
            should_yield=checks, trading_dates=self.calendar)
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
            BackfillBudget(max_calls=1, min_call_interval=0), state_root=self.root, batch_validated=True, trading_dates=self.calendar)
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

    def test_invalid_ohlc_and_nontrading_date_never_checkpoint(self):
        for date, prices, code in [('2023-01-02', (10, 2, 8, 1), 'INVALID_HISTORY_OHLC'),
                                   ('2023-01-08', (1, 2, 1, 2), 'INVALID_HISTORY_TRADING_DATE')]:
            with self.subTest(date=date):
                self.client.index_history = lambda identity, *args: (IndexDailyBar(identity, date, *prices, 10, 20),)
                report = self.run_backfill()
                self.assertFalse(report.complete)
                self.assertEqual(report.coverage[0]['safeErrorCode'], code)
                self.assertEqual(self.store.execute('select count(*) from sector_index_daily').fetchone()[0], 0)
                self.assertGreater(self.run_backfill().calls, 0)

    def test_missing_calendar_fails_before_dispatch(self):
        report = backfill_index_history(self.client, self.store, self.universe, self.window,
            BackfillBudget(min_call_interval=0), state_root=self.root)
        self.assertEqual(report.safe_error_code, 'CALENDAR_UNVERIFIED')
        self.assertEqual(self.calls, [])

    def test_adapter_nested_batch_verification_checks_priority_before_dispatch(self):
        from tools.market_dashboard.hithink_cli import HithinkClient
        import subprocess
        actual = []
        priority = False
        def runner(argv):
            nonlocal priority
            actual.append(argv[2])
            priority = True
            return subprocess.CompletedProcess(argv, 0, json.dumps({
                'ok': True, 'command': 'index.history-batch',
                'meta': {'source': 'remote', 'count': 0, 'truncated': False, 'schema_version': '1'},
                'data': {'item': [], 'interval': '1d', 'adjust': None}}), '')
        client = HithinkClient('/fake/official-cli', runner=runner)
        report = backfill_index_history(client, self.store, self.universe, self.window,
            BackfillBudget(min_call_interval=0), state_root=self.root, batch_validated=True,
            should_yield=lambda: priority, trading_dates=self.calendar)
        self.assertEqual(actual, ['history-batch'])
        self.assertEqual(report.safe_error_code, 'BACKFILL_YIELDED')
        self.assertEqual(report.calls, 1)

    def test_completed_checkpoint_revalidates_stored_ohlc(self):
        self.assertTrue(self.run_backfill().complete)
        self.store.execute('update sector_index_daily set open=100 where sector_id=?', (self.a.code,))
        report = self.run_backfill()
        self.assertFalse(report.complete)
        self.assertEqual(report.safe_error_code, 'INVALID_STORED_HISTORY')
        self.assertEqual(self.calls, [self.a.code, self.b.code])
        self.assertEqual(self.store.execute('select max(open) from sector_index_daily').fetchone()[0], 100)

    def test_observed_calendar_uses_readonly_cli_query_and_validates_dates(self):
        from tools.market_dashboard.hithink_backfill import load_observed_market_calendar
        import subprocess
        calls = []
        days = ['2023-01-03', '2023-01-04']
        def runner(argv):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({'ok': True, 'command': 'db.query',
                'meta': {'count': len(days), 'truncated': False}, 'data': [{'date': day} for day in days]}), '')
        self.assertEqual(load_observed_market_calendar('/fake/cli', '/fake/stock.duckdb', self.window, runner=runner), days)
        self.assertEqual(calls[0][3:5], ['db', 'query'])
        self.assertIn('select distinct', calls[0][6])
        days[:] = ['2023-01-08']
        with self.assertRaises(ValueError):
            load_observed_market_calendar('/fake/cli', '/fake/stock.duckdb', self.window, runner=runner)

    def test_main_defaults_to_observed_calendar_source(self):
        from tools.market_dashboard.hithink_backfill import main
        import contextlib, io
        output = io.StringIO()
        with patch('tools.market_dashboard.hithink_backfill._stock_database', return_value=Path('/fake/stock.duckdb')):
            with patch('tools.market_dashboard.hithink_backfill.load_observed_market_calendar', return_value=self.calendar) as calendar:
                with patch('tools.market_dashboard.hithink_backfill.HithinkClient', return_value=self.client):
                    with contextlib.redirect_stdout(output):
                        result = main(['--cli', '/fake/official-cli', '--store', str(self.root/'other.sqlite3'), '--max-calls', '1'])
        self.assertEqual(result, 1)
        calendar.assert_called_once()
        self.assertEqual(json.loads(output.getvalue())['calendarSource'], 'observed_market_calendar')

    def test_invalid_extra_stored_date_fails_closed_without_refetch_or_repair(self):
        self.assertTrue(self.run_backfill().complete)
        from tools.market_dashboard.hithink_store import upsert_index_daily
        upsert_index_daily(self.store, [IndexDailyBar(self.a.code, '2023-01-08', 1, 2, 1, 2, 10, 20)])
        before = [tuple(r) for r in self.store.execute('select * from sector_index_daily order by sector_id,market_date')]
        calls = list(self.calls)
        report = self.run_backfill()
        self.assertFalse(report.complete)
        self.assertEqual(report.safe_error_code, 'INVALID_STORED_HISTORY')
        self.assertEqual(report.coverage[0]['status'], 'failed')
        self.assertEqual(self.calls, calls)
        self.assertEqual([tuple(r) for r in self.store.execute('select * from sector_index_daily order by sector_id,market_date')], before)
        self.assertFalse(self.run_backfill().complete)

    def test_missing_calendar_with_complete_checkpoints_never_reports_complete(self):
        self.assertTrue(self.run_backfill().complete)
        calls = list(self.calls)
        report = backfill_index_history(self.client, self.store, self.universe, self.window,
            BackfillBudget(min_call_interval=0), state_root=self.root)
        self.assertEqual(report.safe_error_code, 'CALENDAR_UNVERIFIED')
        self.assertFalse(report.complete)
        self.assertEqual(self.calls, calls)
