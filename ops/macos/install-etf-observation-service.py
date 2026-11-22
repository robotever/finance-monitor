#!/usr/bin/env python3
"""Install isolated daily ETF observation; existing sector/radar services untouched."""
import argparse,os,plistlib,subprocess
from pathlib import Path

def build_spec(repo,project,python):
 logs=project/'logs/etf-observation'
 return {'Label':'com.robot-ever.finance-monitor.etf-observation','ProgramArguments':['/bin/bash',str(repo/'ops/macos/run-market-dashboard.sh'),'--etf-observation'],'EnvironmentVariables':{'MARKET_DASHBOARD_PROJECT_ROOT':str(project),'MARKET_DASHBOARD_PYTHON':python,'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},'StartInterval':1800,'RunAtLoad':True,'KeepAlive':False,'ProcessType':'Background','StandardOutPath':str(logs/'launchd.log'),'StandardErrorPath':str(logs/'launchd.log')}

def main():
 p=argparse.ArgumentParser();p.add_argument('--enable',action='store_true');p.add_argument('--repo',type=Path,default=Path.home()/'Codex/Financial Knowledge Repository/finance-monitor');p.add_argument('--project-root',type=Path,default=Path.home()/'Codex/Financial Knowledge Repository');p.add_argument('--python',default='/Library/Frameworks/Python.framework/Versions/3.13/bin/python3');a=p.parse_args();repo=a.repo.resolve();project=a.project_root.resolve()
 if not (repo/'tools/market_dashboard/etf_observation_job.py').is_file():raise SystemExit('Missing ETF collector in stable checkout')
 logs=project/'logs/etf-observation';logs.mkdir(parents=True,exist_ok=True,mode=0o700)
 spec=build_spec(repo,project,a.python);target=Path.home()/'Library/LaunchAgents'/f"{spec['Label']}.plist"
 if target.exists():target.with_suffix('.plist.bak').write_bytes(target.read_bytes())
 temp=target.with_suffix('.plist.pending');temp.write_bytes(plistlib.dumps(spec));temp.chmod(0o600);temp.replace(target)
 subprocess.run(['plutil','-lint',str(target)],check=True,capture_output=True)
 if a.enable:
  domain=f'gui/{os.getuid()}';job=domain+'/'+spec['Label']
  if subprocess.run(['launchctl','print',job],capture_output=True).returncode==0:subprocess.run(['launchctl','bootout',job],check=True,capture_output=True)
  subprocess.run(['launchctl','enable',job],check=True,capture_output=True);subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True,capture_output=True)
 print('ETF daily observation service '+('enabled' if a.enable else 'prepared')+'.')
if __name__=='__main__':main()
