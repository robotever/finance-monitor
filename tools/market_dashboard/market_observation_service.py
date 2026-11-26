"""Isolated, locked 15-minute collector and authenticated derived-data publisher."""
import argparse,fcntl,hashlib,json,os,re,ssl,subprocess,time,urllib.parse,urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from .etf_observation_job import atomic
from .market_observation_data import collect_observation

def bucket(now):
 local=now.astimezone(ZoneInfo('Asia/Shanghai'));minute=local.hour*60+local.minute
 if local.weekday()>=5 or not (575<=minute<=695 or 780<=minute<=935 or 960<=minute<=975):return None
 return local.strftime('%Y-%m-%dT')+f'{minute//60:02}:{minute%60//15*15:02}'

def publish(payload,url,token):
 u=urllib.parse.urlparse(url)
 if u.scheme!='https' or (u.hostname!='newsmonitor.pages.dev' and not (u.hostname or '').endswith('.newsmonitor.pages.dev')) or u.port not in (None,443) or u.path!='/api/market-observation' or u.query or u.fragment or u.username or u.password:raise ValueError('INVALID_PUBLISH_DESTINATION')
 if not token:raise ValueError('NO_PUBLISH_CREDENTIAL')
 class NoRedirect(urllib.request.HTTPRedirectHandler):
  def redirect_request(self,*args,**kwargs):raise ValueError('REDIRECT_DENIED')
 import certifi
 op=urllib.request.build_opener(NoRedirect(),urllib.request.HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
 req=urllib.request.Request(url,data=json.dumps(payload,ensure_ascii=False,separators=(',',':')).encode(),headers={'Content-Type':'application/json','Accept':'application/json','Authorization':'Bearer '+token,'User-Agent':'FinanceMonitorMarketDashboard/1.0'},method='POST')
 with op.open(req,timeout=45) as r:reply=json.load(r)
 if reply.get('ok') is not True:raise ValueError('PUBLICATION_FAILED')

def validate_file(path,repo):
 script="import{readFileSync}from'node:fs';import{validateMarketObservation}from'./src/features/market-observation/model.mjs';const p=validateMarketObservation(JSON.parse(readFileSync(process.argv[1],'utf8')));console.log(JSON.stringify({marketDate:p.marketDate,snapshotAt:p.snapshotAt}));"
 r=subprocess.run(['/usr/local/bin/node','--input-type=module','-e',script,str(path)],cwd=repo,capture_output=True,timeout=15)
 if r.returncode:raise ValueError('INVALID_MARKET_OBSERVATION')

def main():
 project=Path(os.environ.get('MARKET_DASHBOARD_PROJECT_ROOT',Path.home()/'Codex/Financial Knowledge Repository'));repo=Path(__file__).resolve().parents[2]
 p=argparse.ArgumentParser();p.add_argument('--state-root',type=Path,default=project/'state/market-observation');p.add_argument('--force',action='store_true');p.add_argument('--no-publish',action='store_true');p.add_argument('--publish-only',action='store_true');p.add_argument('--url',default='https://newsmonitor.pages.dev/api/market-observation');a=p.parse_args();root=a.state_root.resolve();root.mkdir(parents=True,exist_ok=True,mode=0o700)
 with (root/'service.lock').open('w') as lock:
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('{"status":"already_running"}');return 0
  try:
   slot=bucket(datetime.now(ZoneInfo('Asia/Shanghai')));marker=root/'attempt.json';last=json.loads(marker.read_text()) if marker.exists() else {}
   if not a.force and not a.publish_only:
    if slot is None or last.get('slot')==slot and last.get('ok') is True:return 0
    if marker.exists() and time.time()-marker.stat().st_mtime<120:return 0
   if not a.publish_only:
    atomic(marker,{'slot':slot,'ok':False});data=collect_observation(state_root=root,project_root=project);candidate=root/'candidate.json';atomic(candidate,data);validate_file(candidate,repo)
    latest=root/'latest.json'
    if latest.exists():
     previous=json.loads(latest.read_text());validate_file(latest,repo)
     if data['marketDate']<previous['marketDate'] or datetime.fromisoformat(data['snapshotAt'])<datetime.fromisoformat(previous['snapshotAt']):raise ValueError('OBSOLETE_CAPTURE')
     atomic(root/'previous.json',previous)
    atomic(latest,data)
   else:data=json.loads((root/'latest.json').read_text());validate_file(root/'latest.json',repo)
   if a.no_publish:print(json.dumps({'status':'collected','marketDate':data['marketDate'],'snapshotAt':data['snapshotAt']}));return 0
   digest=hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest();pub=root/'published.json';old=json.loads(pub.read_text()) if pub.exists() else {}
   if old.get('digest')!=digest or old.get('url')!=a.url or a.force:
    publish(data,a.url,os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN',''));atomic(pub,{'digest':digest,'url':a.url,'snapshotAt':data['snapshotAt']})
   if not a.publish_only:atomic(marker,{'slot':slot,'ok':True})
   print(json.dumps({'status':'published','marketDate':data['marketDate'],'snapshotAt':data['snapshotAt']}));return 0
  except Exception as e:
   code=str(e)
   if code=='NON_TRADING_DAY':
    atomic(marker,{'slot':slot,'ok':True});print(json.dumps({'status':'non_trading_day'}));return 0
   safe=code if re.fullmatch(r'[A-Z][A-Z0-9_]*(?::[a-z0-9/_-]+)?',code) else type(e).__name__
   print(json.dumps({'status':'market_observation_failed','safeError':safe}));return 1
if __name__=='__main__':raise SystemExit(main())
