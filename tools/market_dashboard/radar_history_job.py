"""Explicit, resumable historical input reconstruction; never changes score weights."""
import argparse
import concurrent.futures
import csv
from datetime import datetime
import fcntl
import json
import io
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.request
import urllib.parse
import ssl
from zoneinfo import ZoneInfo
from .radar_inputs import OBJECTS,CLI,atomic_json,constituents,parse_current_suspensions
from .radar_fund_history import HistoryClient
from .radar_style_backfill import backfill_bundle
from .radar_input_service import content_digest


def read_panel(path):
 rows=[]
 for r in csv.DictReader(io.StringIO(Path(path).read_text())):
  if not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',r['thscode']):raise ValueError('Invalid panel security')
  rows.append({'code':r['thscode'],'date':r['date'],'close':float(r['close']) if r['close'] else None,'volume':float(r['volume']) if r['volume'] else None,'turnover':float(r['amount']) if r['amount'] else None})
 return rows


def commit_candidate(root,expected_digest,bundle):
 """Take the daily publisher's lock and reject concurrent data changes."""
 root=Path(root)
 with (root/'service.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:raise RuntimeError('COLLECTOR_BUSY') from None
  current=json.loads((root/'latest.json').read_text())
  if content_digest(current)!=expected_digest:raise RuntimeError('BASE_CHANGED')
  stamp=datetime.now(ZoneInfo('UTC')).strftime('%Y%m%dT%H%M%S%f')
  atomic_json(root/f'latest.pre-history-{stamp}.json',current)
  atomic_json(root/'latest.json',bundle)


def token(project):
 value=os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN')
 if value:return value
 for raw in (Path(project)/'.env').read_text().splitlines():
  line=raw.strip().removeprefix('export ');key,sep,value=line.partition('=')
  if sep and key.strip()=='MARKET_DASHBOARD_PUBLISH_TOKEN':
   value=value.strip()
   if value.startswith(('"',"'")):
    end=value.find(value[0],1)
    if end<0:raise ValueError('Invalid credential configuration')
    return value[1:end]
   return re.split(r'\s+#',value)[0].strip()
 raise ValueError('No history transport credential')


def verify_dates(dates,market_date):
 if not isinstance(dates,list) or len(dates)!=7 or any(not isinstance(d,str) or datetime.strptime(d,'%Y-%m-%d').date().isoformat()!=d for d in dates):raise ValueError('Invalid historical session dates')
 if dates!=sorted(set(dates)) or dates[-1]!=market_date:raise ValueError('Need seven actual sessions ending at the validated latest date')
 return dates


def prepare(root,base,project):
 meta=root/'metadata.json'
 if meta.exists() and json.loads(meta.read_text()).get('marketDate')!=base['marketDate']:raise RuntimeError('HISTORY_STATE_TARGET_CHANGED: choose a new job directory')
 atomic_json(meta,{'marketDate':base['marketDate']})
 member_file=root/'members.json'
 if member_file.exists():members=json.loads(member_file.read_text())
 else:
  members={}
  for key,(name,aliases,code,count) in OBJECTS.items():
   if not code:continue
   codes,asof,source=constituents(code,count);members[key]={'members':sorted(codes),'asOf':asof,'source':source,'scope':name}
  atomic_json(member_file,members)
 for key,o in members.items():
  if key not in OBJECTS or len(o['members'])!=OBJECTS[key][3] or len(set(o['members']))!=len(o['members']) or any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',c) for c in o['members']):raise ValueError('Invalid frozen membership')
 if set(members)!=set(OBJECTS)-{'ashare'}:raise ValueError('Incomplete style membership')
 dates_file=root/'dates.json'
 if dates_file.exists():dates=json.loads(dates_file.read_text())
 else:
  result=subprocess.run([str(CLI),'market','calendar','--format','json'],capture_output=True,text=True,timeout=45)
  raw=json.loads(result.stdout)
  if result.returncode or not raw.get('ok'):raise RuntimeError('CALENDAR_UNAVAILABLE')
  days=sorted({datetime.strptime(r['date'],'%Y%m%d').date().isoformat() for r in raw['data']['item']})
  dates=[d for d in days if d<=base['marketDate']][-7:];atomic_json(dates_file,dates)
 verify_dates(dates,base['marketDate'])
 panel_file=root/'panel.csv'
 if not panel_file.exists():
  codes=sorted({c for o in members.values() for c in o['members']});identities=','.join("'"+c+"'" for c in codes)
  sql=f"SELECT thscode,date,close,volume,amount FROM v_daily_qfq WHERE thscode IN ({identities}) AND date BETWEEN '{dates[0]}' AND '{dates[-1]}' ORDER BY date,thscode"
  r=subprocess.run([str(CLI),'--db',str(Path(project)/'data/hithink/market.duckdb'),'db','export','--sql',sql,'--output',str(panel_file),'--file-format','csv','--format','json'],capture_output=True,text=True,timeout=180)
  if r.returncode:raise RuntimeError('LOCAL_PANEL_EXPORT_FAILED')
 return members,dates,read_panel(panel_file)


def exclusions(root,base,members,dates):
 path=root/'exclusions.json'
 # This evidence is tied to an immutable past reconstruction window, not reused by daily collection.
 if path.exists():return json.loads(path.read_text())
 params=urllib.parse.urlencode({'mkt':'1','st':'SUSPEND_START_DATE','sr':'-1','fd':base['marketDate']})
 req=urllib.request.Request('https://datapc.eastmoney.com/emdatacenter/tfg/list2?'+params,headers={'User-Agent':'Mozilla/5.0','Referer':'https://datapc.eastmoney.com/'})
 try:
  import certifi
  context=ssl.create_default_context(cafile=certifi.where())
  with urllib.request.urlopen(req,timeout=30,context=context) as response:raw=json.load(response)
 except Exception:raw=None
 out={}
 config_path=Path(__file__).resolve().parents[2]/'config/radar-confirmed-nontrading.json'
 config=json.loads(config_path.read_text()) if config_path.exists() else {}
 for day in dates:
  known=set(config.get(day,{}).get('small',{}).get('members',[]))
  if raw and not known:
   breadth=next((r for r in base['objects']['small']['history'] if r['date']==day),None)
   try:known=parse_current_suspensions(raw,set(members['small']['members']),day,breadth,datetime.now(ZoneInfo('Asia/Shanghai')))
   except Exception:pass
  out[day]=sorted(known)
 atomic_json(path,out)
 if raw:atomic_json(root/'suspensions-raw.json',raw)
 return out


def download(client,codes,root):
 lock=threading.Lock();last=[0.0];stopped=threading.Event();failed=[];flow={};consecutive=[0]
 def one(code):
  if stopped.is_set():return code,None,'stopped'
  if not (client.cache/(code+'.json')).exists():
   with lock:
    time.sleep(max(0,.6-(time.monotonic()-last[0])));last[0]=time.monotonic()
  try:return code,client.get(code),None
  except Exception as e:return code,None,str(e)[:100]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
  for n,(code,rows,error) in enumerate(pool.map(one,sorted(codes)),1):
   if error:
    failed.append({'code':code,'error':error});consecutive[0]+=1
    if any(str(status) in error for status in [401,403,429]) or consecutive[0]>=8:stopped.set()
   else:flow[code]=rows;consecutive[0]=0
   if n%50==0 or n==len(codes):
    atomic_json(root/'progress.json',{'done':n,'total':len(codes),'success':len(flow),'failed':failed,'stopped':stopped.is_set()})
    print(json.dumps({'historyDone':n,'total':len(codes),'success':len(flow),'failed':len(failed)}),flush=True)
 return flow,failed


def main():
 p=argparse.ArgumentParser(description=__doc__);project=Path(os.environ.get('MARKET_DASHBOARD_PROJECT_ROOT',Path.home()/'Codex/Financial Knowledge Repository'))
 p.add_argument('--project-root',type=Path,default=project);p.add_argument('--state-root',type=Path,default=project/'state/market-radar-inputs')
 p.add_argument('--job-root',type=Path,required=True);p.add_argument('--cache-root',type=Path);p.add_argument('--base-url',default='https://newsmonitor.pages.dev');p.add_argument('--commit',action='store_true')
 a=p.parse_args();root=a.job_root.resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (root/'job.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('HISTORY_JOB_BUSY');return 1
  base=json.loads((a.state_root/'latest.json').read_text());digest=content_digest(base)
  members,dates,panel=prepare(root,base,a.project_root);proof=exclusions(root,base,members,dates[1:])
  active={r['code'] for r in panel if r['date'] in dates[1:] and r['volume'] and r['turnover'] and r['volume']>0 and r['turnover']>0}
  client=HistoryClient(a.cache_root or root/'private-history',a.base_url,token(a.project_root))
  flow,failures=download(client,active,root)
  bundle,report=backfill_bundle(base,members,panel,flow,dates[1:],proof)
  report['transportFailures']=failures
  bundle['observedAt']=datetime.now(ZoneInfo('UTC')).isoformat()
  atomic_json(root/'candidate.json',bundle);atomic_json(root/'verification.json',report)
  if not report['ready']:print(json.dumps({'ready':False,'styles':report['whole']['stylesReady'],'report':str(root/'verification.json')}));return 1
  if a.commit:commit_candidate(a.state_root,digest,bundle)
  print(json.dumps({'ready':True,'styles':6,'marketDate':bundle['marketDate'],'committed':a.commit,'candidate':str(root/'candidate.json')}));return 0
if __name__=='__main__':raise SystemExit(main())
