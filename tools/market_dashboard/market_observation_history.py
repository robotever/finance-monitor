"""Private raw-history export and event adjustment; never writes the provider DB.

Uses the installed official CLI's multiplicative event formula. This is a local
calculation from official raw prices/events, and differs from REST chart qfq.
"""
import bisect
import collections
import csv
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import ssl
import subprocess
import urllib.request
from zoneinfo import ZoneInfo

SH = ZoneInfo('Asia/Shanghai')
EVENT_URL = 'https://fuyao.aicubes.cn/api/dump/market-dumps/adjustment-factors/download-url'
METHOD = '同花顺原始日线+公告事件，按CLI乘法口径自行调整；与REST图表前复权结果不保证相同'
VERSION = 'cli-event-multiplicative-v1'


class HistoryError(ValueError):
    """Safe error code; never provider responses, credentials or signed URLs."""


def _private_write(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.tmp')
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(temporary, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
    os.replace(temporary, path)


def _json_write(path, value):
    _private_write(path, json.dumps(value, ensure_ascii=False, allow_nan=False).encode())


def _run(argv, timeout=120):
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
        if result.returncode != 0:
            raise HistoryError('HISTORY_COMMAND_FAILED')
        return result.stdout
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise HistoryError('HISTORY_COMMAND_FAILED') from None


def _export_raw(project_root, cache, previous_date):
    start = (date.fromisoformat(previous_date) - timedelta(days=180)).isoformat()
    target = cache / 'raw.csv'
    sql = ('SELECT thscode,date,"close",amount AS turnover FROM v_daily '
           f"WHERE date >= DATE '{start}' AND date <= DATE '{previous_date}' ORDER BY thscode,date")
    envelope = json.loads(_run([str(Path.home()/'.local/bin/hithink-finance'), '--db',
        str(project_root/'data/hithink/market.duckdb'), 'db', 'export', '--sql', sql,
        '--output', str(target), '--file-format', 'csv', '--format', 'json']))
    if envelope.get('ok') is not True or not target.exists():
        raise HistoryError('HISTORY_EXPORT_FAILED')
    os.chmod(target, 0o600)
    with target.open(newline='') as stream:
        return [{'thscode':r['thscode'], 'date':r['date'], 'close':float(r['close']),
                 'turnover':float(r['turnover'])} for r in csv.DictReader(stream)]


def _fetch_events(project_root, cache):
    """Keep both API key and short-lived signed URL in process memory only."""
    try:
        helper = project_root/'tools/hithink_mcp_headers.py'
        headers = json.loads(_run(['python3', str(helper)], timeout=15))
        if not headers.get('X-api-key'):
            raise HistoryError('EVENT_CREDENTIAL_UNAVAILABLE')
        ca = '/etc/ssl/cert.pem'
        context = ssl.create_default_context(cafile=ca if Path(ca).exists() else None)
        with urllib.request.urlopen(urllib.request.Request(EVENT_URL, headers=headers),
                                    context=context, timeout=45) as response:
            envelope = json.load(response)
        if envelope.get('code') != 0:
            raise HistoryError('EVENT_DUMP_UNAVAILABLE')
        signed = envelope['data']['presigned_url']
        if not isinstance(signed, str) or not signed.startswith('https://'):
            raise HistoryError('EVENT_DUMP_UNAVAILABLE')
        with urllib.request.urlopen(signed, context=context, timeout=60) as response:
            raw = response.read(20_000_001)
        if len(raw) > 20_000_000 or not raw.startswith(b'PAR1'):
            raise HistoryError('EVENT_DUMP_INVALID')
        path = cache/'events.parquet'
        _private_write(path, raw)
        # Existing source-project environment owns Parquet support. No install,
        # provider connection, source write, or DuckDB opening occurs here.
        python = project_root/'a-share-screener/.venv/bin/python'
        script = ('import json,sys;import pyarrow.parquet as pq;'
                  'print(json.dumps(pq.read_table(sys.argv[1]).to_pylist()))')
        events = json.loads(_run([str(python), '-c', script, str(path)]))
        if not isinstance(events, list) or not events:
            raise HistoryError('EVENT_DUMP_INVALID')
        for row in events:
            row['date'] = datetime.fromtimestamp(row['ex_date_ms']/1000, SH).date().isoformat()
            if row.get('currency') != 'CNY':
                raise HistoryError('EVENT_CURRENCY_INVALID')
        return events, {'sha256':hashlib.sha256(raw).hexdigest(), 'count':len(events),
                        'fetchedAt':datetime.now(SH).isoformat(), 'url':EVENT_URL}
    except HistoryError:
        raise
    except Exception:
        raise HistoryError('EVENT_DUMP_FAILED') from None


def adjust_bars(bars, events, previous_date):
    """Apply event ratios to all earlier prices, excluding future ex-dates.

    Ratio = previous raw close*(1+bonus+rights)/(previous raw close-dividend+
    rights*rights_price). An event takes effect at the first available bar on
    or after its ex-date. Prices are normalized at the last available bar.
    """
    grouped = collections.defaultdict(list)
    seen = set()
    for row in bars:
        key = row['thscode'], row['date']
        if key in seen or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', key[0]):
            raise HistoryError('HISTORY_IDENTITY_INVALID')
        seen.add(key)
        if row['date'] > previous_date:
            raise HistoryError('HISTORY_FUTURE_BAR')
        if not math.isfinite(row['close']) or row['close'] <= 0 or not math.isfinite(row['turnover']) or row['turnover'] < 0:
            raise HistoryError('HISTORY_NUMBER_INVALID')
        grouped[row['thscode']].append(dict(row))
    by_code = collections.defaultdict(list)
    for event in events:
        if event['date'] <= previous_date:
            by_code[event['thscode']].append(event)
    output = []; applied = 0
    for code, rows in sorted(grouped.items()):
        rows.sort(key=lambda r:r['date'])
        dates = [r['date'] for r in rows]; ratios = collections.defaultdict(lambda:1.)
        for event in by_code[code]:
            index = bisect.bisect_left(dates, event['date'])
            # Events effective before/on the first bar adjust no earlier prices
            # in this exported window. Future effective dates adjust nothing.
            if index == 0 or index == len(rows):
                continue
            values = [event[k] for k in ('dividend_per_share','per_share_bonus','allotment_ratio','allotment_price')]
            if any(type(x) not in (int,float) or not math.isfinite(x) or x < 0 for x in values):
                raise HistoryError('EVENT_RATIO_INVALID')
            dividend, bonus, rights, price = values
            previous = rows[index-1]['close']; denominator = previous-dividend+rights*price
            ratio = previous*(1+bonus+rights)/denominator if denominator else 0
            if not math.isfinite(ratio) or ratio <= 0:
                raise HistoryError('EVENT_RATIO_INVALID')
            ratios[index] *= ratio; applied += 1
        factor = 1.
        for index in range(len(rows)-1, -1, -1):
            rows[index]['close'] *= factor
            if not math.isfinite(rows[index]['close']) or rows[index]['close'] <= 0:
                raise HistoryError('EVENT_RATIO_INVALID')
            factor /= ratios.get(index, 1.)
        output.extend(rows)
    return output, {'appliedEvents':applied, 'method':METHOD, 'methodVersion':VERSION}


def ensure_history(state_root:Path, project_root:Path, previous_date:str)->Path:
    """Return a private CSV; refresh events daily and whenever source DB changes."""
    try:
        if date.fromisoformat(previous_date).isoformat() != previous_date:
            raise ValueError()
    except (ValueError, TypeError):
        raise HistoryError('HISTORY_DATE_INVALID') from None
    state_root = Path(state_root); project_root = Path(project_root)
    database = project_root/'data/hithink/market.duckdb'
    mtime = database.stat().st_mtime_ns
    today = datetime.now(SH).date().isoformat()
    cache = state_root/'market-observation-private/history'
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = cache/f'adjusted-{previous_date}.csv'
    meta_path = target.with_suffix('.meta.json')
    if target.exists() and meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            if (meta.get('databaseMtime') == mtime and meta.get('requestedDate') == previous_date
                    and meta.get('eventsCaptureDay') == today and meta.get('methodVersion') == VERSION
                    and meta.get('csvSha256') == hashlib.sha256(target.read_bytes()).hexdigest()):
                return target
        except (ValueError, OSError):
            pass
    bars = _export_raw(project_root, cache, previous_date)
    if not bars or max(r['date'] for r in bars) != previous_date:
        raise HistoryError('HISTORY_DATE_MISMATCH')
    events, event_meta = _fetch_events(project_root, cache)
    adjusted, method_meta = adjust_bars(bars, events, previous_date)
    if database.stat().st_mtime_ns != mtime:
        raise HistoryError('HISTORY_DATABASE_CHANGED')
    import io
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=['thscode','date','close','turnover'])
    writer.writeheader(); writer.writerows(adjusted)
    raw = stream.getvalue().encode()
    _private_write(target, raw)
    _json_write(meta_path, {**method_meta, 'databaseMtime':mtime, 'requestedDate':previous_date,
        'historyAsOf':previous_date, 'factorAsOf':previous_date, 'eventsCaptureDay':today,
        'events':event_meta, 'adjustmentVerified':True, 'csvSha256':hashlib.sha256(raw).hexdigest(),
        'rows':len(adjusted), 'codes':len({r['thscode'] for r in adjusted}),
        'sessions':len({r['date'] for r in adjusted}), 'amountUnit':'CNY',
        'note':'adjustmentVerified means complete application of captured events under the stated formula, not REST chart equivalence'})
    return target
