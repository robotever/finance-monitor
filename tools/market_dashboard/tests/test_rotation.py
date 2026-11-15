"""Synthetic, hand-calculated contracts for the pure sector engine.

Each test's name/docstring names the production break it catches. No provider
data, mocks, wall clock or network is involved.
"""
from copy import deepcopy
from datetime import date, timedelta
import importlib.util
import json
import math
from pathlib import Path
import unittest

from tools.market_dashboard.scoring import load_config

if importlib.util.find_spec('tools.market_dashboard.rotation'):
    from tools.market_dashboard import rotation
else:
    rotation = None


def peers():
    return [dict(id=f's{i}', universe='industry', marketDate='2026-11-14', session='close',
                 metrics=dict(return1d=i, return5d=4-i, return20d=2*i,
                              netFlow1d=(4-i)*100, amount1d=1000,
                              netFlow5d=i*500, amount5d=5000,
                              netFlow20d=(4-i)*2000, amount20d=20000,
                              advancing=i, declining=4-i, unchanged=1,
                              turnover=i+1, marketAmount=100000)) for i in range(5)]


def history(count=20, rows=None):
    rows = rows or peers()
    result = []
    for day in range(count):
        for row in rows:
            result.append(dict(id=row['id'], universe=row['universe'], session='close',
                               marketDate=(date(2025, 1, 1)+timedelta(days=day)).isoformat(),
                               sectorScoringVersion='sector-score-v0.2',
                               sectorUniverseVersion='sector-universe-v0.1',
                               strength=50,
                               _rawScores={'strength':50.},
                               metrics=dict(relativeStrength20d=day-count,
                                            flowRatio1d=(day-count)/100,
                                            breadth=.2, decliningShare=.6,
                                            activityPercentile=30,
                                            strengthPercentile=[80,60,40,20,0][day % 5],
                                            strengthRank=[1,2,3,11,1][day % 5])))
    return result


class RotationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(rotation, 'pure sector rotation engine is missing')
        self.config = load_config()
        self.rows = peers()
        self.past = history()

    def derive(self, index=4, past=None):
        return rotation.derive_sector_components(self.rows[index], self.past if past is None else past,
                                                 self.rows, self.config)

    def score(self, index=4, past=None, config=None):
        return rotation.score_sector(self.rows[index], self.past if past is None else past,
                                     self.rows, config or self.config)

    def test_position_curve_rejects_bottom_fishing_and_overextended_positions(self):
        for value, want in [(None,None), (0,0), (9.99,0), (10,0), (22.5,50),
                            (35,100), (52.5,50), (70,0), (100,0), (float('nan'),None)]:
            with self.subTest(value=value):
                self.assertEqual(rotation.position_curve(value), want)

    def test_winsorization_midpoint_ties_and_reverse_direction_reach_sector_atoms(self):
        self.rows = [deepcopy(self.rows[0]) for _ in range(100)]
        for i, row in enumerate(self.rows):
            row.update(id=f'w{i}')
            row['metrics'].update(return1d=i, return5d=i, return20d=i)
        low = self.derive(0)
        high = self.derive(99)
        self.assertEqual(low['priceTrend']['value'], 2.5)
        self.assertEqual(high['priceTrend']['value'], 97.5)
        self.assertEqual(high['trendDeterioration']['parts']['return20d']['value'], 2.5)
        self.assertEqual(high['funding']['parts']['flow1d']['value'], 50)

    def test_price_weights_are_20_45_35_and_flow_uses_same_period_amounts(self):
        values = self.derive()
        self.assertAlmostEqual(values['priceTrend']['value'], 54)
        self.assertAlmostEqual(values['funding']['value'], 42)
        # Absolute flows rank s4 last in all but the 5d leg; ratios must win.
        self.rows[4]['metrics'].update(netFlow1d=900, amount1d=1000000)
        self.assertEqual(self.derive()['funding']['parts']['flow1d']['value'], 10)

    def test_zero_amount_missing_period_and_incomplete_counts_reduce_coverage(self):
        self.rows[4]['metrics'].update(amount5d=0, unchanged=None)
        values = self.derive()
        self.assertEqual(values['funding']['value'], 10)
        self.assertEqual(values['funding']['coverage'], .6)
        self.assertIsNone(values['breadth']['value'])
        self.assertIn('flow5d.missingInput', values['funding']['missing'])

    def test_breadth_uses_up_down_flat_and_zero_denominator_stays_missing(self):
        self.assertEqual(self.derive()['breadth']['value'], 90)
        self.rows[4]['metrics'].update(advancing=0, declining=0, unchanged=0)
        self.assertIsNone(self.derive()['breadth']['value'])

    def test_persistence_uses_last_five_percentiles_and_top_ten_streak(self):
        self.assertAlmostEqual(self.derive()['persistence']['value'], 32)
        for count, value, coverage in [(2,None,0), (3,60, .6), (4,30, .8), (5,32,1)]:
            with self.subTest(count=count):
                component = self.derive(past=history(count))['persistence']
                if value is None:
                    self.assertIsNone(component['value'])
                else:
                    self.assertAlmostEqual(component['value'],value)
                self.assertAlmostEqual(component['coverage'],coverage)

    def test_relative_strength_subtracts_same_universe_median(self):
        result = self.score()
        self.assertEqual(result['metrics']['relativeStrength20d'],4)
        self.rows += [dict(id='concept', universe='concept', marketDate='2026-11-14',
                           metrics={'return20d':1000000})]
        self.assertEqual(self.score()['metrics']['relativeStrength20d'],4)
        self.assertAlmostEqual(self.derive()['priceTrend']['value'],54)

    def test_current_future_intraday_other_identity_and_wrong_versions_never_enter_baseline(self):
        before = self.derive()
        for change in [dict(marketDate='2026-11-14'), dict(marketDate='2027-01-01'),
                       dict(session='intraday'), dict(universe='concept'),
                       dict(sectorScoringVersion='old'), dict(sectorUniverseVersion='old')]:
            extra = [dict(point, **change) for point in history(250)]
            self.assertEqual(self.derive(past=self.past+extra), before)

    def test_missing_250_positions_stay_missing_instead_of_filling_sixty_day_value(self):
        item = self.derive()['position']
        self.assertIsNone(item['parts']['position250d']['value'])
        self.assertAlmostEqual(item['coverage'],1/6)
        full = self.derive(past=history(250))['position']
        self.assertEqual(full['coverage'],1)
        self.assertFalse(self.score(past=history(60))['coldStart'])
        self.assertTrue(self.score()['coldStart'])

    def test_funds_breadth_momentum_and_activity_improvement_formulas(self):
        values = self.derive()
        for component, want in [('fundsImprovement',53.75), ('breadthImprovement',63),
                                ('momentumImprovement',50), ('activityWarming',79.6)]:
            with self.subTest(component=component):
                self.assertAlmostEqual(values[component]['value'], want)

    def test_three_close_breadth_improvements_need_prior_close_comparisons(self):
        for point in self.past:
            if point['id']=='s4':
                point['metrics']['breadth'] = int(point['marketDate'][-2:])/100
        self.assertEqual(self.derive()['breadthImprovement']['parts']['improvingDays']['value'],100)
        self.assertIsNone(self.derive(past=history(3))['breadthImprovement']['parts']['improvingDays']['value'])

    def test_all_five_risk_components_follow_independent_formulas(self):
        values = self.derive()
        for component, want in [('downsideDiffusion',10), ('fundsWithdrawal',70.8),
                                ('trendDeterioration',34), ('divergence',0), ('crowding',0)]:
            with self.subTest(component=component):
                self.assertAlmostEqual(values[component]['value'],want)

    def test_positive_divergence_maps_the_positive_price_minus_confirmation_gap(self):
        self.rows[4]['metrics'].update(return5d=10, netFlow5d=-1000,
                                      advancing=0, declining=4)
        self.assertAlmostEqual(self.derive()['divergence']['value'], 75)

    def test_activity_crowding_stops_opportunity_reward_and_enables_risk(self):
        self.rows[4]['metrics'].update(turnover=100, amount1d=100000,
                                      netFlow1d=100000, return1d=100)
        values = self.derive()
        self.assertEqual(values['activity']['value'],90)
        self.assertEqual(values['activityWarming']['value'],0)
        self.assertEqual(values['crowding']['value'],90)

    def test_top_level_weights_preserve_raw_precision_and_round_only_public_scores(self):
        result = self.score()
        self.assertEqual((result['strength'],result['opportunity'],result['risk']),(56,44,27))
        self.assertAlmostEqual(result['_rawScores']['strength'],55.6)
        self.assertAlmostEqual(result['_rawScores']['opportunity'],43.9975)
        self.assertAlmostEqual(result['_rawScores']['risk'],27)
        self.assertAlmostEqual(result['axisCompleteness']['opportunity'],79.16666666666667)
        self.assertEqual(result['sectorScoringVersion'],'sector-score-v0.2')
        self.assertEqual(result['sectorUniverseVersion'],'sector-universe-v0.1')
        self.assertNotIn('heat',result)

    def test_high_opportunity_counts_only_funds_breadth_momentum_at_sixty(self):
        self.config['sectorScoring']['weights']['opportunity']={'activityWarming':100}
        self.assertEqual(self.score()['opportunity'],69)  # only breadth passes
        for i,row in enumerate(self.rows):
            row['metrics']['netFlow1d']=i*100
        self.assertEqual(self.score()['opportunity'],86)  # funds and breadth pass; concentration also rises

    def test_opportunity_requires_twenty_valid_closes_and_seventy_percent_coverage(self):
        self.assertIsNone(self.score(past=history(19))['opportunity'])
        for point in self.past:
            point['metrics'].pop('flowRatio1d')
            point['metrics'].pop('breadth')
        self.assertIsNone(self.score()['opportunity'])
        self.assertLess(self.score()['axisCompleteness']['opportunity'],70)

    def test_risk_never_subtracts_from_strength_or_opportunity(self):
        before = self.score()
        self.config['sectorScoring']['weights']['risk']={'fundsWithdrawal':100}
        after = self.score()
        self.assertEqual(after['risk'],71)
        self.assertEqual(after['_rawScores']['strength'],before['_rawScores']['strength'])
        self.assertEqual(after['_rawScores']['opportunity'],before['_rawScores']['opportunity'])

    def test_missing_history_is_not_backfilled_from_current_rolling_fields(self):
        for point in self.past:
            point['metrics']={'relativeStrength20d':-1}
        values=self.derive()
        self.assertIsNone(values['fundsImprovement']['value'])
        self.assertIsNone(values['breadthImprovement']['value'])
        self.assertIsNone(self.score()['opportunity'])

    def test_heat_boundaries_priority_evidence_gate_and_no_continuity_invention(self):
        for activity, mean, concentration, coverage, want in [
                (29.99,0,50,1,'cold'), (30,15,50,1,'warming'), (69.5,54.5,50,1,'warming'),
                (50,36,50,1,None), (70,99,50,1,'active'), (89.99,80,50,1,'active'),
                (90,100,50,1,'crowded'), (1,1,95,1,'crowded'), (90,1,99,.69,None),
                (50,None,50,1,None)]:
            components={'activity':{'value':activity,'coverage':coverage},
                        'activityMean5d':{'value':mean,'coverage':1},
                        'concentration':{'value':concentration,'coverage':coverage}}
            with self.subTest(activity=activity,concentration=concentration):
                self.assertEqual(rotation.classify_heat(components,self.config),want)

    def test_crowded_heat_checks_each_triggers_own_evidence_coverage(self):
        # A blanket activity gate wrongly hides a complete concentration signal;
        # a blanket OR without coverage wrongly promotes incomplete signals.
        for activity, activity_coverage, concentration, concentration_coverage, want in [
                (60,.69,96,1,'crowded'), (None,0,95,1,'crowded'),
                (90,1,None,0,'crowded'), (90,.69,96,.69,None),
                (60,1,96,.69,None), (96,.69,94,1,None), (None,0,96,.69,None)]:
            components={'activity':{'value':activity,'coverage':activity_coverage},
                        'concentration':{'value':concentration,'coverage':concentration_coverage},
                        'activityMean5d':{'value':50,'coverage':1}}
            with self.subTest(activity=activity,activity_coverage=activity_coverage,
                              concentration=concentration,concentration_coverage=concentration_coverage):
                self.assertEqual(rotation.classify_heat(components,self.config),want)

    def test_nonfinite_invalid_negative_denominators_and_large_finite_values_are_safe(self):
        for value in [None,True,float('nan'),float('inf')]:
            self.rows[4]['metrics']['return20d']=value
            self.assertIsNone(self.derive()['priceTrend']['parts']['return20d']['value'])
        self.rows[4]['metrics'].update(amount1d=-1, advancing=-1)
        self.assertIsNone(self.derive()['breadth']['value'])
        self.rows=peers()
        for i,row in enumerate(self.rows):
            row['metrics'].update(return1d=(i-2)*4e307, return5d=(i-2)*4e307,
                                  return20d=(i-2)*4e307)
        result=self.score()
        self.assertTrue(math.isfinite(result['_rawScores']['strength']))
        json.dumps(result,allow_nan=False)

    def test_purity_no_mutation_or_unapproved_input_fields_in_results(self):
        self.rows[4]['rawResponse']={'untrusted':'discard'}
        original=deepcopy((self.rows,self.past,self.config))
        result=self.score()
        self.assertEqual((self.rows,self.past,self.config),original)
        self.assertEqual(self.score(),result)
        self.assertNotIn('rawResponse',result)

    def test_finite_extreme_counts_do_not_overflow_the_breadth_denominator(self):
        self.rows[4]['metrics'].update(advancing=1e308,declining=1e308,unchanged=1e308)
        result=self.score()
        self.assertAlmostEqual(result['metrics']['breadth'],1/3)
        self.assertEqual(result['components']['breadth']['value'],50)

    def test_twenty_closes_do_not_count_a_missing_relative_strength_observation(self):
        self.past[-1]['metrics']['relativeStrength20d']=None
        self.assertEqual(self.score()['validCloses'],19)
        self.assertIsNone(self.score()['opportunity'])

    def test_historical_strength_slope_never_uses_rounded_prior_scores(self):
        for point in self.past:
            point.pop('_rawScores')
        self.assertIsNone(self.derive()['trendDeterioration']['parts']['slope5d']['value'])

    def test_exactly_sixty_is_improvement_evidence_but_single_pulse_is_not_persistence(self):
        self.config['sectorScoring']['weights']['opportunity']={'activityWarming':100}
        for row in self.rows:
            row['metrics']['netFlow1d']=0
        for index,point in enumerate(self.past):
            day=index//5
            point['metrics']['flowRatio1d']=-1 if day<13 else 0 if day<15 else 1
        result=self.score()
        self.assertEqual(result['components']['fundsImprovement']['value'],60)
        self.assertEqual(result['improvementEvidence'],2)
        self.assertEqual(result['opportunity'],83)
        # Current strength rank, including an intraday pulse, cannot extend the
        # historical top-ten streak: that requires a new official close.
        self.rows[4]['metrics']['strengthRank']=1
        self.assertEqual(self.score()['components']['persistence']['value'],32)

    def test_synthetic_fixture_replays_derived_history_without_provider_payloads(self):
        fixture=json.loads((Path(__file__).parents[1]/'fixtures/rotation-history.json').read_text())
        self.assertEqual(self.score(past=fixture['closes'])['components']['persistence']['value'],32)


class ViewTests(unittest.TestCase):
    setUp = RotationTests.setUp
    # These tests catch rounded-score sorting, cross-universe mixing, hidden
    # composites, boundary mistakes, missing-as-zero and unstable ties.
    @staticmethod
    def row(code, strength=69, opportunity=80, risk=30, completeness=100, **extra):
        return dict(id=code,universe='industry',strength=round(strength),opportunity=round(opportunity),
                    risk=round(risk),completeness=completeness,heatState='warming',
                    _rawScores=dict(strength=strength,opportunity=opportunity,risk=risk),
                    change1d=dict(strength=0,risk=0),**extra)

    def test_ranks_use_unrounded_values_then_completeness_then_id_with_universe_isolation(self):
        rows=[self.row('z',strength=70.49),self.row('a',strength=70.01),
              self.row('c',strength=70.49,completeness=99),self.row('b',strength=70.49),
              dict(self.row('other',strength=99),universe='concept')]
        ordered=rotation.rank_sector_scores(rows,'strength')
        self.assertEqual([r['id'] for r in ordered],['other','b','z','c','a'])
        self.assertEqual([r['ranks']['strength'] for r in ordered],[1,1,2,3,4])
        self.assertNotIn('ranks',rows[0])
        with self.assertRaises(ValueError):
            rotation.rank_sector_scores(rows,'heat')

    def test_views_use_exact_boundaries_independent_membership_and_declared_sort_keys(self):
        a=self.row('a',opportunity=80.1); a['change1d']={'strength':1,'risk':10}
        b=self.row('b',opportunity=80.2); b['change1d']={'strength':-1,'risk':0}
        c=self.row('c',strength=70,opportunity=30)
        d=self.row('d',risk=70)
        e=self.row('e'); e['heatState']='crowded'
        f=self.row('f',completeness=69)
        g=self.row('g',strength=70,opportunity=90)
        rows=[a,b,c,d,e,f,g]
        views=rotation.derive_current_views(rows,self.config)
        self.assertEqual([r['id'] for r in views['potentialRotation']],['b','a'])
        self.assertEqual([r['id'] for r in views['confirmedMainline']],['g','c'])
        self.assertEqual([r['id'] for r in views['risingRisk']],['d','a','e'])
        self.assertTrue(all('composite' not in r for view in views.values() for r in view))

    def test_view_ties_use_changes_then_stable_ids_and_missing_axis_is_not_zero(self):
        a=self.row('a'); b=self.row('b'); b['change1d']['strength']=2
        c=self.row('c'); c['risk']=None; c['_rawScores']['risk']=None
        self.assertEqual([r['id'] for r in rotation.derive_current_views([a,c,b],self.config)['potentialRotation']],['b','a'])
        c['heatState']='crowded'
        self.assertEqual([r['id'] for r in rotation.derive_current_views([c],self.config)['risingRisk']],['c'])

    def test_view_predicates_use_published_scores_at_rounding_boundaries(self):
        # Public 70 must satisfy >=70 and fail <70 even when its raw value is 69.8.
        for changes, expected in [
                ({'strength':69.8},{'potentialRotation':[],'confirmedMainline':['a'],'risingRisk':[]}),
                ({'risk':69.8},{'potentialRotation':[],'confirmedMainline':[],'risingRisk':['a']}),
                ({'opportunity':69.8},{'potentialRotation':['a'],'confirmedMainline':[],'risingRisk':[]})]:
            with self.subTest(changes=changes):
                result=rotation.derive_current_views([self.row('a',**changes)],self.config)
                self.assertEqual({key:[row['id'] for row in rows] for key,rows in result.items()},expected)

    def test_public_threshold_members_still_sort_by_unrounded_strength(self):
        # Both publish strength 70, so sorting must not fall through to ID order.
        rows=[self.row('a',strength=69.8),self.row('z',strength=70.2)]
        views=rotation.derive_current_views(rows,self.config)
        self.assertEqual([row['id'] for row in views['confirmedMainline']],['z','a'])

    def test_missing_working_precision_cannot_silently_become_a_rounded_rank(self):
        row=self.row('a')
        row.pop('_rawScores')
        self.assertIsNone(rotation.rank_sector_scores([row],'strength')[0]['ranks']['strength'])

    def test_duplicate_identity_in_a_ranked_universe_is_rejected(self):
        with self.assertRaises(ValueError):
            rotation.rank_sector_scores([self.row('a'),self.row('a')],'strength')


if __name__=='__main__':
    unittest.main()
