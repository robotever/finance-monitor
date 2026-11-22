#!/usr/bin/env python3
"""Install/open the private Mac board without Codex or external network access."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys
import time
from urllib.request import build_opener,ProxyHandler

LABEL='com.robot-ever.finance-monitor.local-board'
URL='http://127.0.0.1:5184/'
APP_NAME='Finance Monitor 本地看板.app'


def service_plist(repo,node,logs):
    return dict(Label=LABEL,ProgramArguments=[node,str(repo/'tools/market_dashboard/hithink_preview_server.mjs')],
        WorkingDirectory=str(repo),RunAtLoad=True,KeepAlive=True,ThrottleInterval=10,
        ProcessType='Background',LimitLoadToSessionType='Aqua',Umask=0o077,
        EnvironmentVariables={'PATH':'/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        StandardOutPath=str(logs/'local-board.log'),StandardErrorPath=str(logs/'local-board-error.log'))


def desktop_launcher(repo,python):
    return '#!/bin/bash\nexec '+shlex.quote(python)+' '+shlex.quote(str(repo/'ops/macos/install-local-board-service.py'))+' --repo-root '+shlex.quote(str(repo))+' --open\n'


def is_local_board_html(content):
    return b'/@id/virtual:hithink-preview' in content or b'/src/main.ts' in content and b'Finance Monitor' in content


def ready():
    try:
        # This connection must not depend on HTTP_PROXY, HTTPS_PROXY or Codex.
        with build_opener(ProxyHandler({})).open(URL,timeout=2) as response:
            return response.status==200 and is_local_board_html(response.read(100000))
    except Exception:return False


def launchctl(*args):
    return subprocess.run(['/bin/launchctl',*args],capture_output=True,text=True,timeout=15)


def write(path,content,mode=0o600):
    path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists() and path.read_bytes()!=content:
        backup=path.with_name(path.name+'.previous')
        if not backup.exists():shutil.copy2(path,backup)
    temp=path.with_name(path.name+'.pending')
    temp.write_bytes(content);temp.chmod(mode);temp.replace(path)


def install(repo):
    node=shutil.which('node');python=shutil.which('python3')
    if not node or not python:raise RuntimeError('本地运行环境未找到')
    if not (repo/'node_modules/vite').exists() or not (repo/'tools/market_dashboard/hithink_preview_server.mjs').exists():raise RuntimeError('本地看板文件不完整')
    if not (repo/'data/market-dashboard/hithink-live/current-snapshot.json').is_file():raise RuntimeError('未找到本地已采集数据，请使用正在运行的数据项目目录')
    home=Path.home();logs=home/'Library/Logs/Finance Monitor';logs.mkdir(parents=True,exist_ok=True)
    logs.chmod(0o700)
    for name in ['local-board.log','local-board-error.log']:
        path=logs/name;path.touch(exist_ok=True);path.chmod(0o600)
    plist=home/'Library/LaunchAgents'/f'{LABEL}.plist'
    app=home/'Desktop'/APP_NAME;info=app/'Contents/Info.plist'
    if app.exists() and (not info.exists() or plistlib.loads(info.read_bytes()).get('CFBundleIdentifier')!=LABEL):raise RuntimeError('桌面存在同名应用，请先保留原文件后重试')
    write(plist,plistlib.dumps(service_plist(repo,node,logs)))
    write(info,plistlib.dumps(dict(CFBundleIdentifier=LABEL,CFBundleName='Finance Monitor 本地看板',CFBundleDisplayName='Finance Monitor 本地看板',CFBundleExecutable='open-local-board',CFBundlePackageType='APPL',CFBundleVersion='1',LSUIElement=True,NSHighResolutionCapable=True)))
    write(app/'Contents/MacOS/open-local-board',desktop_launcher(repo,python).encode(),0o755)
    note=("Finance Monitor 本地看板\n\n"
        "平常打开：双击桌面上的“Finance Monitor 本地看板.app”。\n"
        "不需要打开 Codex，也不需要代理；入口会检查并启动本地服务。\n"
        "登录 Mac 后服务自动运行，关闭浏览器不会停止服务。\n\n"
        f"备用地址：{URL}\n"
        "可以将这个地址加入浏览器书签；仅适用于这台 Mac。\n\n"
        "本地完整首页包括全球联动、市场研究雷达、跨市场风险、财经快讯和板块研究。\n"
        "数据以页面时间为准：网络中断时可以查看已采集的数据；海外来源可能受网络影响；离线数据会标明保存时间，过期新闻只放入存档。\n"
        "如果入口未打开，可以稍后再次双击。后台日志在用户资源库的 Logs/Finance Monitor 文件夹中。\n")
    write(home/'Desktop/Finance Monitor 本地说明.txt',note.encode())
    domain=f'gui/{os.getuid()}'
    if launchctl('print',f'{domain}/{LABEL}').returncode==0:
        launchctl('bootout',f'{domain}/{LABEL}')
        for _ in range(30):
            if launchctl('print',f'{domain}/{LABEL}').returncode!=0:break
            time.sleep(.1)
    result=launchctl('bootstrap',domain,str(plist))
    if result.returncode!=0:raise RuntimeError('登录启动服务未能加载')
    return dict(app=str(app),plist=str(plist),url=URL,loginAutoStart=True)


def open_board(repo):
    domain=f'gui/{os.getuid()}';service=f'{domain}/{LABEL}'
    if not ready():
        if launchctl('print',service).returncode!=0:
            plist=Path.home()/'Library/LaunchAgents'/f'{LABEL}.plist'
            if not plist.exists():install(repo)
            elif launchctl('bootstrap',domain,str(plist)).returncode!=0:raise RuntimeError('本地服务未能加载')
        launchctl('kickstart',service)
        for attempt in range(60):
            if ready():break
            if attempt==30:launchctl('kickstart','-k',service)
            time.sleep(.5)
        else:raise RuntimeError('本地看板尚未就绪，请稍后双击重试')
    subprocess.run(['/usr/bin/open',URL],check=True,timeout=10)
    return dict(opened=True,url=URL)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[2])
    p.add_argument('--install',action='store_true');p.add_argument('--open',action='store_true')
    args=p.parse_args();repo=args.repo_root.resolve()
    try:
        if args.install:result=install(repo)
        elif args.open:result=open_board(repo)
        else:p.error('choose --install or --open')
        print(json.dumps(result,ensure_ascii=False))
    except Exception as error:
        if args.open:
            subprocess.run(['/usr/bin/osascript','-e','display alert "本地看板暂未打开" message "请稍后再双击桌面入口。若仍打不开，可查看用户资源库 Logs/Finance Monitor 中的本地日志。" as warning'],capture_output=True,timeout=30)
        print(str(error),file=sys.stderr);return 1
    return 0

if __name__=='__main__':raise SystemExit(main())
