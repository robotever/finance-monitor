"""Private derived v3 history; never a provider cache or a v2 comparison source."""
from copy import deepcopy
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from .concepts import concept_definitions, load_concept_config
from .rotation import rank_sector_scores
from .scoring import load_config, percentile_rank
from .sources import INDUSTRY_DEFINITIONS


SCHEMA = 'market-dashboard-v3'
VERSIONS = ('sectorScoringVersion', 'sectorUniverseVersion')
AXES = ('strength', 'opportunity', 'risk')
METRICS = set(('return1d return5d return20d turnover flowRatio1d flowRatio5d flowRatio20d '
               'breadth decliningShare marketShare concentration shortAcceleration mediumAcceleration '
               'relativeStrength20d activityPercentile flowDelta5d breadthDelta5d downsideDelta5d '
               'activityDelta5d strengthSlope5d strengthPercentile strengthRank').split())
ROW_KEYS = set(('id name universe marketDate session observedAt officialClose strength opportunity risk '
                '_rawScores components metrics axisCompleteness completeness heatState coldStart validCloses '
                'improvementEvidence missing ranks leaderboard sectorScoringVersion sectorUniverseVersion').split())
SHANGHAI = ZoneInfo('Asia/Shanghai')


def _require(ok):
    if not ok:
        raise ValueError('INVALID_ROTATION_STATE')


def _number(value, low=-math.inf, high=math.inf):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def _day(value):
    _require(isinstance(value, str))
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError('INVALID_ROTATION_STATE') from None
    _require(parsed.isoformat() == value)
    return parsed


def _time(value):
    _require(isinstance(value, str))
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValueError('INVALID_ROTATION_STATE') from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    return parsed.astimezone(SHANGHAI)


def _identities():
    return {'industry': {code for code, _ in INDUSTRY_DEFINITIONS},
            'concept': {code for code, _ in concept_definitions(load_concept_config())}}


def _empty(config):
    return dict(schemaVersion=SCHEMA, **{key: config[key] for key in VERSIONS}, closes=[])


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) and len(item) <= 200 for item in value)


def _component(value, allowed_parts):
    _require(isinstance(value, dict) and {'value', 'coverage', 'missing'} <= value.keys()
             and value.keys() <= {'value', 'coverage', 'missing', 'usedWeight', 'totalWeight', 'effectiveWeight', 'parts', 'percentile'})
    _require(value['value'] is None or _number(value['value'], 0, 100))
    _require(_number(value['coverage'], 0, 1) and _strings(value['missing']))
    for key in ('usedWeight', 'totalWeight', 'effectiveWeight'):
        if key in value:
            _require(_number(value[key], 0))
    if 'percentile' in value:
        _require(value['percentile'] is None or _number(value['percentile'], 0, 100))
    if 'parts' in value:
        _require(isinstance(value['parts'], dict) and value['parts'].keys() <= allowed_parts)
        for component in value['parts'].values():
            _component(component, allowed_parts)


def _row(row, config, *, price_only=False):
    _require(isinstance(row, dict) and row.keys() <= ROW_KEYS)
    universe = row.get('universe')
    _require(universe in _identities() and row.get('id') in _identities()[universe])
    _day(row.get('marketDate'))
    _require(row.get('session') == 'close' and all(row.get(key) == config[key] for key in VERSIONS))
    metrics = row.get('metrics')
    _require(isinstance(metrics, dict) and metrics.keys() <= METRICS
             and all(value is None or _number(value) for value in metrics.values()))
    if price_only:
        _require(row.keys() <= {'id', 'universe', 'marketDate', 'session', 'metrics', *VERSIONS})
        _require(metrics.keys() <= {'return1d', 'return5d', 'return20d', 'relativeStrength20d'})
        return
    observed = _time(row.get('observedAt'))
    _require(str(observed.date()) == row['marketDate'] and observed.hour == 15 and observed.minute <= 30)
    _require(row.get('officialClose') is True and _numeric_scores(row))
    _require(isinstance(row.get('components'), dict))
    allowed_components = set(config['sectorScoring']['componentWeights']) | {'breadth', 'concentration', 'activityMean5d', 'divergence'}
    _require(row['components'].keys() <= allowed_components)
    allowed_parts = {key for weights in config['sectorScoring']['componentWeights'].values() for key in weights}
    for component in row['components'].values():
        _component(component, allowed_parts)
    _require(_number(row.get('completeness'), 0, 100) and _strings(row.get('missing')))
    _require(row.get('heatState') in (None, 'cold', 'warming', 'active', 'crowded'))
    if 'name' in row:
        _require(isinstance(row['name'], str) and len(row['name']) <= 100)
    if 'axisCompleteness' in row:
        _require(isinstance(row['axisCompleteness'], dict) and set(row['axisCompleteness']) == set(AXES)
                 and all(_number(value, 0, 100) for value in row['axisCompleteness'].values()))
    for field in ('validCloses', 'improvementEvidence'):
        if field in row:
            _require(isinstance(row[field], int) and not isinstance(row[field], bool) and row[field] >= 0)
    if 'coldStart' in row:
        _require(isinstance(row['coldStart'], bool))
    if 'ranks' in row:
        _require(isinstance(row['ranks'], dict) and set(row['ranks']) == set(AXES))
        for rank in row['ranks'].values():
            _require(rank is None or isinstance(rank, int) and not isinstance(rank, bool) and 1 <= rank <= len(_identities()[universe]))
    if 'leaderboard' in row:
        _require(isinstance(row['leaderboard'], dict) and set(row['leaderboard']) == {'strength', 'opportunity'})
        for axis, stats in row['leaderboard'].items():
            _require(isinstance(stats, dict) and set(stats) == {'axis', 'topTenStreak', 'topTenCount15d', 'rankChange'} and stats['axis'] == axis)
            _require(all(isinstance(stats[key], int) and not isinstance(stats[key], bool) and stats[key] >= 0 for key in ('topTenStreak', 'topTenCount15d')))
            _require(stats['topTenCount15d'] <= 15 and (stats['rankChange'] is None or _number(stats['rankChange'], -74, 74)))


def _numeric_scores(row):
    raw = row.get('_rawScores')
    if not isinstance(raw, dict) or set(raw) != set(AXES):
        return False
    return all((raw[axis] is None and row.get(axis) is None) or
               (_number(raw[axis], 0, 100) and isinstance(row.get(axis), int)
                and not isinstance(row[axis], bool) and row[axis] == math.floor(raw[axis]+.5)) for axis in AXES)


def _validated_state(value, config):
    state = _empty(config)
    _require(isinstance(value, dict))
    if not value or value.get('schemaVersion') != SCHEMA or any(value.get(key) != config[key] for key in VERSIONS):
        return state
    _require(value.keys() <= {'schemaVersion', *VERSIONS, 'closes', 'priceHistory'})
    incompatible_days = {row.get('marketDate') for row in value.get('closes', []) if isinstance(row, dict)
                         and any(row.get(key) != config[key] for key in VERSIONS)}
    for field in ('closes', 'priceHistory'):
        rows = value.get(field, [])
        _require(isinstance(rows, list))
        selected, seen = [], set()
        for row in rows:
            _require(isinstance(row, dict))
            if any(row.get(key) != config[key] for key in VERSIONS):
                continue
            if field == 'closes' and row.get('marketDate') in incompatible_days:
                continue
            _row(row, config, price_only=field == 'priceHistory')
            identity = (row['marketDate'], row['universe'], row['id'])
            _require(identity not in seen)
            seen.add(identity); selected.append(deepcopy(row))
        if field == 'closes' or selected:
            state[field] = sorted(selected, key=lambda row: (row['marketDate'], row['universe'], row['id']))
    groups = {}
    for row in state['closes']:
        groups.setdefault(row['marketDate'], []).append(row)
    for rows in groups.values():
        _require(len(rows) == 110)
        for universe, ids in _identities().items():
            _require({row['id'] for row in rows if row['universe'] == universe} == ids)
        expected = rows
        for axis in AXES:
            expected = rank_sector_scores(expected, axis)
        by_id = {(row['universe'], row['id']): row for row in expected}
        for row in rows:
            peers = [peer['_rawScores']['strength'] for peer in rows if peer['universe'] == row['universe']]
            _require(row.get('ranks') == by_id[(row['universe'], row['id'])]['ranks'])
            _require(row['metrics'].get('strengthRank') == row['ranks']['strength']
                     and row['metrics'].get('strengthPercentile') == percentile_rank(peers, row['_rawScores']['strength'], config))
    return state


def load_rotation_state(path: Path, config: dict) -> dict:
    """Read an isolated envelope (or the job's embedded envelope), rejecting links."""
    path = Path(path)
    _require(not path.is_symlink() and not path.parent.is_symlink())
    if not path.exists():
        return _empty(config)
    value = json.loads(path.read_text())
    _require(isinstance(value, dict))
    return _validated_state(value.get('rotation', value), config)


def leaderboard_stats(closes: list[dict], universe: str, axis: str, sector_id: str) -> dict:
    """Latest fifteen formal closes, including the latest one; positive change rises."""
    _require(universe in ('industry', 'concept') and axis in ('strength', 'opportunity'))
    days = {}
    anchors = {}
    for row in closes:
        if row.get('universe') != universe or row.get('session') != 'close' or row.get('officialClose') is not True:
            continue
        day = row['marketDate']
        _day(day)
        days.setdefault(day, {})
        _require(row['id'] not in days[day])
        days[day][row['id']] = row.get('ranks', {}).get(axis)
        if row['id'] == sector_id:
            anchors[day] = row.get('leaderboard', {}).get(axis, {}).get('topTenStreak')
    ranks = [days[day].get(sector_id) for day in sorted(days)]
    top = lambda rank: isinstance(rank, int) and not isinstance(rank, bool) and 1 <= rank <= 10
    streak = 0
    for rank in reversed(ranks):
        if not top(rank):
            break
        streak += 1
    # The earliest retained close carries a derived continuity anchor, so
    # dropping old recovery records cannot reset a longer uninterrupted streak.
    if ranks and streak == len(ranks):
        anchor = anchors.get(min(days))
        if isinstance(anchor, int) and not isinstance(anchor, bool) and anchor > 1:
            streak += anchor-1
    change = ranks[-2]-ranks[-1] if len(ranks) >= 2 and all(_number(v, 1) for v in ranks[-2:]) else None
    return dict(axis=axis, topTenStreak=streak, topTenCount15d=sum(top(rank) for rank in ranks[-15:]), rankChange=change)


def append_rotation_close(state: dict, payload: dict, config: dict) -> dict:
    """Prepare an immutable next state; caller commits it only after publication."""
    state = _validated_state(state, config)
    if payload.get('schemaVersion') != SCHEMA or payload.get('session') != 'close' or payload.get('officialClose') is not True:
        return state
    _require(all(payload.get(key) == config[key] for key in VERSIONS))
    day = _day(payload.get('marketDate'))
    observed = _time(payload.get('observedAt'))
    _require(observed.date() == day and observed.hour == 15 and observed.minute <= 30)
    rows = deepcopy(payload.get('sectors'))
    _require(isinstance(rows, list))
    for universe, ids in _identities().items():
        selected = [row for row in rows if row.get('universe') == universe]
        _require(len(selected) == len(ids) and {row.get('id') for row in selected} == ids)
    _require(len(rows) == 110)
    for row in rows:
        row['officialClose'] = True
        _row(row, config)
        _require(row['marketDate'] == str(day) and _time(row['observedAt']) <= observed)
    if any(row['marketDate'] == str(day) for row in state['closes']):
        return state
    _require(not state['closes'] or day > _day(state['closes'][-1]['marketDate']))
    for axis in AXES:
        rows = rank_sector_scores(rows, axis)
    for row in rows:
        peers = [peer['_rawScores']['strength'] for peer in rows if peer['universe'] == row['universe']]
        row['metrics'].update(strengthRank=row['ranks']['strength'],
            strengthPercentile=percentile_rank(peers, row['_rawScores']['strength'], config))
    combined = state['closes']+rows
    for row in rows:
        row['leaderboard'] = {axis: leaderboard_stats(combined, row['universe'], axis, row['id']) for axis in ('strength', 'opportunity')}
    cutoff = day-timedelta(days=90)
    state['closes'] = sorted([row for row in combined if _day(row['marketDate']) >= cutoff],
                             key=lambda row: (row['marketDate'], row['universe'], row['id']))
    return state


def build_price_backfill(histories: dict[str, list[dict]], universe_version: str) -> list[dict]:
    """Convert validated dated closes into returns, never retain OHLC/rolling flows.

    An own return needs the actual N earlier observations. Relative strength is
    established only by an entirely covered same-date universe median.
    """
    config = load_config()
    _require(universe_version == config['sectorUniverseVersion'] and isinstance(histories, dict))
    identities = _identities()
    result = []
    for sector_id, points in histories.items():
        universe = next((key for key, ids in identities.items() if sector_id in ids), None)
        _require(universe is not None and isinstance(points, list))
        unique = {}
        for point in points:
            _require(isinstance(point, dict) and point.get('id') == sector_id and _number(point.get('close'), 0) and point['close'] > 0)
            _require(all(key not in point or point[key] == config[key] for key in VERSIONS))
            day = _day(point.get('date')).isoformat()
            _require(day not in unique or unique[day] == point['close'])
            unique[day] = point['close']
        days = sorted(unique)
        for index, day in enumerate(days):
            metrics = {f'return{period}d': (unique[day]-unique[days[index-period]])/unique[days[index-period]]*100
                       for period in (1, 5, 20) if index >= period}
            _require(all(_number(value) for value in metrics.values()))
            result.append(dict(id=sector_id, universe=universe, marketDate=day, session='close',
                               metrics=metrics, **{key: config[key] for key in VERSIONS}))
    groups = {}
    for row in result:
        groups.setdefault((row['universe'], row['marketDate']), []).append(row)
    for (universe, _), rows in groups.items():
        if {row['id'] for row in rows if 'return20d' in row['metrics']} == identities[universe]:
            values = sorted(row['metrics']['return20d'] for row in rows)
            size = len(values)
            median = math.fsum(value/2 for value in (values[(size-1)//2], values[size//2]))
            for row in rows:
                row['metrics']['relativeStrength20d'] = row['metrics']['return20d']-median
    return sorted(result, key=lambda row: (row['marketDate'], row['universe'], row['id']))
