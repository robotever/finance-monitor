"""Isolated confirmed-daily core CSI300 ETF observation collector and publisher."""
from __future__ import annotations
import argparse,concurrent.futures,fcntl,hashlib,json,math,os,re,ssl,subprocess,sys,time,urllib.parse,urllib.request
from datetime import datetime,timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
from .radar_inputs import MXClient

CORE=[('510300.SH','华泰柏瑞','SSE'),('510310.SH','易方达','SSE'),('510330.SH','华夏','SSE'),('159919.SZ','嘉实','SZSE')]
SSE='https://query.sse.com.cn/commonQuery.do'
SZSE='https://www.szse.cn/api/report/ShowReport/data'
def valid_date(v):
 if not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v):raise ValueError('INVALID_DATE')
 datetime.strptime(v,'%Y-%m-%d');return v

def num(v):
 n=float(v)
 if not math.isfinite(n) or n<=0:raise ValueError('INVALID_VALUE')
 return n

def shares(v):
 n=Decimal(str(v).replace(',',''))*10000
 if n!=n.to_integral_value() or not 0<n<1e14:raise ValueError('INVALID_SHARES')
 return int(n)

def merge_rows(old,new):
 def unique(rows):
  out={}
  for r in rows:
   d=valid_date(r['date'])
   if d in out and out[d]!=r:raise ValueError('CONFLICTING_DATE')
   out[d]=r
  return out
 out=unique(old);out.update(unique(new));return [out[d] for d in sorted(out)]

def parse_sse(raw):
 out={c:[] for c,_,e in CORE if e=='SSE'}
 if not isinstance(raw.get('result'),list):raise ValueError('INVALID_SSE')
 for r in raw['result']:
  c=r['SEC_CODE']+'.SH'
  if c in out:out[c].append({'date':valid_date(r['STAT_DATE']),'shares':shares(r['TOT_VOL'])})
 for c in out:out[c]=merge_rows(out[c],[])
 return out

def parse_szse(raw):
 table=next((x for x in raw if isinstance(x.get('data'),list)),None)
 if not table or table.get('error'):raise ValueError('INVALID_SZSE')
 out=[]
 for r in table['data']:
  if r['fund_code'].strip()!='159919':raise ValueError('WRONG_SZSE_FUND')
  out.append({'date':valid_date(r['size_date']),'shares':shares(r['current_size'])})
 return merge_rows(out,[])

def parse_nav(raw):
 if raw.get('ok') is not True or not isinstance(raw.get('data',{}).get('item'),list) or not all('unit_nav' in r and 'nav_date' in r for r in raw['data']['item']):raise ValueError('NAV_UNAVAILABLE')
 return merge_rows([{'date':datetime.fromtimestamp(r['nav_date']/1000,ZoneInfo('Asia/Shanghai')).date().isoformat(),'nav':num(r['unit_nav'])} for r in raw['data']['item']],[])

def parse_caps(raw):
 tables=[]
 def walk(x):
  if isinstance(x,dict):
   if isinstance(x.get('dataTableDTOList'),list):tables.extend(x['dataTableDTOList'])
   else:
    for v in x.values():
     if isinstance(v,(dict,list)):walk(v)
  elif isinstance(x,list):
   for v in x:walk(v)
 walk(raw)
 candidates=[t for t in tables if t.get('code')=='000300.SH' and t.get('field',{}).get('returnSourceCode')=='SHRMARKETVALUEM' and t['field'].get('returnName')=='流通市值' and t['field'].get('dateGranularity')=='DAY' and str(t['field'].get('unit'))=='1' and t['field'].get('fixedParamValue')=='Period=1']
 if len(candidates)!=1:raise ValueError('INVALID_CAP_BASIS')
 t=candidates[0];table=t['rawTable'];dates=table['headName'];values=table[str(t['field']['returnCode'])]
 if len(dates)!=len(values) or not dates:raise ValueError('INVALID_CAP_SERIES')
 out=[{'date':valid_date(d),'value':num(v)} for d,v in zip(dates,values) if v is not None and str(v) not in ['', '--']]
 if any(not 1e12<r['value']<1e15 for r in out):raise ValueError('INVALID_CAP_UNIT')
 return merge_rows(out,[])

def confirmed_sessions(rows,now):
 today=now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
 return sorted({valid_date(r[0]) for r in rows if r[0]<today})

def atomic(path,value):
 path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
 temp=path.with_name(path.name+f'.{os.getpid()}.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,separators=(',',':')));temp.chmod(0o600);temp.replace(path)

def fetch_json(url):
 # Public endpoints only; no arbitrary proxy API is exposed to the browser.
 if urllib.parse.urlparse(url).hostname not in ['query.sse.com.cn','www.szse.cn','web.ifzq.gtimg.cn']:raise ValueError('INVALID_PUBLIC_HOST')
 ref='https://www.szse.cn/market/fund/volume/etf/index.html' if urllib.parse.urlparse(url).hostname=='www.szse.cn' else 'https://gu.qq.com/' if urllib.parse.urlparse(url).hostname=='web.ifzq.gtimg.cn' else 'https://www.sse.com.cn/'
 r=subprocess.run(['/usr/bin/curl','--noproxy','*','-fsS','--connect-timeout','5','--max-time','20','--max-filesize','3000000','-H','Referer: '+ref,'-H','User-Agent: Mozilla/5.0',url],capture_output=True,timeout=25)
 if r.returncode or len(r.stdout)>3000000:raise RuntimeError('PUBLIC_SOURCE_UNAVAILABLE')
 return json.loads(r.stdout)

def sse_day(day,cache,refresh=False):
 file=cache/'sse'/f'{day}.json'
 if file.exists() and not refresh:return json.loads(file.read_text())
 p={'isPagination':'true','sqlId':'COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L','STAT_DATE':day,'pageHelp.pageSize':'5000','pageHelp.pageNo':'1','pageHelp.beginPage':'1','pageHelp.endPage':'1','pageHelp.cacheSize':'1'}
 raw=fetch_json(SSE+'?'+urllib.parse.urlencode(p));out=parse_sse(raw)
 if any(len(v)!=1 or v[0]['date']!=day for v in out.values()):raise ValueError('INCOMPLETE_SSE_DAY')
 if int(raw.get('pageHelp',{}).get('total',len(raw['result'])))>len(raw['result']):raise ValueError('TRUNCATED_SSE')
 atomic(file,out);return out

def szse_range(start,end):
 # API explicitly limits queries to <=6months; 150 calendar-day chunks are bounded.
 rows=[];day=datetime.strptime(start,'%Y-%m-%d').date();last=datetime.strptime(end,'%Y-%m-%d').date()
 while day<=last:
  stop=min(last,day+timedelta(days=149));page=1;collected=[];expected=None
  while True:
   p={'SHOWTYPE':'JSON','CATALOGID':'scsj_fund_jjgm','TABKEY':'tab1','txtDm':'159919','txtStart':str(day),'txtEnd':str(stop),'jjlb':'ETF','PAGENO':str(page)}
   raw=fetch_json(SZSE+'?'+urllib.parse.urlencode(p));block=raw[0]
   if block.get('error'):raise ValueError('SZSE_QUERY_ERROR')
   meta=block['metadata'];count=int(meta.get('pagecount',0));expected=int(meta.get('recordcount',0))
   if count>40:raise ValueError('SZSE_PAGE_LIMIT')
   collected.extend(parse_szse(raw))
   if page>=count:break
   page+=1;time.sleep(.1)
  if len(collected)!=expected:raise ValueError('TRUNCATED_SZSE')
  rows.extend(collected);day=stop+timedelta(days=1)
 return merge_rows(rows,[])

def complete_at(bundle,day):
 try:
  return len(bundle['funds'])==4 and all(any(p['date']==day and p['shares'] is not None and p['nav'] is not None for p in f['points']) for f in bundle['funds']) and any(p['date']==day for p in bundle['marketCaps']) and any(p['date']==day for p in bundle.get('indexCloses',[]))
 except (KeyError,TypeError):return False

def can_reuse(bundle,day,now,force):
 return bool(bundle and not force and complete_at(bundle,day) and bundle['sessions'][-1]==day and datetime.fromisoformat(bundle['generatedAt'].replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Shanghai')).date()==now.astimezone(ZoneInfo('Asia/Shanghai')).date())

def collect(root,project,repo,backfill=False,force=False):
 local=datetime.now(ZoneInfo('Asia/Shanghai'));today=local.date();cache=root/'private-cache';cache.mkdir(parents=True,exist_ok=True)
 old=json.loads((root/'latest.json').read_text()) if (root/'latest.json').exists() else None
 raw=fetch_json('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh000300,day,,,400,qfq')
 if raw.get('code')!=0:raise ValueError('INVALID_SESSION_SOURCE')
 data=raw['data']['sh000300'];all_sessions=confirmed_sessions(data.get('day',data.get('qfqday',[])),local)
 start=(today-timedelta(days=366)).isoformat();sessions=[d for d in all_sessions if d>=start]
 if len(sessions)<21:raise ValueError('INSUFFICIENT_SESSIONS')
 # A confirmed dataset is collected once per calendar day, with later automatic retries on failure.
 if can_reuse(old,sessions[-1],local,force or backfill):return old
 prior={f['code']:f['points'] for f in old['funds']} if old else {c:[] for c,_,_ in CORE}
 keys=os.environ.get('MX_APIKEY')
 if not keys:raise ValueError('NO_CAP_CREDENTIAL')
 client=MXClient(keys,cache/'mx',force=True)
 refresh_start=sessions[0] if not old or backfill else max(sessions[0],min(old['sessions'][-1],sessions[max(0,len(sessions)-10)]))
 cap_start=refresh_start
 query=f'沪深300指数000300从{cap_start}至{sessions[-1]}每个交易日的流通市值（普通A股流通市值，非自由流通市值），请按日期返回，单位元或亿元'
 caps=merge_rows(old['marketCaps'] if old else [],parse_caps(client.query(query)))
 need=[d for d in sessions if d in sessions[-5:] or not all(any(p['date']==d and p['shares'] is not None for p in prior[c]) for c,_,e in CORE if e=='SSE')]
 sse={c:[] for c,_,e in CORE if e=='SSE'}
 with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
  for result in pool.map(lambda d:sse_day(d,cache,refresh=d in sessions[-5:]),need):
   for c,rows in result.items():sse[c].extend(rows)
 sz_start=refresh_start
 sz=szse_range(sz_start,sessions[-1]);funds=[]
 cli=project/'tools/npm-global/node_modules/@hithink-tech/hithink-finance-cli/dist/cli/main.js'
 if not cli.is_file():raise ValueError('NAV_CLI_UNAVAILABLE')
 for code,name,exchange in CORE:
  command=['/usr/local/bin/node',str(cli),'fund','nav','--thscode',code,'--range','year','--nav-type','unit','--format','json']
  result=subprocess.run(command,capture_output=True,timeout=50)
  if result.returncode or len(result.stdout)>2000000:raise ValueError('NAV_UNAVAILABLE')
  nav=parse_nav(json.loads(result.stdout));share_rows=sse[code] if exchange=='SSE' else sz
  q={p['date']:p['shares'] for p in prior[code]};q.update({r['date']:r['shares'] for r in share_rows})
  n={p['date']:p['nav'] for p in prior[code]};n.update({r['date']:r['nav'] for r in nav})
  funds.append({'code':code,'name':name,'exchange':exchange,'points':[{'date':d,'shares':q.get(d),'nav':n.get(d),'splitFactor':None} for d in sessions]})
 b={'schemaVersion':'etf-observation-v1','capBasis':'circulating-a-share','generatedAt':datetime.now(ZoneInfo('UTC')).isoformat(timespec='seconds'),'sessions':sessions,'indexCloses':[{'date':r[0],'value':num(r[2])} for r in data.get('day',data.get('qfqday',[])) if r[0] in sessions],'funds':funds,'marketCaps':[r for r in caps if r['date'] in sessions],
 'sources':[{'id':'SSE','url':'https://www.sse.com.cn/market/funddata/volumn/etfvolumn/'},{'id':'SZSE','url':'https://www.szse.cn/market/fund/volume/etf/index.html'},{'id':'Hithink','url':'https://fund.10jqka.com.cn/'},{'id':'MX','url':'https://data.eastmoney.com/'},{'id':'Tencent','url':'https://gu.qq.com/','note':'沪深300日收盘，用于交易日对齐和净值异常过滤，不用于推算流通市值'}],
 'notes':['净申赎为近似：缺前日净值或相对沪深300日收益偏差超过0.5个百分点时暂停估算，待核实折算、分红或来源差异；微小折算仍可能无法识别。','份额按交易所统计日对齐；深交所T日份额以T+1早间更新为准，本卡仅使用已跨日数据。','规模=核心4只ETF份额×同日单位净值；分母为妙想沪深300指数流通市值SHRMARKETVALUEM（元），不含自由流通口径。']}
 if not complete_at(b,sessions[-1]):raise ValueError('WAITING_FOR_CONFIRMED_DATA')
 temp=root/'candidate.json';atomic(temp,b)
 check="import{readFileSync}from'node:fs';import{deriveEtfObservation}from'./src/features/etf-observation/model.mjs';const v=deriveEtfObservation(JSON.parse(readFileSync(process.argv[1],'utf8')));if(v.series.filter(p=>p.ratioPct!==null).length<21||!v.date)process.exit(2);console.log(JSON.stringify({date:v.date,ratioPoints:v.series.filter(p=>p.ratioPct!==null).length,ratioPct:v.ratioPct}));"
 result=subprocess.run(['/usr/local/bin/node','--input-type=module','-e',check,str(temp)],cwd=repo,capture_output=True,timeout=15)
 if result.returncode:raise ValueError('INVALID_DERIVED_HISTORY')
 if old:atomic(root/'previous.json',old)
 atomic(root/'latest.json',b);return b

def publish(bundle,url,token):
 u=urllib.parse.urlparse(url)
 if u.scheme!='https' or (u.hostname!='newsmonitor.pages.dev' and not (u.hostname or '').endswith('.newsmonitor.pages.dev')) or u.port not in (None,443) or u.path!='/api/market-radar/etf' or u.username or u.password or u.query or u.fragment:raise ValueError('INVALID_PUBLISH_DESTINATION')
 if not token:raise ValueError('NO_PUBLISH_CREDENTIAL')
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):raise ValueError('REDIRECT_DENIED')
 import certifi
 opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
 req=urllib.request.Request(url,data=json.dumps(bundle,ensure_ascii=False,separators=(',',':')).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token,'User-Agent':'FinanceMonitorMarketDashboard/1.0','Accept':'application/json'},method='POST')
 with opener.open(req,timeout=45) as response:reply=json.load(response)
 if reply.get('ok') is not True:raise ValueError('PUBLICATION_FAILED')

def main():
 project=Path(os.environ.get('MARKET_DASHBOARD_PROJECT_ROOT',Path.home()/'Codex/Financial Knowledge Repository'));repo=Path(__file__).resolve().parents[2]
 parser=argparse.ArgumentParser();parser.add_argument('--state-root',type=Path,default=project/'state/etf-observation');parser.add_argument('--backfill',action='store_true');parser.add_argument('--force',action='store_true');parser.add_argument('--publish-only',action='store_true');parser.add_argument('--no-publish',action='store_true');parser.add_argument('--url',default='https://newsmonitor.pages.dev/api/market-radar/etf');args=parser.parse_args();root=args.state_root.resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (root/'service.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('{"status":"already_running"}');return 0
  try:
   local=datetime.now(ZoneInfo('Asia/Shanghai'));marker=root/'attempt.json'
   if not args.force and not args.publish_only:
    if not 9<=local.hour<=23:return 0
    if marker.exists() and time.time()-marker.stat().st_mtime<3600:return 0
   if not args.publish_only:atomic(marker,{'at':local.isoformat()})
   b=json.loads((root/'latest.json').read_text()) if args.publish_only else collect(root,project,repo,args.backfill,args.force)
   if args.no_publish:print(json.dumps({'status':'collected','marketDate':b['sessions'][-1]}));return 0
   digest=hashlib.sha256(json.dumps(b,sort_keys=True).encode()).hexdigest();pub=root/'published.json';previous=json.loads(pub.read_text()) if pub.exists() else {}
   if previous.get('digest')==digest and previous.get('url')==args.url and not args.force:return 0
   publish(b,args.url,os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN',''));atomic(pub,{'digest':digest,'url':args.url,'marketDate':b['sessions'][-1]});print(json.dumps({'status':'published','marketDate':b['sessions'][-1]}));return 0
  except Exception as error:
   # Never print raw network/CLI responses or credential-bearing exceptions.
   print(json.dumps({'status':'etf_observation_failed','safeError':str(error) if str(error) in ['WAITING_FOR_CONFIRMED_DATA','PUBLIC_SOURCE_UNAVAILABLE','INVALID_DERIVED_HISTORY','NO_CAP_CREDENTIAL','NAV_UNAVAILABLE','INVALID_CAP_BASIS','NO_PUBLISH_CREDENTIAL'] else type(error).__name__}));return 1
if __name__=='__main__':raise SystemExit(main())
