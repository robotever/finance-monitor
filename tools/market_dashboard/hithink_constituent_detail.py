"""Private, read-only constituent ranking. No provider requests on page clicks."""
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sqlite3
import sys


def _panel_rows(panel):
    if panel.exists():
        with panel.open() as stream:
            yield from csv.DictReader(stream)


def constituent_history(connection, sector, cutoffs, current_day, panel, names, *, panel_rows=None, live_quotes=None):
    connection.row_factory = sqlite3.Row
    versions = {}
    for row in connection.execute(
        'SELECT stock_id,membership_date FROM sector_membership_snapshot '
        'WHERE sector_id=? AND membership_version=? ORDER BY membership_date,stock_id',
        (sector, 'sector-membership-ths-v1')):
        versions.setdefault(row['membership_date'], []).append(row['stock_id'])
    if not versions:
        return {}
    selected = {day: max((v for v in versions if v <= day), default=min(versions)) for day in cutoffs}
    wanted = {code for version in selected.values() for code in versions[version]}
    quotes = {day: {} for day in cutoffs}
    if current_day in cutoffs:
        cutoff = cutoffs[current_day]
        # Exclude later cycles, and do not silently reuse a stale quote for a missing stock.
        source = live_quotes if live_quotes is not None else connection.execute(
            'SELECT * FROM stock_market_snapshot WHERE market_date=? AND observed_at BETWEEN ? AND ? '
            'ORDER BY observed_at', (current_day, cutoff-20*60*1000, cutoff))
        for row in source:
            if row['stock_id'] in wanted and cutoff-20*60*1000 <= row['observed_at'] <= cutoff:
                quotes[current_day][row['stock_id']] = dict(row)
    if panel_rows is not None or panel.exists():
            for row in panel_rows if panel_rows is not None else _panel_rows(panel):
                day, code = row['date'], row['thscode']
                if day not in quotes or day == current_day or code not in wanted:
                    continue
                try:
                    close, previous = float(row['close']), float(row['prev_close'])
                    quotes[day][code] = dict(last_price=close, prev_price=previous,
                        price_change_ratio_pct=(close/previous-1)*100,
                        turnover=float(row['turnover']), volume=float(row['volume']), observed_at=None)
                except (ValueError, ZeroDivisionError, KeyError):
                    continue
    result = {}
    for day, version in selected.items():
        rows = []
        for code in versions[version]:
            quote = quotes[day].get(code, {})
            valid = all(isinstance(quote.get(k), (float, int)) and math.isfinite(quote[k])
                        for k in ('last_price','prev_price','price_change_ratio_pct','turnover','volume'))
            valid = valid and all(quote[k] > 0 for k in ('last_price','prev_price','volume','turnover'))
            rows.append(dict(code=code, name=names.get(code), rank=None,
                return1d=quote['price_change_ratio_pct'] if valid else None,
                lastPrice=quote['last_price'] if valid else None,
                turnover=quote['turnover'] if valid else None,
                observedAt=quote.get('observed_at') if valid else None))
        rows.sort(key=lambda r: (r['return1d'] is None, -(r['return1d'] or 0), r['code']))
        valid_count = sum(r['return1d'] is not None for r in rows)
        for i, row in enumerate(rows[:valid_count], 1):
            row['rank'] = i
        result[day] = dict(rows=rows,total=len(rows),validCount=valid_count,
            membershipDate=version,approximateMembership=version>day,
            priceBasis='raw' if day == current_day else 'forward_adjusted',
            observedAt=max((r['observedAt'] for r in rows if r['observedAt'] is not None),default=None))
    return result


def enrich_export(root, directory):
    """One bounded offline pass for a user-authorized deployment snapshot."""
    paths=sorted(directory.glob('detail-*.json'))
    details=[(path,json.loads(path.read_text())) for path in paths]
    dates={point['marketDate'] for _,detail in details for point in detail['history']}
    panel=root/'hithink-breadth/live-panel.csv'
    panel_rows=[r for r in _panel_rows(panel) if r['date'] in dates]
    symbols=root/'hithink-live/stock-symbols.json'
    names={r['thscode']:r['name'] for r in json.loads(symbols.read_text())['data']['item']} if symbols.exists() else {}
    with sqlite3.connect((root/'sector-history.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as connection:
        connection.row_factory=sqlite3.Row
        # Snapshot file already pins dates and cutoff times; future database writes are excluded below.
        day=details[0][1]['marketDate']
        live_cutoffs=[int(datetime.fromisoformat(p['observedAt'].replace('Z','+00:00')).timestamp()*1000)
            for _,detail in details for p in detail['history'] if p['marketDate']==day and p.get('observedAt')]
        low,high=min(live_cutoffs)-20*60*1000,max(live_cutoffs)
        live_quotes=list(connection.execute('SELECT * FROM stock_market_snapshot WHERE market_date=? AND observed_at BETWEEN ? AND ? ORDER BY observed_at',(day,low,high)))
        for path,detail in details:
            cutoffs={p['marketDate']:int(datetime.fromisoformat(p['observedAt'].replace('Z','+00:00')).timestamp()*1000)
                     for p in detail['history'] if p.get('observedAt')}
            latest=next((p for p in detail['history'] if p['marketDate']==day),{})
            live_day=None if latest.get('historicalReconstruction') else day
            detail['constituentsByDate']=constituent_history(connection,detail['id'],cutoffs,live_day,panel,names,
                panel_rows=panel_rows,live_quotes=live_quotes)
            path.write_text(json.dumps(detail,ensure_ascii=False,allow_nan=False,separators=(',',':')))
    print(json.dumps({'details':len(details),'historyDates':len(dates),'names':len(names)}))


def main():
    if len(sys.argv)==4 and sys.argv[1]=='--enrich-export':
        enrich_export(Path(sys.argv[2]),Path(sys.argv[3]))
        return
    root, sector = Path(sys.argv[1]), sys.argv[2]
    if not re.fullmatch(r'\d{6}\.(TI|SH|SZ|BJ)',sector):
        raise ValueError('INVALID_SECTOR')
    request = json.load(sys.stdin)
    cutoffs = {row['marketDate']: int(datetime.fromisoformat(row['observedAt'].replace('Z','+00:00')).timestamp()*1000)
               for row in request['history'] if row.get('observedAt')}
    symbols = root/'hithink-live/stock-symbols.json'
    names = {r['thscode']:r['name'] for r in json.loads(symbols.read_text())['data']['item']} if symbols.exists() else {}
    with sqlite3.connect((root/'sector-history.sqlite3').resolve().as_uri()+'?mode=ro',uri=True) as connection:
        latest=next((p for p in request['history'] if p['marketDate']==request['marketDate']),{})
        live_day=None if latest.get('historicalReconstruction') else request['marketDate']
        print(json.dumps(constituent_history(connection,sector,cutoffs,live_day,
            root/'hithink-breadth/live-panel.csv',names),allow_nan=False))


if __name__ == '__main__':
    main()
