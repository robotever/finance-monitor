"""Private Hithink v4 producer. No network publication or production switch.

Snapshots are shared within a cycle; CLI output never leaves the private boundary.
A success marker is installed last, after a complete local payload is durable.
"""
import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import fcntl
import json
import math
import os
import re
from pathlib import Path
import statistics
import subprocess
import time

from .hithink_cli import HithinkClient, HithinkError, Membership, SHANGHAI, canonical_date
from .hithink_store import (_private_directory, _private_file, store_write_lock,
    open_store, migrate_store, replace_catalog, read_index_daily, read_breadth_daily,
    upsert_index_daily, upsert_breadth_daily, upsert_sector_features)
from .hithink_universe import build_universe, load_catalog_fixture
from .hithink_breadth import refresh_memberships, select_membership_snapshot, BreadthRow
from .rotation_operations import calendar_dates
from .rotation_v4 import build_v4_features, score_v4_sectors, rank_v4_universe, _SNAKE

BASE = Path(__file__).resolve().parents[2]
CLI = '/Users/robot_ever/Codex/Financial Knowledge Repository/tools/npm-global/node_modules/.bin/hithink-finance'

@dataclass(frozen=True)
class CycleBucket:
    key: str
    market_date: str
    official_close: bool
    deadline: datetime

@dataclass(frozen=True)
class HithinkJobResult:
    status: str
    bucket: str | None = None
    safe_error_code: str | None = None
    row_count: int = 0
    published: bool = False


def cycle_bucket(now, trading_dates):
    days=calendar_dates(list(trading_dates))
    if not days or now.tzinfo is None: raise ValueError('CALENDAR_UNVERIFIED')
    now=now.astimezone(SHANGHAI); day=now.date().isoformat(); minute=now.hour*60+now.minute
    if day not in days: return None
    if 900 <= minute < 930:
        return CycleBucket(day+':close',day,True,now.replace(hour=15,minute=30,second=0,microsecond=0))
    if not (570 <= minute <= 690 or 780 <= minute < 900): return None
    floor=now.replace(minute=now.minute//15*15,second=0,microsecond=0)
    return CycleBucket(day+':'+floor.strftime('%H:%M'),day,False,floor+timedelta(minutes=15))


class CycleBudget:
    def __init__(self,max_calls=1200,seconds=840,*,clock=time.monotonic):
        if max_calls<1 or not 0<seconds<=900: raise ValueError('INVALID_CYCLE_BUDGET')
        self.max_calls=max_calls; self.seconds=seconds; self.clock=clock; self.start=clock(); self.calls=0
    def check(self):
        if self.clock()-self.start >= self.seconds: raise TimeoutError('CYCLE_EXPIRED')
    def before_call(self):
        self.check()
        if self.calls>=self.max_calls: raise TimeoutError('CYCLE_BUDGET_STOP')
        self.calls+=1
    def runner(self,argv):
        self.before_call()
        remaining=self.seconds-(self.clock()-self.start)
        result=subprocess.run(argv,capture_output=True,text=True,check=False,timeout=min(60,remaining),umask=0o077)
        self.check(); return result


def _atomic(path,value):
    _private_directory(path.parent)
    temporary=path.with_name(path.name+'.tmp')
    fd=_private_file(temporary)
    os.ftruncate(fd,0)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(value,stream,ensure_ascii=False,allow_nan=False,separators=(',',':'))
            stream.flush(); os.fsync(stream.fileno())
        if path.is_symlink(): raise ValueError('INVALID_STATE')
        os.replace(temporary,path)
        directory_fd=os.open(path.parent,os.O_RDONLY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally: temporary.unlink(missing_ok=True)


def _read(path,default):
    if path.is_symlink(): raise ValueError('INVALID_STATE')
    return json.loads(path.read_text()) if path.exists() else default


@contextmanager
def _live_guard(root):
    fd=_private_file(root/'hithink-live.lock')
    priority=root/'hithink-live-priority'
    try:
        try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise RuntimeError('LIVE_BUSY') from None
        marker=_private_file(priority); os.close(marker)
        try: yield
        finally: priority.unlink(missing_ok=True)
    finally: os.close(fd)


def collect_stock_snapshot(client,codes,page_size=80):
    """One logical shared snapshot; exact explicit-code chunks, never default100.

    A 100-row provider cap cannot silently truncate a requested page: both count
    and identities must match. Chunk assembly timestamps must be within120s.
    """
    if not 1<=page_size<=1000: raise ValueError('INVALID_SNAPSHOT_PAGE_SIZE')
    codes=sorted({c for c in codes if re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)',c)}); result={}; times=[]
    for offset in range(0,len(codes),page_size):
        batch=codes[offset:offset+page_size]; rows=tuple(client.stock_snapshots(batch))
        if len(rows)!=len(batch) or {r.code for r in rows}!=set(batch):
            raise HithinkError('SNAPSHOT_INCOMPLETE')
        for row in rows: result[row.code]=row; times.append(row.timestamp_ms)
    if times and max(times)-min(times)>120000: raise HithinkError('SNAPSHOT_INCOHERENT')
    return result


def validate_snapshot_freshness(timestamps,bucket,collection_now):
    """Reject coherent but stale snapshots before any normalized stock write.

    Sources must belong to this bucket, be at most120seconds old at collection,
    and never reach the next bucket/15:30close cutoff.120seconds future clock skew
    is tolerated only within the same bucket. Close sources must be>=15:00.
    """
    now=collection_now.astimezone(SHANGHAI)
    if not timestamps or now>=bucket.deadline: raise ValueError('SNAPSHOT_STALE')
    if bucket.official_close:
        start=now.replace(hour=15,minute=0,second=0,microsecond=0)
    else:
        start=datetime.fromisoformat(bucket.key[:10]+'T'+bucket.key[11:]).replace(tzinfo=SHANGHAI)
    lower=max(start,now-timedelta(seconds=120)); upper=min(bucket.deadline,now+timedelta(seconds=120))
    for timestamp in timestamps:
        source=datetime.fromtimestamp(timestamp/1000,SHANGHAI)
        if source.date().isoformat()!=bucket.market_date or not lower<=source<=upper or source>=bucket.deadline:
            raise ValueError('SNAPSHOT_STALE')


def _official_calendar(client):
    # Adapter envelope validation rejects truncation/count ambiguity. Calendar
    # capability failures are fatal; weekdays/local price dates are no fallback.
    data=client._call('market','calendar',[],('item','timestamp'))
    rows=data['item']; days=[]
    for row in rows:
        if isinstance(row,str): day=row
        elif isinstance(row,dict) and set(row)=={'date','date_ms'}:
            day=row['date']
            if isinstance(day,str) and len(day)==8 and day.isdigit(): day=day[:4]+'-'+day[4:6]+'-'+day[6:]
            if type(row['date_ms']) is not int or datetime.fromtimestamp(row['date_ms']/1000,SHANGHAI).date().isoformat()!=day:
                raise ValueError('CALENDAR_UNVERIFIED')
        else: raise ValueError('CALENDAR_UNVERIFIED')
        canonical_date(day); days.append(day)
    if len(days)!=len(set(days)): raise ValueError('CALENDAR_UNVERIFIED')
    return calendar_dates(sorted(days))


def _live_breadth(members,snapshot,day,membership_day,observed):
    """Use provider daily price ratios; raw live prices are never called qfq.

    Volume expansion has no verified baseline in this snapshot and stays missing.
    """
    valid=[snapshot[m.stock_code] for m in members if m.stock_code in snapshot
        and snapshot[m.stock_code].last_price>0 and snapshot[m.stock_code].prev_price>0
        and snapshot[m.stock_code].volume>0 and snapshot[m.stock_code].turnover>0]
    returns=[r.last_price/r.prev_price-1 for r in valid]; n=len(valid); total=len(members)
    amounts=sorted([r.turnover for r in valid],reverse=True); amount=sum(amounts); absolute=sum(abs(r) for r in returns)
    mode='current_members_backfill' if membership_day>day else 'point_in_time_snapshot'
    discount=.8 if mode=='current_members_backfill' or (canonical_date(day)-canonical_date(membership_day)).days>7 else 1
    up=sum(r>1e-12 for r in returns); down=sum(r< -1e-12 for r in returns)
    return asdict(BreadthRow(members[0].sector_code,day,mode,up,down,n-up-down,n,total,
        up/n if n else None,down/n if n else None,statistics.median(returns) if n else None,
        sum(r>=.03-1e-12 for r in returns)/n if n else None,statistics.pstdev(returns) if n else None,
        sum(amounts[:5])/amount if amount else None,max(map(abs,returns))/absolute if absolute else None,
        None,n/total*discount,observed))


def prior_close_rows(payloads,market_date):
    """Recover daily-session metadata only from trusted close/reconstruction files.

    Session identifies the sampled daily bar; official/timely status stays
    separate. Arrival evidence and all score fields are copied unchanged.
    """
    result=[]
    for payload in payloads:
        if not (payload.get('officialClose') or payload.get('historicalReconstruction')): continue
        for row in payload.get('rows',[]):
            if row.get('marketDate','')>=market_date: continue
            result.append({**row,'session':'close','officialClose':payload.get('officialClose') is True,
                'historicalReconstruction':payload.get('historicalReconstruction') is True})
    return result


def score_cycle_features(features,prior_closes,bucket,config,*,historical=False):
    """Tag the cycle before scoring so daily history remains usable next cycle."""
    session='close' if historical or bucket.official_close else 'intraday'
    tagged=[{**row,'session':session,'officialClose':bucket.official_close and not historical}
        for row in features]
    scored=score_v4_sectors(tagged,prior_closes,config)
    return [{**row,'historicalReconstruction':historical} for row in scored]


def produce_payload(args,bucket,budget,client,root):
    store=open_store(Path(getattr(args,'store',None) or root/'sector-history.sqlite3'))
    try:
        with store_write_lock(root): migrate_store(store)
        fixtures=Path(__file__).parent/'fixtures/hithink'
        industries=load_catalog_fixture(fixtures/'catalog-industry.json')
        concepts=load_catalog_fixture(fixtures/'catalog-concept.json')
        core=json.loads((BASE/'config/hithink-core-concepts.json').read_text())
        local=root/'hithink-live'; cadence=_read(local/'catalog-state.json',{})
        if cadence.get('date')!=datetime.now(SHANGHAI).date().isoformat():
            industries=client.catalog('industry'); concepts=client.catalog('cn_concept')
        universe=build_universe(industries,concepts,core)
        sectors=(*universe.industries,*universe.concepts)
        observed=int(time.time()*1000)
        with store_write_lock(root): replace_catalog(store,sectors,observed_at_ms=observed)
        _atomic(local/'catalog-state.json',{'date':datetime.now(SHANGHAI).date().isoformat(),'digest':universe.catalog_digest})
        previous_payload=_read(local/'latest.json',{})
        previous=previous_payload.get('rows',[])
        close_history=_read(local/'close-history.json',[])
        if not close_history and (previous_payload.get('officialClose') or previous_payload.get('historicalReconstruction')):
            close_history=[previous_payload]
        prior_closes=prior_close_rows(close_history,bucket.market_date)

        dynamic={r['id'] for r in previous if r.get('universe')=='concept' and (r.get('metrics',{}).get('strengthRank') or 99999)<=40}
        candidates={r['id'] for r in sorted([r for r in previous if r.get('universe')=='concept'],key=lambda r:-(r.get('opportunity') or 0))[:50]}
        refresh_memberships(client,store,sectors,datetime.now(SHANGHAI).date().isoformat(),state_root=root,
            priority_ids=set(universe.core_ids)|dynamic|candidates,catalog_changed=cadence.get('digest') not in (None,universe.catalog_digest))
        budget.check()
        day=bucket.market_date; latest_close=getattr(args,'latest_close',False)
        memberships={}
        for sector in sectors:
            versions={}
            for row in store.execute('SELECT * FROM sector_membership_snapshot WHERE sector_id=? ORDER BY membership_date',(sector.code,)):
                versions.setdefault(row['membership_date'],[]).append(Membership(sector.code,row['stock_id'],row['observed_at_ms']))
            memberships[sector.code]=select_membership_snapshot(versions,day)
        indexes={s.code:read_index_daily(store,s.code,'2000-01-01',day) for s in sectors}
        if latest_close:
            from .hithink_backfill import _stock_database
            from .hithink_breadth import load_stock_panel, derive_daily_breadth, persist_breadth
            start=(canonical_date(day)-timedelta(days=100)).isoformat()
            days=[d for d in args._calendar if d<=day]
            previous_days={d:days[i-1] for i,d in enumerate(days) if i and d>=start}
            symbols={m.stock_code for _,members,_ in memberships.values() for m in members
                if re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)',m.stock_code)}
            panel=load_stock_panel(budget.runner,client.cli_path,
                _stock_database(client.cli_path,getattr(args,'stock_db',None)),symbols,start,day,
                root/'hithink-breadth'/'live-panel.csv')
            by_day={}
            for i,row in enumerate(panel):
                if i%1000==0: budget.check()
                by_day.setdefault(row.market_date,[]).append(row)
            derived=[]
            for member_day,members,_ in memberships.values():
                budget.check()
                for date,previous_day in previous_days.items():
                    derived.append(derive_daily_breadth(members,by_day.get(date,()),market_date=date,
                        previous_market_date=previous_day,membership_date=member_day,observed_at_ms=observed))
            persist_breadth(store,derived,state_root=root)
            for code,rows in indexes.items():
                if not rows or rows[-1]['market_date']!=day: raise ValueError('INDEX_HISTORY_INCOMPLETE')
        else:
            ids=[s.code for s in sectors]; snapshots=[]
            for offset in range(0,len(ids),80): snapshots.extend(client.index_snapshots(ids[offset:offset+80]))
            if len(snapshots)!=len(ids) or {r.code for r in snapshots}!=set(ids): raise HithinkError('SNAPSHOT_INCOMPLETE')
            shared=collect_stock_snapshot(client,[m.stock_code for _,members,_ in memberships.values() for m in members])
            all_times=[r.timestamp_ms for r in snapshots]+[r.timestamp_ms for r in shared.values()]
            collection_now=getattr(args,'now',None) or datetime.now(SHANGHAI)
            validate_snapshot_freshness(all_times,bucket,collection_now)
            stock_records=list(shared.values())
            for offset in range(0,len(stock_records),250):
                budget.check()
                with store_write_lock(root):
                    store.execute('BEGIN IMMEDIATE')
                    try:
                        for r in stock_records[offset:offset+250]:
                            store.execute('INSERT OR REPLACE INTO stock_market_snapshot '
                                '(stock_id,observed_at,market_date,last_price,price_change,price_change_ratio_pct,open_price,high_price,low_price,prev_price,volume,turnover) '
                                'VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                                (r.code,r.timestamp_ms,day,r.last_price,r.price_change,r.price_change_ratio_pct,
                                 r.open_price,r.high_price,r.low_price,r.prev_price,r.volume,r.turnover))
                        store.commit()
                    except BaseException: store.rollback(); raise
            all_times=[r.timestamp_ms for r in snapshots]+[r.timestamp_ms for r in shared.values()]
            if not all_times or max(all_times)-min(all_times)>120000: raise HithinkError('SNAPSHOT_INCOHERENT')
            if any(datetime.fromtimestamp(t/1000,SHANGHAI).date().isoformat()!=day or t>observed+120000 for t in all_times): raise HithinkError('SNAPSHOT_DATE_MISMATCH')
            current=[]
            if bucket.official_close:
                # Response assembly time alone cannot establish an official close.
                start=int(datetime.combine(canonical_date(day),datetime.min.time(),SHANGHAI).timestamp()*1000)
                for sector in sectors:
                    bars=client.index_history(sector.code,start,start+86400000-1)
                    if len(bars)!=1 or bars[0].date!=day: raise HithinkError('OFFICIAL_CLOSE_UNVERIFIED')
                    bar=bars[0]; current.append(dict(sector_id=bar.code,market_date=bar.date,open=bar.open,high=bar.high,low=bar.low,close=bar.close,volume=bar.volume,turnover=bar.turnover,observed_at_ms=observed))
            else:
                current=[dict(sector_id=r.code,market_date=day,close=r.last_price,turnover=r.turnover,volume=r.volume,observed_at_ms=observed) for r in snapshots]
            for row in current: indexes[row['sector_id']]=[r for r in indexes[row['sector_id']] if r['market_date']<day]+[row]
            live_breadth=[_live_breadth(members,shared,day,date,observed) for date,members,_ in memberships.values()]
            if bucket.official_close:
                with store_write_lock(root):
                    upsert_index_daily(store,current,observed_at_ms=observed)
                    upsert_breadth_daily(store,live_breadth)
        # Explicit official benchmark series, never implicit zero-relative return.
        start=(canonical_date(day)-timedelta(days=400)).isoformat()
        def ms(d): return int(datetime.combine(canonical_date(d),datetime.min.time(),SHANGHAI).timestamp()*1000)
        bench=client.index_history('000300.SH',ms(start),ms(day)+86400000-1)
        benchmark=[dict(sector_id=b.code,market_date=b.date,close=b.close,observed_at_ms=observed) for b in bench]
        features=[]
        for sector in sectors:
            budget.check()
            breadth=read_breadth_daily(store,sector.code,'2000-01-01',day)
            if not latest_close: breadth=[b for b in breadth if b['market_date']<day]+[b for b in live_breadth if b['sector_id']==sector.code]
            features.append(build_v4_features(indexes[sector.code],breadth,sector_id=sector.code,market_date=day,
                benchmark_rows=benchmark,prior_scores=prior_closes,universe='industry' if sector.tag=='industry' else 'concept'))
        config=json.loads((BASE/'config/hithink-sector-dashboard.json').read_text())
        scored=score_cycle_features(features,prior_closes,bucket,config,historical=latest_close)
        ranked=[]
        for universe_name in ('industry','concept'):
            rows=[r for r in scored if r['universe']==universe_name]
            for axis in ('strength','opportunity','risk'): rows=rank_v4_universe(rows,axis)
            ranked.extend(rows)
        budget.check()
        feature_records=[]
        for row in features:
            record=dict(sector_id=row['id'],market_date=day,membership_mode=row['membershipMode'],
                observed_at_ms=observed,completeness=row['breadthCompleteness'])
            record.update({target:row['metrics'].get(source) for source,target in _SNAKE.items()})
            if not bucket.official_close and not latest_close: record['observed_at']=observed
            feature_records.append(record)
        for offset in range(0,len(feature_records),250):
            budget.check()
            with store_write_lock(root):
                upsert_sector_features(store,feature_records[offset:offset+250],intraday=not bucket.official_close and not latest_close)
        ranked=annotate_concept_roles(ranked,universe.core_ids)
        for row in ranked: row['name']=next(s.name for s in sectors if s.code==row['id'])
        return dict(schemaVersion='market-dashboard-v4',source='Hithink',mode='shadow',marketDate=day,
            bucket=bucket.key,officialClose=bucket.official_close and not latest_close,
            historicalReconstruction=latest_close,publicReleaseEligible=False,rows=ranked,
            breadthSource='local-qfq-panel' if latest_close else 'provider-daily-price-ratio',
            marketTurnoverStatus='missing_full_market_aggregate',benchmark='000300.SH',
            latestOfficialCompletedDate=getattr(args,'_latest_official_date',day),
            historyLagSessions=sum(day<d<=getattr(args,'_latest_official_date',day) for d in args._calendar),
            unsupportedStockCount=len({m.stock_code for _,members,_ in memberships.values() for m in members if not re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)',m.stock_code)}))
    finally: store.close()


def run_hithink_cycle(args,deps=None):
    deps=deps or {}; root=Path(args.state_root); bucket=None
    _private_directory(root); local=_private_directory(root/'hithink-live')
    now=getattr(args,'now',None) or datetime.now(SHANGHAI)
    seconds=min(840,getattr(args,'max_seconds',840))
    budget=CycleBudget(getattr(args,'max_calls',1200),seconds,clock=deps.get('clock',time.monotonic))
    client=deps.get('client') or HithinkClient(getattr(args,'cli',CLI),runner=budget.runner)
    try:
        with _live_guard(root):
            days=deps.get('calendar')
            if days is None: days=json.loads(args.calendar.read_text()) if getattr(args,'calendar',None) else _official_calendar(client)
            if getattr(args,'latest_close',False):
                eligible=[d for d in calendar_dates(days) if d<now.astimezone(SHANGHAI).date().isoformat()]
                if not eligible: raise ValueError('CALENDAR_UNVERIFIED')
                args._latest_official_date=eligible[-1]
                with store_write_lock(root):
                    store=open_store(Path(getattr(args,'store',None) or root/'sector-history.sqlite3'))
                    try:
                        migrate_store(store)
                        last=store.execute('SELECT min(last_date) FROM (SELECT max(market_date) last_date FROM sector_index_daily GROUP BY sector_id)').fetchone()[0]
                    finally: store.close()
                available=[d for d in eligible if last and d<=last]
                if not available: raise ValueError('INDEX_HISTORY_INCOMPLETE')
                day=available[-1]; bucket=CycleBucket(day+':reconstructed-close',day,False,now+timedelta(seconds=seconds))
            else: bucket=cycle_bucket(now,days)
            if bucket is None: return HithinkJobResult('outside_session')
            args._calendar=days
            budget.seconds=min(budget.seconds,(bucket.deadline-now.astimezone(SHANGHAI)).total_seconds())
            state=_read(local/'state.json',{'completed':[]})
            if bucket.key in state['completed']: return HithinkJobResult('already_complete',bucket.key)
            # Fail fast before remote work if a writer already owns the store.
            with store_write_lock(root): pass
            payload=(deps.get('produce') or produce_payload)(args,bucket,budget,client,root)
            budget.check()
            rows=payload['rows']
            # Pure local projection must succeed before any successful artifacts
            # advance. This constructs requests only; no transport is invoked.
            chunks=build_publish_chunks(rows)
            budget.check()
            with store_write_lock(root):
                budget.check(); _atomic(local/(bucket.key.replace(':','-')+'.json'),payload)
                _atomic(local/(bucket.key.replace(':','-')+'.chunks.json'),chunks)
                _atomic(local/'publish-chunks.json',chunks)
                _atomic(local/'latest.json',payload)
                if payload.get('officialClose') or payload.get('historicalReconstruction'):
                    history=[p for p in _read(local/'close-history.json',[]) if p['marketDate']!=payload['marketDate']]
                    history=sorted(history+[payload],key=lambda p:p['marketDate'])[-15:]
                    _atomic(local/'close-history.json',history)
                _atomic(local/'health.json',dict(mode='shadow',status='success',bucket=bucket.key,rowCount=len(rows),published=False,safeErrorCode=None))
                budget.check()
                _atomic(local/'state.json',{'completed':(state['completed']+[bucket.key])[-2000:]})
            return HithinkJobResult('success',bucket.key,row_count=len(rows))
    except Exception as error:
        code='CYCLE_EXPIRED' if isinstance(error,(TimeoutError,subprocess.TimeoutExpired)) else 'COLLECTION_FAILED'
        if str(error) in ('STORE_BUSY','LIVE_BUSY','CALENDAR_UNVERIFIED'): code=str(error)
        _atomic(local/'health.json',dict(mode='shadow',status='failed',published=False,safeErrorCode=code))
        return HithinkJobResult('failed',bucket.key if bucket else None,code)


_VERSIONS={'schemaVersion':'market-dashboard-v4','sectorScoringVersion':'sector-score-v0.3',
    'sectorUniverseVersion':'sector-universe-ths-v1','featureVersion':'sector-features-ths-v1',
    'membershipVersion':'sector-membership-ths-v1'}
_PUBLIC_FIELDS=('id','name','universe','strength','opportunity','risk','completeness','ranks',
    'heatState','coldStart','validCloses','improvementEvidence','membershipMode','missing')


def public_v4_row(row):
    """Explicit, copied public projection. Private precision/audits remain local."""
    if any(row.get(k)!=v for k,v in _VERSIONS.items()): raise ValueError('CROSS_VERSION_ROW')
    if any(k not in row for k in _PUBLIC_FIELDS): raise ValueError('INVALID_PUBLIC_ROW')
    if set(row['ranks'])!={'strength','opportunity','risk'}: raise ValueError('INVALID_PUBLIC_ROW')
    result={k:row[k] for k in _PUBLIC_FIELDS}
    result['conceptRole']=row.get('conceptRole') if row['universe']=='concept' else None
    if '_rawScores' in row and 'rankKeys' not in row:
        result['rankKeys']={axis:row['_rawScores'].get(axis) for axis in ('strength','opportunity','risk')}
    for key in ('metrics','axisCompleteness','rankKeys'):
        if key in row:
            values=row[key]
            if not isinstance(values,dict) or any(not isinstance(k,str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9]*',k)
                    or not (v is None or isinstance(v,bool) or type(v) in (int,float) and math.isfinite(v)) for k,v in values.items()):
                raise ValueError('INVALID_PUBLIC_ROW')
            result[key]=values
    # Roundtrip rejects NaN and copies all retained nested objects.
    return json.loads(json.dumps(result,ensure_ascii=False,allow_nan=False))


def build_publish_chunks(rows,max_rows=50,max_bytes=131072,*,batch_id=None):
    """Build reviewable local protocol requests; never send or activate them.

    Digests cover the exact compact UTF8 rowsJson string. The size check includes
    the escaped outer request envelope, index and batch identity.
    """
    import hashlib
    if type(max_rows) is not int or not 1<=max_rows<=50 or type(max_bytes) is not int or not 1<=max_bytes<=131072:
        raise ValueError('INVALID_CHUNK_LIMIT')
    projected=[public_v4_row(r) for r in rows]
    if not projected or len({(r['universe'],r['id']) for r in projected})!=len(projected): raise ValueError('INVALID_PUBLIC_ROWS')
    def encode(value): return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':'))
    if batch_id is None: batch_id='ths-'+hashlib.sha256(encode(projected).encode()).hexdigest()[:40]
    if not isinstance(batch_id,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',batch_id): raise ValueError('INVALID_BATCH_ID')
    def request(items,index):
        payload=encode(items)
        return dict(batchId=batch_id,index=index,rowsJson=payload,digest=hashlib.sha256(payload.encode()).hexdigest())
    chunks=[]; pending=[]
    for row in projected:
        candidate=request(pending+[row],len(chunks))
        if len(pending)<max_rows and len(encode(candidate).encode())<=max_bytes:
            pending.append(row);continue
        if not pending: raise ValueError('ROW_EXCEEDS_CHUNK_LIMIT')
        chunks.append(request(pending,len(chunks)));pending=[row]
        if len(encode(request(pending,len(chunks))).encode())>max_bytes: raise ValueError('ROW_EXCEEDS_CHUNK_LIMIT')
    if pending: chunks.append(request(pending,len(chunks)))
    return chunks


def annotate_concept_roles(rows,core_ids):
    """Copy reviewed role metadata without changing scores or provenance."""
    core=set(core_ids)
    dynamic={r['id'] for r in rows if r['universe']=='concept' and r['id'] not in core
        and (r.get('metrics',{}).get('strengthRank') or 99999)<=40}
    candidates={r['id'] for r in sorted([r for r in rows if r['universe']=='concept' and r['id'] not in core|dynamic],
        key=lambda r:(-(r.get('opportunity') or 0),r['id']))[:50]}
    return [{**r,'conceptRole':('core' if r['id'] in core else 'dynamic' if r['id'] in dynamic else 'candidate' if r['id'] in candidates else None)
        if r['universe']=='concept' else None} for r in rows]


def refresh_local_projection(state_root):
    """Refresh existing local role metadata/chunks offline; no bucket rerun.

    No provider access, score recomputation, source/availability timestamps or
    timely-close flags change. The reviewed pinned catalog/mapping is mandatory.
    """
    root=_private_directory(Path(state_root)); local=_private_directory(root/'hithink-live')
    with _live_guard(root),store_write_lock(root):
        payload=_read(local/'latest.json',None)
        if not isinstance(payload,dict) or not isinstance(payload.get('rows'),list): raise ValueError('INVALID_LOCAL_PAYLOAD')
        bucket=payload.get('bucket','')
        if not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}:(?:reconstructed-close|close|[0-9]{2}:[0-9]{2})',bucket):
            raise ValueError('INVALID_LOCAL_PAYLOAD')
        fixtures=Path(__file__).parent/'fixtures/hithink'
        universe=build_universe(load_catalog_fixture(fixtures/'catalog-industry.json'),
            load_catalog_fixture(fixtures/'catalog-concept.json'),json.loads((BASE/'config/hithink-core-concepts.json').read_text()))
        expected={(s.code,'industry' if s.tag=='industry' else 'concept') for s in (*universe.industries,*universe.concepts)}
        if {(r['id'],r['universe']) for r in payload['rows']}!=expected or len(payload['rows'])!=len(expected):
            raise ValueError('INVALID_LOCAL_UNIVERSE')
        session_rows=payload['rows']
        if payload.get('officialClose') or payload.get('historicalReconstruction'):
            session_rows=prior_close_rows([payload],'9999-12-31')
        else:
            session_rows=[{**r,'session':'intraday'} for r in session_rows]
        updated={**payload,'rows':annotate_concept_roles(session_rows,universe.core_ids)}
        chunks=build_publish_chunks(updated['rows'])
        _atomic(local/(bucket.replace(':','-')+'.json'),updated)
        _atomic(local/'latest.json',updated)
        history=_read(local/'close-history.json',[])
        if history:
            _atomic(local/'close-history.json',[updated if p.get('bucket')==bucket else p for p in history])
        _atomic(local/'publish-chunks.json',chunks)
        return dict(status='reprojected',marketDate=payload['marketDate'],rows=len(updated['rows']),
            coreCount=sum(r['conceptRole']=='core' for r in updated['rows']),chunks=len(chunks),
            providerCalls=0,published=False,officialClose=payload.get('officialClose',False),
            historicalReconstruction=payload.get('historicalReconstruction',False))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,default=Path('data/market-dashboard'))
    parser.add_argument('--store',type=Path)
    parser.add_argument('--cli',default=CLI)
    parser.add_argument('--stock-db',type=Path)
    parser.add_argument('--calendar',type=Path,help='explicit verified JSON trading-date array; no weekday fallback')
    parser.add_argument('--refresh-local-projection',action='store_true',help='offline reviewed role metadata/chunk refresh; preserve score/timing evidence')
    parser.add_argument('--latest-close',action='store_true',help='private historical reconstruction, never a timely close success')
    parser.add_argument('--max-calls',type=int,default=1200)
    parser.add_argument('--max-seconds',type=float,default=840)
    args=parser.parse_args(argv)
    if args.refresh_local_projection:
        print(json.dumps(refresh_local_projection(args.state_root),separators=(',',':')))
        return 0
    result=run_hithink_cycle(args)
    print(json.dumps(asdict(result),separators=(',',':')))
    return int(result.status=='failed')

if __name__=='__main__': raise SystemExit(main())
