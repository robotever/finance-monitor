"""Read-only full-A observation. Private provider captures never enter public payloads."""
import csv
from datetime import datetime, timezone, timedelta
import json
import math
import os
from pathlib import Path
import re
import ssl
import statistics
import subprocess
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

SH = ZoneInfo('Asia/Shanghai')
BASE = 'https://fuyao.aicubes.cn/api/a-share/'
SYMBOL = re.compile(r'^\d{6}\.(SH|SZ|BJ)$')

class ObservationError(ValueError):
    pass

def number(v):
    if type(v) not in (int,float) or not math.isfinite(v): return None
    return float(v)

def stamp(v):
    if type(v) not in (int,float) or v <= 0: raise ObservationError('SOURCE_TIMESTAMP_MISSING')
    return datetime.fromtimestamp(v/1000,SH).isoformat()

def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp=path.with_suffix(path.suffix+'.tmp')
    fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f: json.dump(value,f,ensure_ascii=False,allow_nan=False)
    os.replace(tmp,path)

class Rest:
    def __init__(self, project_root, cache):
        helper=Path(project_root)/'tools/hithink_mcp_headers.py'
        try:
            result=subprocess.run(['python3',str(helper)],capture_output=True,text=True,timeout=15,check=True)
            self.headers=json.loads(result.stdout)
            if not self.headers.get('X-api-key'): raise ValueError()
        except Exception: raise ObservationError('HITHINK_CREDENTIAL_UNAVAILABLE') from None
        self.cache=cache
        self.sources=[]
        self.context=ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').exists() else None)
    def get(self, endpoint, **params):
        url=BASE+endpoint+('?' + urllib.parse.urlencode(params) if params else '')
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers=self.headers),context=self.context,timeout=45) as f: raw=json.load(f)
            if raw.get('code')!=0 or not isinstance(raw.get('data'),dict): raise ValueError()
        except Exception: raise ObservationError('HITHINK_SOURCE_FAILED:'+endpoint) from None
        private_json(self.cache/(endpoint.replace('/','-')+'-'+str(len(self.sources))+'.json'),raw)
        d=raw['data'];self.sources.append({'id':endpoint,'url':url,'asOf':stamp(d['timestamp']) if d.get('timestamp') else datetime.now(timezone.utc).isoformat()})
        return d
    def paged(self, endpoint, **params):
        rows=[]; timestamp=None; total=None
        for page in range(1,301):
            d=self.get(endpoint,page=page,size=30 if 'abnormal' in endpoint else 200,**params)
            rows.extend(d.get('item',[])); timestamp=d.get('timestamp',timestamp)
            p=d.get('pagination',{}); total=p.get('total',total)
            more=p.get('has_next') if 'has_next' in p else page<p.get('pages',1)
            if not more:
                if total is not None and len(rows)!=total:raise ObservationError('PAGINATION_INCOMPLETE')
                if 'limit-' in endpoint and len({r.get('thscode') for r in rows})!=len(rows):raise ObservationError('DUPLICATE_POOL_IDENTITY')
                return {'item':rows,'timestamp':timestamp,'pagination':p}
        raise ObservationError('PAGINATION_LIMIT')

def derive_observation(snapshot, history, stats, down_rows, yesterday_rows, dragon, abnormal, *, previous_date, observed_at, calendar_days=None):
    if not isinstance(calendar_days,(list,tuple)) or not calendar_days or previous_date not in calendar_days:
        raise ObservationError('AUTHORITATIVE_CALENDAR_REQUIRED')
    try:
        for day in calendar_days:
            if datetime.fromisoformat(day).date().isoformat()!=day:raise ValueError()
    except (TypeError,ValueError):raise ObservationError('INVALID_CALENDAR') from None
    history_days=sorted({day for day in calendar_days if day<=previous_date})
    rows=snapshot['item']; total=snapshot['total']; ids=[r.get('thscode') for r in rows]
    if len(rows)!=total or len(set(ids))!=len(ids) or any(not isinstance(s,str) or not SYMBOL.fullmatch(s) for s in ids):raise ObservationError('SNAPSHOT_UNIVERSE_INCOMPLETE')
    at=stamp(snapshot['timestamp']); market_date=at[:10]
    if stats.get('trade_date')!=market_date:raise ObservationError('RELAY_DATE_MISMATCH')
    active=[r for r in rows if all(number(r.get(k)) is not None for k in ('last_price','prev_price','volume','turnover','price_change_ratio_pct')) and r['last_price']>0 and r['prev_price']>0 and r['volume']>0 and r['turnover']>=0]
    active_ids={r['thscode'] for r in active}; changes=[r['price_change_ratio_pct'] for r in active]; n=len(active)
    hist={}; seen=set()
    for r in history:
        key=r.get('thscode'),r.get('date')
        if key in seen:raise ObservationError('DUPLICATE_HISTORY')
        seen.add(key)
        if key[0] not in active_ids or not key[1] or key[1]>previous_date:continue
        if number(r.get('close')) is None or r['close']<=0:continue
        hist.setdefault(key[0],[]).append(r)
    for rr in hist.values():rr.sort(key=lambda r:r['date'])
    # A stale security is excluded, never compared to an old last close.
    hist={s:rr for s,rr in hist.items() if rr[-1]['date']==previous_date}
    def metric(mid,label,value,unit,*,date=at,mode='intraday',sample=n,reason=None):
        return {'id':mid,'label':label,'value':value,'unit':unit,'date':date,'mode':mode,'sample':sample,'reason':(reason or '当前有效样本不足或来源未提供') if value is None else None}
    def share(mid,label,predicate,window,prior=False):
        required=history_days[-(window+(1 if prior else 0)):]
        eligible=[rr for rr in hist.values() if len(required)==window+(1 if prior else 0) and [r['date'] for r in rr[-len(required):]]==required]
        value=100*sum(predicate(rr) for rr in eligible)/len(eligible) if eligible else None
        return metric(mid,label,value,'%',date=previous_date,mode='daily',sample=len(eligible),reason='缺少截至前一交易日的足量连续有效日线')
    trend=[]
    for w in (20,60):
        trend.append(share(f'ma{w}Share',f'站上{w}日均线占比',lambda rr,w=w:rr[-1]['close']>statistics.mean(r['close'] for r in rr[-w:]),w))
        trend.append(share(f'high{w}Share',f'创{w}日新高占比',lambda rr,w=w:rr[-1]['close']>max(r['close'] for r in rr[-w-1:-1]),w,True))
        trend.append(share(f'low{w}Share',f'创{w}日新低占比',lambda rr,w=w:rr[-1]['close']<min(r['close'] for r in rr[-w-1:-1]),w,True))
    amounts=sorted((r['turnover'] for r in active),reverse=True); turnover=sum(amounts)
    daily_totals={}
    for rr in hist.values():
        for r in rr:
            a=number(r.get('turnover'))
            if a is not None and a>=0: daily_totals.setdefault(r['date'],[]).append(a)
    # Fixed cohort and full coverage per day prevent listing/history gaps from changing the denominator.
    cohort=[rr for rr in hist.values() if len(rr)>=61 and all(number(r.get('turnover')) is not None and r['turnover']>=0 for r in rr[-61:])]
    day_totals=[]
    if cohort:
        days=history_days[-61:]
        cohort=[rr for rr in cohort if [r['date'] for r in rr[-61:]]==days]
        if cohort and len(days)==61:
            day_totals=[sum(rr[-61+i]['turnover'] for rr in cohort) for i in range(61)]
        else:
            cohort=[]
    ratio=day_totals[-1]/statistics.mean(day_totals[-21:-1]) if day_totals and statistics.mean(day_totals[-21:-1])>0 else None
    percentile=100*sum(a<=day_totals[-1] for a in day_totals[:-1])/60 if day_totals else None
    cur={r['thscode']:r for r in active}; yesterday_ids={r['thscode'] for r in yesterday_rows}; matched=yesterday_ids&set(cur)
    today_up=set(stats.get('_up_ids',[])); expected=len(yesterday_ids)
    mean_return=statistics.mean(cur[s]['price_change_ratio_pct'] for s in matched) if matched else None
    promotion=100*len(matched&today_up)/len(matched) if matched and stats.get('_up_complete') else None
    up=sum(x>0 for x in changes);down=sum(x<0 for x in changes)
    stats_at=stamp(stats['timestamp']); dn=len(down_rows) if isinstance(down_rows,list) else None
    relay={'date':market_date,'asOf':stats_at,'status':'ok','sourceSealRate':number(stats.get('seal_rate')),'upCount':stats.get('limit_up_stock_count'),'downCount':dn,'downAsOf':stats.get('_down_at',at),'upPoolAsOf':stats.get('_up_at',stats_at),'openCount':stats.get('open_stock_count'),'touchedCount':stats.get('touched_limit_up_stock_count'),'ladder':[{'boards':r['board_num'],'count':r['stock_count']} for r in stats.get('exact_boards',[])],'yesterdayLimitUp':{'date':previous_date,'expected':expected,'matched':len(matched),'meanReturn':mean_return,'promotionRate':promotion}}
    groups=[{'id':'breadth','title':'市场广度','asOf':at,'metrics':[metric('upShare','上涨占比',100*up/n if n else None,'%'),metric('upCount','上涨家数',up if n else None,'家'),metric('downCount','下跌家数',down if n else None,'家'),metric('medianChange','涨跌幅中位数',statistics.median(changes) if changes else None,'%')]},{'id':'trend','title':'调整后日线趋势','asOf':previous_date,'metrics':trend},{'id':'turnover','title':'成交结构','asOf':at,'metrics':[metric('turnoverCny','全市场成交额',turnover/1e8 if n else None,'亿元'),metric('top10pctShare','成交额前10%个股占比',100*sum(amounts[:math.ceil(n*.1)])/turnover if turnover else None,'%'),metric('dailyVolumeRatio20','历史样本成交额/前20日均值',ratio,'倍',date=previous_date,mode='daily',sample=len(cohort),reason='缺少完整61日成交额固定样本'),metric('dailyVolumePercentile','历史样本成交额60日分位',percentile,'%',date=previous_date,mode='daily',sample=len(cohort),reason='缺少完整61日成交额固定样本')]},{'id':'relay','title':'封板与接力','asOf':stats_at,'metrics':[metric('upCount','涨停家数',relay['upCount'],'家',date=stats_at,sample=total),metric('downCount','跌停家数',dn,'家',date=stats.get('_down_at',at),sample=total),metric('sealRate','封板率',relay['sourceSealRate']*100 if relay['sourceSealRate'] is not None and relay['touchedCount'] else None,'%',date=stats_at,sample=relay['touchedCount']),metric('yesterdayReturn','昨日涨停股今日均涨幅',mean_return,'%',sample=len(matched),reason='昨日涨停池或今日有效行情缺失'),metric('promotionRate','昨日涨停股今日晋级率',promotion,'%',sample=len(matched),reason='昨日涨停池或今日涨停全集缺失')]}]
    distribution=[{'label':label,'count':sum(predicate(x) for x in changes)} for label,predicate in [('≤-5%',lambda x:x<=-5),('-5%~-2%',lambda x:-5<x<-2),('-2%~0%',lambda x:-2<=x<0),('平盘',lambda x:x==0),('0%~2%',lambda x:0<x<=2),('2%~5%',lambda x:2<x<5),('≥5%',lambda x:x>=5)]]
    if dragon.get('_failed') is not True and dragon.get('trade_date')!=previous_date:raise ObservationError('DRAGON_DATE_MISMATCH')
    dragon_ok=dragon.get('_failed') is not True; abnormal_ok=abnormal.get('_failed') is not True
    return {'schemaVersion':'market-observation-v1','observedAt':observed_at,'marketDate':market_date,'previousMarketDate':previous_date,'snapshotAt':at,'scope':{'name':'沪深北全A（含ST）','expected':total,'received':len(rows),'active':n,'excluded':total-n,'historyMatched':len(hist),'historyExpected':n,'historyAsOf':previous_date},'groups':groups,'details':{'distribution':distribution,'relay':relay,'dragonTiger':{'date':dragon.get('trade_date',previous_date),'asOf':stamp(dragon['timestamp']) if dragon.get('timestamp') else observed_at,'status':'ok' if dragon_ok else 'failed','rows':[{'code':r.get('thscode'),'name':r.get('name'),'netCny':number(r.get('org_net_value')),'buyCny':number(r.get('buy_value')),'sellCny':number(r.get('sell_value')),'rangeDays':r.get('range_days')} for r in dragon.get('stock_items',[])],'note':'机构榜；净额为机构净额，买入/卖出为榜单总额；一日与三日记录分别保留。' if dragon_ok else '来源请求失败，空列表不代表无上榜记录。'},'abnormal':{'asOf':observed_at,'status':'ok' if abnormal_ok else 'failed','rows':[{'code':r.get('thscode'),'name':r.get('name'),'startDate':stamp(r['start_date_ms'])[:10],'endDate':stamp(r['end_date_ms'])[:10] if r.get('end_date_ms') else None,'label':r.get('monitor_label','重点监控')} for r in abnormal.get('item',[])],'note':'来源请求失败，空列表不代表无异动记录。' if not abnormal_ok else '当前监控区间，非当日新增事件。'}},'sources':[],'notes':['广度剔除无有效成交量或行情的证券；平盘单列。','趋势采用前一交易日已完成前复权收盘；新高/低比较此前20/60个交易日收盘。','日成交额倍数和分位使用连续61日完整固定样本，样本数单列。','涨停、打开、触板及封板率取同一统计响应；跌停池、昨日接力独立采样。']}


def enrich_turnover(payload,*,snapshot_rows,snapshot_at,previous_date,calendar_days,state_root,project_root):
    from .market_turnover_data import collect_turnover
    try:
        payload['turnover']=collect_turnover(snapshot_rows=snapshot_rows,snapshot_at=snapshot_at,previous_date=previous_date,calendar_days=calendar_days,state_root=Path(state_root),project_root=Path(project_root))
    except Exception:
        try:
            saved=json.loads((Path(state_root)/'latest.json').read_text()).get('turnover')
            if saved:payload['turnover']=saved
        except (OSError,ValueError):pass
        payload['notes'].append('量能扩展本次未更新；如有已保存数据，保留原始日期与金额。')
    return payload


def collect_observation(*, state_root:Path, project_root:Path, now=None)->dict:
    clock_supplied=now is not None
    now=now or datetime.now(timezone.utc)
    observed=now.isoformat() if isinstance(now,datetime) else str(now)
    cache=Path(state_root)/'market-observation-private'; client=Rest(project_root,cache)
    calendar=client.get('calendar/trading-days')
    days=sorted({stamp(r['date_ms'])[:10] for r in calendar['item']})
    local_day=(now if isinstance(now,datetime) else datetime.fromisoformat(str(now))).astimezone(SH).date().isoformat()
    if local_day not in days:raise ObservationError('NON_TRADING_DAY')
    allrows=[];times=[];total=None
    for offset in range(0,20000,1000):
        d=client.get('prices/snapshot',limit=1000,offset=offset)
        if total is not None and total!=d.get('total'):raise ObservationError('UNIVERSE_CHANGED_DURING_CAPTURE')
        total=d['total'];times.append(d['timestamp']);allrows.extend(d['item'])
        if len(allrows)>=total:break
    if max(times)-min(times)>300000 or len({stamp(t)[:10] for t in times})!=1:raise ObservationError('SNAPSHOT_TIME_SPAN_EXCEEDED')
    day=stamp(max(times))[:10]
    if day!=local_day:raise ObservationError('SNAPSHOT_DATE_MISMATCH')
    previous=max(d for d in days if d<day)
    stats=client.get('special-data/limit-up-statistics',date=day)
    midnight=lambda d:int(datetime.fromisoformat(d).replace(tzinfo=SH).timestamp()*1000)
    up=client.paged('special-data/limit-up-pool',date_ms=midnight(day))
    stats['_up_ids']=[r['thscode'] for r in up['item']];stats['_up_complete']=True
    down=client.paged('special-data/limit-down-pool',date_ms=midnight(day))
    stats['_down_at']=stamp(down['timestamp']);stats['_up_at']=stamp(up['timestamp'])
    yesterday=client.paged('special-data/limit-up-pool',date_ms=midnight(previous))
    try:dragon=client.get('special-data/dragon-tiger-list',board_type='org',date=previous)
    except ObservationError:dragon={'_failed':True}
    try:abnormal=client.paged('special-data/abnormal-monitor-list',state='current')
    except ObservationError:abnormal={'_failed':True}
    from .market_observation_history import ensure_history
    history_path=ensure_history(state_root=Path(state_root),project_root=Path(project_root),previous_date=previous)
    history_meta=json.loads(history_path.with_suffix('.meta.json').read_text())
    history=[]
    if history_path.exists():
        with history_path.open(newline='') as f:
            for r in csv.DictReader(f):
                history.append({'thscode':r.get('thscode',r.get('code')),'date':r['date'][:10],'close':float(r['close']) if r['close'] else None,'turnover':float(r.get('turnover',r.get('amount',''))) if r.get('turnover',r.get('amount','')) else None})
    observed=datetime.now(timezone.utc).isoformat() if not clock_supplied else observed
    payload=derive_observation({'item':allrows,'total':total,'timestamp':max(times)},history,stats,down['item'],yesterday['item'],dragon,abnormal,previous_date=previous,observed_at=observed,calendar_days=days)
    payload['notes'].append('同花顺原始日线+公告事件，按CLI乘法口径自行调整；与实时行情供应商的复权计算存在算法及小数差异。')
    payload['details']['relay']['yesterdayLimitUp']['poolAsOf']=stamp(yesterday['timestamp'])
    payload['sources']=client.sources+[{'id':'hithink-readonly-daily-history','url':'https://fuyao.aicubes.cn/','asOf':history_meta.get('historyAsOf',previous)}]
    enrich_turnover(payload,snapshot_rows=allrows,snapshot_at=payload['snapshotAt'],previous_date=previous,calendar_days=days,state_root=state_root,project_root=project_root)
    if not clock_supplied:payload['observedAt']=datetime.now(timezone.utc).isoformat()
    return payload
