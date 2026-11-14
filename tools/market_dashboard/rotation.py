"""Pure v0.2 sector scoring, with no provider access or state mutation.

Current rows are validated observations with id, universe (industry/concept),
marketDate, session and ``metrics``. Metrics use returns in one consistent unit,
netFlow1d/5d/20d and amount1d/5d/20d in the same currency unit, turnover,
marketAmount, and advancing/declining/unchanged counts. A missing period's
amount is never inferred from today's amount.

``prior_closes`` is a flat list of earlier *derived* sector rows across both
universes. It must have matching sectorScoringVersion/sectorUniverseVersion,
session=close and the metrics emitted by score_sector, plus strengthPercentile
and strengthRank from that close's full-universe ranking. Historical ratios or
breadth are never reconstructed from current rolling fields. The caller owns
validation of identities, units, timestamps and official close eligibility.

``_rawScores`` is private working precision for sorting. Publication must strip
private keys. Audit components contain normalized values, nested coverage,
configured/effective weights and missing reasons; they contain no provider
responses. The returned metrics are derived historical inputs, not an I/O cache.
"""
import math

from .scoring import score_normalized_components


def _number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _finite(value):
    return float(value) if _number(value) else None


def _mean(values):
    return math.fsum(v / len(values) for v in values) if values else None


def _difference(left, right):
    return _finite(left - right) if _number(left) and _number(right) else None


def _ratio(numerator, denominator):
    if not _number(numerator) or not _number(denominator) or denominator <= 0:
        return None
    return _finite(numerator / denominator)


def _percentile(values, value, config, reverse=False):
    """Midpoint ties and linear 5/95 winsorization, stable at finite extremes."""
    valid = sorted(float(v) for v in values if _number(v))
    if not valid or not _number(value):
        return None
    def quantile(fraction):
        index = (len(valid) - 1) * fraction
        lower, upper = math.floor(index), math.ceil(index)
        proportion = index - lower
        return valid[lower] * (1 - proportion) + valid[upper] * proportion
    lower = quantile(config['normalization']['winsorLower'])
    upper = quantile(config['normalization']['winsorUpper'])
    clipped = [min(upper, max(lower, v)) for v in valid]
    target = min(upper, max(lower, value))
    percentile = (sum(v < target for v in clipped) + .5 * sum(v == target for v in clipped)) / len(valid) * 100
    return 100 - percentile if reverse else percentile


def position_curve(percentile: float | None) -> float | None:
    """Reward low-but-recovering positions; reject the bottom and extension."""
    if not _number(percentile):
        return None
    if percentile < 10 or percentile >= 70:
        return 0.
    if percentile <= 35:
        return (percentile - 10) * 4
    return (70 - percentile) / 35 * 100


def _leaf(value, coverage=1., reason='missingInput'):
    value = _finite(value)
    return {'value': value, 'coverage': coverage if value is not None else 0.,
            'missing': [] if value is not None else [reason]}


def _combine(parts, weights):
    scored = score_normalized_components(parts, weights)
    effective = math.fsum(weight * parts.get(key, {}).get('coverage', 0)
                          for key, weight in weights.items()
                          if _number(parts.get(key, {}).get('value')))
    return {'value': scored.raw, 'coverage': effective / scored.total_weight if scored.total_weight else 0.,
            'usedWeight': scored.used_weight, 'totalWeight': scored.total_weight,
            'effectiveWeight': effective,
            'missing': [f'{key}.{reason}' for key in weights
                        for reason in parts.get(key, _leaf(None))['missing']],
            'parts': parts}


def _values(points, key, count):
    """A trailing N-close baseline needs all N dated observations, no gap fill."""
    values = [point.get('metrics', {}).get(key) for point in points[-count:]]
    return values if len(values) == count and all(_number(value) for value in values) else []


def _metrics(row):
    source = row.get('metrics', {})
    values = {key: _finite(source.get(key)) for key in ('return1d', 'return5d', 'return20d', 'turnover')}
    for period in ('1d', '5d', '20d'):
        values['flowRatio' + period] = _ratio(source.get('netFlow' + period), source.get('amount' + period))
    counts = [source.get(key) for key in ('advancing', 'declining', 'unchanged')]
    # Scale before summing: three finite counts can overflow their raw sum.
    scale = max(counts) if all(_number(n) and n >= 0 for n in counts) else None
    scaled = [n / scale for n in counts] if scale else []
    total = math.fsum(scaled) if scaled else None
    values['breadth'] = _ratio(scaled[0], total) if scaled else None
    values['decliningShare'] = _ratio(scaled[1], total) if scaled else None
    values['marketShare'] = _ratio(source.get('amount1d'), source.get('marketAmount'))
    flow = source.get('netFlow1d')
    values['concentration'] = _ratio(abs(flow) if _number(flow) else None, source.get('amount1d'))
    values['shortAcceleration'] = _difference(values['return1d'], values['return5d'] / 5 if values['return5d'] is not None else None)
    values['mediumAcceleration'] = _difference(values['return5d'] / 5 if values['return5d'] is not None else None,
                                               values['return20d'] / 20 if values['return20d'] is not None else None)
    return values


def _context(current, prior_closes, universe_current, config):
    universe, sector_id, today = current.get('universe'), current.get('id'), current.get('marketDate')
    if universe not in ('industry', 'concept') or not isinstance(sector_id, str) or not isinstance(today, str):
        raise ValueError('INVALID_SECTOR_IDENTITY')
    rows = [row for row in universe_current if row.get('universe') == universe and row.get('marketDate') == today]
    ids = [row.get('id') for row in rows]
    if sector_id not in ids or len(ids) != len(set(ids)):
        raise ValueError('INVALID_SECTOR_UNIVERSE')
    rows = [current if row['id'] == sector_id else row for row in rows]
    for row in rows:
        for key in ('sectorScoringVersion', 'sectorUniverseVersion'):
            if key in row and row[key] != config[key]:
                raise ValueError('INCOMPARABLE_SECTOR_VERSION')
    histories = {row['id']: [] for row in rows}
    seen = set()
    for point in prior_closes:
        identity, day = point.get('id'), point.get('marketDate')
        if (point.get('universe') != universe or identity not in histories or point.get('session') != 'close'
            or not isinstance(day, str) or day >= today
            or any(point.get(key) != config[key] for key in ('sectorScoringVersion', 'sectorUniverseVersion'))):
            continue
        if (identity, day) in seen:
            raise ValueError('DUPLICATE_SECTOR_CLOSE')
        seen.add((identity, day))
        histories[identity].append(point)
    for points in histories.values():
        points.sort(key=lambda point: point['marketDate'])
    return rows, histories


def _derive(current, prior_closes, universe_current, config):
    rows, histories = _context(current, prior_closes, universe_current, config)
    settings = config['sectorScoring']
    weights, windows = settings['componentWeights'], settings['history']
    ids = [row['id'] for row in rows]
    metrics = {row['id']: _metrics(row) for row in rows}
    components = {sector_id: {} for sector_id in ids}
    def cross(key, sector_id, reverse=False):
        return _percentile([metrics[item].get(key) for item in ids], metrics[sector_id].get(key), config, reverse)
    def composite(sector_id, name, parts):
        components[sector_id][name] = _combine(parts, weights[name])
    def baseline(sector_id, key, count=None):
        return _mean(_values(histories[sector_id], key, count or windows['shortBaseline']))
    relative = sorted(m['return20d'] for m in metrics.values() if m['return20d'] is not None)
    size = len(relative)
    median = _mean(relative[(size-1)//2:size//2+1]) if size else None
    for sector_id in ids:
        m, c, past = metrics[sector_id], components[sector_id], histories[sector_id]
        m['relativeStrength20d'] = _difference(m['return20d'], median)
        composite(sector_id, 'priceTrend', {key: _leaf(cross(key, sector_id)) for key in weights['priceTrend']})
        composite(sector_id, 'funding', {'flow'+period: _leaf(cross('flowRatio'+period, sector_id)) for period in ('1d','5d','20d')})
        c['breadth'] = _leaf(cross('breadth', sector_id))
        composite(sector_id, 'activity', {key: _leaf(cross('shortAcceleration' if key == 'acceleration' else key, sector_id))
                                           for key in weights['activity']})
        m['activityPercentile'] = c['activity']['value']
        c['concentration'] = _leaf(cross('concentration', sector_id))
        c['activityMean5d'] = _leaf(baseline(sector_id, 'activityPercentile'))
        for key, field in [('flowDelta5d', 'flowRatio1d'), ('breadthDelta5d', 'breadth'),
                           ('downsideDelta5d', 'decliningShare'), ('activityDelta5d', 'activityPercentile')]:
            m[key] = _difference(m[field], baseline(sector_id, field))
        persistence_count = windows['persistenceCloses']
        recent = past[-persistence_count:]
        sufficient = len(recent) >= windows['minimumPersistenceCloses']
        strengths = [p.get('metrics', {}).get('strengthPercentile') for p in recent]
        ranks = [p.get('metrics', {}).get('strengthRank') for p in recent]
        mean_percentile = _mean(strengths) if sufficient and all(_number(v) for v in strengths) else None
        streak = None
        if sufficient and all(_number(v) and v >= 1 for v in ranks):
            streak = 0
            for rank in reversed(ranks):
                if rank > windows['topRank']:
                    break
                streak += 1
        coverage = len(recent) / persistence_count
        composite(sector_id, 'persistence', {
            'meanPercentile': _leaf(mean_percentile, coverage, 'insufficientCloseHistory'),
            'topTenStreak': _leaf(streak / persistence_count * 100 if streak is not None else None,
                                  coverage, 'insufficientCloseHistory')})
        strength = _combine(c, settings['weights']['strength'])['value']
        old_strength = None
        if len(past) >= windows['shortBaseline']:
            old_strength = past[-windows['shortBaseline']].get('_rawScores', {}).get('strength')
        difference = _difference(strength, old_strength)
        m['strengthSlope5d'] = difference / windows['shortBaseline'] if difference is not None else None

    for sector_id in ids:
        m, c, past = metrics[sector_id], components[sector_id], histories[sector_id]
        series = [p.get('metrics', {}).get('relativeStrength20d') for p in past]
        series = [v for v in series if _number(v)]
        position_parts = {}
        for window in windows['positionWindows']:
            minimum = settings['gates']['minimumCloses'] if window == windows['positionWindows'][0] else window
            values = series[-window:]
            percentile = _percentile(values, m['relativeStrength20d'], config) if len(values) >= minimum else None
            part = _leaf(position_curve(percentile), min(1, len(values) / window), 'insufficientPositionHistory')
            part['percentile'] = percentile
            position_parts[f'position{window}d'] = part
        composite(sector_id, 'position', position_parts)
        historical_flow = _values(past, 'flowRatio1d', windows['flowBaseline'])
        composite(sector_id, 'fundsImprovement', {
            'historical20d': _leaf(_percentile(historical_flow, m['flowRatio1d'], config), reason='insufficientFlowHistory'),
            'delta5d': _leaf(cross('flowDelta5d', sector_id), reason='insufficientFlowHistory')})
        breadth_days = windows['breadthImprovementCloses']
        breadth_values = _values(past, 'breadth', breadth_days + 1)
        improving = sum(right > left for left, right in zip(breadth_values, breadth_values[1:])) / breadth_days * 100 if breadth_values else None
        composite(sector_id, 'breadthImprovement', {
            'delta5d': _leaf(cross('breadthDelta5d', sector_id), reason='insufficientBreadthHistory'),
            'improvingDays': _leaf(improving, reason='insufficientBreadthHistory')})
        composite(sector_id, 'momentumImprovement', {key: _leaf(cross(key, sector_id)) for key in weights['momentumImprovement']})
        activity_parts = {'current': c['activity'], 'delta5d': _leaf(cross('activityDelta5d', sector_id), reason='insufficientActivityHistory')}
        composite(sector_id, 'activityWarming', activity_parts)
        if _number(c['activity']['value']) and c['activity']['value'] >= settings['heat']['crowdedAt']:
            c['activityWarming']['value'] = 0.
        composite(sector_id, 'downsideDiffusion', {
            'current': _leaf(cross('decliningShare', sector_id)),
            'delta5d': _leaf(cross('downsideDelta5d', sector_id), reason='insufficientBreadthHistory')})
        funding = c['funding']
        composite(sector_id, 'fundsWithdrawal', {
            'funding': {**funding, 'value': 100-funding['value'] if funding['value'] is not None else None},
            'delta5d': _leaf(cross('flowDelta5d', sector_id, True), reason='insufficientFlowHistory')})
        composite(sector_id, 'trendDeterioration', {
            'return5d': _leaf(cross('return5d', sector_id, True)),
            'return20d': _leaf(cross('return20d', sector_id, True)),
            'slope5d': _leaf(cross('strengthSlope5d', sector_id, True), reason='insufficientStrengthHistory')})
        # Both confirmation legs and price are required; missing confirmation
        # cannot silently become zero divergence or a one-leg substitute.
        price, funds, breadth = (c[key]['value'] for key in ('priceTrend','funding','breadth'))
        gap = price - _mean([funds, breadth]) if all(_number(v) for v in (price,funds,breadth)) else None
        c['divergence'] = _leaf(max(0., min(100., gap)) if gap is not None else None,
                                min(c[key]['coverage'] for key in ('priceTrend','funding','breadth')))
        composite(sector_id, 'crowding', {'activity': c['activity'], 'acceleration': _leaf(cross('shortAcceleration', sector_id))})
        if c['activity']['value'] is None:
            c['crowding'] = _leaf(None)
        elif c['activity']['value'] < settings['heat']['activeAt']:
            c['crowding'] = _leaf(0., c['activity']['coverage'])
    return components[current['id']], metrics[current['id']], histories[current['id']]


def derive_sector_components(current: dict, prior_closes: list[dict], universe_current: list[dict], config: dict) -> dict:
    """Return normalized atom audit records, without rounding or filling gaps."""
    return _derive(current, prior_closes, universe_current, config)[0]


def classify_heat(components: dict, config: dict) -> str | None:
    """Apply evidence gate, then crowded-first half-open activity thresholds.

    The 30..70 band without a 15-point improvement has no specified label and
    remains unclassified. A five-close mean does not invent a warming streak.
    """
    thresholds = config['sectorScoring']['heat']
    activity, concentration = (components.get(key, {}) for key in ('activity','concentration'))
    value, concentration_value = activity.get('value'), concentration.get('value')
    if not _number(value) or activity.get('coverage', 0)*100 < thresholds['minimumCompleteness']:
        return None
    if value >= thresholds['crowdedAt'] or (_number(concentration_value)
            and concentration.get('coverage', 0)*100 >= thresholds['minimumCompleteness']
            and concentration_value >= thresholds['concentrationCrowdedAt']):
        return 'crowded'
    if value < thresholds['coldBelow']:
        return 'cold'
    if value >= thresholds['activeAt']:
        return 'active'
    mean = components.get('activityMean5d', {}).get('value')
    if _number(mean) and value >= mean + thresholds['warmingImprovement']:
        return 'warming'
    return None


def score_sector(current: dict, prior_closes: list[dict], universe_current: list[dict], config: dict) -> dict:
    """Score three independent axes and disclose coverage/evidence gates."""
    components, metrics, past = _derive(current, prior_closes, universe_current, config)
    settings = config['sectorScoring']
    gates = settings['gates']
    axes = {axis: _combine(components, weights) for axis, weights in settings['weights'].items()}
    valid_closes = sum(_number(p.get('metrics', {}).get('relativeStrength20d')) for p in past)
    improvements = sum(_number(components[key]['value']) and components[key]['value'] >= gates['improvementThreshold']
                       for key in ('fundsImprovement','breadthImprovement','momentumImprovement'))
    raw = {axis: value['value'] for axis, value in axes.items()}
    if raw['opportunity'] is not None:
        if improvements < gates['requiredImprovementComponents']:
            raw['opportunity'] = min(raw['opportunity'], gates['unconfirmedOpportunityCap'])
        if valid_closes < gates['minimumCloses'] or axes['opportunity']['coverage']*100 < gates['minimumOpportunityCompleteness']:
            raw['opportunity'] = None
    result = {key: current[key] for key in ('id','name','universe','marketDate','session','observedAt') if key in current}
    result.update({axis: math.floor(value + .5) if value is not None else None for axis, value in raw.items()})
    result.update(sectorScoringVersion=config['sectorScoringVersion'], sectorUniverseVersion=config['sectorUniverseVersion'],
                  _rawScores=raw, components=components, metrics=metrics,
                  axisCompleteness={axis: value['coverage']*100 for axis, value in axes.items()},
                  completeness=math.floor(_mean([value['coverage'] for value in axes.values()])*100+.5),
                  heatState=classify_heat(components, config), coldStart=valid_closes < gates['coldStartCloses'],
                  validCloses=valid_closes, improvementEvidence=improvements,
                  missing=[f'{key}.{reason}' for key, component in components.items() for reason in component['missing']])
    return result


def _axis_value(row, axis):
    # A published integer cannot stand in for discarded working precision.
    value = row.get('_rawScores', {}).get(axis)
    return value if _number(value) and _number(row.get(axis)) else None


def rank_sector_scores(rows: list[dict], axis: str) -> list[dict]:
    """Rank each universe independently; return copied rows grouped by universe."""
    if axis not in ('strength','opportunity','risk'):
        raise ValueError('INVALID_SECTOR_AXIS')
    if any(row.get('universe') not in ('industry','concept') for row in rows):
        raise ValueError('INVALID_SECTOR_UNIVERSE')
    identities = [(row['universe'], row.get('id')) for row in rows]
    if len(identities) != len(set(identities)):
        raise ValueError('DUPLICATE_SECTOR_IDENTITY')
    def order(row):
        value = _axis_value(row, axis)
        return (row['universe'], -(value if value is not None else -math.inf),
                -row.get('completeness', 0), row['id'])
    result, counts = [], {}
    for row in sorted(rows, key=order):
        universe = row['universe']
        rank = None
        if _axis_value(row, axis) is not None:
            counts[universe] = counts.get(universe, 0) + 1
            rank = counts[universe]
        result.append({**row, 'ranks': {**row.get('ranks', {}), axis: rank}})
    return result


def _view_value(row, field):
    if field in ('strength','opportunity','risk'):
        return _axis_value(row, field)
    if field.endswith('Change1d'):
        return (row.get('change1d') or {}).get(field[:-8])
    return row.get(field)


def _matches(value, bounds):
    if 'eq' in bounds or 'not' in bounds:
        return value is not None and ('eq' not in bounds or value == bounds['eq']) and ('not' not in bounds or value != bounds['not'])
    return (_number(value) and ('min' not in bounds or value >= bounds['min'])
            and ('lt' not in bounds or value < bounds['lt']))


def derive_current_views(rows: list[dict], config: dict) -> dict[str, list[dict]]:
    """Independent predicates and explicit lexicographic sorting; no net score."""
    result = {}
    for name, rule in config['sectorScoring']['views'].items():
        def eligible(row):
            all_match = all(_matches(_view_value(row, key), bounds) for key, bounds in rule.get('all', {}).items())
            any_match = not rule.get('any') or any(_matches(_view_value(row, key), bounds) for key, bounds in rule['any'].items())
            return all_match and any_match
        def order(row):
            keys = [row['universe']]
            for field in rule['sort']:
                value = _view_value(row, field)
                keys.append(value if field == 'id' else -(value if _number(value) else -math.inf))
            return tuple(keys)
        result[name] = [dict(row) for row in sorted(filter(eligible, rows), key=order)]
    return result
