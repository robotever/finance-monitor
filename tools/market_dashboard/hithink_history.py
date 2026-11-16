"""Strict read-only access to the local Hithink daily-price database.

This module accepts no arbitrary SQL and retains no provider envelopes.  It is
an offline history boundary only; it never changes production score inputs.
"""
from datetime import date
import json
import math
from pathlib import Path
import re
import subprocess


SCHEMA = 'hithink-daily-history-v1'
_SYMBOL = re.compile(r'^[0-9]{6}\.(?:SH|SZ|BJ)$')
_VIEWS = {'none': 'v_daily', 'qfq': 'v_daily_qfq', 'hfq': 'v_daily_hfq'}


class HithinkHistoryError(ValueError):
    """Stable safe error without provider response details."""

    def __init__(self, code='HITHINK_HISTORY_ERROR'):
        self.code = code
        super().__init__(code)


def _day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (TypeError, ValueError):
        raise HithinkHistoryError('INVALID_HISTORY_REQUEST') from None


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
            try:
                observed = date.fromisoformat(raw_day)
                canonical = observed.isoformat() == raw_day
            except (TypeError, ValueError):
                raise HithinkHistoryError() from None
            if not canonical or not start <= observed <= end:
                raise HithinkHistoryError()
            if (not isinstance(close, (int, float)) or isinstance(close, bool)
                    or not math.isfinite(close) or close <= 0):
                raise HithinkHistoryError()
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
