"""Private shadow ledger and fail-closed release evidence; never publish or enable."""
from datetime import date, datetime
import argparse
import json
import math
import os
from pathlib import Path
from statistics import median
from tempfile import NamedTemporaryFile
from zoneinfo import ZoneInfo

from .scoring import load_config
from .sources import INDUSTRY_DEFINITIONS
from .concepts import concept_definitions, load_concept_config

SHANGHAI = ZoneInfo('Asia/Shanghai')
VERSIONS = ('sectorScoringVersion', 'sectorUniverseVersion')
SAFE_CODES = frozenset({'INVALID_STATE', 'COLLECTION_FAILED', 'INVALID_PAYLOAD', 'SCORING_FAILED',
    'STATE_WRITE_FAILED', 'WINDOW_EXPIRED', 'STATE_DURABILITY_UNCONFIRMED', 'LEDGER_WRITE_FAILED',
    'LIVE_HISTORY_UNVERIFIED', 'LIVE_QUOTA_UNVERIFIED', 'IDENTITY_MISMATCH', 'UNIT_MISMATCH',
    'FUTURE_TIMESTAMP', 'CALENDAR_UNVERIFIED'})
SESSIONS = ('09:45', '11:30', '14:00', 'close')


def number(value, low=0, high=100):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and low <= value <= high


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('INVALID_STATE')
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('INVALID_STATE')
    return parsed.astimezone(SHANGHAI)


def calendar_dates(values):
    if not isinstance(values, list) or any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day for day in values):
        raise ValueError('INVALID_CALENDAR')
    if values != sorted(set(values)):
        raise ValueError('INVALID_CALENDAR')
    return values


def _stamp(value):
    try:
        return timestamp(value).isoformat()
    except (ValueError, TypeError, OverflowError):
        return None


def _counts(value):
    value = value if isinstance(value, dict) else {}
    return {key: value.get(key) if isinstance(value.get(key), int) and number(value[key], 0, bound) else 0
            for key, bound in [('industries', 35), ('concepts', 75)]}


def safe_health(value):
    """Whitelist both keys and values, even when reading corrupt private metadata."""
    value = value if isinstance(value, dict) else {}
    code = value.get('rotationSafeErrorCode')
    return {'rotationMode': 'shadow',
        'rotationSession': value.get('rotationSession') if value.get('rotationSession') in SESSIONS else None,
        'rotationCoverage': value.get('rotationCoverage') if number(value.get('rotationCoverage')) else None,
        'rotationUniverseCounts': _counts(value.get('rotationUniverseCounts')),
        'rotationLatencySeconds': value.get('rotationLatencySeconds') if number(value.get('rotationLatencySeconds'), 0, 86400) else None,
        'rotationCloseSuccesses': value.get('rotationCloseSuccesses') if isinstance(value.get('rotationCloseSuccesses'), int) and number(value.get('rotationCloseSuccesses'), 0, 100000) else None,
        'rotationSafeErrorCode': code if code is None or isinstance(code, str) and code in SAFE_CODES else 'INVALID_STATE',
        'rotationObservedAt': _stamp(value.get('rotationObservedAt')),
        'rotationSourceAt': _stamp(value.get('rotationSourceAt'))}


def _versions(config):
    return {key: config[key] for key in VERSIONS}


def _no_links(path):
    if any(part.is_symlink() for part in [path, path.parent, path.parent.parent]):
        raise ValueError('INVALID_STATE')


def _event(value, config):
    """No payloads, provider rows, arbitrary strings or credentials survive."""
    if not isinstance(value, dict):
        raise ValueError('INVALID_STATE')
    day = value.get('marketDate')
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day or value.get('session') not in SESSIONS:
        raise ValueError('INVALID_STATE')
    observed, source = _stamp(value.get('observedAt')), _stamp(value.get('sourceAt'))
    if observed is None or timestamp(observed).date().isoformat() != day:
        raise ValueError('INVALID_STATE')
    code = value.get('safeErrorCode')
    code = code if code is None or isinstance(code, str) and code in SAFE_CODES else 'INVALID_STATE'
    official = value.get('officialClose') is True and value['session'] == 'close'
    if official and value.get('success') is True:
        valid_time = source is not None and timestamp(source).date().isoformat() == day and timestamp(source).hour >= 15 and timestamp(source) <= timestamp(observed)
        close = timestamp(observed)
        valid_time = valid_time and close.hour == 15 and (close.minute < 30 or close.minute == 30 and close.second == 0 and close.microsecond == 0)
        if not valid_time:
            code, official = 'FUTURE_TIMESTAMP', False
    definitions = {'industry': {i for i, _ in INDUSTRY_DEFINITIONS},
                   'concept': {i for i, _ in concept_definitions(load_concept_config())}}
    lists = value.get('opportunityLists', {})
    lists = lists if isinstance(lists, dict) else {}
    selected = {u: list(dict.fromkeys(i for i in lists.get(u, []) if isinstance(i, str) and i in ids))[:10]
                if isinstance(lists.get(u, []), list) else [] for u, ids in definitions.items()}
    count = value.get('candidateCount')
    return {'marketDate': day, 'session': value['session'], 'observedAt': observed, 'sourceAt': source,
        'success': value.get('success') is True and code is None and value.get('publicationSkipped') is True,
        'officialClose': official, 'officialMarketDate': day in calendar_dates(config.get('schedule', {}).get('tradingDates', [])),
        'publicationSkipped': value.get('publicationSkipped') is True, 'counts': _counts(value.get('counts')),
        'medianCompleteness': value.get('medianCompleteness') if number(value.get('medianCompleteness')) else None,
        'minimumCandidateCompleteness': value.get('minimumCandidateCompleteness') if number(value.get('minimumCandidateCompleteness')) else None,
        'candidateCount': count if isinstance(count, int) and number(count, 0, 110) else 0,
        'latencySeconds': value.get('latencySeconds') if number(value.get('latencySeconds'), 0, 86400) else None,
        'safeErrorCode': code, 'opportunityLists': selected}


def _envelope(events, config):
    events = [_event(event, config) for event in events]
    successes = sorted({event['marketDate'] for event in events if event['success'] and event['officialClose'] and event['officialMarketDate']})
    # Churn compares consecutive successful formal closes within each universe.
    previous = {}
    for event in sorted(events, key=lambda event: (event['observedAt'], event['session'], event['success'])):
        event['opportunityListChurn'] = {u: None for u in ('industry', 'concept')}
        if not (event['success'] and event['officialClose']):
            continue
        for universe, identities in event['opportunityLists'].items():
            current = set(identities)
            if universe in previous:
                old = previous[universe]
                event['opportunityListChurn'][universe] = 1-len(old & current)/max(len(old), len(current)) if old or current else 0
            previous[universe] = current
    return {'schemaVersion': 'rotation-shadow-ledger-v1', 'versions': _versions(config),
            'events': events, 'successfulCloseDates': successes}


def read_ledger(path, config):
    path = Path(path); _no_links(path)
    if not path.exists():
        return _envelope([], config)
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get('schemaVersion') != 'rotation-shadow-ledger-v1' or value.get('versions') != _versions(config) or not isinstance(value.get('events'), list):
        raise ValueError('INVALID_STATE')
    return _envelope(value['events'], config)


def update_ledger(path, event, config):
    """Caller holds the provider job lock. Replace atomically, including fsync."""
    path = Path(path); ledger = read_ledger(path, config)
    event = _event(event, config)
    def identity(row):
        # Retain failed attempts even after recovery; repeated reporting is idempotent.
        return row['marketDate'], row['session'], row['observedAt'], row['success'], row['safeErrorCode']
    events = {identity(row): row for row in ledger['events']}
    events[identity(event)] = event
    ledger = _envelope(list(events.values()), config)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700); path.parent.chmod(0o700)
    temporary = None
    try:
        with NamedTemporaryFile(mode='w', dir=path.parent, prefix='.rotation-', delete=False) as output:
            temporary = Path(output.name); os.fchmod(output.fileno(), 0o600)
            json.dump(ledger, output, allow_nan=False, separators=(',', ':'))
            output.flush(); os.fsync(output.fileno())
        temporary.replace(path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return ledger


def event_from_block(block, now, source_at, config, *, success=True, code=None, session=None, scored_rows=None):
    from .rotation import derive_current_views
    rows = block.get('industries', []) + block.get('concepts', [])
    candidates = derive_current_views(scored_rows if scored_rows is not None else rows, config).get('potentialRotation', []) if rows else []
    # All candidate scores are already versioned derived values; IDs stay private.
    return _event({'marketDate': now.astimezone(SHANGHAI).date().isoformat(),
        'session': session or block.get('session', 'close'), 'observedAt': now.isoformat(), 'sourceAt': source_at,
        'success': success, 'officialClose': block.get('officialClose') is True,
        'publicationSkipped': True, 'counts': {'industries': len(block.get('industries', [])), 'concepts': len(block.get('concepts', []))},
        'medianCompleteness': median([row['completeness'] for row in rows]) if rows else None,
        'candidateCount': len(candidates), 'minimumCandidateCompleteness': min((row['completeness'] for row in candidates), default=None),
        'latencySeconds': (now-timestamp(source_at)).total_seconds() if source_at else None,
        'safeErrorCode': code,
        'opportunityLists': {u: [row['id'] for row in candidates if row['universe'] == u][:10] for u in ('industry', 'concept')}}, config)


def health_for_event(event, ledger):
    return safe_health({'rotationSession': event['session'], 'rotationCoverage': event['medianCompleteness'],
        'rotationUniverseCounts': event['counts'], 'rotationLatencySeconds': event['latencySeconds'],
        'rotationCloseSuccesses': len(ledger['successfulCloseDates']), 'rotationSafeErrorCode': event['safeErrorCode'],
        'rotationObservedAt': event['observedAt'], 'rotationSourceAt': event['sourceAt']})


def _mapping(value):
    return value if isinstance(value, dict) else {}


def evaluate_release(ledger, official_dates, historical):
    """Evidence assessment only. No return value can authorize production changes."""
    failed = []
    try:
        dates = calendar_dates(official_dates)
        if len(dates) != 10:
            failed.append('TEN_OFFICIAL_DATES')
    except (ValueError, TypeError):
        dates = []; failed.append('TEN_OFFICIAL_DATES')
    events = [event for event in ledger.get('events', []) if event.get('marketDate') in dates]
    closes = {e['marketDate'] for e in events if e.get('success') is True and e.get('officialClose') is True and e.get('officialMarketDate') is True}
    if len(closes) < 9: failed.append('CLOSE_SUCCESS_9_OF_10')
    valid = [event for event in events if event.get('success') is True]
    if not valid or any(e.get('counts', {}).get('industries') != 35 or not number(e.get('counts', {}).get('concepts'), 72, 75) for e in valid):
        failed.append('UNIVERSE_COVERAGE')
    if not valid or any(not number(e.get('medianCompleteness'), 80) for e in valid): failed.append('MEDIAN_COMPLETENESS')
    if not valid or not any(e.get('candidateCount', 0) > 0 for e in valid) or any(e.get('candidateCount', 0) > 0 and not number(e.get('minimumCandidateCompleteness'), 70) for e in valid):
        failed.append('CANDIDATE_COMPLETENESS')
    if any(e.get('safeErrorCode') in {'IDENTITY_MISMATCH', 'UNIT_MISMATCH', 'FUTURE_TIMESTAMP', 'INVALID_PAYLOAD', 'INVALID_STATE'} for e in events): failed.append('IDENTITY_UNIT_TIME')
    if any(not number(e.get('latencySeconds'), 0, 600) for e in valid if e.get('session') == 'close'): failed.append('CLOSE_LATENCY')
    if not valid or any(e.get('publicationSkipped') is not True for e in valid): failed.append('PUBLICATION_SKIPPED')
    historical = historical if isinstance(historical, dict) else {}
    if historical.get('liveVerified') is not True or historical.get('versions') != ledger.get('versions'):
        failed.append('LIVE_HISTORY_EVIDENCE')
    for universe in ('industry', 'concept'):
        universe_report = _mapping(_mapping(historical.get('universes')).get(universe))
        horizons = _mapping(universe_report.get('horizons'))
        complete = number(universe_report.get('listTurnover'), 0, 1)
        for horizon in ('1', '3', '5'):
            point = _mapping(horizons.get(horizon))
            rows = point.get('dates', [])
            complete = complete and isinstance(rows, list) and bool(rows) and isinstance(point.get('validDates'), int)
            complete = complete and all(isinstance(row, dict) and isinstance(row.get('marketDate'), str) for row in rows)
            complete = complete and len({row['marketDate'] for row in rows}) == len(rows)
            complete = complete and sum(row.get('status') == 'VALID' for row in rows) == point.get('validDates')
            complete = complete and all(key in point for key in ('rankCorrelation', 'spread', 'hitRate', 'maximumDrawdown'))
            complete = complete and (point.get('rankCorrelation') is None or number(point['rankCorrelation'], -1, 1))
            complete = complete and number(point.get('hitRate'), 0, 1) and number(point.get('maximumDrawdown'))
        if not complete:
            failed.append('HISTORICAL_DIAGNOSTICS_'+universe.upper())
        if not any(number(_mapping(horizons.get(h)).get('spread'), 0, 100000) and horizons[h]['spread'] > 0 and horizons[h].get('nonDominated') is True and number(horizons[h].get('validDates'), 2, 100000) for h in ('3', '5')):
            failed.append('HISTORICAL_SPREAD_'+universe.upper())
    return {'evidenceGatesPassed': not failed, 'failedGates': failed, 'officialDates': dates,
        'successfulCloses': len(closes), 'productionMode': 'v2', 'productionSwitchApproved': False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--calendar', type=Path, required=True, help='JSON ordered ten-date window, from verified official calendar')
    parser.add_argument('--historical', type=Path, required=True)
    parser.add_argument('--config', type=Path)
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        dates = calendar_dates(json.loads(args.calendar.read_text()))
        config.setdefault('schedule', {})['tradingDates'] = dates
        result = evaluate_release(read_ledger(args.ledger, config), dates, json.loads(args.historical.read_text()))
        print(json.dumps(result, separators=(',', ':')))
        return 0 if result['evidenceGatesPassed'] else 1
    except (ValueError, TypeError, KeyError, OSError):
        print('{"evidenceGatesPassed":false,"failedGates":["INVALID_STATE"],"productionMode":"v2","productionSwitchApproved":false}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
