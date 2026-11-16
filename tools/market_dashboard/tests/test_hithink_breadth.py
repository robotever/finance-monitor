import csv
from dataclasses import asdict
from pathlib import Path
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from tools.market_dashboard.hithink_cli import Membership, SectorDefinition
from tools.market_dashboard.hithink_store import open_store, migrate_store, replace_catalog, read_memberships
from tools.market_dashboard.hithink_breadth import (StockDailyObservation, derive_daily_breadth,
    derive_breadth_panel, load_stock_panel, refresh_memberships, membership_refresh_due,
    select_membership_snapshot, persist_breadth)


def observation(stock, close=11, previous=10, **kw):
    return StockDailyObservation(stock, '2026-11-13', close, previous, 100, 1000,
                                 '2026-11-12', **kw)


class BreadthTests(unittest.TestCase):
    def members(self, *stocks, sector='881121.TI'):
        return [Membership(sector, s, 1794499200000) for s in stocks]

    def test_counts_diffusion_concentration_and_approximation(self):
        m = self.members('000001.SZ', '000002.SZ', '000003.SZ', '000004.SZ')
        rows = [observation('000001.SZ', 11), observation('000002.SZ', 9), observation('000003.SZ', 10)]
        result = derive_daily_breadth(m, rows, market_date='2026-11-13', previous_market_date='2026-11-12', membership_date='2026-11-16')
        self.assertEqual((result.advancing_count, result.declining_count, result.unchanged_count), (1, 1, 1))
        self.assertEqual((result.valid_count, result.total_count), (3, 4))
        self.assertAlmostEqual(result.strong_stock_share, 1/3)
        self.assertEqual(result.median_return, 0)
        self.assertEqual(result.top5_turnover_share, 1)
        self.assertEqual(result.membership_mode, 'current_members_backfill')
        self.assertAlmostEqual(result.completeness, .75*.8)

    def test_missing_suspension_new_listing_and_stale_previous_excluded(self):
        m = self.members(*[f'{i:06}.SZ' for i in range(1, 6)])
        rows = [observation('000001.SZ'), observation('000002.SZ', volume_mean_5d=50),
                observation('000003.SZ', previous=None),
                StockDailyObservation('000004.SZ', '2026-11-13', 10, 9, 0, 0, '2026-11-12'),
                StockDailyObservation('000005.SZ', '2026-11-13', 10, 9, 100, 100, '2026-11-10')]
        r = derive_daily_breadth(m, rows, market_date='2026-11-13', previous_market_date='2026-11-12', membership_date='2026-11-13')
        self.assertEqual(r.valid_count, 2)
        self.assertEqual(r.volume_expansion_share, 1)
        self.assertEqual(r.completeness, .4)
        empty = derive_daily_breadth(m, [], market_date='2026-11-13', previous_market_date='2026-11-12', membership_date='2026-11-13')
        self.assertIsNone(empty.advancing_share)
        self.assertIsNone(empty.median_return)

    def test_qfq_only_duplicate_rejection(self):
        for rows in ([observation('000001.SZ', adjustment='none')], [observation('000001.SZ')]*2):
            with self.assertRaises(ValueError):
                derive_daily_breadth(self.members('000001.SZ'), rows, market_date='2026-11-13', previous_market_date='2026-11-12', membership_date='2026-11-13')

    def test_one_stock_many_concepts_panel_consumed_once(self):
        calls = []
        def panel():
            calls.append(1)
            yield observation('000001.SZ')
        snapshots = {'881121.TI': ('2026-11-13', self.members('000001.SZ')),
                     '885001.TI': ('2026-11-13', self.members('000001.SZ', sector='885001.TI'))}
        rows = derive_breadth_panel(snapshots, panel(), {'2026-11-13': '2026-11-12'})
        self.assertEqual(calls, [1])
        self.assertEqual([r.valid_count for r in rows], [1, 1])

    def test_snapshot_no_future_pit_and_refresh_schedule(self):
        snapshots = {'2026-11-12': ['old'], '2026-11-16': ['new']}
        self.assertEqual(select_membership_snapshot(snapshots, '2026-11-13'), ('2026-11-12', ['old'], 'point_in_time_snapshot'))
        self.assertEqual(select_membership_snapshot(snapshots, '2026-11-10')[2], 'current_members_backfill')
        self.assertTrue(membership_refresh_due('industry', '2026-11-13', '2026-11-16'))
        self.assertFalse(membership_refresh_due('cn_concept', '2026-11-13', '2026-11-16'))
        self.assertTrue(membership_refresh_due('cn_concept', '2026-11-13', '2026-11-16', priority=True))
        self.assertTrue(membership_refresh_due('cn_concept', '2026-11-06', '2026-11-16'))
        self.assertTrue(membership_refresh_due('cn_concept', '2026-11-13', '2026-11-16', catalog_changed=True))

    def test_refresh_replaces_snapshot_atomically_and_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            db = open_store(root/'store.sqlite3'); migrate_store(db)
            sector = SectorDefinition('881121.TI', 'test', 'industry')
            replace_catalog(db, [sector], observed_at_ms=1)
            client = SimpleNamespace(constituents=lambda code: self.members('000001.SZ', '000002.SZ'))
            refresh_memberships(client, db, [sector], '2026-11-13', state_root=root)
            client.constituents = lambda code: self.members('000001.SZ')
            refresh_memberships(client, db, [sector], '2026-11-13', state_root=root, force=True)
            self.assertEqual(len(read_memberships(db, sector.code, '2026-11-13')), 1)
            r = derive_daily_breadth(self.members('000001.SZ'), [observation('000001.SZ')], market_date='2026-11-13', previous_market_date='2026-11-12', membership_date='2026-11-13')
            persist_breadth(db, [r], state_root=root)
            self.assertEqual(db.execute('SELECT valid_count FROM sector_breadth_daily').fetchone()[0], 1)
            db.close()

    def test_stale_membership_discount_and_fraction_units(self):
        result = derive_daily_breadth(self.members('000001.SZ'), [observation('000001.SZ')],
            market_date='2026-11-13', previous_market_date='2026-11-12', membership_date='2026-11-01')
        self.assertAlmostEqual(result.median_return, .1)
        self.assertEqual(result.membership_mode, 'point_in_time_snapshot')
        self.assertEqual(result.completeness, .8)

    def test_index_independent_trade_calendar_excludes_suspension_gap(self):
        rows = derive_breadth_panel({'881121.TI': ('2026-11-13', self.members('000001.SZ'))},
            [StockDailyObservation('000001.SZ', '2026-11-13', 11, 10, 100, 100, '2026-11-11')],
            {'2026-11-13': '2026-11-12'})
        self.assertEqual(rows[0].valid_count, 0)

    def test_future_observation_cannot_be_saved_as_historical_pit(self):
        from tools.market_dashboard.hithink_store import replace_membership_snapshot
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            db = open_store(root/'store.sqlite3'); migrate_store(db)
            replace_catalog(db, [SectorDefinition('881121.TI', 'test', 'industry')], observed_at_ms=1)
            with self.assertRaisesRegex(ValueError, 'FUTURE_MEMBERSHIP_OBSERVATION'):
                replace_membership_snapshot(db, self.members('000001.SZ'), sector_id='881121.TI', membership_date='2026-11-10')
            db.close()

    def test_backfill_orchestrator_reuses_one_panel_and_persists_counts(self):
        from unittest.mock import patch
        from tools.market_dashboard.hithink_backfill import backfill_breadth_history, HistoryWindow
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            db = open_store(root/'store.sqlite3'); migrate_store(db)
            sector = SectorDefinition('881121.TI', 'test', 'industry')
            replace_catalog(db, [sector], observed_at_ms=1)
            universe = SimpleNamespace(industries=[sector], concepts=[], core_ids=[])
            client = SimpleNamespace(constituents=lambda code: self.members('000001.SZ'))
            with patch('tools.market_dashboard.hithink_breadth.load_stock_panel', return_value=iter([observation('000001.SZ')])) as loader:
                report = backfill_breadth_history(client, db, universe,
                    HistoryWindow('2026-11-13', '2026-11-13'), None,
                    cli_path=Path('/cli'), db_path=root/'provider', state_root=root,
                    trading_dates=['2026-11-12', '2026-11-13'])
            self.assertEqual(loader.call_count, 1)
            self.assertEqual(report['rows'], 1)
            self.assertEqual(report['sectors'][0]['validCount'], 1)
            self.assertEqual(db.execute('SELECT count(*) FROM sector_breadth_daily').fetchone()[0], 1)
            db.close()

    def test_export_cannot_overwrite_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            provider = Path(directory).resolve()/'provider.duckdb'
            provider.write_bytes(b'provider')
            with self.assertRaisesRegex(ValueError, 'INVALID_PANEL_REQUEST'):
                list(load_stock_panel(lambda argv: self.fail('must not dispatch'), Path('/cli'),
                    provider, ['000001.SZ'], '2026-11-13', '2026-11-13', provider))
            self.assertEqual(provider.read_bytes(), b'provider')

    def test_export_one_read_only_qfq_request(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()/'panel.csv'; dbpath = Path(directory).resolve()/'provider.duckdb'; dbpath.touch()
            calls = []
            def runner(argv):
                calls.append(argv)
                path.write_text('thscode,date,close,prev_close,volume,turnover,prev_date,volume_mean_5d\n000001.SZ,2026-11-13,11,10,100,1000,2026-11-12,50\n')
                return subprocess.CompletedProcess(argv, 0, '{"ok":true,"command":"db.export","meta":{"truncated":false}}', '')
            rows = list(load_stock_panel(runner, Path('/official/cli'), dbpath, ['000001.SZ'], '2026-11-13', '2026-11-13', path))
            self.assertEqual(len(calls), 1)
            self.assertIn('v_daily_qfq', calls[0][calls[0].index('--sql')+1])
            self.assertNotIn('data', calls[0])
            self.assertEqual(rows[0].adjustment, 'qfq')
            self.assertEqual(rows[0].previous_close, 10)

if __name__ == '__main__':
    unittest.main()
