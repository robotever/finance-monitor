#!/usr/bin/env python3
"""Independent market-observation scheduler; no existing jobs are altered."""
import argparse,os,plistlib,subprocess
from pathlib import Path

def main():
 p=argparse.ArgumentParser();p.add_argument('--enable',action='store_true');p.add_argument('--repo',type=Path,default=Path.home()/'Codex/Financial Knowledge Repository/finance-monitor');p.add_argument('--project-root',type=Path,default=Path.home()/'Codex/Financial Knowledge Repository');a=p.parse_args();repo=a.repo.resolve();project=a.project_root.resolve()
 if not (repo/'tools/market_dashboard/market_observation_service.py').is_file():raise SystemExit('Stable project is missing market observation collector')
 label='com.robot-ever.finance-monitor.market-observation';logs=project/'logs/market-observation';logs.mkdir(parents=True,exist_ok=True,mode=0o700)
 spec={'Label':label,'ProgramArguments':['/bin/bash',str(repo/'ops/macos/run-market-dashboard.sh'),'--market-observation'],'EnvironmentVariables':{'MARKET_DASHBOARD_PROJECT_ROOT':str(project),'MARKET_DASHBOARD_PYTHON':'/Library/Frameworks/Python.framework/Versions/3.13/bin/python3','PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},'RunAtLoad':True,'KeepAlive':False,'StartInterval':300,'ProcessType':'Background','StandardOutPath':str(logs/'launchd.log'),'StandardErrorPath':str(logs/'launchd.log')}
 target=Path.home()/'Library/LaunchAgents'/f'{label}.plist'
 if target.exists():target.with_suffix('.plist.bak').write_bytes(target.read_bytes())
 tmp=target.with_suffix('.plist.pending');tmp.write_bytes(plistlib.dumps(spec));tmp.chmod(0o600);tmp.replace(target);subprocess.run(['plutil','-lint',str(target)],check=True,capture_output=True)
 if a.enable:
  domain=f'gui/{os.getuid()}';job=domain+'/'+label
  if subprocess.run(['launchctl','print',job],capture_output=True).returncode==0:subprocess.run(['launchctl','bootout',job],check=True,capture_output=True)
  subprocess.run(['launchctl','enable',job],check=True,capture_output=True);subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True,capture_output=True)
 print('Market observation service '+('enabled' if a.enable else 'prepared')+'.')
if __name__=='__main__':main()
