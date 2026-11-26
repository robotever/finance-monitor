"""Full-A turnover in CNY; verified exact-minute comparisons, no interpolation.

Provider credentials and captures stay in the existing private state tree.
History uses native five-market daily totals, independent of individual bars.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
import hashlib
import json
import math
from pathlib import Path
import re
import ssl
import subprocess
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from .market_observation_data import private_json
from .radar_inputs import MXClient, credential, find_tables

SH = ZoneInfo('Asia/Shanghai')
GROUPS = [('all','全市场'),('sh','沪市'),('sz','深市'),('chinext','创业板'),('star','科创板')]
QQ = 'https://web.ifzq.gtimg.cn/appstock/app/day/query'
EM = 'https://push2his.eastmoney.com/api/qt/stock/trends2/get'
MEMBERS = 'https://fuyao.aicubes.cn/api/a-share-index/constituents/ths-stock-list'


def _number(value):
    return type(value) in (int,float) and math.isfinite(value) and value >= 0


def _groups(code):
    if not isinstance(code,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',code):
        raise ValueError('证券范围校验失败')
    exchange=code[-2:].lower()
    return ['all',exchange]+(['chinext'] if exchange=='sz' and code.startswith('30') else [])+(['star'] if exchange=='sh' and code.startswith('68') else [])


def _unquoted(row):
    return all(key in row and row[key] is None for key in ('turnover','last_price','volume'))


def snapshot_totals(rows):
    totals={k:0. for k in ['all','sh','sz','bj','chinext','star']}; invalid=set(); seen=set()
    for row in rows:
        code=row.get('thscode'); groups=_groups(code)
        if code in seen: raise ValueError('证券重复')
        seen.add(code)
        if _unquoted(row):continue
        value=row.get('turnover')
        for group in groups:
            if _number(value):totals[group]+=value
            else:invalid.add(group)
    for group in invalid:totals[group]=None
    if not rows:return {k:None for k in totals}
    return totals


def _time(value):
    if not re.fullmatch(r'\d{2}:\d{2}',value):raise ValueError('分钟时间无效')
    if not ('09:30'<=value<='11:30' or '13:00'<=value<='15:00'):
        raise ValueError('非交易分钟')
    return value


def parse_tencent(raw,code,dates=None):
    output={}
    for day in raw['data'][code]['data']:
        day_date=datetime.strptime(day['date'],'%Y%m%d').date().isoformat()
        if dates is not None and day_date not in dates:continue
        points={}
        for line in day['data']:
            fields=line.split()
            if len(fields)!=4:raise ValueError('分钟成交额缺失')
            key=_time(fields[0][:2]+':'+fields[0][2:]); value=float(fields[3])
            if not _number(value):raise ValueError('分钟成交额无效')
            points[key]=value
        values=[points[k] for k in sorted(points)]
        if any(a-b>0.1 for a,b in zip(values,values[1:])):raise ValueError('累计成交额倒退')
        output[day_date]=points
    return output


def parse_eastmoney(raw):
    output={}; seen=set()
    for line in raw['data']['trends']:
        fields=line.split(','); stamp=fields[0]; day=stamp[:10]; key=_time(stamp[11:16])
        date.fromisoformat(day); value=float(fields[6])
        if not _number(value) or (day,key) in seen:raise ValueError('分钟成交额无效或重复')
        seen.add((day,key)); points=output.setdefault(day,{})
        if points and key<=max(points):raise ValueError('分钟顺序无效')
        points[key]=(list(points.values())[-1] if points else 0)+value
    standard=[f'{minute//60:02d}:{minute%60:02d}' for minute in range(570,901) if minute<=690 or minute>=781]
    for points in output.values():
        if points:
            expected={key for key in standard if key<=max(points)}
            if not expected<=set(points):raise ValueError('逐分钟成交额缺少交易分钟，不能累加为完整值')
    return output


def sum_curves(curves):
    if not curves:return {}
    days=set(curves[0])
    for curve in curves[1:]:days.intersection_update(curve)
    output={}
    for day in days:
        times=set(curves[0][day])
        for curve in curves[1:]:times.intersection_update(curve[day])
        if times:output[day]={key:sum(curve[day][key] for curve in curves) for key in sorted(times)}
    return output


def same_time(curve,today,previous,previous_total,cutoff):
    current=curve.get(today,{}); prior=curve.get(previous,{})
    if not _number(previous_total) or previous_total<=0 or '15:00' not in prior:
        raise ValueError('前一交易日完整日线或收盘分钟缺失')
    if abs(prior['15:00']-previous_total)/previous_total>0.001:
        raise ValueError('分钟与日线市场范围核验未通过')
    common=sorted(k for k in set(current)&set(prior) if k<=cutoff)
    if not common:raise ValueError('缺少两日同时间分钟成交额')
    key=common[-1]
    if prior[key]<=0:raise ValueError('前日同时间成交额为零')
    return current[key],prior[key],key


def _year_start(day):
    d=date.fromisoformat(day)
    try:return d.replace(year=d.year-1).isoformat()
    except ValueError:return d.replace(year=d.year-1,day=28).isoformat()


def build_turnover(snapshot_rows,snapshot_at,previous_date,calendar_days,history,curves,errors=None,*,history_asof=None):
    at=datetime.fromisoformat(snapshot_at).astimezone(SH); today=at.date().isoformat(); cutoff=min(at.strftime('%H:%M'),'15:00')
    if previous_date not in calendar_days or max((d for d in calendar_days if d<today),default=None)!=previous_date:
        raise ValueError('前一交易日不符官方日历')
    totals=snapshot_totals(snapshot_rows); by_day={r['date']:r for r in history}
    prior=by_day.get(previous_date,{})
    # A common cutoff across all markets avoids summing differently timed data.
    usable={}; failures=dict(errors or {})
    for group in ['sh','sz','bj','chinext','star']:
        try:usable[group]=same_time(curves.get(group,{}),today,previous_date,prior.get(group),cutoff)
        except ValueError as exc:failures.setdefault(group,str(exc))
    common=set.intersection(*(set(curves[g].get(today,{}))&set(curves[g].get(previous_date,{})) for g in usable)) if usable else set()
    common=sorted(k for k in common if k<=cutoff)
    comparison_time=common[-1] if common else None
    if usable and not comparison_time:
        failures.update({group:'各市场缺少共同交易分钟' for group in usable});usable={}
    if comparison_time:
        for group in list(usable):usable[group]=same_time(curves[group],today,previous_date,prior.get(group),comparison_time)
    if all(group in usable for group in ['sh','sz','bj']):
        usable['all']=(sum(usable[g][0] for g in ['sh','sz','bj']),sum(usable[g][1] for g in ['sh','sz','bj']),comparison_time)
    else:failures['all']='沪深北至少一市场缺少通过口径核验的同时间分钟数据'
    daily_close=at.strftime('%H:%M')>='15:30'
    if daily_close:
        usable={g:(totals[g],prior[g],None) for g,_ in GROUPS if _number(totals[g]) and _number(prior.get(g)) and prior[g]>0}
        comparison_time=None
        failures.update({g:'收盘后完整快照或前一交易日日成交额缺失，未进行全天比较' for g,_ in GROUPS if g not in usable})
    rows=[]
    for group,name in GROUPS:
        compared=usable.get(group); current=totals[group]; previous=None; change=None; pct=None; current_at=snapshot_at; comparison_at=None
        if compared:
            current,previous,key=compared; change=current-previous; pct=change/previous*100
            if daily_close:comparison_at=previous_date
            else:current_at=f'{today}T{key}:00+08:00';comparison_at=f'{previous_date}T{key}:00+08:00'
        rows.append(dict(id=group,name=name,comparisonMode=('daily-close' if daily_close else 'same-minute') if compared else 'unavailable',currentCny=current,currentAsOf=current_at,previousSameTimeCny=previous,
                         changeCny=change,changePct=pct,comparisonAsOf=comparison_at,
                         reason=None if compared else failures.get(group,'分钟数据不可用')))
    start=_year_start(today)
    points=[dict(date=day,**{g:by_day.get(day,{}).get(g) for g,_ in GROUPS}) for day in sorted(set(calendar_days)) if start<=day<=previous_date]
    return dict(version='turnover-structure-v1',date=today,previousDate=previous_date,asOf=snapshot_at,
                comparisonTime=comparison_time,rows=rows,history=dict(startDate=start,endDate=previous_date,asOf=history_asof or snapshot_at,points=points),
                sources=[],notes=['范围为沪深北A股，含ST及CDR；创业板、科创板为深市、沪市子集，五行不能相加。',
                '金额单位为人民币元；分钟值来自腾讯及东方财富同一时刻真实累计值，不插值；与妙想前日市场合计核验容差0.1%。',
                '历史及昨日基准为东方财富妙想五市场原生成交额合计（人民币元），不是个股日线样本求和；当前金额为同花顺全量快照汇总，两来源细微差异保留。',
                '15:30后采用同花顺完整当日快照与妙想前一交易日市场级全天成交额比较，标记daily-close并保留真实快照时刻；盘中不使用昨日全天替代同时间值。',
                f'快照中{sum(_unquoted(r) for r in snapshot_rows)}只证券最新价/成交量/成交额均为空，未视为已交易证券；部分报价缺失不补零。'])


def _fetch(url,cache,name,headers=None,cache_used=None):
    context=ssl.create_default_context(cafile='/etc/ssl/cert.pem' if Path('/etc/ssl/cert.pem').exists() else None)
    for attempt in range(2):
        try:
            request=urllib.request.Request(url,headers=headers or {'User-Agent':'Mozilla/5.0'})
            with urllib.request.urlopen(request,context=context,timeout=20) as stream:raw=json.load(stream)
            private_json(cache/(name+'.json'),raw)
            return raw
        except Exception:
            if attempt:
                try:
                    raw=json.loads((cache/(name+'.json')).read_text())
                    if cache_used is not None:cache_used.add(name)
                    return raw
                except (OSError,ValueError):raise ValueError('分钟来源请求失败') from None


MX_URL='https://mkapi2.dfcfs.com/finskillshub/api/claw/query'
MX_MARKETS={'全部A股(板块)':'all','上证A股(板块)':'sh','深证A股(板块)':'sz','全部创业板(板块)':'chinext','科创板(板块)':'star'}


def mx_history_question(start,previous):
    def chinese(value):
        day=date.fromisoformat(value)
        return f'{day.year}年{day.month}月{day.day}日'
    return '全部A股(板块)、上证A股(板块)、深证A股(板块)、全部创业板(板块)、科创板(板块)，'+chinese(start)+'至'+chinese(previous)+'每日成交额合计，人民币元，请返回完整每日历史数据，不是区间总和。'


def _validate_native_rows(rows,start,previous,calendar_days):
    expected=sorted({day for day in calendar_days if start<=day<=previous})
    if not expected or [row.get('date') for row in rows]!=expected:raise ValueError('市场合计日期与官方交易日历不一致')
    output=[]
    for row in rows:
        values={group:row.get(group) for group,_ in GROUPS}
        if any(not _number(v) or v>=1e16 for v in values.values()):raise ValueError('市场合计成交额缺失或无效')
        if values['all']<values['sh']+values['sz'] or values['chinext']>values['sz'] or values['star']>values['sh']:
            raise ValueError('市场合计范围层级不一致')
        output.append(dict(date=row['date'],**values,bj=values['all']-values['sh']-values['sz']))
    return output


def parse_mx_history(raw,start,previous,calendar_days):
    """Accept only native five-market daily aggregates in exact raw CNY."""
    if raw.get('success') is False or raw.get('status',0)!=0 or raw.get('code',0)!=0:raise ValueError('妙想市场合计来源失败')
    tables=find_tables(raw)
    if len(tables)!=1:raise ValueError('市场合计表缺失或不唯一')
    table=tables[0];field=table.get('field') or {}
    required={'returnSourceCode':'TVAL','returnSourceName':'成交额(合计)_板块','dateGranularity':'DAY','unit':'1'}
    if any(field.get(key)!=value for key,value in required.items()):raise ValueError('市场合计指标、频率或单位不符')
    if field.get('startDate','')[:10]!=start or field.get('endDate','')[:10]!=previous:raise ValueError('市场合计查询窗口不符')
    values=table.get('rawTable')
    if not isinstance(values,dict) or set(values)!=(set(MX_MARKETS)|{'headName'}):raise ValueError('市场合计完整五市场原始值缺失')
    days=values['headName']
    if not isinstance(days,list) or not days or any(not isinstance(day,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day) for day in days):raise ValueError('市场合计日期无效')
    for day in days:date.fromisoformat(day)
    if days!=sorted(set(days),reverse=True):raise ValueError('市场合计日期重复或顺序不符')
    if any(not isinstance(values[name],list) or len(values[name])!=len(days) for name in MX_MARKETS):raise ValueError('市场合计列不完整')
    rows=[]
    for index,day in enumerate(days):
        row={'date':day}
        for name,group in MX_MARKETS.items():
            value=values[name][index]
            if isinstance(value,str):
                if not re.fullmatch(r'\d+(?:\.\d+)?',value):raise ValueError('市场原始成交额不是人民币数值')
                value=float(value)
            if not _number(value):raise ValueError('市场原始成交额缺失或无效')
            row[group]=value
        rows.append(row)
    return _validate_native_rows(list(reversed(rows)),start,previous,calendar_days)


def _history_native(project_root,cache,start,previous,calendar_days):
    """One immutable completed-window capture, independent of individual bars."""
    target=cache/f'mx-native-v1-{start}-{previous}.json'
    if target.exists():
        stored=json.loads(target.read_text())
        if stored.get('version')!='mx-native-market-totals-v1' or stored.get('startDate')!=start or stored.get('endDate')!=previous:
            raise ValueError('已缓存市场合计契约不符')
        captured=datetime.fromisoformat(stored['capturedAt'])
        if captured.tzinfo is None:raise ValueError('市场合计取得时间缺少时区')
        return _validate_native_rows(stored['rows'],start,previous,calendar_days),captured.isoformat()
    question=mx_history_question(start,previous);rawcache=cache/'mx-raw'
    rawpath=rawcache/(hashlib.sha256(('query'+question).encode()).hexdigest()+'.json')
    if rawpath.exists():raw=json.loads(rawpath.read_text())
    else:
        client=MXClient(credential(Path(project_root)),rawcache)
        raw=client.query(question)
    rows=parse_mx_history(raw,start,previous,calendar_days)
    captured=datetime.fromtimestamp(rawpath.stat().st_mtime,SH).isoformat()
    private_json(target,dict(version='mx-native-market-totals-v1',startDate=start,endDate=previous,capturedAt=captured,rows=rows))
    return rows,captured


def collect_turnover(*,snapshot_rows,snapshot_at,previous_date,calendar_days,state_root,project_root):
    cache=Path(state_root)/'market-observation-private/turnover';cache.mkdir(parents=True,exist_ok=True,mode=0o700)
    errors={}; cache_used=set()
    history_asof=datetime.now(SH).isoformat()
    try:history,history_asof=_history_native(project_root,cache,_year_start(snapshot_at[:10]),previous_date,calendar_days)
    except Exception:history=[];errors={g:'妙想完整五市场日合计来源不可用，未验证前日基准' for g,_ in GROUPS}
    if datetime.fromisoformat(snapshot_at).astimezone(SH).strftime('%H:%M')>='15:30':
        payload=build_turnover(snapshot_rows,snapshot_at,previous_date,calendar_days,history,{},errors,history_asof=history_asof)
        payload['sources']=[dict(id=identifier,url=url,asOf=history_asof if identifier in ('mx-native-market-totals',) else snapshot_at) for identifier,url in [
            ('hithink-full-a-snapshot','https://fuyao.aicubes.cn/api/a-share/prices/snapshot'),
            ('mx-native-market-totals',MX_URL)]]
        return payload
    def qq(code):
        url=QQ+'?'+urllib.parse.urlencode({'code':code})
        return parse_tencent(_fetch(url,cache,code,cache_used=cache_used),code,dates={snapshot_at[:10],previous_date})
    curves={}
    base={'sh':'sh000002','sz':'sz399107','chinext':'sz399102','star':'sh000680'}
    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={key:pool.submit(qq,code) for key,code in base.items()}
        for key,job in jobs.items():
            try:curves[key]=job.result()
            except Exception:errors[key]='公开市场分钟成交额请求失败'
    try:
        # The SH A index omits this CDR; preserve the full SH A/CDR definition.
        cdr=[r['thscode'] for r in snapshot_rows if r['thscode'].endswith('.SH') and r['thscode'].startswith('689') and not _unquoted(r)]
        if cdr and 'sh' in curves:curves['sh']=sum_curves([curves['sh']]+[qq('sh'+code[:6]) for code in cdr])
    except Exception:curves.pop('sh',None);errors['sh']='沪市CDR补集分钟缺失'
    try:
        helper=Path(project_root)/'tools/hithink_mcp_headers.py'
        result=subprocess.run(['python3',str(helper)],capture_output=True,text=True,timeout=15,check=True)
        headers=json.loads(result.stdout)
        url=MEMBERS+'?thscode=399102.SZ';raw=_fetch(url,cache,'chinext-members',headers,cache_used)
        if raw.get('code')!=0:raise ValueError()
        if datetime.fromtimestamp(raw['data']['timestamp']/1000,SH).date().isoformat()!=snapshot_at[:10]:raise ValueError()
        members={r['thscode'] for r in raw['data']['item']}
        full={r['thscode'] for r in snapshot_rows if 'chinext' in _groups(r['thscode']) and not _unquoted(r)}
        if not members or any(not s.startswith('30') or not s.endswith('.SZ') for s in members):raise ValueError()
        missing=sorted(full-members)
        if len(missing)>100:raise ValueError()
        if 'chinext' not in curves:raise ValueError()
        with ThreadPoolExecutor(max_workers=6) as pool:supplements=list(pool.map(qq,['sz'+s[:6] for s in missing]))
        curves['chinext']=sum_curves([curves['chinext']]+supplements)
    except Exception:curves.pop('chinext',None);errors['chinext']='创业板综补集范围或分钟数据不可用'
    try:
        url=EM+'?'+urllib.parse.urlencode(dict(secid='0.899050',fields1='f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11',fields2='f51,f52,f53,f54,f55,f56,f57,f58',ndays=5,iscr=0))
        curves['bj']=parse_eastmoney(_fetch(url,cache,'bj899050',cache_used=cache_used))
    except Exception:errors['bj']='北市分钟成交额来源不可用'
    payload=build_turnover(snapshot_rows,snapshot_at,previous_date,calendar_days,history,curves,errors,history_asof=history_asof)
    payload['sources']=[dict(id=identifier,url=url,asOf=history_asof if identifier in ('mx-native-market-totals',) else snapshot_at) for identifier,url in [
        ('hithink-full-a-snapshot','https://fuyao.aicubes.cn/api/a-share/prices/snapshot'),
        ('mx-native-market-totals',MX_URL),('tencent-multiday-minutes',QQ),
        ('hithink-chinext-members',MEMBERS),('eastmoney-bj-minutes',EM)]]
    if cache_used:payload['notes'].append(f'本次{len(cache_used)}个公开/成份请求失败后复用私有真实捕获；分钟仍须包含当日及前一交易日，保留原分钟时间并重新核对日线，不将重试时间当行情时间。')
    return payload
