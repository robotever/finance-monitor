"""Derived-only recovery and official-close continuity contracts, all synthetic."""
from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tools.market_dashboard import rotation
from tools.market_dashboard.concepts import concept_definitions, load_concept_config
from tools.market_dashboard.scoring import load_config
from tools.market_dashboard.sources import INDUSTRY_DEFINITIONS

if importlib.util.find_spec('tools.market_dashboard.rotation_store'):
    from tools.market_dashboard import rotation_store as store
else:
    store = None


def snapshot(day='2026-11-13'):
    rows = []
    for universe, definitions in [('industry', INDUSTRY_DEFINITIONS),
                                  ('concept', concept_definitions(load_concept_config()))]:
        for code, name in definitions:
            rows.append(dict(id=code, name=name, universe=universe, marketDate=day,
                session='close', observedAt=day+'T15:00:02+08:00', strength=80,
                opportunity=None, risk=20, _rawScores=dict(strength=80.49, opportunity=None, risk=20.1),
                completeness=80, components={'breadth': {'value': 50., 'coverage': 1., 'missing': []}},
                metrics={'return20d': 2., 'relativeStrength20d': 0., 'flowRatio1d': None},
                heatState='active', missing=['flow.missingInput'],
                sectorScoringVersion='sector-score-v0.2', sectorUniverseVersion='sector-universe-v0.1'))
    return dict(schemaVersion='market-dashboard-v3', sectorScoringVersion='sector-score-v0.2',
                sectorUniverseVersion='sector-universe-v0.1', marketDate=day, session='close',
                observedAt=day+'T15:05:00+08:00', officialClose=True, sectors=rows)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store, 'derived rotation store is missing')
        self.config = load_config()

    def test_append_is_immutable_idempotent_and_preserves_precision(self):
        original = snapshot()
        state = store.append_rotation_close({}, original, self.config)
        self.assertEqual(len(state['closes']), 110)
        self.assertNotIn('ranks', original['sectors'][0])
        self.assertEqual(state['closes'][0]['_rawScores']['strength'], 80.49)
        self.assertEqual(state['closes'][0]['metrics']['strengthPercentile'], 50.)
        self.assertEqual(state['closes'][0]['metrics']['strengthRank'], 1)
        self.assertEqual(store.append_rotation_close(state, original, self.config), state)

    def test_official_close_requires_complete_identity_and_close_time(self):
        mutations = [lambda p: p['sectors'].pop(),
                     lambda p: p['sectors'][0].update(id='unknown'),
                     lambda p: p['sectors'][0].update(observedAt='2026-11-13T14:59:59+08:00'),
                     lambda p: p.update(observedAt='2026-11-13T15:31:00+08:00')]
        for mutate in mutations:
            value = snapshot(); mutate(value)
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                store.append_rotation_close({}, value, self.config)

    def test_v2_intraday_and_unofficial_snapshots_do_not_advance(self):
        for changes in [dict(schemaVersion='market-dashboard-v2'), dict(session='intraday'),
                        dict(officialClose=False)]:
            self.assertEqual(store.append_rotation_close({}, snapshot() | changes, self.config)['closes'], [])

    def test_wrong_version_rows_are_skipped_but_malformed_current_rows_reject(self):
        state = store.append_rotation_close({}, snapshot(), self.config)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'
            old = deepcopy(state)
            for row in old['closes']:
                row['sectorScoringVersion'] = 'old'
            path.write_text(json.dumps(old))
            self.assertEqual(store.load_rotation_state(path, self.config)['closes'], [])
            for mutate in [lambda row: row['components']['breadth'].update(value=101),
                           lambda row: row.update(rawRows=[{'secret': 'raw'}]),
                           lambda row: row['_rawScores'].update(strength=None),
                           lambda row: row['metrics'].update(netFlow1d=123),
                           lambda row: row.update(id='unknown')]:
                bad = deepcopy(state); mutate(bad['closes'][0]); path.write_text(json.dumps(bad))
                with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                    store.load_rotation_state(path, self.config)
            path.write_text(json.dumps({'payload': {'schemaVersion': 'market-dashboard-v2'}}))
            self.assertEqual(store.load_rotation_state(path, self.config)['closes'], [])

    def test_ninety_calendar_days_retain_boundary_and_trim_older(self):
        state = {}
        for day in ['2026-08-14', '2026-08-15', '2026-11-13']:
            state = store.append_rotation_close(state, snapshot(day), self.config)
        self.assertEqual(sorted({r['marketDate'] for r in state['closes']}), ['2026-08-15', '2026-11-13'])

    def test_reload_rejects_incomplete_or_forged_rank_history(self):
        state = store.append_rotation_close({}, snapshot(), self.config)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'
            for mutate in [lambda value: value['closes'].pop(),
                           lambda value: value['closes'][0]['ranks'].update(strength=35),
                           lambda value: value['closes'][0]['metrics'].update(strengthPercentile=99),
                           lambda value: value['closes'][0]['components']['breadth'].update(parts={'rawProvider': {'value': 50., 'coverage': 1., 'missing': []}})]:
                bad = deepcopy(state); mutate(bad); path.write_text(json.dumps(bad))
                with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                    store.load_rotation_state(path, self.config)

    def test_reload_rejects_forged_later_streak_before_retention_can_promote_it(self):
        state = store.append_rotation_close({}, snapshot('2026-08-14'), self.config)
        state = store.append_rotation_close(state, snapshot('2026-08-15'), self.config)
        forged = deepcopy(state)
        target = next(row for row in forged['closes']
                      if row['marketDate'] == '2026-08-15' and row['id'] == '882100.WI')
        target['leaderboard']['strength']['topTenStreak'] = 999
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'; path.write_text(json.dumps(forged))
            with self.assertRaises(ValueError):
                store.load_rotation_state(path, self.config)
            with self.assertRaises(ValueError):
                store.append_rotation_close(forged, snapshot('2026-11-13'), self.config)
        self.assertEqual(next(row for row in state['closes'] if row['marketDate'] == '2026-08-15'
                              and row['id'] == '882100.WI')['leaderboard']['strength']['topTenStreak'], 2)

    def test_reload_checks_each_axis_count_and_rank_change_against_prior_closes(self):
        state = store.append_rotation_close({}, snapshot('2026-08-14'), self.config)
        state = store.append_rotation_close(state, snapshot('2026-08-15'), self.config)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'
            for axis, field, value in [('strength', 'rankChange', 1),
                                       ('opportunity', 'topTenStreak', 1),
                                       ('opportunity', 'rankChange', 0)]:
                forged = deepcopy(state)
                target = next(row for row in forged['closes']
                              if row['marketDate'] == '2026-08-15' and row['id'] == '882100.WI')
                target['leaderboard'][axis][field] = value
                path.write_text(json.dumps(forged))
                with self.subTest(axis=axis, field=field), self.assertRaises(ValueError):
                    store.load_rotation_state(path, self.config)

    def test_reload_rejects_count_forgery_when_fifteen_closes_are_reconstructible(self):
        state = store.append_rotation_close({}, snapshot('2026-08-01'), self.config)
        template = deepcopy(state['closes'])
        state['closes'] = []
        for index in range(15):
            day = (date(2026, 8, 1)+timedelta(days=index)).isoformat()
            for row in deepcopy(template):
                row.update(marketDate=day, observedAt=day+'T15:00:02+08:00')
                for axis in ('strength', 'opportunity'):
                    rank = row['ranks'][axis]
                    top = rank is not None and rank <= 10
                    row['leaderboard'][axis].update(topTenStreak=index+1 if top else 0,
                        topTenCount15d=index+1 if top else 0,
                        rankChange=0 if index and rank is not None else None)
                state['closes'].append(row)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'; path.write_text(json.dumps(state))
            self.assertEqual(len(store.load_rotation_state(path, self.config)['closes']), 1650)
            for axis, forged_count in [('strength', 14), ('opportunity', 1)]:
                forged = deepcopy(state)
                target = next(row for row in forged['closes']
                              if row['marketDate'] == '2026-08-15' and row['id'] == '882100.WI')
                target['leaderboard'][axis]['topTenCount15d'] = forged_count
                path.write_text(json.dumps(forged))
                with self.subTest(axis=axis), self.assertRaises(ValueError):
                    store.load_rotation_state(path, self.config)

    def test_reload_preserves_only_earliest_anchor_through_repeated_retention(self):
        state = store.append_rotation_close({}, snapshot('2026-08-14'), self.config)
        state = store.append_rotation_close(state, snapshot('2026-08-15'), self.config)
        for row in state['closes']:
            if row['id'] == '882100.WI':
                row['leaderboard']['strength'].update(topTenStreak=50 if row['marketDate'] == '2026-08-14' else 51,
                                                     topTenCount15d=15, rankChange=0)
        before = deepcopy(state)
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'; path.write_text(json.dumps(state))
            recovered = store.load_rotation_state(path, self.config)
            for day, expected in [('2026-11-13', 52), ('2026-11-16', 53)]:
                recovered = store.append_rotation_close(recovered, snapshot(day), self.config)
                current = next(row for row in recovered['closes'] if row['marketDate'] == day and row['id'] == '882100.WI')
                self.assertEqual(current['leaderboard']['strength']['topTenStreak'], expected)
                path.write_text(json.dumps(recovered))
                recovered = store.load_rotation_state(path, self.config)
        self.assertEqual(state, before)

    def test_price_history_cannot_smuggle_forward_flow_or_score_fields(self):
        price = store.build_price_backfill({'882100.WI': [dict(id='882100.WI', date='2026-10-01', close=100.)]}, 'sector-universe-v0.1')[0]
        state = store.append_rotation_close({}, snapshot(), self.config)
        state['priceHistory'] = [price | {'metrics': {'flowRatio1d': .9}}]
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'; path.write_text(json.dumps(state))
            with self.assertRaises(ValueError):
                store.load_rotation_state(path, self.config)

    def test_private_atomic_writer_rejects_symlinks_and_cleans_failed_temporary(self):
        from tools.market_dashboard import job
        with TemporaryDirectory() as directory:
            path = Path(directory)/'state.json'
            job._write_json(path, {'safe': True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            path.with_name('link').symlink_to(path)
            with self.assertRaises(ValueError):
                job._write_json(path.with_name('link'), {'overwrite': True})
            with self.assertRaises(ValueError):
                store.load_rotation_state(path.with_name('link'), self.config)
            with self.assertRaises(ValueError):
                job._write_json(path, {'bad': float('nan')})
            self.assertEqual(json.loads(path.read_text()), {'safe': True})
            self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ['link', 'state.json'])


class LeaderboardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store, 'derived rotation store is missing')

    def closes(self, ranks):
        return [dict(id='882100.WI', universe='industry', marketDate=(date(2026, 10, 1)+timedelta(days=i*3)).isoformat(),
                     session='close', officialClose=True, ranks={'strength': rank, 'opportunity': 11})
                for i, rank in enumerate(ranks)]

    def test_axis_specific_streak_and_count_use_exactly_last_fifteen_official_closes(self):
        rows = self.closes([1, 1]+[11]*12+[10, 9, 8])
        rows.append(rows[-1] | dict(session='intraday', ranks={'strength': 20}))
        value = store.leaderboard_stats(rows, 'industry', 'strength', '882100.WI')
        self.assertEqual(value, dict(axis='strength', topTenStreak=3, topTenCount15d=3, rankChange=1))
        self.assertEqual(store.leaderboard_stats(rows, 'industry', 'opportunity', '882100.WI'),
                         dict(axis='opportunity', topTenStreak=0, topTenCount15d=0, rankChange=0))
        with self.assertRaises(ValueError):
            store.leaderboard_stats(rows, 'industry', 'risk', '882100.WI')

    def test_holidays_do_not_break_streak_null_rank_breaks_and_other_universe_ignored(self):
        rows = self.closes([1, None, 10, 9])
        rows.append(rows[-1] | dict(universe='concept', ranks={'strength': 11}))
        value = store.leaderboard_stats(list(reversed(rows)), 'industry', 'strength', '882100.WI')
        self.assertEqual(value, dict(axis='strength', topTenStreak=2, topTenCount15d=3, rankChange=1))

    def test_recovery_retention_preserves_long_streak_from_earliest_derived_anchor(self):
        rows = self.closes([1, 2, 3])
        rows[0]['leaderboard'] = {'strength': {'axis': 'strength', 'topTenStreak': 50}}
        self.assertEqual(store.leaderboard_stats(rows, 'industry', 'strength', '882100.WI')['topTenStreak'], 52)
        rows[1]['ranks']['strength'] = 11
        self.assertEqual(store.leaderboard_stats(rows, 'industry', 'strength', '882100.WI')['topTenStreak'], 1)


class BackfillTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(store, 'derived rotation store is missing')

    def test_backfill_derives_returns_sorts_deduplicates_and_never_copies_flow(self):
        points = [dict(id='882100.WI', date=f'2026-10-{i+1:02d}', close=100.+i,
                       netFlow1d=999., breadth=.9) for i in range(21)]
        result = store.build_price_backfill({'882100.WI': list(reversed(points))+[points[0]]}, 'sector-universe-v0.1')
        self.assertEqual(len(result), 21)
        last = result[-1]
        self.assertEqual(last['metrics']['return20d'], 20.)
        self.assertAlmostEqual(last['metrics']['return5d'], 100*(120/115-1))
        self.assertNotIn('close', last)
        self.assertFalse({'flowRatio1d', 'breadth', 'netFlow1d'} & last['metrics'].keys())
        self.assertNotIn('relativeStrength20d', last['metrics'])  # partial universe cannot establish median
        config = load_config()
        current = dict(id='882100.WI', universe='industry', marketDate='2026-11-13', session='close',
                       metrics=dict(return1d=1., return5d=3., return20d=5.))
        self.assertIsNone(rotation.score_sector(current, result, [current], config)['opportunity'])

    def test_backfill_rejects_unknown_identity_version_mismatch_conflicting_duplicates(self):
        point = dict(id='882100.WI', date='2026-10-01', close=100.)
        for histories, version in [({'unknown': []}, 'sector-universe-v0.1'),
                                   ({'882100.WI': [point]}, 'old'),
                                   ({'882100.WI': [point | dict(id='882101.WI')]}, 'sector-universe-v0.1'),
                                   ({'882100.WI': [point, point | dict(close=101.)]}, 'sector-universe-v0.1')]:
            with self.subTest(histories=histories), self.assertRaises(ValueError):
                store.build_price_backfill(histories, version)

    def test_full_universe_median_establishes_only_dated_relative_strength(self):
        histories = {code: [dict(id=code, date=(date(2026, 8, 1)+timedelta(days=i)).isoformat(),
                                close=100.+i*(index+1)) for i in range(40)]
                     for index, (code, _) in enumerate(INDUSTRY_DEFINITIONS)}
        rows = store.build_price_backfill(histories, 'sector-universe-v0.1')
        last = next(row for row in rows if row['id'] == '882100.WI' and row['marketDate'] == '2026-08-21')
        self.assertEqual(last['metrics']['relativeStrength20d'], -340.)  # 20% minus median 360%
        current = dict(id='882100.WI', universe='industry', marketDate='2026-11-13', session='close',
                       metrics=dict(return1d=1., return5d=3., return20d=5.))
        config = load_config()
        scored = rotation.score_sector(current, rows, [current], config)
        self.assertEqual(scored['validCloses'], 20)
        self.assertTrue(scored['coldStart'])
        self.assertIsNone(scored['opportunity'])  # missing historical flow/breadth still lowers coverage
