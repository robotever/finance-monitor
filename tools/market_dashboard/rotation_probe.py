"""Read-only Wind feasibility probe. stdout contains allowlisted metadata only.

No file writes, publication, retries or full historical backfill. A full probe
checks the current universe and estimates history request cost before any call.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
from time import monotonic

from . import sources
from .concepts import concept_definitions, load_concept_config


# Deliberate liquid/defensive/cyclical and broad/niche theme spread. These are
# sampling hypotheses, not measured size or activity classifications.
SAMPLE_INDUSTRIES = ('882100.WI', '882115.WI', '882120.WI', '882125.WI', '882130.WI', '882136.WI')
SAMPLE_CONCEPTS = ('884201.WI', '8841349.WI', '8841699.WI', '8841049.WI', '8841432.WI', '8841201.WI')
FIELDS = ('涨跌幅', '5日涨跌幅', '20日涨跌幅', '成交额', '换手率',
          '当日主力净流入额', '近5日主力净流入额', '近20日主力净流入额',
          '上涨家数', '下跌家数', '平盘家数')
SAFE_CODES = {'AUTH_ERROR', 'RATE_LIMIT_ERROR', 'backend_error', 'NETWORK_ERROR',
              'TOOL_RUNTIME_ERROR', 'COMMAND_ERROR', 'MALFORMED_RESPONSE',
              'IDENTITY_MISMATCH', 'MISSING_FIELDS', 'UNIT_MISMATCH',
              'INVALID_HISTORY_DATE', 'INVALID_HISTORY_OHLC', 'INVALID_HISTORY_REQUEST'}
SAFE_UNITS = {'元', '万元', '亿元', '个', '%', '点', '指数点', '无单位'}


def summarize_rotation_capability(batches: dict[str, sources.SourceBatch],
                                  histories: dict[str, list[dict]],
                                  requested_at: datetime) -> dict:
    """Only counts, dates, allowlisted fields/units and safe codes leave memory."""
    groups = {}
    for group in ('industries', 'concepts'):
        if group not in batches:
            continue
        batch = batches[group]
        groups[group] = {
            'rowCount': len(batch.rows),
            'identityCount': len({row.get('id') for row in batch.rows if row.get('id')}),
            'complete': batch.complete,
            'fieldCoverage': {field: sum(row.get(field) not in (None, '', '.') for row in batch.rows)
                              for field in FIELDS},
            'units': {field: sorted({row.get('_units', {}).get(field, 'unknown')
                                    if row.get('_units', {}).get(field) in SAFE_UNITS else 'unknown'
                                    for row in batch.rows}) for field in FIELDS},
            'timestamps': sorted({sources._observation_time(row['_timestamp']) for row in batch.rows
                                  if row.get('_timestamp')}),
        }
    dates = sorted({point['date'] for history in histories.values() for point in history})
    return {
        'requestedAt': requested_at.isoformat(), 'groups': groups,
        'history': {
            'price': {'status': 'verified' if dates else 'still_to_confirm',
                      'identityCount': sum(bool(rows) for rows in histories.values()),
                      'minimumCloses': min((len(rows) for rows in histories.values()), default=0),
                      'maximumCloses': max((len(rows) for rows in histories.values()), default=0),
                      'earliestDate': dates[0] if dates else None,
                      'latestDate': dates[-1] if dates else None,
                      'closesAtLeast': {str(count): sum(len(rows) >= count for rows in histories.values())
                                        for count in (20, 60, 250)}},
            'flow': {'status': 'unavailable', 'reason': 'CURRENT_ROLLING_FIELDS_ARE_NOT_DATED_HISTORY'},
            'breadth': {'status': 'unavailable', 'reason': 'KLINE_HAS_NO_DATED_COMPONENT_COUNTS'},
        },
    }


def _status(code):
    if code == 'AUTH_ERROR':
        return 'BLOCKED_KEY'
    if code == 'RATE_LIMIT_ERROR':
        return 'BLOCKED_QUOTA'
    return 'BLOCKED_RUNTIME'


def main(argv=None, *, runner=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scope', choices=('sample', 'full'), default='sample')
    parser.add_argument('--metadata-only', required=True, action='store_true')
    args = parser.parse_args(argv)
    runner = runner or sources.run_command
    requested_at = datetime.now(timezone.utc)
    start = monotonic()
    concept_config = load_concept_config()
    industries = sources.INDUSTRY_DEFINITIONS
    if args.scope == 'sample':
        industries = tuple(item for item in industries if item[0] in SAMPLE_INDUSTRIES)
        concept_config = {**concept_config, 'universe': [entry for entry in concept_config['universe']
                                                       if entry['id'] in SAMPLE_CONCEPTS]}
    definitions = (*industries, *concept_definitions(concept_config))
    cost = {'historicalCallsEstimated': len(definitions),
            'currentCallsEstimated': 1 + (len(concept_config['universe']) + 49) // 50,
            'historicalBackfillAttempted': False, 'quotaFit': 'still_to_confirm'}
    if args.scope == 'full':
        print(json.dumps({'phase': 'cost_estimate', **cost}), flush=True)
    batches, histories, errors, requests = {}, {}, [], []

    def timed_runner(argv, **kwargs):
        before = monotonic()
        try:
            return runner(argv, **kwargs)
        finally:
            requests.append(round(monotonic() - before, 3))

    batches['industries'] = sources._wind(
        timed_runner, {}, 'industries', industries, sources.INDUSTRY_PRICE_FIELDS)
    if batches['industries'].errors:
        errors.extend(error.get('code') for error in batches['industries'].errors)
    else:
        batches['concepts'] = sources.collect_wind_concepts(timed_runner, {}, concept_config)
        errors.extend(error.get('code') for error in batches['concepts'].errors)
    if not errors:
        # Explicit calendar interval gives room for 250 closes; actual counts
        # remain observed, never inferred from a rolling return field.
        end = requested_at.astimezone(timezone(timedelta(hours=8))).date() - timedelta(days=1)
        begin = end - timedelta(days=550)
        # Full mode estimates only; backfill belongs to a later gated task.
        for code, _ in definitions if args.scope == 'sample' else ():
            try:
                histories[code] = sources.collect_index_history(
                    timed_runner, code, begin.isoformat(), end.isoformat())
            except sources.SourceError as error:
                errors.append(error.code)
                break
    errors = sorted({code if code in SAFE_CODES else 'MALFORMED_RESPONSE' for code in errors})
    summary = summarize_rotation_capability(batches, histories, requested_at)
    summary.update(scope=args.scope, status=_status(errors[0]) if errors else 'DONE_WITH_LIMITS',
                   safeErrorCodes=errors, requestDurationsSeconds=requests,
                   requestedIdentityCounts={'industries': len(industries),
                                            'concepts': len(concept_config['universe'])},
                   historicalSampleAttempted=bool(histories) or len(requests) > cost['currentCallsEstimated'],
                   durationSeconds=round(monotonic() - start, 3), **cost)
    print(json.dumps(summary, ensure_ascii=False))
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main())
