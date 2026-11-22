#!/usr/bin/env python3
"""Install the isolated daily radar collector. Defaults to preparing the plist."""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys

def main():
 p=argparse.ArgumentParser();p.add_argument('--enable',action='store_true');p.add_argument('--repo',type=Path,default=Path.home()/'Codex/Financial Knowledge Repository/finance-monitor');p.add_argument('--project-root',type=Path,default=Path.home()/'Codex/Financial Knowledge Repository');p.add_argument('--python',default='/Library/Frameworks/Python.framework/Versions/3.13/bin/python3');a=p.parse_args()
 repo=a.repo.resolve();root=a.project_root.resolve()
 for rel in ['ops/macos/run-market-dashboard.sh','tools/market_dashboard/radar_inputs.py','tools/market_dashboard/radar_input_service.py']:
  if not (repo/rel).is_file():raise SystemExit('The stable checkout is missing radar files')
 label='com.robot-ever.finance-monitor.market-radar-inputs';logs=root/'logs/market-radar-inputs';logs.mkdir(parents=True,exist_ok=True,mode=0o700);logs.chmod(0o700)
 target=Path.home()/'Library/LaunchAgents'/f'{label}.plist';target.parent.mkdir(parents=True,exist_ok=True)
 spec={'Label':label,'ProgramArguments':['/bin/bash',str(repo/'ops/macos/run-market-dashboard.sh'),'--radar-inputs'],'EnvironmentVariables':{'MARKET_DASHBOARD_PROJECT_ROOT':str(root),'MARKET_DASHBOARD_PYTHON':a.python,'PATH':'/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},'StartInterval':300,'RunAtLoad':False,'KeepAlive':False,'ProcessType':'Background','StandardOutPath':str(logs/'launchd.log'),'StandardErrorPath':str(logs/'launchd.log')}
 if target.exists():target.with_suffix('.plist.bak').write_bytes(target.read_bytes())
 temp=target.with_suffix('.plist.pending');temp.write_bytes(plistlib.dumps(spec));temp.chmod(0o600);temp.replace(target)
 subprocess.run(['plutil','-lint',str(target)],check=True,capture_output=True)
 if a.enable:
  domain=f'gui/{os.getuid()}';job=f'{domain}/{label}'
  if subprocess.run(['launchctl','print',job],capture_output=True).returncode==0:subprocess.run(['launchctl','bootout',job],check=True,capture_output=True)
  subprocess.run(['launchctl','enable',job],check=True,capture_output=True);subprocess.run(['launchctl','bootstrap',domain,str(target)],check=True,capture_output=True)
  subprocess.run(['launchctl','print',job],check=True,capture_output=True)
 print('Radar daily input service '+('enabled' if a.enable else 'prepared')+'. Existing sector services unchanged.')
if __name__=='__main__':main()
