from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.market_dashboard.scoring import load_config
from tools.market_dashboard.sources import INDUSTRY_DEFINITIONS
from tools.market_dashboard.concepts import concept_definitions, load_concept_config
from tools.market_dashboard import rotation_evaluation, rotation_store


def trading_dates(count=12):
    return [(date(2026, 10, 1) + timedelta(days=index)).isoformat() for index in range(count)]


def sample_rows(count=12):
    config = load_config()
    dates = trading_dates(count)
    identities = [identity for identity, _ in INDUSTRY_DEFINITIONS[:10]]
    rows = []
    for day_index, day in enumerate(dates):
        for index, identity in enumerate(identities):
            score = 100 - index * 10
            rows.append({
                'id': identity,
                'universe': 'industry',
                'marketDate': day,
                'session': 'close',
                'officialClose': True,
                'observedAt': day + 'T15:05:00+08:00',
                'sectorScoringVersion': config['sectorScoringVersion'],
                'sectorUniverseVersion': config['sectorUniverseVersion'],
                '_rawScores': {'strength': score, 'opportunity': score, 'risk': index * 10},
                'axisCompleteness': {'strength': 90, 'opportunity': 90, 'risk': 90},
                'completeness': 90,
                'validCloses': 25,
                'components': {'position': {'value': score, 'coverage': 1, 'missing': []}},
                'metrics': {
                    'return1d': 5 - index,
                    'return5d': score,
                    'return20d': score,
                    'relativeStrength20d': score,
                },
            })
    return rows, dates, config, identities


def canonical_state(day='2026-10-01'):
    rows = []
    for universe, definitions in [('industry', INDUSTRY_DEFINITIONS),
                                  ('concept', concept_definitions(load_concept_config()))]:
        for identity, name in definitions:
            rows.append({
                'id': identity, 'name': name, 'universe': universe,
                'marketDate': day, 'session': 'close',
                'observedAt': day + 'T15:00:02+08:00',
                'strength': 80, 'opportunity': None, 'risk': 20,
                '_rawScores': {'strength': 80.49, 'opportunity': None, 'risk': 20.1},
                'completeness': 80,
                'components': {'breadth': {'value': 50.0, 'coverage': 1.0, 'missing': []}},
                'metrics': {'return20d': 2.0, 'relativeStrength20d': 0.0, 'flowRatio1d': None},
                'heatState': 'active', 'missing': ['flow.missingInput'],
                'sectorScoringVersion': 'sector-score-v0.2',
                'sectorUniverseVersion': 'sector-universe-v0.1',
            })
    payload = {
        'schemaVersion': 'market-dashboard-v3',
        'sectorScoringVersion': 'sector-score-v0.2',
        'sectorUniverseVersion': 'sector-universe-v0.1',
        'marketDate': day, 'session': 'close',
        'observedAt': day + 'T15:05:00+08:00', 'officialClose': True,
        'sectors': rows,
    }
    return rotation_store.append_rotation_close({}, payload, load_config())


class RotationEvaluationCoreTests(unittest.TestCase):
    def test_evaluates_exact_forward_horizons_with_hand_checked_metrics(self):
        rows, dates, config, _ = sample_rows()

        report = rotation_evaluation.evaluate(rows, dates, config)

        self.assertEqual(report['schemaVersion'], 'sector-score-evaluation-v1')
        self.assertEqual(report['evidenceStatus'], 'CALCULATION_ONLY')
        self.assertFalse(report['liveVerified'])
        opportunity = report['universes']['industry']['signals']['opportunity']
        self.assertEqual(opportunity['nativeCoverage']['scoreDates'], 12)
        for horizon, valid in [('1', 11), ('3', 9), ('5', 7), ('10', 2)]:
            result = opportunity['horizons'][horizon]
            self.assertEqual(result['validDates'], valid)
            self.assertAlmostEqual(result['meanRankIc'], 1)
            self.assertGreater(result['meanSpread'], 0)
            self.assertEqual(result['meanHitRate'], 1)
            self.assertEqual(result['worstTopGroupDrawdown'], 0)
        self.assertEqual(opportunity['horizons']['10']['dates'][-1]['status'], 'UNMATURED_OUTCOME')

    def test_missing_one_forward_identity_invalidates_the_whole_score_date(self):
        rows, dates, config, identities = sample_rows()
        rows = [row for row in rows
                if not (row['marketDate'] == dates[1] and row['id'] == identities[-1])]

        report = rotation_evaluation.evaluate(rows, dates, config)

        first = report['universes']['industry']['signals']['opportunity']['horizons']['1']['dates'][0]
        self.assertEqual(first['status'], 'MISSING_FORWARD_RETURNS')
        self.assertEqual(first['sampleCount'], 10)

    def test_future_availability_excludes_the_score_before_outcomes_are_seen(self):
        rows, dates, config, _, = sample_rows()
        for row in rows:
            if row['marketDate'] == dates[0]:
                row['availableAt'] = dates[1] + 'T09:00:00+08:00'

        report = rotation_evaluation.evaluate(rows, dates, config)

        first = report['universes']['industry']['signals']['strength']['horizons']['1']['dates'][0]
        self.assertEqual(first['status'], 'NO_PIT_SCORES')
        self.assertEqual(report['universes']['industry']['signals']['strength']['nativeCoverage']['scoreDates'], 11)

    def test_compounded_path_drawdown_uses_starting_wealth_as_peak(self):
        rows, dates, config, identities = sample_rows()
        for row in rows:
            day = dates.index(row['marketDate'])
            if row['id'] in identities[:2]:
                row['metrics']['return1d'] = (10, -20, 10)[(day - 1) % 3]
            else:
                row['metrics']['return1d'] = 0

        report = rotation_evaluation.evaluate(rows, dates, config)

        first = report['universes']['industry']['signals']['opportunity']['horizons']['3']['dates'][0]
        self.assertAlmostEqual(first['spread'], -3.2)
        self.assertAlmostEqual(first['topGroupDrawdown'], 20)
        self.assertEqual(first['hitRate'], 0)


class RotationEvaluationRobustnessTests(unittest.TestCase):
    def test_reports_ic_stability_turnover_slices_and_leave_one_out_checks(self):
        rows, dates, config, _ = sample_rows()

        report = rotation_evaluation.evaluate(rows, dates, config)

        signal = report['universes']['industry']['signals']['strength']
        self.assertEqual(signal['topQuintileTurnover'], 0)
        horizon = signal['horizons']['1']
        self.assertEqual(horizon['icPositiveRate'], 1)
        self.assertIsNone(horizon['icInformationRatio'])
        self.assertGreater(horizon['minimumLeaveOneDateSpread'], 0)
        self.assertGreater(horizon['minimumLeaveOneSectorSpread'], 0)
        self.assertEqual([horizon['slices'][name]['validDates']
                          for name in ('early', 'middle', 'late')], [4, 4, 3])
        self.assertEqual(horizon['evidenceStatus'], 'INSUFFICIENT_EVIDENCE')

    def test_model_baseline_comparison_uses_same_date_identity_intersection(self):
        rows, dates, config, identities = sample_rows()
        for row in rows:
            if row['id'] == identities[-1]:
                row['components']['position']['value'] = None

        report = rotation_evaluation.evaluate(rows, dates, config)

        opportunity = report['universes']['industry']['signals']['opportunity']
        position = report['universes']['industry']['signals']['position']
        comparison = report['universes']['industry']['comparisons']['opportunity']['position']['horizons']['1']
        self.assertEqual(opportunity['nativeCoverage']['maximumSectors'], 10)
        self.assertEqual(position['nativeCoverage']['maximumSectors'], 9)
        self.assertEqual(comparison['validDates'], 11)
        self.assertTrue(all(point['sampleCount'] == 9 for point in comparison['dates']
                            if point['status'] == 'VALID'))
        self.assertEqual(set(report['universes']['industry']['comparisons']['strength']),
                         {'return5d', 'return20d', 'relativeStrength20d'})
        self.assertEqual(set(report['universes']['industry']['comparisons']['opportunity']),
                         {'position', 'return5d', 'return20d'})
        self.assertNotIn('risk', report['universes']['industry']['comparisons'])

    def test_raw_risk_diagnostics_reward_identifying_losses_and_drawdowns(self):
        rows, dates, config, identities = sample_rows()
        for row in rows:
            index = identities.index(row['id'])
            row['metrics']['return1d'] = 2 - index

        report = rotation_evaluation.evaluate(rows, dates, config)

        risk = report['universes']['industry']['signals']['risk']
        returns = risk['horizons']['1']
        diagnostics = risk['riskDiagnostics']['horizons']['1']
        self.assertGreater(returns['meanRankIc'], 0)
        self.assertEqual(risk['direction'], 'higher-is-better')
        self.assertEqual(risk['rawDirection'], 'higher-is-worse')
        self.assertEqual(diagnostics['highMinusLowNegativeReturnRate'], 1)
        self.assertGreater(diagnostics['highMinusLowMaximumDrawdown'], 0)
        self.assertEqual(diagnostics['interpretation'], 'HIGHER_RAW_RISK_IDENTIFIES_WORSE_OUTCOMES')

    def test_overlapping_horizons_disclose_effective_independent_evidence(self):
        rows, dates, config, _ = sample_rows(31)

        report = rotation_evaluation.evaluate(rows, dates, config)

        horizons = report['universes']['industry']['signals']['strength']['horizons']
        self.assertEqual(horizons['1']['effectiveIndependentDates'], 30)
        self.assertEqual(horizons['1']['evidenceStatus'], 'SUFFICIENT_FOR_REVIEW')
        self.assertEqual(horizons['3']['effectiveIndependentDates'], 10)
        self.assertEqual(horizons['3']['evidenceStatus'], 'INSUFFICIENT_EVIDENCE')
        self.assertIn('NO_OVERLAP_ADJUSTMENT', report['limitations'])
        self.assertEqual(report['inputAudit']['inputRows'], len(rows))
        self.assertEqual(report['method']['tieRule'], 'SCORE_DESC_THEN_SECTOR_ID')


class RotationEvaluationCliTests(unittest.TestCase):
    def run_cli(self, state, dates, *extra):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path, calendar_path = root / 'state.json', root / 'calendar.json'
            state_path.write_text(json.dumps(state))
            calendar_path.write_text(json.dumps(dates))
            return subprocess.run(
                [sys.executable, '-m', 'tools.market_dashboard.rotation_evaluation',
                 '--state', str(state_path), '--calendar', str(calendar_path), *extra],
                cwd=Path(__file__).resolve().parents[3], capture_output=True, text=True,
            )

    def test_cli_emits_parseable_json_and_human_markdown_without_writing_files(self):
        dates = ['2026-10-01']
        state = {'rotation': canonical_state()}

        json_result = self.run_cli(state, dates)
        markdown_result = self.run_cli(state, dates, '--format', 'markdown')

        self.assertEqual(json_result.returncode, 0, json_result.stderr)
        self.assertEqual(json.loads(json_result.stdout)['schemaVersion'], 'sector-score-evaluation-v1')
        self.assertEqual(markdown_result.returncode, 0, markdown_result.stderr)
        self.assertIn('# 板块评分评价报告', markdown_result.stdout)
        self.assertIn('仅用于计算检验', markdown_result.stdout)
        self.assertIn('| 维度 | 周期 | 有效日期 | 非重叠证据日 | Rank IC |', markdown_result.stdout)
        self.assertIn('样本不足', markdown_result.stdout)

    def test_cli_rejects_partial_noncanonical_state_even_when_evaluate_accepts_fixture(self):
        rows, dates, config, _ = sample_rows()
        self.assertEqual(rotation_evaluation.evaluate(rows, dates, config)['schemaVersion'],
                         'sector-score-evaluation-v1')

        result = self.run_cli({'rotation': {'closes': rows}}, dates)

        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['safeErrorCode'], 'INVALID_EVALUATION_INPUT')

    def test_cli_invalid_input_returns_format_appropriate_safe_error_without_traceback(self):
        json_result = self.run_cli([], ['2026-10-01'])
        markdown_result = self.run_cli([], ['2026-10-01'], '--format', 'markdown')

        self.assertEqual(json_result.returncode, 1)
        self.assertEqual(json.loads(json_result.stdout), {
            'evidenceStatus': 'CALCULATION_ONLY',
            'liveVerified': False,
            'safeErrorCode': 'INVALID_EVALUATION_INPUT',
        })
        self.assertEqual(markdown_result.returncode, 1)
        self.assertIn('INVALID_EVALUATION_INPUT', markdown_result.stdout)
        self.assertNotIn('Traceback', json_result.stderr + markdown_result.stderr)

    def test_markdown_renderer_uses_report_values_and_preserves_evidence_warning(self):
        rows, dates, config, _ = sample_rows()
        report = rotation_evaluation.evaluate(rows, dates, config)

        markdown = rotation_evaluation.render_markdown(report)

        self.assertIn(config['sectorScoringVersion'], markdown)
        self.assertIn('1日', markdown)
        self.assertIn('机会', markdown)
        self.assertIn('INSUFFICIENT_EVIDENCE', markdown)


if __name__ == '__main__':
    unittest.main()


class HithinkEvaluationTests(unittest.TestCase):
    def test_v4_replay_separates_membership_modes_and_keeps_forward_outcomes(self):
        rows,dates,_,_=sample_rows(12)
        config=json.loads(Path('config/hithink-sector-dashboard.json').read_text())
        for index,row in enumerate(rows):
            row.update(id='881%03d.TI' % (index%10),schemaVersion='market-dashboard-v4',
                       sectorScoringVersion=config['scoreVersion'],sectorUniverseVersion=config['universeVersion'],
                       featureVersion=config['featureVersion'],membershipVersion=config['membershipVersion'],
                       membershipMode='point_in_time_snapshot' if row['marketDate']>=dates[5] else 'current_members_backfill')
        old=deepcopy(rows)
        result=rotation_evaluation.evaluate_v4(rows,dates,config,
            {'industry':{r['id'] for r in rows},'concept':set()})
        self.assertEqual(rows,old)
        strict=result['membershipSensitivity']['point_in_time_snapshot']['universes']['industry']['signals']['strength']
        approx=result['membershipSensitivity']['current_members_backfill']['universes']['industry']['signals']['strength']
        self.assertEqual(strict['nativeCoverage']['scoreDates'],7)
        self.assertEqual(approx['nativeCoverage']['scoreDates'],5)
        # Approximate membership may score on day 5 and mature on strict day 6;
        # the outcome is the official index and does not inherit membership bias.
        self.assertEqual(approx['horizons']['1']['validDates'],5)
        self.assertEqual(result['inputAudit']['membershipModes'],{'current_members_backfill':50,'point_in_time_snapshot':70})
        self.assertEqual(result['versions']['sectorScoringVersion'],'sector-score-v0.3')

    def test_v4_rejects_unknown_provenance_and_cross_version(self):
        c=json.loads(Path('config/hithink-sector-dashboard.json').read_text())
        rows,dates,_,_=sample_rows(2)
        with self.assertRaises(ValueError): rotation_evaluation.evaluate_v4(rows,dates,c)
