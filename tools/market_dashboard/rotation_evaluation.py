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
BASELINES = {
    'strength': ('return5d', 'return20d', 'relativeStrength20d'),
    'opportunity': ('position', 'return5d', 'return20d'),
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


def _eligible(universe, signal, grouped, dates):
    eligible = {}
    for day in dates:
        values = []
        for identity, row in grouped[universe, day].items():
            value = _signal(row, signal)
            if _available(row) and value is not None:
                values.append((identity, value))
        eligible[day] = sorted(values, key=lambda item: (-item[1], item[0]))
    return eligible


def _spread(sample, omit=None):
    high = [value for identity, value in sample['high'] if identity != omit]
    low = [value for identity, value in sample['low'] if identity != omit]
    return mean(high) - mean(low) if high and low else None


def _slice_summary(samples):
    count, names = len(samples), ('early', 'middle', 'late')
    base, remainder = divmod(count, 3)
    sizes = [base + (1 if index < remainder else 0) for index in range(3)]
    result, start = {}, 0
    for name, size in zip(names, sizes):
        selected = samples[start:start + size]
        start += size
        result[name] = {
            'validDates': len(selected),
            'meanRankIc': mean(sample['rankIc'] for sample in selected
                               if sample['rankIc'] is not None) if selected and all(
                                   sample['rankIc'] is not None for sample in selected) else None,
            'meanSpread': mean(_spread(sample) for sample in selected) if selected else None,
            'evidenceStatus': 'SLICE_AVAILABLE' if count >= 3 else 'INSUFFICIENT_EVIDENCE',
        }
    return result


def _summary(samples, date_results):
    finite_ics = [sample['rankIc'] for sample in samples if sample['rankIc'] is not None]
    ic_deviation = None
    if len(finite_ics) >= 2:
        average = mean(finite_ics)
        variance = sum((value - average) ** 2 for value in finite_ics) / (len(finite_ics) - 1)
        ic_deviation = math.sqrt(variance)
    spreads = [_spread(sample) for sample in samples]
    leave_dates = [mean(spreads[:index] + spreads[index + 1:])
                   for index in range(len(spreads))] if len(spreads) >= 2 else []
    identities = {identity for sample in samples for side in ('high', 'low')
                  for identity, _ in sample[side]}
    leave_sectors = []
    for identity in identities:
        values = [_spread(sample, identity) for sample in samples]
        if values and all(value is not None for value in values):
            leave_sectors.append(mean(values))
    return {
        'validDates': len(samples),
        'evidenceStatus': 'SUFFICIENT_FOR_REVIEW' if len(samples) >= 20 else 'INSUFFICIENT_EVIDENCE',
        'meanRankIc': mean(finite_ics) if finite_ics else None,
        'icPositiveRate': mean(value > 0 for value in finite_ics) if finite_ics else None,
        'icInformationRatio': mean(finite_ics) / ic_deviation if ic_deviation else None,
        'meanSpread': mean(spreads) if spreads else None,
        'meanHitRate': mean(sample['hitRate'] for sample in samples) if samples else None,
        'worstTopGroupDrawdown': max((sample['topGroupDrawdown'] for sample in samples), default=None),
        'minimumLeaveOneDateSpread': min(leave_dates, default=None),
        'minimumLeaveOneSectorSpread': min(leave_sectors, default=None),
        'slices': _slice_summary(samples),
        'dates': date_results,
    }


def _evaluate_eligible(universe, eligible, grouped, dates):

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
                      'topGroupDrawdown': drawdown,
                      'high': [(identity, outcomes[identity]) for identity, _ in high],
                      'low': [(identity, outcomes[identity]) for identity, _ in low],
                      'outcomes': outcomes, 'paths': paths}
            samples.append(sample)
            result.update(status='VALID', rankIc=rank_ic, spread=spread,
                          hitRate=hit_rate, topGroupDrawdown=drawdown)
        horizons[str(horizon)] = _summary(samples, date_results)
    return horizons


def _turnover(eligible, dates):
    changes, prior = [], None
    for day in dates:
        scored = eligible[day]
        if not scored:
            continue
        size = max(1, len(scored) // 5)
        current = {identity for identity, _ in scored[:size]}
        if prior is not None:
            changes.append(1 - len(current & prior) / max(len(current), len(prior)))
        prior = current
    return mean(changes) if changes else None


def _evaluate_signal(universe, signal, grouped, dates):
    eligible = _eligible(universe, signal, grouped, dates)
    return {'direction': 'lower-is-better' if signal == 'risk' else 'higher-is-better',
            'nativeCoverage': _native_coverage(eligible, dates),
            'topQuintileTurnover': _turnover(eligible, dates),
            'horizons': _evaluate_eligible(universe, eligible, grouped, dates)}


def _comparison(universe, model, baseline, grouped, dates):
    model_native = _eligible(universe, model, grouped, dates)
    baseline_native = _eligible(universe, baseline, grouped, dates)
    model_common, baseline_common = {}, {}
    for day in dates:
        model_values, baseline_values = dict(model_native[day]), dict(baseline_native[day])
        common = model_values.keys() & baseline_values.keys()
        model_common[day] = sorted(((identity, model_values[identity]) for identity in common),
                                   key=lambda item: (-item[1], item[0]))
        baseline_common[day] = sorted(((identity, baseline_values[identity]) for identity in common),
                                      key=lambda item: (-item[1], item[0]))
    model_results = _evaluate_eligible(universe, model_common, grouped, dates)
    baseline_results = _evaluate_eligible(universe, baseline_common, grouped, dates)
    horizons = {}
    for horizon in map(str, HORIZONS):
        model_result, baseline_result = model_results[horizon], baseline_results[horizon]
        horizons[horizon] = {
            'validDates': model_result['validDates'],
            'evidenceStatus': model_result['evidenceStatus'],
            'dates': model_result['dates'],
            'model': {key: model_result[key] for key in ('meanRankIc', 'meanSpread', 'meanHitRate')},
            'baseline': {key: baseline_result[key] for key in ('meanRankIc', 'meanSpread', 'meanHitRate')},
            'delta': {
                'meanRankIc': (model_result['meanRankIc'] - baseline_result['meanRankIc']
                               if all(_number(value) for value in (model_result['meanRankIc'], baseline_result['meanRankIc'])) else None),
                'meanSpread': (model_result['meanSpread'] - baseline_result['meanSpread']
                               if all(_number(value) for value in (model_result['meanSpread'], baseline_result['meanSpread'])) else None),
            },
        }
    return {'commonCoverage': _native_coverage(model_common, dates), 'horizons': horizons}


def _risk_diagnostics(universe, grouped, dates):
    raw = {}
    for day in dates:
        values = []
        for identity, row in grouped[universe, day].items():
            value = row.get('_rawScores', {}).get('risk')
            completeness = row.get('axisCompleteness', {}).get('risk')
            if _available(row) and _number(value, 0, 100) and _number(completeness, 70, 100):
                values.append((identity, value))
        raw[day] = sorted(values, key=lambda item: (-item[1], item[0]))
    evaluated = _evaluate_eligible(universe, raw, grouped, dates)
    result = {}
    for horizon, summary in evaluated.items():
        negative_spreads, drawdown_spreads = [], []
        # Reconstruct dedicated risk statistics only for dates already proven valid.
        for index, point in enumerate(summary['dates']):
            if point['status'] != 'VALID':
                continue
            day = dates[index]
            scored, length = raw[day], int(horizon)
            size = max(1, len(scored) // 5)
            outcomes, drawdowns = {}, {}
            for identity, _ in scored:
                wealth, path = 1.0, []
                for forward_day in dates[index + 1:index + length + 1]:
                    value = grouped[universe, forward_day][identity]['metrics']['return1d']
                    wealth *= 1 + value / 100
                    path.append(wealth)
                outcomes[identity] = (wealth - 1) * 100
                drawdowns[identity] = _drawdown([path])
            high, low = scored[:size], scored[-size:]
            negative_spreads.append(mean(outcomes[identity] < 0 for identity, _ in high)
                                    - mean(outcomes[identity] < 0 for identity, _ in low))
            drawdown_spreads.append(mean(drawdowns[identity] for identity, _ in high)
                                    - mean(drawdowns[identity] for identity, _ in low))
        result[horizon] = {
            'validDates': len(negative_spreads),
            'evidenceStatus': summary['evidenceStatus'],
            'highMinusLowNegativeReturnRate': mean(negative_spreads) if negative_spreads else None,
            'highMinusLowMaximumDrawdown': mean(drawdown_spreads) if drawdown_spreads else None,
            'interpretation': 'HIGHER_RAW_RISK_IDENTIFIES_WORSE_OUTCOMES',
        }
    return {'horizons': result}


def evaluate(rows: list[dict], official_dates: list[str], config: dict) -> dict:
    """Evaluate current scores without fitting or mutating the supplied rows."""
    dates = calendar_dates(official_dates)
    grouped, versions = _validate(rows, dates, config)
    universes = {}
    for universe in ('industry', 'concept'):
        signals = {
            signal: _evaluate_signal(universe, signal, grouped, dates) for signal in SIGNALS
        }
        signals['risk']['riskDiagnostics'] = _risk_diagnostics(universe, grouped, dates)
        comparisons = {model: {baseline: _comparison(universe, model, baseline, grouped, dates)
                               for baseline in baselines}
                       for model, baselines in BASELINES.items()}
        universes[universe] = {'signals': signals, 'comparisons': comparisons}
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
