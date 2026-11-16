"""Strict, read-only CLI boundary for the Hithink sector universe.

Only normalized immutable records leave this module. Provider stdout, stderr,
request identifiers and exception text are never included in errors.
"""
from dataclasses import dataclass
from datetime import date, datetime
import json
import math
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo('Asia/Shanghai')
_INDEX = re.compile(r'^[0-9]{6}\.(?:TI|SH|SZ|BJ)$')
_STOCK = re.compile(r'^[0-9]{6}\.(?:SH|SZ|BJ)$')


class HithinkError(ValueError):
    """Stable safe code, without provider content."""

    def __init__(self, code='INVALID_HITHINK_RESPONSE'):
        self.code = code
        super().__init__(code)


def finite_number(value, *, positive=False, nonnegative=False):
    if (not isinstance(value, (int, float)) or isinstance(value, bool)):
        raise HithinkError()
    try:
        number = float(value)
    except (OverflowError, ValueError):
        raise HithinkError() from None
    if (not math.isfinite(number) or (positive and number <= 0)
            or (nonnegative and number < 0)):
        raise HithinkError()
    return number


def canonical_date(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError()
        return parsed
    except (TypeError, ValueError):
        raise HithinkError() from None


def _timestamp(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HithinkError()
    try:
        datetime.fromtimestamp(value / 1000, SHANGHAI)
    except (OverflowError, OSError, ValueError):
        raise HithinkError() from None
    return value


def shanghai_market_date(date_ms: int) -> str:
    return datetime.fromtimestamp(_timestamp(date_ms) / 1000, SHANGHAI).date().isoformat()


@dataclass(frozen=True)
class SectorDefinition:
    code: str
    name: str
    tag: str


@dataclass(frozen=True)
class Membership:
    sector_code: str
    stock_code: str
    observed_at_ms: int


@dataclass(frozen=True)
class IndexDailyBar:
    code: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    turnover: float


@dataclass(frozen=True)
class IndexSnapshot:
    code: str
    timestamp_ms: int
    last_price: float
    price_change: float
    price_change_ratio_pct: float
    open_price: float
    high_price: float
    low_price: float
    prev_price: float
    volume: float
    turnover: float


@dataclass(frozen=True)
class StockSnapshot(IndexSnapshot):
    pass


def _fields(value, required, optional=()):
    if (not isinstance(value, dict) or not set(required) <= set(value)
            or set(value) - set(required) - set(optional)):
        raise HithinkError()
    return value


def _code(value, pattern=_INDEX):
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise HithinkError()
    return value


def _text(value):
    if not isinstance(value, str) or not value.strip():
        raise HithinkError()
    return value


def _count(value):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise HithinkError()
    return value


def _unique(values):
    if len(set(values)) != len(values):
        raise HithinkError()


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise HithinkError()
        result[key] = value
    return result


def run_command(argv):
    return subprocess.run(argv, capture_output=True, text=True, timeout=90, check=False)


class HithinkClient:
    def __init__(self, cli_path, *, runner=run_command):
        try:
            path = Path(cli_path)
            if not path.is_absolute():
                raise ValueError()
        except (TypeError, ValueError):
            raise HithinkError('INVALID_HITHINK_REQUEST') from None
        self.cli_path = str(path)
        self.runner = runner

    def _request_codes(self, codes, pattern=_INDEX):
        try:
            if not isinstance(codes, list) or not codes:
                raise HithinkError()
            for code in codes:
                _code(code, pattern)
            _unique(codes)
        except HithinkError:
            raise HithinkError('INVALID_HITHINK_REQUEST') from None
        return codes

    def _window(self, start_ms, end_ms):
        try:
            _timestamp(start_ms)
            _timestamp(end_ms)
            if start_ms > end_ms:
                raise HithinkError()
        except HithinkError:
            raise HithinkError('INVALID_HITHINK_REQUEST') from None

    def _call(self, domain, command, options, data_fields):
        argv = [self.cli_path, domain, command, *options, '--format', 'json']
        try:
            result = self.runner(argv)
        except (OSError, subprocess.SubprocessError, TimeoutError, UnicodeError):
            raise HithinkError('HITHINK_COMMAND_FAILED') from None
        if not hasattr(result, 'returncode') or result.returncode != 0:
            raise HithinkError('HITHINK_COMMAND_FAILED')
        try:
            raw = json.loads(result.stdout, object_pairs_hook=_json_object)
        except (ValueError, TypeError, UnicodeError):
            raise HithinkError() from None
        _fields(raw, ('ok', 'command', 'data', 'meta'))
        if raw['ok'] is not True or raw['command'] != f'{domain}.{command}':
            raise HithinkError()
        meta = _fields(raw['meta'], ('source', 'count', 'truncated', 'schema_version'), ('request_id',))
        if (meta['source'] != 'remote' or meta['truncated'] is not False
                or meta['schema_version'] != '1'):
            raise HithinkError()
        if 'request_id' in meta:
            _text(meta['request_id'])
        data = _fields(raw['data'], data_fields)
        if not isinstance(data['item'], list) or _count(meta['count']) != len(data['item']):
            raise HithinkError()
        if 'timestamp' in data:
            _timestamp(data['timestamp'])
        return data

    def catalog(self, tag):
        if tag not in ('industry', 'cn_concept', 'region', 'tszs'):
            raise HithinkError('INVALID_HITHINK_REQUEST')
        data = self._call('index', 'catalog', ['--tag', tag], ('item', 'timestamp'))
        rows = []
        for raw in data['item']:
            _fields(raw, ('thscode', 'name'))
            rows.append(SectorDefinition(_code(raw['thscode']), _text(raw['name']), tag))
        _unique([row.code for row in rows])
        return tuple(rows)

    def constituents(self, code):
        self._request_codes([code])
        data = self._call('index', 'constituents', ['--thscode', code], ('item', 'timestamp'))
        rows = []
        for raw in data['item']:
            _fields(raw, ('thscode', 'ticker', 'name'))
            stock = _code(raw['thscode'], _STOCK)
            if raw['ticker'] != stock.split('.')[0]:
                raise HithinkError()
            _text(raw['name'])
            rows.append(Membership(code, stock, data['timestamp']))
        _unique([row.stock_code for row in rows])
        return tuple(rows)

    def _bars(self, code, items, start_ms, end_ms):
        rows = []
        for raw in items:
            _fields(raw, ('date_ms', 'open_price', 'high_price', 'low_price', 'close_price', 'volume', 'turnover'))
            observed = _timestamp(raw['date_ms'])
            if not start_ms <= observed <= end_ms:
                raise HithinkError()
            prices = [finite_number(raw[key], positive=True) for key in ('open_price', 'high_price', 'low_price', 'close_price')]
            rows.append(IndexDailyBar(code, shanghai_market_date(observed), *prices,
                                      finite_number(raw['volume'], nonnegative=True),
                                      finite_number(raw['turnover'], nonnegative=True)))
        _unique([row.date for row in rows])
        return tuple(sorted(rows, key=lambda row: row.date))

    def index_history(self, code, start_ms, end_ms):
        self._request_codes([code])
        self._window(start_ms, end_ms)
        data = self._call('index', 'history', ['--thscode', code, '--start-ms', str(start_ms), '--end-ms', str(end_ms)],
                          ('item', 'timestamp', 'thscode', 'interval', 'adjust'))
        if data['thscode'] != code or data['interval'] != '1d' or data['adjust'] is not None:
            raise HithinkError()
        return self._bars(code, data['item'], start_ms, end_ms)

    def index_history_batch(self, codes, start_ms, end_ms):
        """Probe batch support; cross-check empty/missing groups using singles.

        An empty batch contradicted by a single response fails explicitly;
        callers must budget those additional read calls.
        """
        self._request_codes(codes)
        self._window(start_ms, end_ms)
        if len(codes) > 10:
            raise HithinkError('INVALID_HITHINK_REQUEST')
        data = self._call('index', 'history-batch', ['--thscodes', ','.join(codes), '--start-ms', str(start_ms), '--end-ms', str(end_ms)],
                          ('item', 'interval', 'adjust'))
        if data['interval'] != '1d' or data['adjust'] is not None:
            raise HithinkError()
        groups = {}
        for raw in data['item']:
            _fields(raw, ('thscode', 'timestamp', 'item'))
            code = _code(raw['thscode'])
            _timestamp(raw['timestamp'])
            if code not in codes or code in groups or not isinstance(raw['item'], list):
                raise HithinkError()
            groups[code] = self._bars(code, raw['item'], start_ms, end_ms)
        for code in codes:
            if not groups.get(code) and self.index_history(code, start_ms, end_ms):
                raise HithinkError('HISTORY_BATCH_INCOMPLETE')
        return tuple(row for code in codes for row in groups.get(code, ()))

    def _snapshots(self, codes, *, stock):
        self._request_codes(codes, _STOCK if stock else _INDEX)
        options = ['--thscodes', ','.join(codes)]
        if stock:
            options += ['--limit', str(len(codes)), '--offset', '0']
        data = self._call('market' if stock else 'index', 'snapshot', options, ('item', 'timestamp', 'total'))
        if _count(data['total']) != len(codes) or len(data['item']) != len(codes):
            raise HithinkError()
        rows = []
        prices = ('last_price', 'price_change', 'price_change_ratio_pct', 'open_price', 'high_price', 'low_price', 'prev_price', 'volume', 'turnover')
        for raw in data['item']:
            _fields(raw, ('thscode', 'ticker', *prices))
            code = _code(raw['thscode'], _STOCK if stock else _INDEX)
            if code not in codes or raw['ticker'] != code.split('.')[0]:
                raise HithinkError()
            values = [finite_number(raw[key], nonnegative=key not in ('price_change', 'price_change_ratio_pct')) for key in prices]
            rows.append((StockSnapshot if stock else IndexSnapshot)(code, data['timestamp'], *values))
        _unique([row.code for row in rows])
        return tuple(rows)

    def index_snapshots(self, codes):
        return self._snapshots(codes, stock=False)

    def stock_snapshots(self, codes):
        return self._snapshots(codes, stock=True)
