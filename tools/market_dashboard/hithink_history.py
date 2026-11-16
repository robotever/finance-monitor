"""Strict read-only access to the local Hithink daily-price database.

This module accepts no arbitrary SQL and retains no provider envelopes.  It is
an offline history boundary only; it never changes production score inputs.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess

from tools.market_dashboard.hithink_cli import HithinkError, canonical_date, finite_number


SCHEMA = 'hithink-daily-history-v1'
_SYMBOL = re.compile(r'^[0-9]{6}\.(?:SH|SZ|BJ)$')
_VIEWS = {'none': 'v_daily', 'qfq': 'v_daily_qfq', 'hfq': 'v_daily_hfq'}
AUDIT_SCHEMA = 'hithink-history-audit-v1'


class HithinkHistoryError(ValueError):
    """Stable safe error without provider response details."""

    def __init__(self, code='HITHINK_HISTORY_ERROR'):
        self.code = code
        super().__init__(code)


def _day(value):
    try:
        return canonical_date(value)
    except HithinkError:
        raise HithinkHistoryError('INVALID_HISTORY_REQUEST') from None


def _response_day(value):
    try:
        return canonical_date(value)
    except HithinkError:
        raise HithinkHistoryError() from None


def _close(value):
    try:
        return finite_number(value, positive=True)
    except HithinkError:
        raise HithinkHistoryError() from None


def _request(cli_path, db_path, symbols, start_date, end_date, adjustment, page_size):
    cli, database = Path(cli_path), Path(db_path)
    if not cli.is_absolute() or not database.is_absolute():
        raise HithinkHistoryError('INVALID_HISTORY_REQUEST')
    if (not isinstance(symbols, list) or not symbols
            or any(not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) for symbol in symbols)
            or len(set(symbols)) != len(symbols)):
        raise HithinkHistoryError('INVALID_HISTORY_REQUEST')
    start, end = _day(start_date), _day(end_date)
    if start > end or adjustment not in _VIEWS:
        raise HithinkHistoryError('INVALID_HISTORY_REQUEST')
    if (not isinstance(page_size, int) or isinstance(page_size, bool)
            or not 1 <= page_size <= 1000):
        raise HithinkHistoryError('INVALID_HISTORY_REQUEST')
    return cli, database, sorted(symbols), start, end, _VIEWS[adjustment]


def _decode(value):
    if hasattr(value, 'returncode'):
        if value.returncode != 0:
            raise HithinkHistoryError()
        value = value.stdout
    if isinstance(value, bytes):
        try:
            value = value.decode('utf-8')
        except UnicodeDecodeError:
            raise HithinkHistoryError() from None
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            raise HithinkHistoryError() from None
    if (not isinstance(value, dict) or value.get('ok') is not True
            or value.get('command') != 'db.query' or not isinstance(value.get('data'), list)):
        raise HithinkHistoryError()
    meta = value.get('meta')
    if not isinstance(meta, dict) or meta.get('truncated') is not False:
        raise HithinkHistoryError()
    count = meta.get('count')
    if not isinstance(count, int) or isinstance(count, bool) or count != len(value['data']):
        raise HithinkHistoryError()
    return value['data']


def _sql(view, symbols, start_date, end_date, page_size, offset):
    identities = ','.join(f"'{symbol}'" for symbol in symbols)
    return (f'select thscode, date, close from {view} '
            f'where thscode in ({identities}) '
            f"and date between '{start_date}' and '{end_date}' "
            f'order by date, thscode limit {page_size} offset {offset}')


def load_daily_closes(runner, cli_path: Path, db_path: Path, symbols: list[str],
                      start_date: str, end_date: str, *, adjustment: str = 'qfq',
                      page_size: int = 500) -> dict:
    """Load minimized daily closes through the official CLI's read-only query."""
    cli, database, requested, start, end, view = _request(
        cli_path, db_path, symbols, start_date, end_date, adjustment, page_size)
    rows, seen, pages, offset = [], set(), 0, 0
    while True:
        query = _sql(view, requested, start.isoformat(), end.isoformat(), page_size, offset)
        argv = [str(cli), '--db', str(database), 'db', 'query', '--sql', query]
        try:
            page = _decode(runner(argv))
        except HithinkHistoryError:
            raise
        except (OSError, subprocess.SubprocessError, TimeoutError):
            raise HithinkHistoryError() from None
        pages += 1
        if len(page) > page_size:
            raise HithinkHistoryError()
        for raw in page:
            if not isinstance(raw, dict) or set(raw) != {'thscode', 'date', 'close'}:
                raise HithinkHistoryError()
            identity, raw_day, close = raw['thscode'], raw['date'], raw['close']
            if identity not in requested:
                raise HithinkHistoryError()
            observed = _response_day(raw_day)
            if not start <= observed <= end:
                raise HithinkHistoryError()
            close = _close(close)
            key = raw_day, identity
            if key in seen:
                raise HithinkHistoryError()
            seen.add(key)
            rows.append({'id': identity, 'date': raw_day, 'close': float(close),
                         'adjustment': adjustment, 'source': 'Hithink'})
        if len(page) < page_size:
            break
        offset += page_size
    rows.sort(key=lambda row: (row['date'], row['id']))
    returned = sorted({row['id'] for row in rows})
    missing = sorted(set(requested) - set(returned))
    return {
        'schemaVersion': SCHEMA,
        'source': 'Hithink',
        'adjustment': adjustment,
        'startDate': start.isoformat(),
        'endDate': end.isoformat(),
        'requestedSymbols': requested,
        'returnedSymbols': returned,
        'missingSymbols': missing,
        'complete': not missing,
        'pages': pages,
        'rows': rows,
    }


def audit_history(batch: dict) -> dict:
    """Project a validated batch to aggregate-only coverage metadata."""
    if (not isinstance(batch, dict) or batch.get('schemaVersion') != SCHEMA
            or batch.get('source') != 'Hithink' or batch.get('adjustment') not in _VIEWS):
        raise HithinkHistoryError()
    requested = batch.get('requestedSymbols')
    returned = batch.get('returnedSymbols')
    missing = batch.get('missingSymbols')
    rows = batch.get('rows')
    pages = batch.get('pages')
    if (not isinstance(requested, list) or requested != sorted(set(requested))
            or not requested or any(not isinstance(value, str) or not _SYMBOL.fullmatch(value)
                                    for value in requested)
            or not isinstance(returned, list) or returned != sorted(set(returned))
            or not isinstance(missing, list) or missing != sorted(set(missing))
            or not isinstance(rows, list) or not isinstance(pages, int)
            or isinstance(pages, bool) or pages < 1):
        raise HithinkHistoryError()
    start, end = batch.get('startDate'), batch.get('endDate')
    start_day, end_day = _day(start), _day(end)
    if start_day > end_day:
        raise HithinkHistoryError()
    dates, identities = [], set()
    for row in rows:
        if (not isinstance(row, dict)
                or set(row) != {'id', 'date', 'close', 'adjustment', 'source'}
                or row.get('source') != 'Hithink'
                or row.get('adjustment') != batch['adjustment']):
            raise HithinkHistoryError()
        identity, observed = row.get('id'), row.get('date')
        if identity not in requested:
            raise HithinkHistoryError()
        observed_day = _response_day(observed)
        if not start_day <= observed_day <= end_day:
            raise HithinkHistoryError()
        _close(row.get('close'))
        identities.add(identity)
        dates.append(observed)
    derived_returned = sorted(identities)
    derived_missing = sorted(set(requested) - identities)
    if (returned != derived_returned or missing != derived_missing
            or batch.get('complete') is not (not derived_missing)):
        raise HithinkHistoryError()
    return {
        'schemaVersion': AUDIT_SCHEMA,
        'source': 'Hithink',
        'adjustment': batch['adjustment'],
        'startDate': start,
        'endDate': end,
        'requestedSymbols': len(requested),
        'returnedSymbols': len(returned),
        'missingSymbols': missing,
        'rowCount': len(rows),
        'firstDate': min(dates, default=None),
        'lastDate': max(dates, default=None),
        'pages': pages,
        'complete': not missing,
    }


def run_command(argv):
    """Run the official CLI without a shell and keep output private."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=90, check=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', required=True, type=Path)
    parser.add_argument('--db', required=True, type=Path)
    parser.add_argument('--symbols', required=True)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--adjustment', choices=tuple(_VIEWS), default='qfq')
    parser.add_argument('--page-size', type=int, default=500)
    args = parser.parse_args(argv)
    try:
        symbols = [value.strip() for value in args.symbols.split(',')]
        batch = load_daily_closes(
            run_command, args.cli, args.db, symbols, args.start, args.end,
            adjustment=args.adjustment, page_size=args.page_size)
        audit = audit_history(batch)
        print(json.dumps(audit, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
        return 0 if audit['complete'] else 1
    except (HithinkHistoryError, OSError, subprocess.SubprocessError, TimeoutError):
        print(json.dumps({'schemaVersion': AUDIT_SCHEMA, 'complete': False,
                          'safeErrorCode': 'HITHINK_HISTORY_ERROR'}, separators=(',', ':')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
