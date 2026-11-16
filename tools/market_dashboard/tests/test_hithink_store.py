"""Private store contract tests; all persistence stays in temporary directories."""
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

from tools.market_dashboard import hithink_store as store
from tools.market_dashboard.hithink_cli import SectorDefinition, Membership, IndexDailyBar


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve() / 'private'
        self.path = self.root / 'sector-history.sqlite3'
        self.db = store.open_store(self.path)
        self.addCleanup(self.db.close)
        store.migrate_store(self.db)

    def catalog(self, records=None):
        store.replace_catalog(self.db, records if records is not None else [
            SectorDefinition('881001.TI', '煤炭', 'industry')], observed_at_ms=1000)

    def bar(self, day='2026-11-13', close=12):
        return IndexDailyBar('881001.TI', day, 10, 13, 9, close, 100, 1200)

    def test_migration_has_nine_tables_and_is_idempotent(self):
        self.catalog()
        store.migrate_store(self.db)
        tables = {row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {'sector_catalog', 'sector_membership_snapshot', 'sector_index_daily',
            'sector_index_intraday', 'stock_market_snapshot', 'sector_breadth_daily',
            'sector_features_daily', 'sector_features_intraday', 'ingest_runs'})
        self.assertEqual(len(store.read_catalog(self.db)), 1)
        self.assertEqual(self.db.execute('PRAGMA user_version').fetchone()[0], 1)
        for table in tables:
            info = list(self.db.execute(f'PRAGMA table_info({table})'))
            self.assertTrue(any(row['pk'] for row in info), table)
            self.assertFalse(any('json' in row['name'] or 'raw' in row['name'] for row in info), table)

    def test_connection_and_file_privacy(self):
        self.assertEqual(self.db.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        self.assertEqual(self.db.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(self.db.execute('PRAGMA busy_timeout').fetchone()[0], 5000)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)
        for path in (self.path, Path(str(self.path) + '-wal'), Path(str(self.path) + '-shm')):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_catalog_replacement_rolls_back_and_preserves_other_versions(self):
        self.catalog()
        store.replace_catalog(self.db, [SectorDefinition('885001.TI', '机器人', 'cn_concept')],
            catalog_version='other-version', observed_at_ms=2000)
        with self.assertRaises(sqlite3.IntegrityError):
            self.catalog([SectorDefinition('881002.TI', 'new', 'industry'),
                          SectorDefinition('881003.TI', None, 'industry')])
        self.assertEqual(store.read_catalog(self.db)[0]['sector_id'], '881001.TI')
        self.catalog([SectorDefinition('881002.TI', 'new', 'industry')])
        self.assertEqual(store.read_catalog(self.db)[0]['sector_id'], '881002.TI')
        self.assertEqual(len(store.read_catalog(self.db, catalog_version='other-version')), 1)

    def test_catalog_refresh_does_not_delete_referenced_rows(self):
        self.catalog()
        store.upsert_index_daily(self.db, [self.bar()])
        self.catalog([SectorDefinition('881001.TI', 'renamed', 'industry')])
        self.assertEqual(len(store.read_index_daily(self.db, '881001.TI', '2026-11-01', '2026-11-16')), 1)

    def test_foreign_keys_primary_keys_and_batch_rollback(self):
        with self.assertRaises(sqlite3.IntegrityError):
            store.upsert_index_daily(self.db, [self.bar()])
        self.catalog()
        store.upsert_index_daily(self.db, [self.bar()])
        store.upsert_index_daily(self.db, [self.bar(close=11)])
        with self.assertRaises(sqlite3.IntegrityError):
            store.upsert_index_daily(self.db, [self.bar('2026-11-12'), self.bar('2026-11-13', -1)])
        rows = store.read_index_daily(self.db, '881001.TI', '2026-11-01', '2026-11-16')
        self.assertEqual([(r['market_date'], r['close']) for r in rows], [('2026-11-13', 11)])
        self.assertFalse(self.db.in_transaction)

    def test_membership_and_feature_versions_round_trip(self):
        self.catalog()
        member = Membership('881001.TI', '600001.SH', 1000)
        store.upsert_memberships(self.db, [member, member], membership_date='2026-11-13')
        self.assertEqual(len(store.read_memberships(self.db, '881001.TI', '2026-11-13')), 1)
        feature = dict(sector_id='881001.TI', market_date='2026-11-13', return_1d=0.02,
            completeness=0.8, membership_mode='current_members_backfill', observed_at_ms=1000)
        store.upsert_sector_features(self.db, [feature])
        rows = store.read_sector_features(self.db, '881001.TI', '2026-11-01', '2026-11-16')
        self.assertEqual(rows[0]['return_1d'], 0.02)
        self.assertEqual(rows[0]['feature_version'], 'sector-features-ths-v1')
        self.assertEqual(rows[0]['membership_mode'], 'current_members_backfill')
        store.upsert_sector_features(self.db, [dict(feature, observed_at=2000)], intraday=True)
        self.assertEqual(len(store.read_sector_features(self.db, '881001.TI', 0, 3000, intraday=True)), 1)
        with self.assertRaises(sqlite3.IntegrityError):
            store.upsert_sector_features(self.db, [dict(feature, completeness=2)])
        with self.assertRaises(ValueError):
            store.upsert_sector_features(self.db, [dict(feature, raw_json='secret')])

    def test_reads_are_ordered_bounded_and_validate_bounds(self):
        self.catalog()
        store.upsert_index_daily(self.db, [self.bar('2026-11-13'), self.bar('2026-11-12')])
        self.assertEqual(store.read_index_daily(self.db, '881001.TI', '2026-11-12', '2026-11-13', limit=1)[0]['market_date'], '2026-11-12')
        for limit in (0, -1, 10001, True):
            with self.assertRaises(ValueError):
                store.read_catalog(self.db, limit=limit)
        with self.assertRaises(ValueError):
            store.read_index_daily(self.db, '881001.TI', '2026-11-14', '2026-11-12')

    def test_symlink_database_parent_sidecars_and_lock_rejected(self):
        alias = self.root / 'alias.sqlite3'
        alias.symlink_to(self.path)
        with self.assertRaises(ValueError):
            store.open_store(alias)
        parent = self.root / 'alias-parent'
        parent.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(ValueError):
            store.open_store(parent / 'child.sqlite3')
        target = self.root / 'target'
        target.write_text('unchanged')
        Path(str(self.root / 'new.sqlite3') + '-wal').symlink_to(target)
        with self.assertRaises(ValueError):
            store.open_store(self.root / 'new.sqlite3')
        (self.root / 'sector-history.lock').symlink_to(target)
        with self.assertRaises(ValueError):
            with store.store_write_lock(self.root):
                pass
        self.assertEqual(target.read_text(), 'unchanged')

    def test_single_writer_lock_contends_and_releases_after_exception(self):
        with self.assertRaisesRegex(RuntimeError, 'STORE_BUSY'):
            with store.store_write_lock(self.root):
                with store.store_write_lock(self.root):
                    self.fail('concurrent writer entered')
        with store.store_write_lock(self.root):
            self.assertEqual(stat.S_IMODE((self.root / 'sector-history.lock').stat().st_mode), 0o600)

    def test_schema_primary_keys_and_foreign_keys_for_all_tables(self):
        self.catalog()
        common = dict(sector_id='881001.TI', catalog_version='sector-universe-ths-v1')
        feature = dict(common, feature_version='sector-features-ths-v1',
            membership_version='sector-membership-ths-v1', membership_mode='point_in_time_snapshot',
            market_date='2026-11-13', observed_at_ms=1000, completeness=1)
        snapshot = dict(market_date='2026-11-13', observed_at=1000, last_price=12,
            price_change=2, price_change_ratio_pct=20, open_price=10, high_price=13,
            low_price=9, prev_price=10, volume=100, turnover=1200)
        fixtures = {
            'sector_catalog': dict(common, name='coal', tag='industry', observed_at_ms=1000),
            'sector_membership_snapshot': dict(common, membership_date='2026-11-13',
                stock_id='600001.SH', membership_version='sector-membership-ths-v1', observed_at_ms=1000),
            'sector_index_daily': dict(common, market_date='2026-11-13', open=10, high=13,
                low=9, close=12, volume=100, turnover=1200),
            'sector_index_intraday': dict(common, **snapshot),
            'stock_market_snapshot': dict(snapshot, stock_id='600001.SH'),
            'sector_breadth_daily': {k: v for k, v in feature.items() if k != 'feature_version'},
            'sector_features_daily': feature,
            'sector_features_intraday': dict(feature, observed_at=1000),
            'ingest_runs': dict(run_id='run-1', kind='backfill', started_at_ms=1000),
        }
        for table, row in fixtures.items():
            with self.subTest(table=table):
                sql = f'INSERT INTO {table} ({",".join(row)}) VALUES ({",".join("?" for _ in row)})'
                if table != 'sector_catalog':
                    self.db.execute(sql, list(row.values()))
                with self.assertRaises(sqlite3.IntegrityError):
                    self.db.execute(sql, list(row.values()))
                if table not in ('sector_catalog', 'stock_market_snapshot', 'ingest_runs'):
                    with self.assertRaises(sqlite3.IntegrityError):
                        self.db.execute(sql, list(dict(row, sector_id='881999.TI').values()))

    def test_migration_failure_rolls_back_and_unknown_versions_fail_closed(self):
        other = store.open_store(self.root / 'other.sqlite3')
        self.addCleanup(other.close)
        other.execute('CREATE TABLE sector_index_daily (sentinel TEXT)')
        with self.assertRaises(sqlite3.OperationalError):
            store.migrate_store(other)
        self.assertEqual(other.execute('PRAGMA user_version').fetchone()[0], 0)
        self.assertEqual([r[0] for r in other.execute("SELECT name FROM sqlite_master WHERE type='table'")],
                         ['sector_index_daily'])
        other.execute('PRAGMA user_version=99')
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_STORE_VERSION'):
            store.migrate_store(other)

    def test_store_does_not_commit_callers_transaction_or_nonfinite_values(self):
        self.db.execute('BEGIN')
        with self.assertRaisesRegex(ValueError, 'STORE_TRANSACTION_ACTIVE'):
            self.catalog()
        with self.assertRaisesRegex(ValueError, 'STORE_TRANSACTION_ACTIVE'):
            store.migrate_store(self.db)
        self.assertTrue(self.db.in_transaction)
        self.db.rollback()
        self.catalog()
        for value in (float('nan'), float('inf'), True):
            with self.assertRaisesRegex(ValueError, 'INVALID_STORE_ROW'):
                store.upsert_index_daily(self.db, [self.bar(close=value)])
        self.assertEqual(store.read_index_daily(self.db, '881001.TI', '2026-11-01', '2026-11-16'), [])


if __name__ == '__main__':
    unittest.main()
