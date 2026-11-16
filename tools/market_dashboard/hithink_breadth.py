"""Normalized membership history and one-pass local forward-adjusted breadth.

All returns are decimal fractions. Strong means daily qfq return >= 3%; volume
expansion means volume > preceding five recorded sessions' mean. Top-one absolute
return contribution is an equal-weight structural proxy, never index attribution.
Current-member history is discounted 20%; snapshots older than seven days receive
an additional 20% discount. Coverage remains separately recoverable as valid/total.
"""
import csv
from dataclasses import asdict, dataclass
from datetime import timedelta
import json
import math
from pathlib import Path
import re
import statistics
import subprocess
import time

from .hithink_cli import Membership, canonical_date
from .hithink_store import (store_write_lock, replace_membership_snapshot,
                            upsert_breadth_daily, MEMBERSHIP_VERSION)

_SYMBOL = re.compile(r'^[0-9]{6}\.(SH|SZ|BJ)$')


@dataclass(frozen=True)
class StockDailyObservation:
    stock_id: str
    market_date: str
    close: float
    previous_close: float | None
    volume: float
    turnover: float
    previous_date: str | None
    volume_mean_5d: float | None = None
    adjustment: str = 'qfq'


@dataclass(frozen=True)
class BreadthRow:
    sector_id: str
    market_date: str
    membership_mode: str
    advancing_count: int
    declining_count: int
    unchanged_count: int
    valid_count: int
    total_count: int
    advancing_share: float | None
    declining_share: float | None
    median_return: float | None
    strong_stock_share: float | None
    return_dispersion: float | None
    top5_turnover_share: float | None
    top1_contribution_share: float | None
    volume_expansion_share: float | None
    completeness: float
    observed_at_ms: int


def membership_refresh_due(tag, last_date, today, *, priority=False, catalog_changed=False):
    today = canonical_date(today)
    if not last_date or catalog_changed:
        return True
    age = (today-canonical_date(last_date)).days
    if age < 0:
        raise ValueError('FUTURE_MEMBERSHIP')
    return age >= (1 if tag == 'industry' or priority else 7)


def select_membership_snapshot(snapshots, market_date):
    """Use latest nonfuture snapshot; earliest future is explicitly approximate."""
    canonical_date(market_date)
    if not snapshots:
        raise ValueError('MEMBERSHIP_MISSING')
    for day in snapshots:
        canonical_date(day)
    past = [day for day in snapshots if day <= market_date]
    day = max(past) if past else min(snapshots)
    return day, snapshots[day], ('point_in_time_snapshot' if past else 'current_members_backfill')


def refresh_memberships(client, store, sectors, today, *, state_root, priority_ids=(),
                        catalog_changed=False, force=False, budget=None, should_yield=None):
    """Request outside lock; atomically replace each complete normalized snapshot.

    Existing daily snapshots provide restart checkpoints. Adapter/network failures
    propagate a safe code and preserve prior snapshots. Daily callers pass the
    union of core, dynamic and candidate-50 identities as ``priority_ids``.
    """
    canonical_date(today)
    report = []
    for sector in sectors:
        if should_yield and should_yield():
            raise RuntimeError('BACKFILL_YIELDED')
        last = store.execute('SELECT max(membership_date) FROM sector_membership_snapshot WHERE sector_id=? AND membership_version=?',
                             (sector.code, MEMBERSHIP_VERSION)).fetchone()[0]
        if not force and not membership_refresh_due(sector.tag, last, today,
                priority=sector.code in priority_ids, catalog_changed=catalog_changed):
            continue
        if budget is not None:
            budget.before_call()
        rows = tuple(client.constituents(sector.code))
        if not rows or any(r.sector_code != sector.code for r in rows):
            raise ValueError('INVALID_MEMBERSHIP_SNAPSHOT')
        with store_write_lock(state_root):
            replace_membership_snapshot(store, rows, sector_id=sector.code, membership_date=today)
        report.append({'code': sector.code, 'memberCount': len(rows), 'membershipDate': today})
    return report


def _finite(value, *, positive=False):
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def derive_daily_breadth(membership, closes, *, market_date, previous_market_date,
                        membership_date, observed_at_ms=None, approximation_discount=.8):
    canonical_date(market_date); canonical_date(previous_market_date); canonical_date(membership_date)
    if previous_market_date >= market_date or not 0 < approximation_discount <= 1:
        raise ValueError('INVALID_BREADTH_REQUEST')
    membership = tuple(membership)
    sectors = {m.sector_code for m in membership}
    members = {m.stock_code for m in membership}
    if len(sectors) != 1 or len(members) != len(membership):
        raise ValueError('INVALID_MEMBERSHIP_SNAPSHOT')
    seen, valid = set(), []
    for row in closes:
        if row.adjustment != 'qfq':
            raise ValueError('QFQ_REQUIRED')
        key = row.stock_id, row.market_date
        if key in seen:
            raise ValueError('DUPLICATE_STOCK_DATE')
        seen.add(key)
        if row.stock_id not in members or row.market_date != market_date:
            continue
        if (row.previous_date != previous_market_date or not _finite(row.close, positive=True)
                or not _finite(row.previous_close, positive=True) or not _finite(row.volume, positive=True)
                or not _finite(row.turnover, positive=True)):
            continue
        valid.append((row, row.close/row.previous_close-1))
    returns = [r for _, r in valid]
    n, total = len(valid), len(members)
    up = sum(r > 1e-12 for r in returns); down = sum(r < -1e-12 for r in returns)
    amounts = sorted((r.turnover for r, _ in valid), reverse=True)
    total_amount = sum(amounts)
    absolute = sum(abs(r) for r in returns)
    volume_rows = [r for r, _ in valid if _finite(r.volume_mean_5d, positive=True)]
    mode = 'current_members_backfill' if membership_date > market_date else 'point_in_time_snapshot'
    completeness = n/total
    if mode == 'current_members_backfill':
        completeness *= approximation_discount
    elif (canonical_date(market_date)-canonical_date(membership_date)).days > 7:
        completeness *= .8
    return BreadthRow(next(iter(sectors)), market_date, mode, up, down, n-up-down, n, total,
        up/n if n else None, down/n if n else None, statistics.median(returns) if n else None,
        sum(r >= .03-1e-12 for r in returns)/n if n else None,
        statistics.pstdev(returns) if n else None,
        sum(amounts[:5])/total_amount if total_amount else None,
        max((abs(r) for r in returns), default=0)/absolute if absolute else None,
        sum(r.volume > r.volume_mean_5d for r in volume_rows)/len(volume_rows) if volume_rows else None,
        completeness, observed_at_ms if observed_at_ms is not None else int(time.time()*1000))


def derive_breadth_panel(snapshots, observations, trading_days, *, observed_at_ms=None):
    """Read the stock/date iterator once, reuse per-day observations across sectors.

    ``snapshots`` accepts {sector: {snapshot_date: memberships}}; a single
    (snapshot_date, memberships) pair is also accepted for backfill convenience.
    ``trading_days`` maps requested sessions to their immediately prior session.
    """
    by_day, seen = {}, set()
    for row in observations:
        key = row.stock_id, row.market_date
        if key in seen:
            raise ValueError('DUPLICATE_STOCK_DATE')
        if row.adjustment != 'qfq':
            raise ValueError('QFQ_REQUIRED')
        seen.add(key)
        by_day.setdefault(row.market_date, {})[row.stock_id] = row
    output = []
    for sector, versions in sorted(snapshots.items()):
        if isinstance(versions, tuple):
            versions = {versions[0]: versions[1]}
        for day, previous in sorted(trading_days.items()):
            snapshot_day, members, _ = select_membership_snapshot(versions, day)
            if any(m.sector_code != sector for m in members):
                raise ValueError('INVALID_MEMBERSHIP_SNAPSHOT')
            stocks = by_day.get(day, {})
            output.append(derive_daily_breadth(members,
                (stocks[m.stock_code] for m in members if m.stock_code in stocks),
                market_date=day, previous_market_date=previous, membership_date=snapshot_day,
                observed_at_ms=observed_at_ms))
    return output


def load_stock_panel(runner, cli_path, db_path, symbols, start_date, end_date, output_path):
    """One official CLI read-only CSV export; never connect to DuckDB directly.

    Warm-up rows supply lag and five-session volume baselines. Missing sessions
    are checked against the caller's actual market calendar, never filled as zero.
    """
    start, end = canonical_date(start_date), canonical_date(end_date)
    symbols = sorted(set(symbols))
    if (start > end or not symbols or any(not _SYMBOL.fullmatch(s) for s in symbols)
            or not Path(cli_path).is_absolute() or not Path(db_path).is_absolute()
            or not Path(db_path).is_file()):
        raise ValueError('INVALID_PANEL_REQUEST')
    from .hithink_store import _private_directory, _private_file
    import os
    output_path = Path(output_path).absolute()
    if output_path.resolve() == Path(db_path).resolve() or (output_path.exists() and output_path.samefile(db_path)):
        raise ValueError('INVALID_PANEL_REQUEST')
    _private_directory(output_path.parent)
    os.close(_private_file(output_path))
    identities = ','.join("'"+s+"'" for s in symbols)
    warmup = (start-timedelta(days=45)).isoformat()
    query = ("WITH panel AS (SELECT thscode,date,close,volume,amount AS turnover,"
        "lag(close) OVER w AS prev_close,lag(date) OVER w AS prev_date,"
        "CASE WHEN count(*) OVER b=5 THEN avg(volume) OVER b END AS volume_mean_5d "
        f"FROM v_daily_qfq WHERE thscode IN ({identities}) AND date BETWEEN '{warmup}' AND '{end}' "
        "WINDOW w AS (PARTITION BY thscode ORDER BY date),"
        "b AS (PARTITION BY thscode ORDER BY date ROWS BETWEEN 5 PRECEDING AND 1 PRECEDING)) "
        "SELECT thscode,date,close,prev_close,volume,turnover,prev_date,volume_mean_5d "
        f"FROM panel WHERE date >= '{start}' ORDER BY date,thscode")
    argv = [str(cli_path), '--db', str(db_path), 'db', 'export', '--sql', query,
            '--output', str(output_path), '--file-format', 'csv', '--format', 'json']
    try:
        result = runner(argv)
        envelope = json.loads(result.stdout)
        if result.returncode != 0 or envelope.get('ok') is not True or envelope.get('command') != 'db.export':
            raise ValueError('PANEL_EXPORT_FAILED')
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        raise ValueError('PANEL_EXPORT_FAILED') from None
    seen = set()
    with output_path.open(newline='') as source:
        reader = csv.DictReader(source)
        expected = {'thscode','date','close','prev_close','volume','turnover','prev_date','volume_mean_5d'}
        if set(reader.fieldnames or ()) != expected:
            raise ValueError('INVALID_PANEL_SCHEMA')
        for row in reader:
            day = canonical_date(row['date']).isoformat()
            key = row['thscode'], day
            if row['thscode'] not in symbols or not start_date <= day <= end_date or key in seen:
                raise ValueError('INVALID_PANEL_ROWS')
            seen.add(key)
            def number(field):
                value = float(row[field]) if row[field] else None
                if value is not None and not _finite(value):
                    raise ValueError('INVALID_PANEL_ROWS')
                return value
            previous = canonical_date(row['prev_date']).isoformat() if row['prev_date'] else None
            yield StockDailyObservation(row['thscode'], day, number('close'), number('prev_close'),
                number('volume'), number('turnover'), previous, number('volume_mean_5d'))


def persist_breadth(store, rows, *, state_root, should_yield=None):
    rows = list(rows)
    for offset in range(0, len(rows), 250):
        if should_yield and should_yield():
            raise RuntimeError('BACKFILL_YIELDED')
        with store_write_lock(state_root):
            upsert_breadth_daily(store, rows[offset:offset+250])
