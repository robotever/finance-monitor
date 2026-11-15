from copy import deepcopy
from datetime import date, timedelta
import unittest

from tools.market_dashboard.scoring import load_config
from tools.market_dashboard.sources import INDUSTRY_DEFINITIONS
from tools.market_dashboard import rotation_evaluation


def trading_dates(count=12):
    return [(date(2026, 10, 1) + timedelta(days=index)).isoformat() for index in range(count)]


def sample_rows(count=12):
    config = load_config()
    dates = trading_dates(count)
    identities = [identity for identity, _ in INDUSTRY_DEFINITIONS[:5]]
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
        self.assertEqual(first['sampleCount'], 5)

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
            if row['id'] == identities[0]:
                row['metrics']['return1d'] = (10, -20, 10)[(day - 1) % 3]
            else:
                row['metrics']['return1d'] = 0

        report = rotation_evaluation.evaluate(rows, dates, config)

        first = report['universes']['industry']['signals']['opportunity']['horizons']['3']['dates'][0]
        self.assertAlmostEqual(first['spread'], -3.2)
        self.assertAlmostEqual(first['topGroupDrawdown'], 20)
        self.assertEqual(first['hitRate'], 0)


if __name__ == '__main__':
    unittest.main()
