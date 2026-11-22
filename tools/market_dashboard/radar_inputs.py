"""Daily, local-only radar input collection. Raw provider caches never enter bundles."""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
import hashlib
import json
import io
import math
import os
from pathlib import Path
import re
import ssl
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import urllib.parse
from zoneinfo import ZoneInfo

OBJECTS = {
    'ashare': ('全部A股', {'001071'}, None, None),
    'large': ('沪深300', {'000300.SH','399300.SZ'}, '000300.SH',300),
    'small': ('中证1000', {'000852.SH','399852.SZ'}, '000852.SH',1000),
    'value': ('沪深300价值', {'000919.SH','399919.SZ'}, '000919.SH',100),
    'growth': ('创业板指', {'399006.SZ'}, '399006.SZ',100),
    'dividend': ('中证红利', {'000922.SH'}, '000922.SH',100),
    'tech': ('科创50', {'000688.SH'}, '000688.SH',50),
}
FIELDS={'up':('上涨家数',),'down':('下跌家数',),'flat':('平盘家数',),'mainNetFlow':('主力净流入','主力净额'),'turnover':('成交额',)}
CLI=Path('/Users/robot_ever/Codex/Financial Knowledge Repository/tools/npm-global/node_modules/.bin/hithink-finance')


def number(value, unit='元'):
    if value is None or str(value).strip() in ('','--','-','暂无','None','null'): return None
    text=str(value).strip().replace(',','').replace('，','').replace('−','-')
    match=re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*(万亿|亿|万)?(?:元|家|%)?',text)
    if not match:raise ValueError('Invalid numeric value')
    scale={'万亿':10**12,'亿':10**8,'万':10**4,None:1}[match[2]]
    if match[2] is None:scale={'元':1,'':1,'家':1,'%':1,'万元':10**4,'亿元':10**8,'万亿元':10**12}.get(unit)
    if scale is None:raise ValueError('Unknown amount unit')
    result=float(Decimal(match[1])*scale)
    if not math.isfinite(result):raise ValueError('Nonfinite value')
    return int(result) if result.is_integer() else result


def date_only(value):
    match=re.match(r'^(\d{4})[-.](\d{2})[-.](\d{2})',str(value))
    if not match:raise ValueError('Invalid data date')
    return datetime(*map(int,match.groups())).date().isoformat()


def find_tables(raw):
    if isinstance(raw,dict):
        if 'dataTableDTOList' in raw:return raw['dataTableDTOList']
        for value in raw.values():
            found=find_tables(value)
            if found:return found
    return []


def point(date,mode='provider-aggregate'):
    return dict(date=date,up=None,down=None,flat=None,turnover=None,mainNetFlow=None,fundMatched=None,fundExpected=None,membershipMode=mode)


def parse_aggregate(raw,object_id):
    tables=find_tables(raw)
    if not tables:raise ValueError('No aggregate data')
    history={}
    for table in tables:
        if table.get('code') not in OBJECTS[object_id][1]:raise ValueError('Wrong aggregate identity')
        values=table.get('rawTable') or table.get('table',{})
        dates=values.get('headName',[])
        metadata={str(f.get('returnCode')):f for f in table.get('fieldSet',[])}
        for key,label in table.get('nameMap',{}).items():
            field=next((f for f,names in FIELDS.items() if any(n in label for n in names)),None)
            if not field:continue
            meta=metadata.get(str(key),{})
            units={meta.get(k) for k in ('unitName','unitDesc') if meta.get(k)}
            if len(units)>1:raise ValueError('Conflicting indicator units')
            unit=next(iter(units),None)
            is_count=field in ('up','down','flat')
            if is_count and unit!='家':raise ValueError('Unverified breadth unit')
            if not is_count and unit not in ('元','万元','亿元','万亿元'):
                if unit is not None or str(key) not in ('326256','327483'):raise ValueError('Unverified amount unit')
            column=values.get(key,[])
            if len(column)!=len(dates):raise ValueError('Truncated aggregate column')
            display=table.get('table',{}).get(key,[])
            for index,(day,value) in enumerate(zip(dates,column)):
                day=date_only(day);p=history.setdefault(day,point(day))
                parsed=number(value,unit or '元')
                # These verified MX turnover indicators omit unit metadata. Confirm
                # their base-yuan raw values against the independently suffixed display.
                if not is_count and unit is None and parsed is not None:
                    formatted=display[index] if index<len(display) else None
                    if not isinstance(formatted,str) or not re.search(r'(万亿|亿|万|元)',formatted):raise ValueError('Missing display amount unit')
                    shown=number(formatted)
                    if shown is None or abs(shown-parsed)>max(abs(parsed)*0.001,1):raise ValueError('Amount unit mismatch')
                if field in ('up','down','flat') and parsed is not None and (parsed<0 or int(parsed)!=parsed):raise ValueError('Invalid breadth count')
                if field=='turnover' and parsed is not None and parsed<0:raise ValueError('Invalid turnover')
                p[field]=parsed
    return [history[d] for d in sorted(history)][-320:]


def screen_result(raw):
    inner=(raw.get('data') or {}).get('data') or {}
    return inner.get('allResults',{}).get('result',inner.get('result',{}))


def parse_screen(raw,expected_members,date):
    inner=(raw.get('data') or {}).get('data') or {}
    conditions=str(inner.get('totalCondition',''))+' '+str(inner.get('responseConditionList',''))
    if re.search(r'主力(?:净额|净流入(?:资金)?)[^且；;]{0,12}(?:为正|大于零)',conditions):raise ValueError('Unexpected positive funding filter')
    for match in re.finditer(r'主力(?:净额|净流入(?:资金)?)\s*(?:大于等于|大于|>=|>|≥)\s*([+-]?\d+(?:\.\d+)?(?:万亿|亿|万)?元?)',conditions):
        if number(match[1])>-100000000000:raise ValueError('Unexpected funding filter')
    result=screen_result(raw);rows=result.get('dataList',[])
    if not rows or result.get('total')!=len(rows) or result.get('totalRecordCount',len(rows))!=len(rows):raise ValueError('Truncated screen result')
    actual=[str(r.get('SECURITY_CODE',''))+'.'+str(r.get('MARKET_SHORT_NAME','')) for r in rows]
    if len(actual)!=len(set(actual)) or set(actual)!=set(expected_members):raise ValueError('Membership mismatch')
    columns=result.get('columns',[])
    def column_for(label):
        matches=[c for c in columns if label in c.get('title','')]
        if len(matches)!=1:raise ValueError('Missing or ambiguous screen column')
        col=matches[0]
        if date_only(col.get('dateMsg'))!=date:raise ValueError('Wrong screen date')
        return col
    flow=column_for('主力净额');amount=column_for('成交额');change=column_for('涨跌幅')
    p=point(date,'current-members');p['fundExpected']=len(expected_members)
    flows=[number(r.get(flow['key']),flow.get('unit') or '元') for r in rows]
    amounts=[number(r.get(amount['key']),amount.get('unit') or '元') for r in rows]
    changes=[number(r.get(change['key']),'%') for r in rows]
    p['fundMatched']=sum(v is not None for v in flows)
    if all(v is not None for v in flows):p['mainNetFlow']=sum(flows)
    if any(v is not None and v<0 for v in amounts):raise ValueError('Negative member turnover')
    if all(v is not None for v in amounts):p['turnover']=sum(amounts)
    if p['mainNetFlow'] is not None and p['turnover'] is not None and abs(p['mainNetFlow'])>p['turnover']*1.05:raise ValueError('Invalid funding turnover relationship')
    if all(v is not None for v in changes):
        p.update(up=sum(v>0 for v in changes),down=sum(v<0 for v in changes),flat=sum(v==0 for v in changes))
    return p


FUND_GROUP=('mainNetFlow','turnover','fundMatched','fundExpected','membershipMode')


def funding_complete(p):
    flow=p.get('mainNetFlow');amount=p.get('turnover')
    if flow is None or amount is None or amount<=0 or abs(flow)>amount*1.05:return False
    return p.get('membershipMode')=='provider-aggregate' or (p.get('fundExpected') is not None and p.get('fundExpected')>0 and p.get('fundMatched')==p.get('fundExpected'))


def merge_history(previous,new):
    merged={p['date']:dict(p) for p in previous}
    for p in new:
        old=merged.get(p['date'],{})
        value={**old,**{k:v for k,v in p.items() if k not in FUND_GROUP and (v is not None or k not in old)}}
        group=old if funding_complete(old) and not funding_complete(p) else p
        value.update({field:group.get(field) for field in FUND_GROUP})
        merged[p['date']]=value
    return [merged[d] for d in sorted(merged)][-320:]


def validated_query(client,text,parser,screen=False):
    raw=client.query(text,screen=screen)
    try:return parser(raw)
    except Exception:
        if hasattr(client,'invalidate'):client.invalidate(text,screen=screen)
        raise


def atomic_json(path,value):
    path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False));temporary.chmod(0o600);temporary.replace(path)


def rounding_tolerance(value):
    if isinstance(value,(int,float)):return 0.1
    match=re.fullmatch(r'[+-]?(\d+(?:\.(\d+))?)(万亿|亿|万)?(?:元)?',str(value).replace(',',''))
    if not match:raise ValueError('Unknown MX display precision')
    scale={None:1,'万':10000,'亿':100000000,'万亿':1000000000000}[match[3]]
    return scale*(10**(-len(match[2] or '')))/2+0.1


def parse_public_funding(raw,missing,day,known):
    # Eastmoney official stock.js uses fltt=2 yuan for f6, and f124*1000.
    # data.eastmoney.com/zjlx/000001.html defines f62 as today's main net flow.
    data=raw.get('data') or {};rows=data.get('diff',[])
    if raw.get('rc')!=0 or not isinstance(rows,list) or data.get('total')!=len(rows):raise ValueError('Truncated public response')
    normalized={}
    for row in rows:
        ticker=str(row.get('f12',''));market=row.get('f13')
        suffix='SH' if market==1 else ('BJ' if ticker.startswith(('4','8','92')) else 'SZ') if market==0 else None
        code=ticker+'.'+str(suffix)
        if not re.fullmatch(r'\d{6}',ticker) or suffix is None or code in normalized:raise ValueError('Invalid public identity')
        stamp=row.get('f124')
        if not isinstance(stamp,int) or isinstance(stamp,bool):raise ValueError('Invalid public timestamp')
        observed=datetime.fromtimestamp(stamp,ZoneInfo('Asia/Shanghai'))
        if observed.date().isoformat()!=day or observed.hour<15:raise ValueError('Wrong public date or intraday value')
        values={}
        for key in ('f62','f66','f72','f6','f3'):
            value=row.get(key)
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):raise ValueError('Unverified public yuan value')
            values[key]=value
        if abs(values['f62']-values['f66']-values['f72'])>0.01 or values['f6']<0 or abs(values['f62'])>values['f6']*1.05:raise ValueError('Public main-flow classification mismatch')
        p=point(day,'current-members');p.update(mainNetFlow=values['f62'],turnover=values['f6'],fundMatched=1,fundExpected=1,up=int(values['f3']>0),down=int(values['f3']<0),flat=int(values['f3']==0))
        normalized[code]=p
    if not missing or not missing.issubset(normalized):raise ValueError('Missing public member')
    controls=set(normalized)-set(missing)
    if len(controls)<3 or not controls.issubset(known):raise ValueError('Insufficient same-day MX controls')
    signs=set()
    for code in controls:
        reference=known[code];p=reference['point'];actual=normalized[code]
        if p['date']!=day or not funding_complete(p):raise ValueError('Wrong MX control date')
        for field,text in (('mainNetFlow','flowText'),('turnover','turnoverText')):
            if abs(actual[field]-p[field])>rounding_tolerance(reference[text]):raise ValueError('Public/MX unit or classification mismatch')
        signs.add(1 if p['mainNetFlow']>0 else -1 if p['mainNetFlow']<0 else 0)
    if not {-1,1}.issubset(signs):raise ValueError('Public controls must include both flow signs')
    return combine_funding([normalized[code] for code in sorted(missing)],day,len(missing))


def parse_current_suspensions(raw,members,day,breadth,observed_at):
    """Use a freshly fetched continuous-suspension list only with dated MX breadth.

    list2's fd is not a strict historical filter. Its response must never prove a
    future day, and an unknown resume date alone never establishes suspension.
    """
    observed_day=observed_at.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    if date_only(day)!=day or day>observed_day:raise ValueError('Future suspension inference prohibited')
    result=raw.get('result') or {};rows=result.get('data')
    if raw.get('success') is not True or raw.get('code')!=0 or type(result.get('pages')) is not int or result['pages']!=1 or not isinstance(rows,list) or type(result.get('count')) is not int or result['count']!=len(rows):raise ValueError('Incomplete suspension snapshot')
    fields=('up','down','flat')
    if not breadth or breadth.get('date')!=day or breadth.get('membershipMode')!='provider-aggregate' or any(type(breadth.get(field)) is not int or breadth[field]<0 for field in fields):raise ValueError('No same-day official breadth')
    candidates=set();seen=set()
    for row in rows:
        code=row.get('SECUCODE')
        if code not in members:continue
        if code in seen or row.get('SECURITY_CODE')!=code[:6]:raise ValueError('Ambiguous suspension identity')
        seen.add(code)
        if row.get('SUSPEND_EXPIRE')!='连续停牌':continue
        start=date_only(row.get('SUSPEND_START_TIME') or row.get('SUSPEND_START_DATE'))
        if row.get('SUSPEND_START_DATE') and date_only(row['SUSPEND_START_DATE'])!=start:raise ValueError('Conflicting suspension start date')
        if start>day:continue
        if 'SUSPEND_END_TIME' not in row or 'PREDICT_RESUME_DATE' not in row:raise ValueError('Unknown suspension schema')
        end=row.get('SUSPEND_END_TIME');resume=row.get('PREDICT_RESUME_DATE')
        if (end and date_only(end)<=day) or (resume and date_only(resume)<=day):continue
        candidates.add(code)
    effective=len(members)-len(candidates)
    if effective<=0 or sum(breadth[field] for field in fields)!=effective:raise ValueError('Suspension count disagrees with official breadth')
    return candidates


class EastmoneyClient:
    def __init__(self,cache,transport=None,suspension_transport=None):
        self.cache=Path(cache);self.transport=transport;self.suspension_transport=suspension_transport
    def suspensions(self,members,day,breadth,observed_at):
        parameters={'mkt':'1','st':'SUSPEND_START_DATE','sr':'-1','fd':day}
        if self.suspension_transport:raw=self.suspension_transport(parameters)
        else:
            request=urllib.request.Request('https://datapc.eastmoney.com/emdatacenter/tfg/list2?'+urllib.parse.urlencode(parameters),headers={'User-Agent':'Mozilla/5.0','Referer':'https://datapc.eastmoney.com/emdatacenter/tfg/index?color=b'})
            try:
                import certifi
                context=ssl.create_default_context(cafile=certifi.where())
            except ImportError:context=ssl.create_default_context()
            with urllib.request.urlopen(request,timeout=45,context=context) as response:raw=json.load(response)
        return parse_current_suspensions(raw,members,day,breadth,observed_at)
    def funding(self,missing,day,known):
        digest=hashlib.sha256(','.join(sorted(missing)).encode()).hexdigest()
        path=self.cache/f'public-{day}-{digest}.json'
        if path.exists():
            try:return parse_public_funding(json.loads(path.read_text()),missing,day,known)
            except Exception:path.unlink(missing_ok=True)
        candidates=[code for code in sorted(known) if code not in missing and funding_complete(known[code]['point'])]
        positives=[c for c in candidates if known[c]['point']['mainNetFlow']>0];negatives=[c for c in candidates if known[c]['point']['mainNetFlow']<0]
        if not positives or not negatives:raise ValueError('No signed public controls')
        controls=list(dict.fromkeys(positives[:2]+negatives[:2]+candidates[:8]))[:8]
        requested=set(missing)|set(controls)
        if len(requested)>200:raise ValueError('Public fallback request too large')
        parameters={'fields':'f12,f13,f14,f2,f3,f6,f62,f66,f72,f124','fltt':'2','invt':'2','secids':','.join(('1.' if c.endswith('.SH') else '0.')+c[:6] for c in sorted(requested))}
        if self.transport:raw=self.transport(parameters)
        else:
            request=urllib.request.Request('https://push2.eastmoney.com/api/qt/ulist.np/get?'+urllib.parse.urlencode(parameters),headers={'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'})
            try:
                import certifi
                context=ssl.create_default_context(cafile=certifi.where())
            except ImportError:context=ssl.create_default_context()
            with urllib.request.urlopen(request,timeout=45,context=context) as response:raw=json.load(response)
        result=parse_public_funding(raw,missing,day,known)
        atomic_json(path,raw)
        return result


class MXClient:
    def __init__(self,key,cache,force=False,transport=None,sleeper=time.sleep):
        self.key=key;self.cache=Path(cache);self.force=force;self.transport=transport;self.sleeper=sleeper;self.last_request=0;self.cooldown_until=0
    def member_points(self,day):
        known={}
        for path in sorted(self.cache.glob('*.json')):
            if not re.fullmatch(r'[a-f0-9]{64}\.json',path.name):continue
            try:
                raw=json.loads(path.read_text());result=screen_result(raw);rows=result.get('dataList',[])
                actual={str(row['SECURITY_CODE'])+'.'+str(row['MARKET_SHORT_NAME']) for row in rows}
                parse_screen(raw,actual,day)
                columns=result['columns'];flow=next(c['key'] for c in columns if '主力净额' in c.get('title',''));amount=next(c['key'] for c in columns if '成交额' in c.get('title',''))
                inner=(raw.get('data') or {}).get('data') or {}
                for row in rows:
                    code=str(row['SECURITY_CODE'])+'.'+str(row['MARKET_SHORT_NAME'])
                    single={'data':{'data':{'totalCondition':inner.get('totalCondition'),'responseConditionList':inner.get('responseConditionList'),'allResults':{'result':{'total':1,'totalRecordCount':1,'columns':columns,'dataList':[row]}}}}}
                    p=parse_screen(single,{code},day)
                    if funding_complete(p):known[code]={'point':p,'flowText':row[flow],'turnoverText':row[amount]}
            except Exception:continue
        return known
    def invalidate(self,text,screen=False):
        endpoint='stock-screen' if screen else 'query'
        path=self.cache/(hashlib.sha256((endpoint+text).encode()).hexdigest()+'.json')
        path.unlink(missing_ok=True)
    def query(self,text,screen=False):
        endpoint='stock-screen' if screen else 'query'
        cache=self.cache/(hashlib.sha256((endpoint+text).encode()).hexdigest()+'.json')
        if cache.exists() and not self.force and (screen or time.time()-cache.stat().st_mtime<900):return json.loads(cache.read_text())
        quota=self.cache/'quota-exhausted.json'
        today=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
        if quota.exists() and json.loads(quota.read_text()).get('date')==today:raise RuntimeError('MX quota exhausted')
        if time.monotonic()<self.cooldown_until:raise RuntimeError('MX request temporarily unavailable')
        body={'keyword' if screen else 'toolQuery':text}
        try:
            for attempt in range(4):
                try:
                    if self.transport:raw=self.transport(endpoint,body)
                    else:
                        self.sleeper(max(0,2-(time.monotonic()-self.last_request)))
                        self.last_request=time.monotonic()
                        request=urllib.request.Request('https://mkapi2.dfcfs.com/finskillshub/api/claw/'+endpoint,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','apikey':self.key})
                        try:
                            import certifi
                            context=ssl.create_default_context(cafile=certifi.where())
                        except ImportError:context=ssl.create_default_context()
                        with urllib.request.urlopen(request,timeout=90,context=context) as response:raw=json.load(response)
                    if raw.get('status')==113 or raw.get('code')==113:
                        atomic_json(quota,{'date':today})
                        raise ValueError('Provider daily quota exhausted')
                    limited=raw.get('status') in (112,429,503) or raw.get('code') in (112,429,503)
                except urllib.error.HTTPError as error:
                    if error.code not in (429,503):raise
                    limited=True
                if limited:
                    if attempt==3:
                        self.cooldown_until=time.monotonic()+1200
                        raise ValueError('Provider temporarily unavailable')
                    self.sleeper(10*(2**attempt));continue
                if raw.get('status',0)!=0 or raw.get('success') is False:raise ValueError('Provider failure')
                break
            inner=(raw.get('data') or {}).get('data') or {}
            if screen and (str(inner.get('responseCode')) not in ('None','0','100','200') or not screen_result(raw).get('dataList')):raise ValueError('Screen unavailable')
            atomic_json(cache,raw)
            return raw
        except Exception:raise RuntimeError('MX request failed') from None


def credential(project_root):
    if os.environ.get('MX_APIKEY'):return os.environ['MX_APIKEY']
    for raw in (project_root/'.env').read_text().splitlines():
        line=raw.strip();line=line[7:].lstrip() if line.startswith('export ') else line
        name,sep,value=line.partition('=')
        if sep and name.strip()=='MX_APIKEY':
            value=value.strip()
            if value.startswith(('"',"'")):return value[1:value.find(value[0],1)]
            return re.split(r'\s+#',value)[0].strip()
    raise RuntimeError('MX credential unavailable')


def parse_csi_rows(rows,code,expected):
    markets={'上海证券交易所':'SH','深圳证券交易所':'SZ','北京证券交易所':'BJ'}
    members=set();dates=set()
    for row in rows:
        normalized={k.replace(' ',''):str(v).strip() for k,v in row.items()}
        if normalized.get('指数代码IndexCode')!=code[:6]:raise ValueError('Wrong CSI index')
        rawdate=normalized.get('日期Date','')
        dates.add(datetime.strptime(rawdate,'%Y%m%d').date().isoformat())
        market=markets.get(normalized.get('交易所Exchange'))
        ticker=normalized.get('成份券代码ConstituentCode','')
        if not market or not re.fullmatch(r'\d{6}',ticker):raise ValueError('Invalid CSI member')
        member=ticker+'.'+market
        if member in members:raise ValueError('Duplicate CSI member')
        members.add(member)
    if len(members)!=expected or len(dates)!=1:raise ValueError('Incomplete CSI membership')
    return members,next(iter(dates))


def constituents(code,expected):
    if code in ('000919.SH','000922.SH'):
        import pandas as pd
        request=urllib.request.Request('https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/file/autofile/cons/'+code[:6]+'cons.xls',headers={'User-Agent':'Mozilla/5.0'})
        try:
            import certifi
            context=ssl.create_default_context(cafile=certifi.where())
        except ImportError:context=ssl.create_default_context()
        with urllib.request.urlopen(request,timeout=60,context=context) as response:payload=response.read()
        return (*parse_csi_rows(pd.read_excel(io.BytesIO(payload),dtype=str).to_dict('records'),code,expected),'CSI')
    result=subprocess.run([str(CLI),'index','constituents','--thscode',code,'--format','json'],capture_output=True,text=True,timeout=60)
    raw=json.loads(result.stdout);members={r['thscode'] for r in raw.get('data',{}).get('item',[])}
    if not raw.get('ok') or len(members)!=expected:raise ValueError('Incomplete index membership')
    return members,datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),'Hithink'


def combine_funding(parts,date,expected):
    p=point(date,'current-members');p['fundExpected']=expected;p['fundMatched']=sum(v.get('fundMatched') or 0 for v in parts)
    for field in ('up','down','flat','turnover','mainNetFlow'):
        p[field]=sum(v[field] for v in parts) if all(v[field] is not None for v in parts) else None
    return p


def member_funding_batch(client,members,day):
    query_day=datetime.strptime(day,'%Y-%m-%d').strftime('%Y年%m月%d日')
    query='股票代码属于['+','.join(sorted(v[:6] for v in members))+f']，{query_day}主力净额大于-100000000000元，显示股票代码、主力净额、成交额、涨跌幅'
    try:return validated_query(client,query,lambda raw:parse_screen(raw,members,day),screen=True)
    except Exception:
        if len(members)<=1:
            missing=point(day,'current-members');missing['fundMatched']=0;missing['fundExpected']=len(members)
            return missing
        size=10 if len(members)>10 else 5 if len(members)>5 else 1
        ordered=sorted(members)
        parts=[member_funding_batch(client,set(ordered[offset:offset+size]),day) for offset in range(0,len(ordered),size)]
        return combine_funding(parts,day,len(members))


def confirmed_exclusions(object_id,day,members,config=None):
    if config is None:
        path=Path(__file__).resolve().parents[2]/'config'/'radar-confirmed-nontrading.json'
        config=json.loads(path.read_text()) if path.exists() else {}
    record=config.get(day,{}).get(object_id)
    if not record:return set()
    excluded=set(record.get('members',[]))
    if not record.get('sources') or not excluded or not excluded.issubset(members):raise ValueError('Invalid confirmed nontrading evidence')
    if any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',v) for v in excluded):raise ValueError('Invalid nontrading member')
    if any(not str(url).startswith('https://') for url in record['sources']):raise ValueError('Invalid nontrading source')
    return excluded


def closed_market_end(now):
    day=now.date()
    if now.hour*60+now.minute<15*60+20 or day.weekday()>=5:day-=timedelta(days=1)
    while day.weekday()>=5:day-=timedelta(days=1)
    return day.isoformat()


def migrate_private_cache(root):
    root.mkdir(parents=True,exist_ok=True,mode=0o700)
    for directory in sorted(root.iterdir()):
        if not directory.is_dir() or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',directory.name):continue
        for path in directory.glob('*.json'):
            if not re.fullmatch(r'[a-f0-9]{64}\.json',path.name) and path.name!='quota-exhausted.json':continue
            target=root/path.name
            if not target.exists() or path.stat().st_mtime>target.stat().st_mtime:shutil.copy2(path,target)


def collect(client,previous=None,member_loader=None,now=None,batch_size=20,public_client=None):
    member_loader=member_loader or constituents
    now=now or datetime.now(ZoneInfo('Asia/Shanghai'))
    end=closed_market_end(now);start=(datetime.strptime(end,'%Y-%m-%d').date()-timedelta(days=450)).isoformat()
    objects={};failures=[];validated=0
    for object_id,(name,identities,code,expected) in OBJECTS.items():
        old=(previous or {}).get('objects',{}).get(object_id,{})
        obj={'id':object_id,'scope':old.get('scope',name),'sources':list(old.get('sources',[])),'membershipAsOf':old.get('membershipAsOf'),'history':[p for p in old.get('history',[]) if p['date']<=end]}
        provider_history=[]
        try:
            query=f'查询{name}'+('板块' if object_id=='ashare' else '指数')+f'从{start}至{end}每个交易日的上涨家数、下跌家数、平盘家数'+('、主力净流入资金合计、成交额合计' if object_id=='ashare' else '、成交额')+'，返回每日实际日期和单位，缺失保留为空。'
            history=validated_query(client,query,lambda raw:[p for p in parse_aggregate(raw,object_id) if p['date']<=end])
            provider_history=history
            if history:validated+=1
            obj['history']=merge_history(obj['history'],history)
            obj['sources']=sorted(set(obj['sources']+['MX']))
        except Exception:failures.append(object_id+':aggregate unavailable')
        reference=objects.get('ashare',{}).get('history',[])
        if code and (obj['history'] or reference):
            try:
                members,as_of,member_source=member_loader(code,expected)
                day=max(p['date'] for p in (obj['history']+reference))
                query_day=datetime.strptime(day,'%Y-%m-%d').strftime('%Y年%m月%d日')
                parts=[]
                ordered=sorted(members)
                excluded=confirmed_exclusions(object_id,day,members)
                if not excluded and object_id=='small' and public_client is not None and hasattr(public_client,'suspensions'):
                    official=next((p for p in provider_history if p['date']==day),None)
                    if official is not None:
                        try:
                            excluded=public_client.suspensions(members,day,official,now)
                            if not excluded.issubset(members):raise ValueError('Unexpected suspension member')
                            if excluded:obj['sources']=sorted(set(obj['sources']+['Eastmoney']))
                        except Exception:
                            excluded=set();failures.append(object_id+':unconfirmed suspension exclusions')
                obj['scope']=name
                if excluded:
                    original=len(members);members=members-excluded
                    obj['scope']=f'{name}：{original}成份，{len(members)}有效交易样本，{len(excluded)}经证实无交易/无有效报价排除'
                if object_id in ('growth','tech'):
                    query=f'{name}指数的成份股，{query_day}主力净额大于-100000000000元，显示股票代码、主力净额、成交额、涨跌幅'
                    parts.append(validated_query(client,query,lambda raw:parse_screen(raw,members,day),screen=True))
                else:
                    for offset in range(0,len(ordered),batch_size):
                        group=set(ordered[offset:offset+batch_size])-excluded
                        if not group:continue
                        try:parts.append(member_funding_batch(client,group,day))
                        except Exception:
                            missing=point(day,'current-members');missing['fundMatched']=0;missing['fundExpected']=len(group);parts.append(missing)
                            failures.append(object_id+':funding batch unavailable')
                p=combine_funding(parts,day,len(members))
                if p['fundMatched']<len(members) and hasattr(client,'member_points'):
                    known=client.member_points(day);available=set(members)&set(known);missing=set(members)-available
                    recovered=[known[code]['point'] for code in sorted(available)]
                    used_public=False
                    if missing and public_client is not None:
                        try:
                            recovered.append(public_client.funding(missing,day,known));used_public=True
                        except Exception:pass
                    if missing and not used_public:
                        absent=point(day,'current-members');absent['fundMatched']=0;absent['fundExpected']=len(missing);recovered.append(absent)
                    p=combine_funding(recovered,day,len(members))
                    if used_public:obj['sources']=sorted(set(obj['sources']+['Eastmoney']))
                if p['fundMatched']<len(members):failures.append(object_id+':partial member funding')
                # Keep provider breadth when supplied; current members are explicitly approximate.
                existing=next((v for v in obj['history'] if v['date']==day),{})
                breadth=('up','down','flat')
                if all(existing.get(field) is not None for field in breadth) and sum(existing[field] for field in breadth)<=len(members):
                    for field in breadth:p[field]=existing[field]
                if p['turnover'] is None and p['mainNetFlow'] is None:p['turnover']=existing.get('turnover')
                preserving=funding_complete(existing) and not funding_complete(p)
                obj['history']=merge_history(obj['history'],[p])
                if not preserving:obj['membershipAsOf']=as_of
                else:obj['scope']=old.get('scope',name)
                if p['fundMatched']>0:validated+=1
                obj['sources']=sorted(set(obj['sources']+['MX',member_source]))
            except Exception:failures.append(object_id+':member funding unavailable')
        objects[object_id]=obj
    dates=[p['date'] for obj in objects.values() for p in obj['history']]
    if not dates or not validated:raise RuntimeError('No validated radar input history')
    return {'schemaVersion':'radar-inputs-v1','observedAt':now.isoformat(),'marketDate':max(dates),'objects':objects},failures


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,required=True);parser.add_argument('--project-root',type=Path,required=True);parser.add_argument('--force',action='store_true')
    args=parser.parse_args(argv)
    latest=args.state_root/'latest.json'
    previous=json.loads(latest.read_text()) if latest.exists() else None
    current=datetime.now(ZoneInfo('Asia/Shanghai'))
    today=current.date().isoformat()
    marker=args.state_root/'last-success.json'
    if not args.force and marker.exists() and json.loads(marker.read_text()).get('date')==today and json.loads(marker.read_text()).get('marketDate')==today:
        print(json.dumps({'status':'cached','path':str(latest)}));return 0
    attempt=args.state_root/'last-attempt.json'
    if not args.force and attempt.exists() and latest.exists():
        retry_at=json.loads(attempt.read_text()).get('retryAt')
        if retry_at and current<datetime.fromisoformat(retry_at):
            print(json.dumps({'status':'partial-cooldown','path':str(latest),'retryAt':retry_at}));return 0
    try:
        cache_root=args.state_root/'private-cache'
        migrate_private_cache(cache_root)
        client=MXClient(credential(args.project_root),cache_root)
        bundle,failures=collect(client,previous,public_client=EastmoneyClient(cache_root))
        atomic_json(latest,bundle)
        complete=set(bundle['objects'])==set(OBJECTS) and bundle['marketDate']==today
        for object_id,obj in bundle['objects'].items():
            p=obj['history'][-1] if obj['history'] else {}
            complete=complete and p.get('date')==bundle['marketDate'] and funding_complete(p) and all(isinstance(p.get(field),int) and p[field]>=0 for field in ('up','down','flat')) and sum(p.get(field) or 0 for field in ('up','down','flat'))>0
            if object_id!='ashare':complete=complete and p.get('fundExpected') is not None and 0<p['fundExpected']<=OBJECTS[object_id][3] and p.get('fundMatched')==p.get('fundExpected')
        if complete:atomic_json(marker,{'date':today,'marketDate':bundle['marketDate']})
        atomic_json(attempt,{'retryAt':(current+timedelta(minutes=20)).isoformat()})
        print(json.dumps({'status':'collected','path':str(latest),'marketDate':bundle['marketDate'],'warnings':failures},ensure_ascii=False));return 0
    except Exception:
        print(json.dumps({'status':'failed','error':'Radar input collection unavailable; previous bundle preserved'}));return 1


if __name__=='__main__':raise SystemExit(main())
