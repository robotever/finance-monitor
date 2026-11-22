"""Daily-close radar input collector/publisher, isolated from sector services."""
import argparse
from datetime import datetime, timedelta
import fcntl
import hashlib
import json
import os
from pathlib import Path
import ssl
import subprocess
import sys
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo

def should_collect(now,pending=False):
 local=now.astimezone(ZoneInfo('Asia/Shanghai'))
 minute=local.hour*60+local.minute
 return local.weekday()<5 and 15*60+20<=minute<=22*60+30 or pending and 8*60+30<=minute<=9*60+15

def pending_inputs(root,expected_date=None):
 try:
  from .radar_inputs import OBJECTS,funding_complete
  p=json.loads((root/'latest.json').read_text())
  if expected_date and p.get('marketDate','')<expected_date:return True
  if set(p.get('objects',{}))!=set(OBJECTS):return True
  for o in p['objects'].values():
   r=o.get('history',[])[-1] if o.get('history') else {}
   if r.get('date')!=p['marketDate'] or any(r.get(k) is None for k in ['up','down','flat']) or not funding_complete(r):return True
  return False
 except Exception:return True

def expected_session(root,now):
 """One verified exchange-calendar read per Shanghai day, only for recovery."""
 local=now.astimezone(ZoneInfo('Asia/Shanghai'));today=local.date().isoformat();cache=root/'trading-calendar.json'
 try:
  previous=json.loads(cache.read_text()) if cache.exists() else {}
  if previous.get('checkedDate')!=today:
   from .radar_inputs import CLI
   r=subprocess.run([str(CLI),'market','calendar','--format','json'],capture_output=True,text=True,timeout=30)
   raw=json.loads(r.stdout)
   if not raw.get('ok'):return None
   dates=sorted({datetime.strptime(row['date'],'%Y%m%d').date().isoformat() for row in raw['data']['item']})
   if len(dates)<50:return None
   previous={'checkedDate':today,'dates':dates};temp=cache.with_suffix('.pending');temp.write_text(json.dumps(previous));temp.chmod(0o600);temp.replace(cache)
  cutoff=today if local.hour*60+local.minute>=15*60+20 else (local.date()-timedelta(days=1)).isoformat()
  return max((d for d in previous['dates'] if d<=cutoff),default=None)
 except Exception:return None

def content_digest(payload):
 return hashlib.sha256(json.dumps({k:v for k,v in payload.items() if k!='observedAt'},sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

class NoRedirect(urllib.request.HTTPRedirectHandler):
 def redirect_request(self,*args,**kwargs):return None

def publish(payload,url,token):
 from urllib.parse import urlparse
 u=urlparse(url)
 if u.scheme!='https' or u.hostname!='newsmonitor.pages.dev' and not (u.hostname or '').endswith('.newsmonitor.pages.dev') or u.username or u.password or u.path!='/api/market-radar/inputs':raise ValueError('INVALID_PUBLISH_DESTINATION')
 if not token:raise ValueError('NO_PUBLISH_CREDENTIAL')
 try:
  import certifi
  context=ssl.create_default_context(cafile=certifi.where())
 except ImportError:context=ssl.create_default_context()
 opener=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=context))
 req=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token,'User-Agent':'FinanceMonitorMarketDashboard/1.0','Accept':'application/json'},method='POST')
 with opener.open(req,timeout=40) as response:result=json.load(response)
 if result.get('ok') is not True:raise ValueError('PUBLICATION_FAILED')

def main():
 p=argparse.ArgumentParser();project=Path(os.environ.get('MARKET_DASHBOARD_PROJECT_ROOT',Path(__file__).resolve().parents[3]))
 p.add_argument('--state-root',type=Path,default=project/'state/market-radar-inputs');p.add_argument('--project-root',type=Path,default=project)
 p.add_argument('--publish-only',action='store_true');p.add_argument('--force',action='store_true');p.add_argument('--url',default='https://newsmonitor.pages.dev/api/market-radar/inputs')
 args=p.parse_args();root=args.state_root.resolve();root.mkdir(parents=True,exist_ok=True)
 with (root/'service.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print(json.dumps({'status':'already_running'}));return 0
  if not args.publish_only:
   local=datetime.now(ZoneInfo('Asia/Shanghai'));minute=local.hour*60+local.minute
   expected=expected_session(root,local) if 8*60+30<=minute<=9*60+15 else None
   if not args.force and not should_collect(local,pending=pending_inputs(root,expected)):print(json.dumps({'status':'outside_daily_window'}));return 0
   cmd=[sys.executable,'-m','tools.market_dashboard.radar_inputs','--state-root',str(root),'--project-root',str(args.project_root)]
   if args.force:cmd.append('--force')
   try:r=subprocess.run(cmd,capture_output=True,text=True,timeout=2400)
   except subprocess.TimeoutExpired:print(json.dumps({'status':'collection_timeout'}));return 1
   if r.returncode:print(json.dumps({'status':'collection_failed'}));return 1
  try:
   payload=json.loads((root/'latest.json').read_text());digest=content_digest(payload);marker=root/'published.json'
   previous=json.loads(marker.read_text()) if marker.exists() else {}
   if not args.force and previous.get('digest')==digest and previous.get('url')==args.url:print(json.dumps({'status':'unchanged','marketDate':payload['marketDate']}));return 0
   publish(payload,args.url,os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN',''))
   temp=root/'published.pending';temp.write_text(json.dumps({'digest':digest,'url':args.url,'marketDate':payload['marketDate']}));temp.replace(marker)
   print(json.dumps({'status':'published','marketDate':payload['marketDate']}));return 0
  except urllib.error.HTTPError as e:
   try:code=json.loads(e.read()).get('error')
   except Exception:code=None
   safe=code if code in ['UNAUTHORIZED','INVALID_RADAR_INPUTS','OBSOLETE_INPUTS','SERVICE_UNAVAILABLE','STORAGE_UNAVAILABLE'] else 'HTTP_ERROR'
   print(json.dumps({'status':'publication_failed','httpStatus':e.code,'safeError':safe}));return 1
  except Exception:print(json.dumps({'status':'publication_failed'}));return 1
if __name__=='__main__':raise SystemExit(main())
