"""Local collection and publication of derived market dashboard snapshots."""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener
from zoneinfo import ZoneInfo
import argparse
import fcntl
import json
import math
import os
import re
import time

from . import sources, rotation_operations
from .concepts import (build_concept_payload, concept_definitions, core_concept_ids,
                       load_concept_config)
from .scoring import load_config, build_dashboard_payload, percentile_rank, score_family
from .sources import STYLE_DEFINITIONS, INDUSTRY_DEFINITIONS
from .rotation import score_sector, rank_sector_scores
from .rotation_store import load_rotation_state, append_rotation_close, leaderboard_stats


SHANGHAI = ZoneInfo('Asia/Shanghai')
TRADING_CALENDAR_SCHEMA = 'market-trading-calendar-v1'


def _local(now):
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Clock requires a timezone')
    return now.astimezone(SHANGHAI)


def _bucket(now):
    local = _local(now)
    minute = local.hour * 60 + local.minute
    if minute >= 15 * 60:
        return f'{local.date()}:close'
    return f'{local.date()}:intraday:{local.hour:02d}:{local.minute // 15 * 15:02d}'


def should_collect(now, state, config):
    """Weekday session gate, optionally restricted by an explicit trading calendar.

    Default weekdays are a scheduling approximation, never a comparison calendar.
    The close catch-up window is 15:00–15:30, producing a single final snapshot.
    """
    local = _local(now)
    dates = config.get('schedule', {}).get('tradingDates')
    if local.weekday() >= 5 or dates is not None and str(local.date()) not in dates:
        return False
    minute = local.hour * 60 + local.minute
    scheduled = 570 <= minute < 690 or 780 <= minute < 900 or 900 <= minute <= 930
    return scheduled and state.get('bucket') != _bucket(now)


def scheduled_rotation_session(now: datetime, state: dict, config: dict) -> str | None:
    """Inclusive key windows, with exact end instants and no missed-window replay.

    Returns the key time (or ``close``), rather than the legacy 15-minute bucket.
    A shadow success stores ``YYYY-MM-DD:<key>`` independently of v2 state.
    Force never bypasses these windows or official-close eligibility.
    """
    local = _local(now)
    dates = config.get('schedule', {}).get('tradingDates')
    if local.weekday() >= 5 or dates is not None and str(local.date()) not in dates:
        return None
    seconds = local.hour * 3600 + local.minute * 60 + local.second + local.microsecond / 1e6
    settings = config['rotationSchedule']
    for key, end in settings['windows']:
        start_hour, start_minute = map(int, ('15:00' if key == 'close' else key).split(':'))
        end_hour, end_minute = map(int, end.split(':'))
        if start_hour*3600 + start_minute*60 <= seconds <= end_hour*3600 + end_minute*60:
            return None if state.get('bucket') == f'{local.date()}:{key}' else key
    return None


def verify_market_date(batches: dict, now: datetime) -> bool:
    """Use the already collected broad-market observation as today's session proof."""
    try:
        batch = batches['breadth']
        if batch.source != 'Wind' or batch.source_mode != 'wind' or len(batch.rows) != 1:
            return False
        value = batch.rows[0].get('_timestamp')
        observed = datetime.fromisoformat(value)
        if observed.tzinfo is None or observed.utcoffset() is None:
            return False
        return observed.astimezone(SHANGHAI).date() == _local(now).date()
    except (AttributeError, KeyError, TypeError, ValueError):
        return False



@dataclass(frozen=True)
class PublishResult:
    success: bool
    status_code: int | None = None
    attempts: int = 0
    error_code: str | None = None


class ValidationError(ValueError):
    """Deliberately carries no payload, credential or upstream message."""


def _require(condition):
    if not condition:
        raise ValidationError('INVALID_PAYLOAD')


def _numeric(value, low=0, high=100):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and low <= value <= high)


def _timestamp(value):
    _require(isinstance(value, str))
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise ValidationError('INVALID_PAYLOAD') from None
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    return parsed


def _strings(value):
    return isinstance(value, list) and all(isinstance(s, str) and len(s) <= 200 for s in value)


def validate_payload(payload, config=None):
    """Validate derived-only v1 shape, identity coverage and evidence before I/O.

    70/50 are evidence/stage thresholds, not publication minimums. A configurable
    publication.minimumCompleteness defaults to >0; nullable scores stay missing.
    """
    config = config or load_config()
    _require(isinstance(payload, dict))
    required = {'schemaVersion', 'scoringVersion', 'observedAt', 'marketDate', 'session',
                'global', 'aShare', 'styles', 'industries', 'concepts', 'dataStatus'}
    _require(required <= payload.keys() and payload.keys() <= required | {'sourceMode'})
    _require(payload['schemaVersion'] == config['schemaVersion']
             and payload['scoringVersion'] == config['scoringVersion'])
    observed = _timestamp(payload['observedAt'])
    _require(payload['marketDate'] == str(observed.astimezone(SHANGHAI).date()))
    _require(payload['session'] in ('intraday', 'close'))
    objects = []
    for key, expected in [('global', 'global'), ('aShare', 'a-share')]:
        obj = payload[key]
        _require(isinstance(obj, dict) and obj.get('id') == expected)
        objects.append(obj)
    for key, definitions in [('styles', STYLE_DEFINITIONS), ('industries', INDUSTRY_DEFINITIONS)]:
        items = payload[key]
        _require(isinstance(items, list) and len(items) == len(definitions)
                 and all(isinstance(obj, dict) for obj in items))
        ids = [obj.get('id') for obj in items]
        _require(all(isinstance(id, str) for id in ids) and len(set(ids)) == len(ids)
                 and set(ids) == {id for id, _ in definitions})
        objects.extend(items)
    concepts = payload['concepts']
    _require(isinstance(concepts, dict)
             and set(concepts) == {'selectionVersion', 'scoringVersion', 'selectedAt', 'core', 'dynamic'})
    _require(concepts['selectionVersion'] == config['conceptSelection']['version']
             and concepts['scoringVersion'] == config['conceptSelection']['scoringVersion'])
    _timestamp(concepts['selectedAt'])
    core, dynamic = concepts['core'], concepts['dynamic']
    _require(isinstance(core, list) and len(core) == 25
             and isinstance(dynamic, list) and len(dynamic) == 10
             and all(isinstance(item, dict) for item in core + dynamic))
    core_ids = [item.get('id') for item in core]
    dynamic_ids = [item.get('id') for item in dynamic]
    _require(all(isinstance(object_id, str) and re.fullmatch(r'884\d{2,4}\.WI', object_id)
                 for object_id in core_ids + dynamic_ids)
             and len(set(core_ids)) == 25 and len(set(dynamic_ids)) == 10
             and not set(core_ids) & set(dynamic_ids))
    for item in core:
        _require(not ({'selectionScore', 'selectedOn', 'retainedTradingDays'} & item.keys()))
    for item in dynamic:
        _require(_numeric(item.get('selectionScore'))
                 and isinstance(item.get('selectedOn'), str)
                 and isinstance(item.get('retainedTradingDays'), int)
                 and not isinstance(item.get('retainedTradingDays'), bool)
                 and item['retainedTradingDays'] >= 1)
        try:
            date.fromisoformat(item['selectedOn'])
        except ValueError:
            raise ValidationError('INVALID_PAYLOAD') from None
    objects.extend(core + dynamic)
    required_obj = {'id', 'strength', 'heat', 'risk', 'completeness', 'missing',
                    'contributors', 'sourceTimestamps', 'change1d', 'change5d'}
    allowed_obj = required_obj | {'name', 'frequency', 'observedAt', 'stage',
                                  'comparisonFallback', 'comparisonUnavailable',
                                  'selectionScore', 'selectedOn', 'retainedTradingDays'}
    for obj in objects:
        _require(required_obj <= obj.keys() and obj.keys() <= allowed_obj)
        _require(_numeric(obj['completeness']) and _strings(obj['missing']))
        scores = [obj[axis] for axis in ('strength', 'heat', 'risk')]
        _require(all(v is None or isinstance(v, int) and _numeric(v) for v in scores))
        _require(any(v is not None for v in scores) and obj['completeness'] > 0)
        if 'observedAt' in obj:
            _timestamp(obj['observedAt'])
        if 'frequency' in obj:
            _require(obj['frequency'] in ('intraday', 'daily', 'monthly'))
        if 'name' in obj:
            _require(isinstance(obj['name'], str) and len(obj['name']) <= 100)
        if obj['completeness'] < config['completeness']['stageThreshold']:
            _require(obj.get('stage') is None)
        if obj.get('stage') is not None:
            _require(obj['stage'] in [stage['label'] for stage in config['stages']] + [config['defaultStage']])
        for change in ('change1d', 'change5d'):
            value = obj[change]
            _require(value is None or isinstance(value, dict) and set(value) == {'strength', 'heat', 'risk'}
                     and all(v is None or _numeric(v, -100, 100) for v in value.values()))
        timestamps = obj['sourceTimestamps']
        _require(isinstance(timestamps, list) and bool(timestamps))
        for provenance in timestamps:
            _require(isinstance(provenance, dict) and set(provenance) == {'source', 'timestamp'}
                     and provenance['source'] in ('Wind', 'FRED', 'MX', 'Derived'))
            _timestamp(provenance['timestamp'])
        contributors = obj['contributors']
        _require(isinstance(contributors, list) and len(contributors) <= 3)
        for contributor in contributors:
            _require(isinstance(contributor, dict) and {'label', 'impact'} <= contributor.keys()
                     and contributor.keys() <= {'label', 'impact', 'evidence'}
                     and isinstance(contributor['label'], str) and len(contributor['label']) <= 200
                     and _numeric(contributor['impact'], -100, 100))
            if 'evidence' in contributor:
                _require(isinstance(contributor['evidence'], str) and len(contributor['evidence']) <= 200)
        if 'comparisonFallback' in obj:
            _require(obj['comparisonFallback'] == 'close')
        if 'comparisonUnavailable' in obj:
            unavailable = obj['comparisonUnavailable']
            _require(isinstance(unavailable, dict) and unavailable.keys() <= {'change1d', 'change5d'}
                     and all(reason in ('missingObservation', 'missingCurrentScores', 'missingTradingCalendar',
                                        'missingTargetTradingDate') for reason in unavailable.values()))
    status = payload['dataStatus']
    _require(isinstance(status, dict) and set(status) == {'completeness', 'stale', 'missing'}
             and _numeric(status['completeness']) and isinstance(status['stale'], bool)
             and _strings(status['missing']))
    expected_completeness = math.floor(sum(obj['completeness'] for obj in objects) / len(objects) + .5)
    _require(status['completeness'] == expected_completeness)
    minimum = config.get('publication', {}).get('minimumCompleteness', 0)
    _require(_numeric(minimum) and status['completeness'] > 0 and status['completeness'] >= minimum)
    if 'sourceMode' in payload:
        modes = payload['sourceMode']
        _require(isinstance(modes, dict) and set(modes) == {
            'breadth', 'styles', 'industries', 'concepts', 'conceptDiscovery', 'global'})
        for group, mode in modes.items():
            if group == 'global':
                _require(isinstance(mode, dict) and all(isinstance(key, str) and key.isalnum()
                         and value in ('fred', 'wind', 'mx') for key, value in mode.items()))
            elif group == 'conceptDiscovery':
                _require(mode == 'mx')
            else:
                _require(mode == 'wind')
    # Catch NaN, unserializable objects and excessive derived bodies before transport.
    try:
        _require(len(json.dumps(payload, allow_nan=False).encode()) <= 256 * 1024)
    except (TypeError, ValueError):
        raise ValidationError('INVALID_PAYLOAD') from None
    return payload


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # Never forward the Bearer credential to a redirect target.


# Keep the transport patchable while disabling urllib's cross-host auth redirects.
urlopen = build_opener(_NoRedirect()).open


def publish_payload(payload, url, token, timeout=20, *, config=None):
    """Three bounded attempts only for network errors/5xx; never logs secrets."""
    try:
        validate_payload(payload, config)
    except (ValidationError, TypeError, KeyError):
        return PublishResult(False, error_code='INVALID_PAYLOAD')
    try:
        target = urlsplit(url)
        valid_target = target.scheme == 'https' and bool(target.hostname) and not target.username and not target.password
        valid_auth = isinstance(token, str) and bool(token.strip()) and '\n' not in token and '\r' not in token
        if not valid_target or not valid_auth or not _numeric(timeout, .001, 300):
            return PublishResult(False, error_code='INVALID_PUBLISH_CONFIG')
        request = Request(url, data=json.dumps(payload, allow_nan=False, separators=(',', ':')).encode(),
                          headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json',
                                   'User-Agent': 'NewsmonitorMarketDashboard/1.0'}, method='POST')
    except (TypeError, ValueError):
        return PublishResult(False, error_code='INVALID_PUBLISH_CONFIG')
    for attempt in range(1, 4):
        try:
            with urlopen(request, timeout=timeout) as response:
                status = response.status
            if 200 <= status < 300:
                return PublishResult(True, status, attempt)
            transient = 500 <= status < 600
            error_code = f'HTTP_{status}'
        except HTTPError as error:
            status = error.code
            transient = 500 <= status < 600
            error_code = f'HTTP_{status}'
            error.close()
        except (URLError, OSError, TimeoutError):
            status, transient, error_code = None, True, 'NETWORK_ERROR'
        except Exception:
            return PublishResult(False, attempts=attempt, error_code='TRANSPORT_ERROR')
        if not transient or attempt == 3:
            return PublishResult(False, status, attempt, error_code)
        time.sleep(.25 * 2 ** (attempt - 1))



FIXTURES = Path(__file__).with_name('fixtures')
FIXTURE_NOW = datetime.fromisoformat('2026-11-13T10:15:00+08:00')


def collect_batches(config, *, concept_config=None, fixture=False, runner=None, fetcher=None):
    """Serial adapter calls; fixture mode replaces I/O, never production failures."""
    config = deepcopy(config)
    if fixture:
        config.setdefault('sources', {}).update(now=config.get('sources', {}).get('now', FIXTURE_NOW.isoformat()))
        config['sources']['global'] = {'metrics': {
            'DGS10': {'source': 'fred', 'series': 'DGS10', 'frequency': 'daily', 'unit': '%'},
            'gold': {'source': 'mx', 'entityName': '现货黄金', 'field': '最新价', 'frequency': 'daily'},
        }}
        def runner(argv, *, cwd=None):
            if argv[0] == 'python3':
                name = 'mx-global.json'
            else:
                params = json.loads(argv[-1])
                windcodes = params.get('windcode', '')
                name = ('wind-industries.json' if 'question' in params or windcodes.startswith('882') else
                        'wind-breadth.json' if windcodes == '881001.WI' else
                        'wind-concepts.json' if windcodes.startswith('884') else 'wind-styles.json')
            envelope = json.loads((FIXTURES / name).read_text())
            if name == 'wind-concepts.json':
                requested = set(params['windcode'].split(','))
                content = json.loads(envelope['content'][0]['text'])
                table = content['data']
                code_index = next(index for index, column in enumerate(table['columns'])
                                  if column['name'] == 'Wind代码')
                time_index = next(index for index, column in enumerate(table['columns'])
                                  if column['name'] == '交易时间')
                table['rows'] = [row for row in table['rows'] if row[code_index] in requested]
                for row in table['rows']:
                    row[time_index] = FIXTURE_NOW.isoformat()
                envelope['content'][0]['text'] = json.dumps(content, ensure_ascii=False)
            return envelope
        def fetcher(url):
            return (FIXTURES / 'fred-series.csv').read_text()
    runner = runner or sources.run_command
    fetcher = fetcher or sources.fetch_csv
    concept_config = concept_config or load_concept_config()
    return {'breadth': sources.collect_wind_breadth(runner, config),
            'styles': sources.collect_wind_styles(runner, config),
            'industries': sources.collect_wind_industries(runner, config),
            'concepts': sources.collect_wind_concepts(runner, config, concept_config),
            'global': sources.collect_global_inputs(runner, fetcher, config)}


def _value(row, field, *, units=None):
    value = row.get(field)
    if units is not None and row.get('_units', {}).get(field) not in units:
        return None
    if isinstance(value, bool) or value is None:
        return None
    try:
        value = float(value)
    except (ValueError, TypeError):
        return None
    return value if math.isfinite(value) else None


def _money(row, field):
    units = row.get('_units', {}).get(field)
    value = _value(row, field)
    if value is None or units not in ('元', '亿元'):
        return None
    return value * (100000000 if units == '亿元' else 1)


def _fresh(row, now):
    try:
        timestamp = _timestamp(row.get('_timestamp'))
    except ValidationError:
        return False
    age = now - timestamp
    if _local(now).hour >= 15:
        return (age >= timedelta(0) and _local(timestamp).date() == _local(now).date()
                and _local(timestamp).hour >= 15)
    return timedelta(0) <= age <= timedelta(minutes=30)


def _component(row, value, now, **normalization):
    timestamp = row.get('_timestamp', row.get('timestamp'))
    fresh = row.get('available', False) and not row.get('stale', False) if 'timestamp' in row else _fresh(row, now)
    return {'value': value, 'available': fresh and value is not None,
            'stale': not fresh, 'timestamp': timestamp, 'source': row.get('source', 'Wind'), **normalization}


def _cross(row, value, history, now):
    return _component(row, value, now, mode='cross_sectional', history=history)


def _ratio(numerator, denominator):
    return numerator / denominator if numerator is not None and denominator is not None and denominator > 0 else None


def _breadth(row):
    values = [_value(row, field, units=('个', '家')) for field in ('上涨家数', '下跌家数', '平盘家数')]
    if any(v is None or v < 0 for v in values) or sum(values) <= 0:
        return None, None
    return values[0] / sum(values) * 100, values[1] / sum(values) * 100


def derive_concept_candidates(batch, market_amount, market_risk, now, config):
    """Convert the full Wind concept batch into comparable derived candidates.

    All ranks are calculated against the same fresh candidate universe.  Raw
    provider fields are never exposed, and missing observations remain missing
    rather than being coerced to neutral values.
    """
    rows = batch.rows
    by_id = {row.get('id'): row for row in rows if isinstance(row.get('id'), str)}

    def metrics(row):
        amount = _money(row, '成交额')
        flow = _money(row, '当日主力净流入额')
        advancing, declining = _breadth(row)
        return {
            'relativeReturn1d': _value(row, '涨跌幅'),
            'relativeReturn5d': _value(row, '5日涨跌幅'),
            'relativeReturn20d': _value(row, '20日涨跌幅'),
            'turnoverCrossSection': _value(row, '换手率'),
            'amountCrossSection': amount,
            'marketAmountShare': _ratio(amount, market_amount),
            'mainFlowDirection': _ratio(flow, amount),
            'advancingShare': advancing,
            'decliningShare': declining,
        }

    values = {row['id']: metrics(row) for row in rows if row.get('id') in by_id}
    ranked_keys = ('relativeReturn1d', 'relativeReturn5d', 'relativeReturn20d',
                   'turnoverCrossSection', 'amountCrossSection', 'marketAmountShare',
                   'mainFlowDirection')
    histories = {
        key: [metric[key] for object_id, metric in values.items()
              if _fresh(by_id[object_id], now) and metric[key] is not None]
        for key in ranked_keys
    }
    acceleration_values = {
        object_id: (metric['relativeReturn1d'] - metric['relativeReturn5d'] / 5
                    if metric['relativeReturn1d'] is not None
                    and metric['relativeReturn5d'] is not None else None)
        for object_id, metric in values.items()
    }
    acceleration_history = [value for object_id, value in acceleration_values.items()
                            if _fresh(by_id[object_id], now) and value is not None]

    candidates = []
    for row in rows:
        object_id = row.get('id')
        if object_id not in values:
            continue
        metric = values[object_id]
        indicators = {key: _cross(row, metric[key], histories[key], now) for key in ranked_keys}
        indicators['advancingShare'] = _component(row, metric['advancingShare'], now)
        indicators['decliningShare'] = _component(row, metric['decliningShare'], now)

        flow = metric['mainFlowDirection']
        indicators['mainOutflow'] = _cross(row, flow, histories['mainFlowDirection'], now)
        indicators['mainOutflow']['reverse'] = True
        indicators['mainFlowConcentration'] = _cross(
            row, abs(flow) if flow is not None else None,
            [abs(value) for value in histories['mainFlowDirection']], now)
        indicators['mediumTrendDeterioration'] = _cross(
            row, metric['relativeReturn20d'], histories['relativeReturn20d'], now)
        indicators['mediumTrendDeterioration']['reverse'] = True
        indicators['momentumAcceleration'] = _cross(
            row, acceleration_values[object_id], acceleration_history, now)

        return_rank = percentile_rank(histories['relativeReturn1d'], metric['relativeReturn1d'], config)
        flow_rank = percentile_rank(histories['mainFlowDirection'], flow, config)
        divergence = (abs(return_rank - flow_rank)
                      if return_rank is not None and flow_rank is not None else None)
        indicators['priceVolumeFlowDivergence'] = _component(row, divergence, now)
        if market_risk is not None:
            indicators['marketRiskTransmission'] = {
                'value': market_risk, 'available': _fresh(row, now),
                'stale': not _fresh(row, now), 'source': 'Derived',
                'timestamp': now.isoformat(),
            }

        component_inputs = {
            'momentum': percentile_rank(histories['relativeReturn5d'], metric['relativeReturn5d'], config),
            'flow': flow_rank,
            'breadth': metric['advancingShare'],
            'activity': percentile_rank(histories['turnoverCrossSection'], metric['turnoverCrossSection'], config),
        }
        weights = config['conceptSelection']['weights']
        observed_weight = sum(weights[key] for key, value in component_inputs.items()
                              if value is not None)
        selection_completeness = observed_weight / sum(weights.values()) * 100
        candidates.append({
            'id': object_id, 'name': row.get('name', object_id),
            'frequency': 'intraday', 'indicators': indicators,
            'selectionComponents': component_inputs,
            'selectionCompleteness': selection_completeness,
            'relativeReturn5dRaw': metric['relativeReturn5d'],
        })
    return candidates


def _global_components(rows, now, config):
    """Use only supported observations; no guessed bounds or synthetic histories.

    Source-role fixed bounds live in versioned config. Other rolling indicators
    remain unavailable until 20 observations. Composite/unsupported evidence is
    explicitly absent from the scoring builder's expected denominator.
    """
    by_id = {row['id']: row for row in rows}
    expected_units = {'DGS10': ('%',), 'BAMLH0A0HYM2': ('%',), 'DFII10': ('%',),
                      'IRLTLT01JPM156N': ('%',), 'vix': ('index', '点'),
                      'dollar': ('index', '点'), 'usEquity': ('index', '点')}
    by_id = {role: row if row.get('unit') in expected_units.get(role, ()) else {**row, 'available': False}
             for role, row in by_id.items()}
    indicators = {}
    mapping = {'ratesLiquidity': ('DGS10', True), 'creditConditions': ('BAMLH0A0HYM2', True),
               'highYieldSpread': ('BAMLH0A0HYM2', False), 'realRates': ('DFII10', False),
               'vixPressure': ('vix', False), 'vixPercentile': ('vix', False),
               'currencyEnvironment': ('dollar', True), 'currencyPressure': ('dollar', False),
               'sovereignPressure': ('IRLTLT01JPM156N', False)}
    for component, (role, reverse) in mapping.items():
        row = by_id.get(role)
        if not row:
            continue
        history = [point['value'] for point in row.get('history', []) if _numeric(point.get('value'), -1e15, 1e15)]
        bounds = config['normalization'].get('fixedBounds', {}).get(role)
        normalization = {'mode': 'rolling', 'history': history, 'reverse': reverse}
        if bounds:
            normalization['fixedBounds'] = [bounds['min'], bounds['max']]
        indicators[component] = _component(row, row.get('value'), now, **normalization)
    # Actual changes are derived only from dated history with at least two points.
    for component, role, absolute, percentage in [('equityTrend', 'usEquity', False, True),
                                                    ('rateMoves', 'DGS10', True, False)]:
        row = by_id.get(role)
        if not row:
            continue
        points = row.get('history', [])
        changes = []
        for previous, current in zip(points, points[1:]):
            a, b = previous.get('value'), current.get('value')
            if not _numeric(a, -1e15, 1e15) or not _numeric(b, -1e15, 1e15) or percentage and a <= 0:
                continue
            value = (b / a - 1) * 100 if percentage else b - a
            changes.append(abs(value) if absolute else value)
        indicators[component] = _component(row, changes[-1] if changes else None, now,
                                           mode='rolling', history=changes)
    return indicators


def derive_inputs(batches, now, config, concept_config=None):
    """Derive interpretable component inputs from unit-checked adapter rows.

    Return/flow/turnover ranks compare fresh peers in the same source batch.
    Market amount shares use the all-A denominator, never overlapping style sums.
    Unknown flat counts and unavailable industry 5d/20d returns stay missing.
    """
    local = _local(now)
    broad = batches['breadth'].rows[0] if batches['breadth'].rows else {}
    market_amount = _money(broad, '成交额') if _fresh(broad, now) else None
    global_rows = batches['global'].rows
    global_obj = {'id': 'global', 'name': '全球环境', 'indicators': _global_components(global_rows, now, config)}
    global_score = score_family('global', global_obj, config)
    used = {(p['source'], p['timestamp']) for p in global_score['sourceTimestamps']}
    observed_rows = [row for row in global_rows if (row.get('source'), row.get('timestamp')) in used]
    frequencies = {row.get('frequency') for row in observed_rows}
    if frequencies and frequencies <= {'daily', 'monthly'}:
        global_obj['frequency'] = 'daily' if 'daily' in frequencies else 'monthly'
        global_obj['observedAt'] = max((row['timestamp'] for row in observed_rows), key=_timestamp)
    global_risk = global_score['risk']
    advancing, declining = _breadth(broad)
    style_returns = [_value(row, '涨跌幅', units=('%',)) for row in batches['styles'].rows if _fresh(row, now)]
    broad_return = _value(broad, '涨跌幅', units=('%',))
    amount_rows = batches['industries'].rows
    industry_amounts = [_money(row, '最新成交额(亿元)') for row in amount_rows if _fresh(row, now)]
    industry_amounts = [value for value in industry_amounts if value is not None and value >= 0]
    # Top-five industry amount share is observable concentration, already 0–100.
    concentration = (sum(sorted(industry_amounts, reverse=True)[:5]) / sum(industry_amounts) * 100
                     if len(industry_amounts) == len(INDUSTRY_DEFINITIONS) and sum(industry_amounts) > 0 else None)
    a_indicators = {'breadth': _component(broad, advancing, now),
                    'indexTrend': _cross(broad, broad_return, [v for v in style_returns if v is not None], now),
                    'downsideDiffusion': _component(broad, declining, now),
                    'industryConcentration': _component(broad, concentration, now)}
    if global_risk is not None:
        a_indicators['globalPressure'] = {'value': global_risk, 'source': 'Derived', 'timestamp': now.isoformat()}
    a_obj = {'id': 'a-share', 'name': 'A股整体', 'frequency': 'intraday', 'indicators': a_indicators}
    market_risk = score_family('aShare', a_obj, config)['risk']
    output = {'observedAt': now.isoformat(), 'marketDate': str(local.date()),
              'session': 'close' if local.hour >= 15 else 'intraday',
              'global': global_obj, 'aShare': a_obj}
    if 'tradingDates' in config.get('schedule', {}):
        output['tradingDates'] = list(config['schedule']['tradingDates'])
    for group, definitions in [('styles', STYLE_DEFINITIONS), ('industries', INDUSTRY_DEFINITIONS)]:
        industry = group == 'industries'
        rows = batches[group].rows
        by_id = {row['id']: row for row in rows}
        ret_field = '最新涨跌幅(%)' if industry else '涨跌幅'
        turnover_field = '最新换手率(%)' if industry else '换手率'
        amount_field = '最新成交额(亿元)' if industry else '成交额'
        flow_field = '最新主力净流入额(亿元)' if industry else '当日主力净流入额'
        def metrics(row):
            amount, flow = _money(row, amount_field), _money(row, flow_field)
            up, down = _breadth(row)
            return {'relativeReturn1d': _value(row, ret_field, units=('%',)),
                    'relativeReturn5d': _value(row, '5日涨跌幅', units=('%',)),
                    'relativeReturn20d': _value(row, '20日涨跌幅', units=('%',)),
                    'advancingShare': up, 'decliningShare': down,
                    'turnoverCrossSection': _value(row, turnover_field, units=('%',)),
                    'amountCrossSection': amount, 'marketAmountShare': _ratio(amount, market_amount),
                    'mainFlowDirection': _ratio(flow, amount)}
        values = {row['id']: metrics(row) for row in rows}
        histories = {key: [m[key] for id, m in values.items() if _fresh(by_id[id], now) and m[key] is not None]
                     for key in ('relativeReturn1d', 'relativeReturn5d', 'relativeReturn20d',
                                 'turnoverCrossSection', 'amountCrossSection', 'marketAmountShare', 'mainFlowDirection')}
        objects = []
        for id, name in definitions:
            row = by_id.get(id, {})
            metric = values.get(id, {})
            indicators = {key: _cross(row, metric.get(key), history, now) for key, history in histories.items()}
            indicators['advancingShare'] = _component(row, metric.get('advancingShare'), now)
            indicators['decliningShare' if industry else 'negativeBreadth'] = _component(row, metric.get('decliningShare'), now)
            flow = metric.get('mainFlowDirection')
            indicators['mainOutflow'] = _cross(row, flow, histories['mainFlowDirection'], now)
            indicators['mainOutflow']['reverse'] = True
            indicators['mainFlowConcentration'] = _cross(row, abs(flow) if flow is not None else None,
                [abs(v) for v in histories['mainFlowDirection']], now)
            trend = metric.get('relativeReturn20d')
            indicators['mediumTrendDeterioration' if industry else 'trendDeterioration20d'] = _cross(
                row, trend, histories['relativeReturn20d'], now)
            indicators['mediumTrendDeterioration' if industry else 'trendDeterioration20d']['reverse'] = True
            risk = market_risk if industry else global_risk
            if risk is not None:
                indicators['marketRiskTransmission' if industry else 'globalRiskTransmission'] = {
                    'value': risk, 'available': _fresh(row, now), 'stale': not _fresh(row, now),
                    'source': 'Derived', 'timestamp': now.isoformat()}
            objects.append({'id': id, 'name': name, 'frequency': 'intraday', 'indicators': indicators})
        output[group] = objects
    if batches.get('concepts') and batches['concepts'].rows:
        concept_config = concept_config or load_concept_config()
        core = core_concept_ids(concept_config)
        core_order = {object_id: index for index, object_id in enumerate(core)}
        candidates = derive_concept_candidates(
            batches['concepts'], market_amount, market_risk, now, config)
        for candidate in candidates:
            candidate['core'] = candidate['id'] in core_order
            candidate['coreOrder'] = core_order.get(candidate['id'])
        output['conceptCandidates'] = candidates
    return output


def _concept_previous(history):
    for snapshot in reversed(history or []):
        concepts = snapshot.get('concepts') if isinstance(snapshot, dict) else None
        if isinstance(concepts, dict) and isinstance(concepts.get('dynamic'), list):
            return concepts['dynamic']
    return []


def _latest_concept_block(history):
    for snapshot in reversed(history or []):
        concepts = snapshot.get('concepts') if isinstance(snapshot, dict) else None
        if isinstance(concepts, dict) and isinstance(concepts.get('dynamic'), list):
            return concepts
    return None


def _concept_comparisons(concepts):
    for item in [*concepts['core'], *concepts['dynamic']]:
        item.setdefault('change1d', None)
        item.setdefault('change5d', None)


def build_market_payload(inputs, previous, config):
    payload = build_dashboard_payload(inputs, previous, config)
    candidates = inputs.get('conceptCandidates')
    if not candidates:
        raise ValueError('CONCEPTS_UNAVAILABLE')
    prior_block = _latest_concept_block(previous)
    reuse = inputs['session'] == 'intraday' and prior_block is not None
    payload['concepts'] = build_concept_payload(
        candidates, _concept_previous(previous), inputs['marketDate'],
        prior_block['selectedAt'] if reuse else inputs['observedAt'], config,
        reuse_previous=reuse)
    _concept_comparisons(payload['concepts'])
    objects = [payload['global'], payload['aShare'], *payload['styles'],
               *payload['industries'], *payload['concepts']['core'],
               *payload['concepts']['dynamic']]
    payload['dataStatus']['completeness'] = math.floor(
        sum(item['completeness'] for item in objects) / len(objects) + .5)
    payload['dataStatus']['missing'] = [
        f"{item.get('id', 'unknown')}:{key}" for item in objects for key in item['missing']]
    return payload


def _rotation_inputs(batches, config):
    """Canonical unit-checked inputs, never a rolling-flow history substitute."""
    now = _timestamp(config['sources']['now'])
    local = _local(now)
    session = 'close' if local.hour >= 15 else 'intraday'
    supported = load_config()
    _require(all(config[key] == supported[key] for key in ('sectorScoringVersion', 'sectorUniverseVersion')))
    broad = batches['breadth'].rows[0] if batches['breadth'].rows else {}
    market_amount = _money(broad, '成交额') if _fresh(broad, now) else None
    result = []
    for universe, group, definitions in [('industry', 'industries', INDUSTRY_DEFINITIONS),
            ('concept', 'concepts', concept_definitions(load_concept_config()))]:
        batch = batches.get(group)
        _require(batch is not None and batch.source == 'Wind' and batch.source_mode == 'wind')
        rows = batch.rows
        _require(len(rows) == len(definitions)
                 and {row.get('id') for row in rows} == {code for code, _ in definitions})
        names = dict(definitions)
        for row in rows:
            _require(_fresh(row, now))  # every sector timestamp, including both concept batches
            timestamp = _timestamp(row['_timestamp'])
            _require(_local(timestamp).date() == local.date())
            if session == 'close':
                _require(local.hour == 15 and local <= local.replace(minute=30, second=0, microsecond=0)
                         and _local(timestamp).hour == 15)
            industry = universe == 'industry'
            metrics = {key: _value(row, field, units=('%',)) for key, field in {
                'return1d': '最新涨跌幅(%)' if industry else '涨跌幅',
                'return5d': '5日涨跌幅', 'return20d': '20日涨跌幅',
                'turnover': '最新换手率(%)' if industry else '换手率'}.items()}
            metrics.update(amount1d=_money(row, '最新成交额(亿元)' if industry else '成交额'),
                netFlow1d=_money(row, '最新主力净流入额(亿元)' if industry else '当日主力净流入额'),
                netFlow5d=_money(row, '近5日主力净流入额'),
                netFlow20d=_money(row, '近20日主力净流入额'), marketAmount=market_amount)
            # No verified same-period amount fields exist yet. Do not divide a
            # 5/20-day rolling flow by today's amount or infer old observations.
            for key, field in [('advancing', '上涨家数'), ('declining', '下跌家数'), ('unchanged', '平盘家数')]:
                value = _value(row, field, units=('个', '家'))
                metrics[key] = value if value is not None and value >= 0 else None
            result.append(dict(id=row['id'], name=names[row['id']], universe=universe,
                observedAt=timestamp.isoformat(), marketDate=str(local.date()), session=session, metrics=metrics))
    return result


def _score_rotation_rows(current, prior_closes, config):
    rows = [score_sector(row, prior_closes, current, config) for row in current]
    for axis in ('strength', 'opportunity', 'risk'):
        rows = rank_sector_scores(rows, axis)
    return rows


def _rotation_projection(row, *, audit=True):
    """Project allowed derived fields; block assembly losslessly indexes audits."""
    fields = ('id', 'name', 'universe', 'observedAt', 'strength', 'opportunity', 'risk',
              'heatState', 'axisCompleteness', 'completeness', 'coldStart', 'validCloses',
              'improvementEvidence', 'ranks', 'leaderboard', 'officialClose')
    projected = {key: deepcopy(row[key]) for key in fields if key in row}
    if audit:
        projected['components'] = deepcopy(row['components'])
        projected['missing'] = row['missing']
    return projected


COMPONENT_FIELDS = ('value', 'coverage', 'missing', 'usedWeight', 'totalWeight',
                    'effectiveWeight', 'percentile', 'parts')


def _index_rotation_audits(rows):
    """Lossless normalized-component DAG, with exact floats and absent fields.

    A node is [presence bitmask, present fields in COMPONENT_FIELDS order].
    Missing values index missingReasons; parts are [part-name index, node index]
    pairs. Children precede parents and identical complete nodes share an index.
    No working score, historical metric or provider input enters this table.
    """
    reasons = {reason for row in rows for reason in row['missing']}
    names = set()
    def inventory(component):
        _require(component.keys() <= set(COMPONENT_FIELDS))
        reasons.update(component.get('missing', []))
        for name, child in component.get('parts', {}).items():
            names.add(name)
            inventory(child)
    for row in rows:
        for component in row['components'].values():
            inventory(component)
    reasons, names = sorted(reasons), sorted(names)
    reason_ids = {reason: index for index, reason in enumerate(reasons)}
    name_ids = {name: index for index, name in enumerate(names)}
    nodes, node_ids = [], {}
    def encode(component):
        mask, values = 0, []
        for bit, key in enumerate(COMPONENT_FIELDS):
            if key not in component:
                continue
            mask |= 1 << bit
            value = component[key]
            if key == 'missing':
                value = [reason_ids[reason] for reason in value]
            elif key == 'parts':
                value = [[name_ids[name], encode(child)] for name, child in value.items()]
            values.append(value)
        node = [mask, *values]
        identity = json.dumps(node, allow_nan=False, separators=(',', ':'))
        if identity not in node_ids:
            node_ids[identity] = len(nodes)
            nodes.append(node)
        return node_ids[identity]
    for row in rows:
        row['components'] = {name: encode(component) for name, component in row['components'].items()}
        row['missing'] = [reason_ids[reason] for reason in row['missing']]
    return {'componentEncoding': 'node-mask-v1', 'componentFields': list(COMPONENT_FIELDS),
            'componentPartNames': names, 'componentNodes': nodes, 'missingReasons': reasons}


def build_rotation_block(batches: dict, prior_closes: list[dict], config: dict) -> dict:
    """Local v3 full-universe block; not a production publication interface."""
    current = _rotation_inputs(batches, config)
    rows = _score_rotation_rows(current, prior_closes, config)
    official = current[0]['session'] == 'close'
    for row in rows:
        row['officialClose'] = official
    closes = prior_closes + rows if official else prior_closes
    for row in rows:
        row['leaderboard'] = {axis: leaderboard_stats(closes, row['universe'], axis, row['id'])
                              for axis in ('strength', 'opportunity')}
    projected = [_rotation_projection(row) for row in rows]
    audit_tables = _index_rotation_audits(projected)
    return {'sectorScoringVersion': config['sectorScoringVersion'],
            'sectorUniverseVersion': config['sectorUniverseVersion'],
            'observedAt': config['sources']['now'], 'marketDate': current[0]['marketDate'],
            'session': current[0]['session'], 'officialClose': official,
            'industries': [row for row in projected if row['universe'] == 'industry'],
            'concepts': [row for row in projected if row['universe'] == 'concept'],
            **audit_tables,
            'auditDefinitions': {'weights': config['sectorScoring']['weights'],
                'componentWeights': config['sectorScoring']['componentWeights'],
                'gates': config['sectorScoring']['gates'],
                'heat': config['sectorScoring']['heat']},
            # Task 1 did not verify live history/quota. No config flag unlocks
            # public opportunity output or production release in this task.
            'releaseEligible': False, 'safeCodes': ['LIVE_HISTORY_UNVERIFIED', 'LIVE_QUOTA_UNVERIFIED']}


def build_rotation_payload(inputs, previous, block, config):
    """Preserve legacy global/A-share/style semantics in an isolated v3 body."""
    legacy = build_market_payload(inputs, previous, config)
    validate_payload(legacy, config)
    payload = deepcopy(legacy)
    payload['schemaVersion'] = 'market-dashboard-v3'
    payload['sectorScoringVersion'] = config['sectorScoringVersion']
    payload['sectorUniverseVersion'] = config['sectorUniverseVersion']
    payload['sectorRotation'] = block
    payload['concepts']['selectionScoringVersion'] = payload['concepts']['scoringVersion']
    payload['concepts']['scoringVersion'] = config['sectorScoringVersion']
    payload['industries'] = [_rotation_projection(row, audit=False) for row in block['industries']]
    concepts = {row['id']: row for row in block['concepts']}
    for key in ('core', 'dynamic'):
        selected = []
        for old in legacy['concepts'][key]:
            row = _rotation_projection(concepts[old['id']], audit=False)
            if key == 'dynamic':
                row.update({field: old[field] for field in ('selectionScore', 'selectedOn', 'retainedTradingDays')})
            selected.append(row)
        payload['concepts'][key] = selected
    objects = [payload['global'], payload['aShare'], *payload['styles'], *block['industries'], *block['concepts']]
    payload['dataStatus'] = {'completeness': math.floor(sum(row['completeness'] for row in objects)/len(objects)+.5),
        'stale': legacy['dataStatus']['stale'],
        'missing': ['sectorRotation:LIVE_HISTORY_UNVERIFIED', 'sectorRotation:LIVE_QUOTA_UNVERIFIED']}
    _require(len(json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()) <= 256*1024)
    return payload



@dataclass(frozen=True)
class JobResult:
    success: bool
    status: str
    payload: dict | None = None
    error_code: str | None = None
    publish_result: PublishResult | None = None
    metadata: dict | None = None


@dataclass(frozen=True)
class CombinedCycleResult:
    success: bool
    status: str
    legacy: JobResult
    rotation: JobResult


def _read_json(path):
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('INVALID_STATE')
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError('INVALID_STATE')
    return data


def _write_json(path, value, *, on_replace=None):
    """Same-directory atomic replace; runtime derived state only, private mode."""
    if path.is_symlink() or path.parent.is_symlink():
        raise ValueError('INVALID_STATE')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', dir=path.parent, prefix='.dashboard-', delete=False) as file:
            temporary = Path(file.name)
            os.fchmod(file.fileno(), 0o600)
            json.dump(value, file, ensure_ascii=False, allow_nan=False, separators=(',', ':'))
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(path)
        if on_replace is not None:
            on_replace()
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _calendar_path(state_root: Path) -> Path:
    return state_root / 'market-dashboard/trading-calendar.json'


def _calendar_state(path: Path) -> dict:
    value = _read_json(path)
    if not value:
        return {'schemaVersion': TRADING_CALENDAR_SCHEMA, 'nonTradingDates': []}
    dates = value.get('nonTradingDates')
    if (value.get('schemaVersion') != TRADING_CALENDAR_SCHEMA or not isinstance(dates, list)
            or any(not isinstance(day, str) for day in dates)
            or dates != sorted(set(dates))):
        raise ValueError('INVALID_STATE')
    for day in dates:
        date.fromisoformat(day)
    return value


def _is_cached_non_trading_date(state_root: Path, now: datetime) -> bool:
    return str(_local(now).date()) in _calendar_state(_calendar_path(state_root))['nonTradingDates']


def _record_non_trading_date(state_root: Path, now: datetime) -> None:
    path = _calendar_path(state_root)
    state = _calendar_state(path)
    state['nonTradingDates'] = sorted(set(state['nonTradingDates']) | {str(_local(now).date())})
    _write_json(path, state)


def _mark_verified_trading_date(config: dict, now: datetime) -> None:
    """Make a source-verified date available to ledger/comparison consumers this run."""
    day = str(_local(now).date())
    schedule = config.setdefault('schedule', {})
    dates = schedule.get('tradingDates')
    if dates is None:
        schedule['tradingDates'] = [day]
    elif day not in dates:
        schedule['tradingDates'] = sorted([*dates, day])


def prepare_rotation_state(inputs, state, config):
    """Task 4 supplies canonical full-universe sectorRows, never provider rows.

    This prepares private history only. It cannot publish or commit; run_job
    includes it in the legacy success file only after successful publication.
    Absent rows retain v2 isolation. Intraday rows never advance a leaderboard.
    """
    if 'sectorRows' not in inputs or inputs.get('session') != 'close':
        return state
    current = inputs['sectorRows']
    prior = state.get('priceHistory', []) + state.get('closes', [])
    # Forward-collected evidence supersedes price-only backfill on overlap.
    prior = list({(row['universe'], row['id'], row['marketDate']): row for row in prior}.values())
    scored = [score_sector(row, prior, current, config) for row in current]
    return append_rotation_close(state, dict(schemaVersion='market-dashboard-v3',
        **{key: config[key] for key in ('sectorScoringVersion', 'sectorUniverseVersion')},
        observedAt=inputs['observedAt'], marketDate=inputs['marketDate'], session='close',
        officialClose=True, sectors=scored), config)


def _source_modes(batches):
    return {'breadth': 'wind', 'styles': 'wind', 'industries': 'wind',
            'concepts': 'wind', 'conceptDiscovery': 'mx',
            'global': {row['id']: row['sourceMode'] for row in batches['global'].rows
                       if isinstance(row.get('id'), str) and row['id'].isalnum()
                       and row.get('sourceMode') in ('fred', 'wind', 'mx')}}


def _safe_error(code, fallback):
    return code if isinstance(code, str) and re.fullmatch(r'(HTTP_[1-5][0-9]{2}|NETWORK_ERROR|INVALID_PAYLOAD|TRANSPORT_ERROR|INVALID_PUBLISH_CONFIG)', code) else fallback


def _rotation_report(health, config):
    """Whitelist even persisted metadata; never print rows, identifiers or paths."""
    counts = health.get('counts', {})
    coverage = health.get('coverage')
    latency = health.get('latencySeconds')
    allowed_codes = {'LIVE_HISTORY_UNVERIFIED', 'LIVE_QUOTA_UNVERIFIED', 'INVALID_STATE',
        'COLLECTION_FAILED', 'INVALID_PAYLOAD', 'SCORING_FAILED', 'STATE_WRITE_FAILED', 'WINDOW_EXPIRED',
        *rotation_operations.SAFE_CODES}
    return {**rotation_operations.safe_health(health), 'counts': {key: counts.get(key, 0) if isinstance(counts, dict)
                and isinstance(counts.get(key, 0), int) and not isinstance(counts.get(key, 0), bool)
                and 0 <= counts.get(key, 0) <= maximum else 0
                for key, maximum in [('industries', 35), ('concepts', 75)]},
            'versions': {'schemaVersion': 'market-dashboard-v3',
                **{key: config[key] for key in ('scoringVersion', 'sectorScoringVersion', 'sectorUniverseVersion')}},
            'coverage': coverage if _numeric(coverage) else None,
            'latencySeconds': latency if _numeric(latency, 0, 86400) else None,
            'safeCodes': sorted({code for code in health.get('safeCodes', [])
                                 if isinstance(code, str) and code in allowed_codes})}


def _pending_rotation_operation(state, ledger):
    """Return a committed operation absent from the ledger, without mutating it."""
    pending = state.get('shadowOperation')
    if pending is None:
        return None
    _require(isinstance(pending, dict))
    return pending if not any(all(row.get(field) == pending.get(field)
        for field in ('marketDate', 'session', 'observedAt', 'success', 'safeErrorCode'))
        for row in ledger.get('events', [])) else None


def _rotation_audit_warning(metadata):
    return {**metadata, 'rotationSafeErrorCode': 'LEDGER_WRITE_FAILED',
            'safeCodes': sorted(set(metadata['safeCodes']) | {'LEDGER_WRITE_FAILED'})}


def _run_rotation_job(args, deps):
    """Collect/assemble rotation data; publication requires an explicit flag."""
    arg = (lambda key, default=None: args.get(key, default)) if isinstance(args, dict) else (lambda key, default=None: getattr(args, key, default))
    fixture, dry_run = arg('fixture', False), arg('dry_run', False)
    if fixture and not dry_run and not arg('rotation_report', False):
        return JobResult(False, 'configuration', error_code='FIXTURE_SHADOW_WRITE_DISABLED')
    try:
        config = deepcopy(deps.get('config') or load_config(arg('config')))
        now = deps.get('now') or (FIXTURE_NOW.replace(hour=9, minute=50) if fixture else datetime.now(timezone.utc))
        now = now() if callable(now) else now
        _local(now)
        config.setdefault('sources', {})['now'] = now.isoformat()
        state_root = Path(deps.get('state_root') or os.environ.get('MARKET_DASHBOARD_STATE_ROOT')
                         or Path(__file__).resolve().parents[2].parent / 'state')
        _require(not state_root.is_symlink())
    except (ValueError, TypeError, KeyError, OSError):
        return JobResult(False, 'configuration', error_code='INVALID_CONFIG')
    shadow = state_root / 'market-dashboard-shadow'
    path, health_path = shadow/'last-success.json', shadow/'health.json'
    pending_path = shadow/'pending-publication.json'
    ledger_path = shadow/'rotation-ledger.json'
    if arg('rotation_report', False):
        try:
            metadata = _rotation_report(_read_json(health_path), config)
            ledger = rotation_operations.read_ledger(ledger_path, config)
            metadata['rotationCloseSuccesses'] = len(ledger['successfulCloseDates'])
            if _pending_rotation_operation(_read_json(path), ledger) is not None:
                metadata = _rotation_audit_warning(metadata)
            return JobResult(True, 'rotation_report', metadata=metadata)
        except (ValueError, TypeError, OSError):
            return JobResult(False, 'rotation_report', error_code='INVALID_STATE',
                metadata=_rotation_report({'safeCodes': ['INVALID_STATE']}, config))
    lock = None
    stage, metadata = 'state', _rotation_report({'safeCodes': [
        'LIVE_HISTORY_UNVERIFIED', 'LIVE_QUOTA_UNVERIFIED']}, config)
    committed = False
    publish_result = None
    event, ledger, key = None, None, None

    def record_operation(event):
        nonlocal metadata
        try:
            ledger = rotation_operations.update_ledger(ledger_path, event, config)
            metadata.update(rotation_operations.health_for_event(event, ledger))
            metadata['safeCodes'] = [code for code in metadata['safeCodes'] if code != 'LEDGER_WRITE_FAILED']
            _write_json(health_path, metadata)
        except (OSError, ValueError, TypeError):
            # Health warning persistence does not depend on a writable ledger.
            metadata = _rotation_audit_warning(metadata)
            try:
                _write_json(health_path, metadata)
            except (OSError, ValueError, TypeError):
                pass  # A read-only report also detects the committed pending proof.
            raise

    try:
        if not (fixture and dry_run):
            # Share the v2 provider lock, while every JSON write stays in shadow.
            directory = state_root/'market-dashboard'
            _require(not directory.is_symlink() and not (directory/'job.lock').is_symlink())
            directory.mkdir(parents=True, exist_ok=True)
            lock = (directory/'job.lock').open('a')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return JobResult(True, 'locked')
        if not fixture and _is_cached_non_trading_date(state_root, now):
            return JobResult(True, 'market_closed_cached', metadata=metadata)
        ledger = rotation_operations.read_ledger(ledger_path, config) if not fixture else {'successfulCloseDates': []}
        state = {} if fixture else _read_json(path)
        rotation_state = {} if fixture else load_rotation_state(path, config)
        if not fixture and health_path.exists():
            metadata = _rotation_report(_read_json(health_path), config)
        pending_publication = {} if fixture else _read_json(pending_path)
        if pending_publication and arg('rotation_publish', False):
            stage = 'publish'
            _require(pending_publication.get('mode') == 'rotation_published'
                     and isinstance(pending_publication.get('payload'), dict)
                     and isinstance(pending_publication.get('shadowOperation'), dict))
            payload = pending_publication['payload']
            publish_result = deps.get('publisher', publish_payload)(payload,
                arg('url') or os.environ.get('MARKET_DASHBOARD_PUBLISH_URL', ''),
                arg('token') or os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN', ''),
                arg('timeout', 20), config=config)
            if not publish_result.success:
                metadata['safeCodes'] = ['PUBLISH_FAILED']
                metadata['rotationSafeErrorCode'] = 'PUBLISH_FAILED'
                _write_json(health_path, metadata)
                return JobResult(False, 'publish', payload, error_code='PUBLISH_FAILED',
                                 publish_result=publish_result, metadata=metadata)
            event = pending_publication['shadowOperation']
            stage = 'persist'
            def acknowledge_pending_replace():
                nonlocal committed
                committed = True
            _write_json(path, pending_publication, on_replace=acknowledge_pending_replace)
            try:
                record_operation(event)
            except (OSError, ValueError, TypeError):
                pass
            pending_path.unlink(missing_ok=True)
            return JobResult(True, 'rotation_published', payload, publish_result=publish_result,
                             metadata=metadata)
        pending = _pending_rotation_operation(state, ledger)
        if pending is not None and not dry_run:
            # Reconcile before any later session replaces the recovery proof.
            # If audit repair fails, leave the earlier success file untouched.
            stage = 'audit'
            record_operation(pending)
            stage = 'state'
        key = scheduled_rotation_session(now, {}, config)
        bucket = f'{_local(now).date()}:{key}'
        if key is not None and state.get('bucket') == bucket:
            # Repair an interrupted audit write from the authoritative committed
            # snapshot before returning duplicate. Never recollect or republish.
            if state.get('shadowOperation') and not dry_run:
                try:
                    record_operation(state['shadowOperation'])
                except (OSError, ValueError, TypeError):
                    pass  # record_operation already persisted/marked the safe warning.
            return JobResult(True, 'duplicate', metadata=metadata)
        if key is None:
            return JobResult(True, 'outside_schedule')
        stage = 'collect'
        batches = deps['collector'](config) if 'collector' in deps else collect_batches(config, fixture=fixture)
        if fixture:
            for group in ('breadth', 'styles', 'industries', 'concepts'):
                for row in batches[group].rows:
                    row['_timestamp'] = now.isoformat()
        if callable(deps.get('now')):
            now = deps['now']()
        elif 'now' not in deps and not fixture:
            now = datetime.now(timezone.utc)
        if scheduled_rotation_session(now, {}, config) != key or f'{_local(now).date()}:{key}' != bucket:
            raise sources.SourceError('WINDOW_EXPIRED')
        if not verify_market_date(batches, now):
            if not fixture and not dry_run:
                _record_non_trading_date(state_root, now)
            return JobResult(True, 'market_closed', metadata=metadata)
        _mark_verified_trading_date(config, now)
        config['sources']['now'] = now.isoformat()
        stage = 'score'
        current = _rotation_inputs(batches, config)
        prior = rotation_state.get('priceHistory', []) + rotation_state.get('closes', [])
        prior = list({(row['universe'], row['id'], row['marketDate']): row for row in prior}.values())
        block = build_rotation_block(batches, prior, config)
        inputs = derive_inputs(batches, now, config)
        inputs['sectorRows'] = current
        # At 11:30 the legacy job's session is intraday; only a validated 15:00
        # sector batch may enter the store's official-close accumulator.
        next_rotation = prepare_rotation_state(inputs, rotation_state, config)
        previous = state.get('legacyHistory', [])
        _require(isinstance(previous, list))
        for snapshot in previous:
            validate_payload(snapshot, config)
        stage = 'validate'
        payload = build_rotation_payload(inputs, previous, block, config)
        metadata = _rotation_report({'counts': {'industries': 35, 'concepts': 75},
            'coverage': sum(row['completeness'] for row in block['industries']+block['concepts'])/110,
            'latencySeconds': max((now-_timestamp(row['observedAt'])).total_seconds() for row in current),
            'safeCodes': block['safeCodes']}, config)
        scored_closes = [row for row in next_rotation.get('closes', [])
                         if row['marketDate'] == inputs['marketDate']] if key == 'close' else None
        event = rotation_operations.event_from_block(block, now,
            min((row['observedAt'] for row in current), key=_timestamp), config, session=key,
            scored_rows=scored_closes, published=arg('rotation_publish', False))
        metadata.update(rotation_operations.health_for_event(event, ledger))
        if dry_run:
            return JobResult(True, 'dry_run', payload, metadata=metadata)
        stage = 'persist'
        _require(not shadow.is_symlink())
        shadow.mkdir(parents=True, exist_ok=True, mode=0o700)
        shadow.chmod(0o700)
        history = [snapshot for snapshot in previous
                   if _timestamp(snapshot['observedAt']) >= now-timedelta(days=90)]
        history.append(build_market_payload(inputs, previous, config))
        _write_json(health_path, metadata)
        mode = 'rotation_published' if arg('rotation_publish', False) else 'rotation_shadow'
        prepared = {'bucket': bucket, 'mode': mode, 'payload': payload,
            'rotation': next_rotation, 'legacyHistory': history, 'shadowOperation': event}
        if arg('rotation_publish', False):
            _write_json(pending_path, prepared)
            stage = 'publish'
            publish_result = deps.get('publisher', publish_payload)(payload,
                arg('url') or os.environ.get('MARKET_DASHBOARD_PUBLISH_URL', ''),
                arg('token') or os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN', ''),
                arg('timeout', 20), config=config)
            if not publish_result.success:
                metadata['safeCodes'] = ['PUBLISH_FAILED']
                metadata['rotationSafeErrorCode'] = 'PUBLISH_FAILED'
                _write_json(health_path, metadata)
                return JobResult(False, 'publish', payload, error_code='PUBLISH_FAILED',
                                 publish_result=publish_result, metadata=metadata)
            stage = 'persist'
        # Health is preparatory. Replacing success is the final commit boundary;
        # any failure before it leaves the official close available for retry.
        def acknowledge_replace():
            nonlocal committed
            committed = True
        _write_json(path, prepared, on_replace=acknowledge_replace)
        try:
            record_operation(event)
        except (OSError, ValueError, TypeError):
            pass  # The close stays committed; record_operation marked its audit warning.
        if arg('rotation_publish', False):
            pending_path.unlink(missing_ok=True)
        return JobResult(True, mode, payload, publish_result=publish_result, metadata=metadata)
    except Exception as error:
        if committed:
            # Replacement already consumed this close. A later directory-fsync
            # failure is a durability warning, never a failed/retryable close.
            metadata = deepcopy(metadata)
            metadata['safeCodes'] = sorted(set(metadata['safeCodes'] + ['STATE_DURABILITY_UNCONFIRMED']))
            metadata['rotationSafeErrorCode'] = 'STATE_DURABILITY_UNCONFIRMED'
            return JobResult(True, 'rotation_shadow', payload, metadata=metadata)
        code = 'INVALID_PAYLOAD' if isinstance(error, ValidationError) else {
            'state': 'INVALID_STATE', 'collect': 'COLLECTION_FAILED', 'score': 'SCORING_FAILED',
            'validate': 'INVALID_PAYLOAD', 'publish': 'PUBLISH_FAILED', 'persist': 'STATE_WRITE_FAILED',
            'audit': 'LEDGER_WRITE_FAILED'}.get(stage, 'SCORING_FAILED')
        if isinstance(error, sources.SourceError) and error.code in rotation_operations.SAFE_CODES:
            code = error.code
        metadata['safeCodes'] = sorted(set(metadata['safeCodes'] + [code])) if code == 'LEDGER_WRITE_FAILED' else [code]
        metadata['rotationSafeErrorCode'] = code
        if not dry_run:
            try:
                _require(not shadow.is_symlink())
                shadow.mkdir(parents=True, exist_ok=True, mode=0o700)
                shadow.chmod(0o700)
                failed_event = event or rotation_operations.event_from_block(
                    {'session': key if key in rotation_operations.SESSIONS else 'close'}, now, None, config,
                    success=False, code=code)
                failed_event = {**failed_event, 'success': False, 'safeErrorCode': code}
                record_operation(failed_event)
            except (OSError, ValueError, TypeError):
                pass
        return JobResult(False, stage, error_code=code, publish_result=publish_result, metadata=metadata)
    finally:
        if lock is not None:
            lock.close()


def run_job(args, deps=None):
    """Collect → score → validate → publish under a nonblocking process lock.

    deps is an optional dict: now, config, state_root, collector(config),
    builder(inputs, previous, config), publisher(payload, url, token, timeout,
    config=...). All tests inject external I/O. Live dry runs share the collection
    lock but never write snapshot/health state; fixture dry runs write nothing.
    Skip-publish writes health only. Only a successful publish advances buckets
    and the derived comparison history in last-success.json.
    """
    deps = deps or {}
    arg = (lambda key, default=None: args.get(key, default)) if isinstance(args, dict) else (lambda key, default=None: getattr(args, key, default))
    if any(arg(key, False) for key in ('rotation_shadow', 'rotation_publish', 'rotation_report', 'skip_rotation_publish')):
        return _run_rotation_job(args, deps)
    fixture, dry_run, skip_publish = arg('fixture', False), arg('dry_run', False), arg('skip_publish', False)
    if fixture and not (dry_run or skip_publish):
        return JobResult(False, 'configuration', error_code='FIXTURE_PUBLISH_DISABLED')
    now = deps.get('now') or (FIXTURE_NOW if fixture else datetime.now(timezone.utc))
    if callable(now):
        now = now()
    try:
        _local(now)
        config = deepcopy(deps.get('config') or load_config(arg('config')))
        concept_config = deepcopy(deps.get('concept_config') or load_concept_config())
        config.setdefault('sources', {})['now'] = now.isoformat()
    except (ValueError, TypeError, OSError, KeyError):
        return JobResult(False, 'configuration', error_code='INVALID_CONFIG')
    state_root = Path(deps.get('state_root') or os.environ.get('MARKET_DASHBOARD_STATE_ROOT')
                      or Path(__file__).resolve().parents[2].parent / 'state')
    state_path = state_root / 'market-dashboard/last-success.json'
    health_path = state_root / 'service-health/market-dashboard.json'
    lock = None
    stage, counts, completeness = 'state', {}, None
    last_status = 'never'
    payload = None
    try:
        if not (dry_run and fixture):
            state_path.parent.mkdir(parents=True, exist_ok=True)
            if (state_path.parent / 'job.lock').is_symlink():
                raise ValueError('INVALID_STATE')
            lock = (state_path.parent / 'job.lock').open('a')
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return JobResult(True, 'locked')
        if not fixture and _is_cached_non_trading_date(state_root, now):
            return JobResult(True, 'market_closed_cached')
        state = {} if fixture else _read_json(state_path)
        rotation_state = {} if fixture else load_rotation_state(state_path, config)
        old_health = {} if fixture else _read_json(health_path)
        last_status = old_health.get('lastPublishStatus', 'published' if state else 'never')
        if last_status not in ('published', 'failed', 'never', 'skipped'):
            last_status = 'never'
        counts = old_health.get('sourceCounts', {})
        counts = {key: value for key, value in counts.items() if key in ('breadth', 'global', 'styles', 'industries', 'concepts')
                  and isinstance(value, int) and 0 <= value <= 1000} if isinstance(counts, dict) else {}
        prior_payload = state.get('payload', {})
        completeness = prior_payload.get('dataStatus', {}).get('completeness') if isinstance(prior_payload, dict) else None
        # Force never overrides duplicate-bucket idempotency.
        if state.get('bucket') == _bucket(now):
            return JobResult(True, 'duplicate')
        if not arg('force', False) and not should_collect(now, state, config):
            return JobResult(True, 'outside_schedule')
        stage = 'collect'
        batches = deps['collector'](config) if 'collector' in deps else collect_batches(config, fixture=fixture)
        counts = {group: len(batch.rows) for group, batch in batches.items()}
        concept_available = bool(batches.get('concepts') and batches['concepts'].rows)
        prior_payload = state.get('payload', {})
        prior_concepts = prior_payload.get('concepts') if isinstance(prior_payload, dict) else None
        if not concept_available and prior_concepts is None:
            raise sources.SourceError('CONCEPTS_UNAVAILABLE')
        # Evaluate freshness at completion, so observations arriving during the
        # serial provider calls are not incorrectly classified as future data.
        if callable(deps.get('now')):
            now = deps['now']()
        elif 'now' not in deps and not fixture:
            now = datetime.now(timezone.utc)
        _local(now)
        if not verify_market_date(batches, now):
            if not fixture and not dry_run:
                _record_non_trading_date(state_root, now)
            return JobResult(True, 'market_closed')
        _mark_verified_trading_date(config, now)
        stage = 'score'
        inputs = derive_inputs(batches, now, config, concept_config)
        next_rotation_state = prepare_rotation_state(inputs, rotation_state, config)
        previous = state.get('history', [])
        previous = previous if isinstance(previous, list) else []
        if 'builder' in deps:
            payload = deps['builder'](inputs, previous, config)
        elif concept_available:
            payload = build_market_payload(inputs, previous, config)
        else:
            validate_payload(prior_payload, config)
            payload = build_dashboard_payload(inputs, previous, config)
            payload['concepts'] = deepcopy(prior_concepts)
            objects = [payload['global'], payload['aShare'], *payload['styles'],
                       *payload['industries'], *payload['concepts']['core'],
                       *payload['concepts']['dynamic']]
            payload['dataStatus']['completeness'] = math.floor(
                sum(item['completeness'] for item in objects) / len(objects) + .5)
            payload['dataStatus']['missing'] = [
                f"{item.get('id', 'unknown')}:{key}" for item in objects for key in item['missing']]
            payload['dataStatus']['missing'].append('concepts:collectionUnavailable')
            payload['dataStatus']['stale'] = True
        # Only explicit safe provenance survives Task 1's derived-field whitelist.
        payload['sourceMode'] = _source_modes(batches)
        stage = 'validate'
        validate_payload(payload, config)
        completeness = payload['dataStatus']['completeness']
        if dry_run:
            return JobResult(True, 'dry_run', payload)
        if skip_publish:
            _write_json(health_path, {'stage': 'complete', 'observedAt': now.isoformat(),
                        'sourceCounts': counts, 'completeness': completeness,
                        'lastPublishStatus': last_status, 'publishStatus': 'skipped', 'errorCode': None})
            return JobResult(True, 'skip_publish', payload)
        stage = 'publish'
        result = deps.get('publisher', publish_payload)(payload,
            arg('url') or os.environ.get('MARKET_DASHBOARD_PUBLISH_URL', ''),
            arg('token') or os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN', ''),
            arg('timeout', 20), config=config)
        if not result.success:
            code = _safe_error(result.error_code, 'PUBLISH_FAILED')
            _write_json(health_path, {'stage': stage, 'observedAt': now.isoformat(), 'sourceCounts': counts,
                        'completeness': completeness, 'lastPublishStatus': 'failed', 'errorCode': code})
            return JobResult(False, stage, error_code=code,
                             publish_result=PublishResult(False, result.status_code, result.attempts, code))
        stage = 'persist'
        # Store only validated derived snapshots, retaining at least 90 calendar days.
        history = []
        for snapshot in previous:
            try:
                validate_payload(snapshot, config)
                if _timestamp(snapshot['observedAt']) >= now - timedelta(days=90):
                    history.append(snapshot)
            except (ValidationError, TypeError, KeyError):
                continue
        history.append(payload)
        _write_json(state_path, {'bucket': _bucket(now), 'mode': 'published',
                    'observedAt': now.isoformat(), 'payload': payload, 'history': history,
                    'rotation': next_rotation_state})
        _write_json(health_path, {'stage': 'complete', 'observedAt': now.isoformat(), 'sourceCounts': counts,
                    'completeness': completeness, 'lastPublishStatus': 'published', 'errorCode': None})
        return JobResult(True, 'published', payload, publish_result=PublishResult(True, result.status_code, result.attempts))
    except Exception as error:
        code = 'INVALID_PAYLOAD' if isinstance(error, ValidationError) else {
            'state': 'INVALID_STATE', 'collect': 'COLLECTION_FAILED', 'score': 'SCORING_FAILED',
            'validate': 'INVALID_PAYLOAD', 'publish': 'PUBLISH_FAILED', 'persist': 'STATE_WRITE_FAILED',
        }.get(stage, 'JOB_FAILED')
        if not dry_run:
            try:
                _write_json(health_path, {'stage': stage, 'observedAt': now.isoformat(), 'sourceCounts': counts,
                            'completeness': completeness if _numeric(completeness) else None,
                            'lastPublishStatus': 'failed' if stage == 'publish' else last_status, 'errorCode': code})
            except (OSError, ValueError, TypeError):
                pass
        return JobResult(False, stage, error_code=code)
    finally:
        if lock is not None:
            lock.close()


def run_combined_cycle(args, deps=None):
    """Run rotation first and v2 second with one cached provider collection."""
    deps = dict(deps or {})
    values = dict(args) if isinstance(args, dict) else vars(args).copy()
    fixture = bool(values.get('fixture', False))
    supplied = deps.get('collector')
    cached, failed = [], []

    def collect_once(config):
        if cached:
            return cached[0]
        if failed:
            raise failed[0]
        try:
            result = supplied(config) if supplied else collect_batches(
                config, concept_config=deps.get('concept_config'), fixture=fixture)
        except Exception as error:
            failed.append(error)
            raise
        cached.append(result)
        return result

    shared = {**deps, 'collector': collect_once}
    rotation_args = {**values, 'rotation_shadow': True}
    rotation_args.pop('with_rotation', None)
    legacy_args = dict(values)
    legacy_args.pop('with_rotation', None)
    for flag in ('rotation_shadow', 'rotation_report', 'skip_rotation_publish', 'rotation_publish'):
        legacy_args.pop(flag, None)
    rotation = run_job(rotation_args, shared)
    legacy = run_job(legacy_args, shared)
    return CombinedCycleResult(rotation.success and legacy.success, 'combined', legacy, rotation)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Validate and summarize; no publication or snapshot/health writes (live runs use the collection lock)')
    parser.add_argument('--fixture', action='store_true', help='Use sanitized synthetic fixtures and their fixed observation clock')
    parser.add_argument('--force', action='store_true', help='Bypass session gate only; validation/idempotency still apply')
    parser.add_argument('--skip-publish', action='store_true', help='Collect/validate and write health, without advancing last-success')
    parser.add_argument('--config', help='Versioned config JSON path')
    parser.add_argument('--url', help='HTTPS publication URL (or MARKET_DASHBOARD_PUBLISH_URL)')
    parser.add_argument('--token', help='Publication Bearer token (prefer MARKET_DASHBOARD_PUBLISH_TOKEN)')
    parser.add_argument('--timeout', type=float, default=20)
    parser.add_argument('--rotation-shadow', action='store_true', help='Assemble v3 locally in private shadow state; never publish')
    parser.add_argument('--rotation-publish', action='store_true', help='Publish validated v3, then commit its private success state')
    parser.add_argument('--skip-rotation-publish', action='store_true', help='Select the shadow-only path; production publication is unavailable')
    parser.add_argument('--rotation-report', action='store_true', help='Read private shadow metadata only; no collection or state writes')
    parser.add_argument('--with-rotation', action='store_true', help='Run rotation then v2 with one shared provider collection')
    args = parser.parse_args(argv)
    if args.with_rotation:
        result = run_combined_cycle(args)
        print(json.dumps({'status': result.status, 'success': result.success,
            'rotationStatus': result.rotation.status, 'legacyStatus': result.legacy.status,
            **({'rotationErrorCode': result.rotation.error_code} if result.rotation.error_code else {}),
            **({'legacyErrorCode': result.legacy.error_code} if result.legacy.error_code else {})},
            ensure_ascii=False, separators=(',', ':')))
        return 0 if result.success else 1
    result = run_job(args)
    if args.rotation_report:
        print(json.dumps(result.metadata or {}, ensure_ascii=False, separators=(',', ':')))
        return 0 if result.success else 1
    summary = {'status': result.status, 'success': result.success}
    if result.payload:
        summary.update(observedAt=result.payload['observedAt'], session=result.payload['session'],
                       completeness=result.payload['dataStatus']['completeness'],
                       objectCounts={'global': 1, 'aShare': 1, 'styles': len(result.payload['styles']),
                                     'industries': len(result.payload['industries']),
                                     'coreConcepts': len(result.payload['concepts']['core']),
                                     'dynamicConcepts': len(result.payload['concepts']['dynamic'])},
                       synthetic=bool(args.fixture))
    if result.error_code:
        summary['errorCode'] = result.error_code
    if result.metadata:
        summary['safeCodes'] = result.metadata['safeCodes']
        summary.update(rotation_operations.safe_health(result.metadata))
    print(json.dumps(summary, ensure_ascii=False, separators=(',', ':')))
    return 0 if result.success else 1


if __name__ == '__main__':
    raise SystemExit(main())
