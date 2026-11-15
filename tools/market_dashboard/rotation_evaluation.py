"""Read-only point-in-time evaluation of versioned sector scores.

The evaluator never collects, fits, persists or publishes data. Forward returns
are outcomes only and start on the next exact official market date.
"""
from collections import defaultdict
import math
from statistics import mean

from .concepts import concept_definitions, load_concept_config
from .rotation_operations import VERSIONS, calendar_dates, timestamp
from .sources import INDUSTRY_DEFINITIONS


HORIZONS = (1, 3, 5, 10)
SIGNALS = {
    'strength': ('axis', 1),
    'opportunity': ('axis', 1),
    'risk': ('axis', -1),
    'return5d': ('metric', 1),
    'return20d': ('metric', 1),
    'relativeStrength20d': ('metric', 1),
    'position': ('component', 1),
}


def _number(value, low=-math.inf, high=math.inf):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


def _ranks(values):
    return [sum(other < value for other in values)
            + (sum(other == value for other in values) + 1) / 2 for value in values]


def _rank_ic(scores, outcomes):
    x, y = _ranks(scores), _ranks(outcomes)
    mx, my = mean(x), mean(y)
    denominator = math.sqrt(sum((value - mx) ** 2 for value in x)
                            * sum((value - my) ** 2 for value in y))
    return sum((left - mx) * (right - my) for left, right in zip(x, y)) / denominator if denominator else None


def _drawdown(paths):
    peak, worst = 1.0, 0.0
    for wealth in (mean(point) for point in zip(*paths)):
        peak = max(peak, wealth)
        worst = max(worst, (peak - wealth) / peak * 100)
    return worst


def _available(row):
    try:
        day = row['marketDate']
        observed = timestamp(row.get('observedAt'))
        available = timestamp(row.get('availableAt', row.get('observedAt')))
        return (timestamp(day + 'T15:00:00+08:00') <= observed
                <= timestamp(day + 'T15:30:00+08:00') and available <= observed)
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _signal(row, key):
    source, direction = SIGNALS[key]
    if source == 'axis':
        value = row.get('_rawScores', {}).get(key)
        completeness = row.get('axisCompleteness', {}).get(key)
        if not _number(completeness, 70, 100):
            return None
        if key == 'opportunity' and not _number(row.get('validCloses'), 20):
            return None
    elif source == 'metric':
        value = row.get('metrics', {}).get(key)
    else:
        value = row.get('components', {}).get(key, {}).get('value')
    if not _number(value):
        return None
    return value if direction > 0 else -value


def _validate(rows, dates, config):
    if not isinstance(rows, list):
        raise ValueError('INVALID_STATE')
    definitions = {
        'industry': {identity for identity, _ in INDUSTRY_DEFINITIONS},
        'concept': {identity for identity, _ in concept_definitions(load_concept_config())},
    }
    versions = {key: config[key] for key in VERSIONS}
    grouped, seen = defaultdict(dict), set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('INVALID_STATE')
        universe, identity, day = row.get('universe'), row.get('id'), row.get('marketDate')
        if universe not in definitions or identity not in definitions[universe]:
            raise ValueError('IDENTITY_MISMATCH')
        if any(row.get(key) != value for key, value in versions.items()):
            raise ValueError('VERSION_MISMATCH')
        if day not in dates or row.get('session') != 'close' or row.get('officialClose') is not True:
            continue
        key = day, universe, identity
        if key in seen:
            raise ValueError('DUPLICATE_CLOSE')
        seen.add(key)
        grouped[universe, day][identity] = row
    return grouped, versions


def _native_coverage(eligible, dates):
    counts = [len(eligible[day]) for day in dates if eligible[day]]
    return {
        'scoreDates': len(counts),
        'observations': sum(counts),
        'minimumSectors': min(counts, default=0),
        'maximumSectors': max(counts, default=0),
    }


def _evaluate_signal(universe, signal, grouped, dates):
    eligible = {}
    for day in dates:
        values = []
        for identity, row in grouped[universe, day].items():
            value = _signal(row, signal)
            if _available(row) and value is not None:
                values.append((identity, value))
        eligible[day] = sorted(values, key=lambda item: (-item[1], item[0]))

    horizons = {}
    for horizon in HORIZONS:
        samples, date_results = [], []
        for index, day in enumerate(dates):
            scored = eligible[day]
            result = {'marketDate': day, 'status': 'NO_PIT_SCORES', 'sampleCount': len(scored)}
            date_results.append(result)
            if len(scored) < 2:
                continue
            if index + horizon >= len(dates):
                result['status'] = 'UNMATURED_OUTCOME'
                continue
            outcomes, paths = {}, {}
            for identity, _ in scored:
                wealth, path = 1.0, []
                for forward_day in dates[index + 1:index + horizon + 1]:
                    future = grouped[universe, forward_day].get(identity, {})
                    daily_return = future.get('metrics', {}).get('return1d')
                    if not _available(future) or not _number(daily_return, -100, 100000):
                        break
                    wealth *= 1 + daily_return / 100
                    path.append(wealth)
                if len(path) == horizon:
                    outcomes[identity], paths[identity] = (wealth - 1) * 100, path
            if len(outcomes) != len(scored):
                result['status'] = 'MISSING_FORWARD_RETURNS'
                continue
            group_size = max(1, len(scored) // 5)
            high, low = scored[:group_size], scored[-group_size:]
            benchmark = mean(outcomes.values())
            rank_ic = _rank_ic([value for _, value in scored], [outcomes[identity] for identity, _ in scored])
            spread = mean(outcomes[identity] for identity, _ in high) - mean(outcomes[identity] for identity, _ in low)
            hit_rate = mean(outcomes[identity] > benchmark for identity, _ in high)
            drawdown = _drawdown([paths[identity] for identity, _ in high])
            sample = {'rankIc': rank_ic, 'spread': spread, 'hitRate': hit_rate,
                      'topGroupDrawdown': drawdown}
            samples.append(sample)
            result.update(status='VALID', rankIc=rank_ic, spread=spread,
                          hitRate=hit_rate, topGroupDrawdown=drawdown)
        finite_ics = [sample['rankIc'] for sample in samples if sample['rankIc'] is not None]
        horizons[str(horizon)] = {
            'validDates': len(samples),
            'evidenceStatus': 'SUFFICIENT_FOR_REVIEW' if len(samples) >= 20 else 'INSUFFICIENT_EVIDENCE',
            'meanRankIc': mean(finite_ics) if finite_ics else None,
            'meanSpread': mean(sample['spread'] for sample in samples) if samples else None,
            'meanHitRate': mean(sample['hitRate'] for sample in samples) if samples else None,
            'worstTopGroupDrawdown': max((sample['topGroupDrawdown'] for sample in samples), default=None),
            'dates': date_results,
        }
    return {'direction': 'lower-is-better' if signal == 'risk' else 'higher-is-better',
            'nativeCoverage': _native_coverage(eligible, dates), 'horizons': horizons}


def evaluate(rows: list[dict], official_dates: list[str], config: dict) -> dict:
    """Evaluate current scores without fitting or mutating the supplied rows."""
    dates = calendar_dates(official_dates)
    grouped, versions = _validate(rows, dates, config)
    universes = {}
    for universe in ('industry', 'concept'):
        universes[universe] = {'signals': {
            signal: _evaluate_signal(universe, signal, grouped, dates) for signal in SIGNALS
        }}
    return {
        'schemaVersion': 'sector-score-evaluation-v1',
        'versions': versions,
        'evidenceStatus': 'CALCULATION_ONLY',
        'liveVerified': False,
        'officialDates': dates,
        'universes': universes,
        'limitations': ['NO_AUTOMATIC_WEIGHT_TUNING', 'NO_TRANSACTION_COSTS',
                        'CANONICAL_STATE_DOES_NOT_REPROVE_PROVIDER_ARRIVAL'],
    }
