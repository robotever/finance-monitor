"""One collector and one resumable publication loop, dispatched by launchd."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from copy import copy
from contextlib import closing
import fcntl
import importlib.util
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import time

from .hithink_job import run_hithink_cycle, read_committed_snapshot, CLI, CycleBudget, load_complete_close_panel
from .hithink_cli import SHANGHAI, HithinkClient
from .sector_live_publish import LiveTransport, publish_export, _atomic

BASE=Path(__file__).resolve().parents[2]


def publication_health(transport,phase,state,code=None):
    previous=getattr(transport,'deadline',None)
    try:
        if isinstance(transport,LiveTransport):transport.deadline=time.monotonic()+12
        transport(dict(action='health',status=dict(phase=phase,state=state,safeErrorCode=code,
            attemptedAt=datetime.now(timezone.utc).isoformat())))
    except Exception:
        pass  # Failed health transport must not corrupt the last successful dataset.
    finally:
        if isinstance(transport,LiveTransport):transport.deadline=previous


def ensure_awake():
    project=Path(os.environ.get('MARKET_DASHBOARD_PROJECT_ROOT',BASE.parent))
    spec=importlib.util.spec_from_file_location('sector_live_awake',BASE/'ops/macos/market_dashboard_awake.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.ensure_guard(project/'state')
    if sys.platform=='darwin':
        # Renewable AC-only lease bridges overnight idle periods to the next
        # five-minute launchd wake. It expires within eleven minutes after
        # disabling the job, without changing permanent power preferences.
        subprocess.Popen(['/usr/bin/caffeinate','-s','-t','660'],stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,close_fds=True)


def archive_stock_close(args,root,day,*,loader=load_complete_close_panel):
    """Refresh constituent daily history even when timely close already succeeded.

    Does not relabel/recompute that successful score or change its availability.
    Failure leaves the existing panel and publication untouched for a later wake.
    """
    marker=root/'hithink-live/stock-close-archive.json'
    prior=json.loads(marker.read_text()) if marker.exists() else {}
    if prior.get('marketDate')==day and prior.get('status')=='success':return
    try:
        budget=CycleBudget(20,240);client=HithinkClient(args.cli,runner=budget.runner)
        with closing(sqlite3.connect((root/'sector-history.sqlite3').as_uri()+'?mode=ro',uri=True)) as store:
            symbols={r[0] for r in store.execute('SELECT DISTINCT m.stock_id FROM sector_membership_snapshot m '
                'JOIN (SELECT sector_id,max(membership_date) AS day FROM sector_membership_snapshot '
                'WHERE membership_date<=? AND membership_version=? GROUP BY sector_id) latest '
                'ON latest.sector_id=m.sector_id AND latest.day=m.membership_date '
                'WHERE m.membership_version=?',(day,'sector-membership-ths-v1','sector-membership-ths-v1'))
                if re.fullmatch(r'[0-9]{6}\.(SH|SZ|BJ)',r[0])}
        if not symbols:raise ValueError('NO_MEMBERSHIPS')
        loader(budget,client,args.stock_db,symbols,day,day,root/'hithink-breadth/live-panel.csv')
        _atomic(marker,dict(marketDate=day,status='success',archivedAt=datetime.now(timezone.utc).isoformat()))
    except Exception:
        _atomic(marker,dict(marketDate=day,status='failed',safeErrorCode='STOCK_ARCHIVE_INCOMPLETE'))


def run_service(args,*,collector=run_hithink_cycle,exporter=None,transport=None,settings=None):
    root=Path(args.state_root).resolve();root.mkdir(parents=True,exist_ok=True)
    collect_only=getattr(args,'collect_only',False)
    lock=os.open(root/('sector-live-collector.lock' if collect_only else 'sector-live-service.lock'),os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    os.fchmod(lock,0o600)
    try:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return dict(status='already_running',published=False)
        collection=None
        if not args.publish_only:
            collection=collector(args)
        snapshot=read_committed_snapshot(root/'hithink-live')
        now=datetime.now(SHANGHAI)
        payload=snapshot.get('payload') if snapshot else None
        # Daily bars may arrive after the strict timely-close window. Recover
        # truthfully as a late reconstruction, never forge a timely close.
        if (not args.publish_only and collection and collection.status=='outside_session'
                and now.hour*60+now.minute>=930 and payload
                and payload.get('marketDate')==now.date().isoformat()
                and not payload.get('officialClose') and not payload.get('historicalReconstruction')):
            recovery=copy(args);recovery.latest_close=True
            collection=collector(recovery)
            snapshot=read_committed_snapshot(root/'hithink-live')
        payload=snapshot.get('payload') if snapshot else None
        if (not args.publish_only and payload and payload.get('officialClose')
                and payload.get('marketDate')==now.date().isoformat() and now.hour*60+now.minute>=930):
            archive_stock_close(args,root,payload['marketDate'])
        if collect_only:
            result=dict(status=collection.status,collected=collection.row_count,published=False,
                safeErrorCode=collection.safe_error_code,sourceGeneration=snapshot.get('generation') if snapshot else None)
            _atomic(root/'hithink-live/collector-service-health.json',result|{'checkedAt':datetime.now(timezone.utc).isoformat()})
            return result
        transport=transport or LiveTransport(os.environ.get('MARKET_DASHBOARD_PUBLISH_TOKEN',''))
        collector_health_path=root/'hithink-live/collector-service-health.json'
        collector_health=json.loads(collector_health_path.read_text()) if collector_health_path.exists() else {}
        collection_failed=bool(collection and collection.status=='failed') or collector_health.get('status')=='failed'
        if not snapshot or not snapshot.get('payload'):
            publication_health(transport,'collection','failed','NO_SNAPSHOT')
            return dict(status='no_snapshot',published=False)
        directory=root/'hithink-online-export';checkpoint=root/'hithink-live/live-publication-checkpoint.json'
        settings=settings or json.loads((BASE/'config/sector-live-operation.json').read_text())
        storage_mode=settings.get('storageMode','full')
        state=json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
        generation=snapshot['generation']
        if state.get('sourceGeneration',state.get('generation'))==generation and state.get('storageMode','full')==storage_mode and state.get('activated'):
            if collection_failed:publication_health(transport,'collection','failed','COLLECTION_FAILED')
            return dict(status=collection.status if collection else 'already_published',generation=state['generation'],sourceGeneration=generation,published=True)
        manifest=directory/'manifest.json'
        exported=json.loads(manifest.read_text()) if manifest.exists() else {}
        if exported.get('sourceGeneration',exported.get('generation'))!=generation or exported.get('storageMode','full')!=storage_mode:
            if exporter:exporter(root,directory)
            else:
                node=shutil.which('node')
                if not node:raise ValueError('NODE_UNAVAILABLE')
                options=['--storage-mode',storage_mode]
                if storage_mode=='daily-v1':options+=['--history-base-generation',settings['historyBaseGeneration']]
                subprocess.run([node,str(BASE/'tools/market_dashboard/export_sector_snapshot.mjs'),
                    '--state-root',str(root),'--output-root',str(directory),*options],cwd=BASE,check=True,
                    stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=360)
        if isinstance(transport,LiveTransport):transport.deadline=time.monotonic()+540
        result=publish_export(directory,transport,checkpoint=checkpoint)
        # Pointer activation is idempotent; publisher checkpoint advances only afterwards.
        publication_health(transport,'publication','success')
        if collection_failed:publication_health(transport,'collection','failed','COLLECTION_FAILED')
        health=dict(status='success',generation=result['generation'],sourceGeneration=result.get('sourceGeneration',generation),published=True,
            publishedAt=datetime.now(timezone.utc).isoformat(),collection=asdict(collection) if collection else None,
            publication={k:result[k] for k in ('documents','parts','requests','elapsedSeconds','plannedWireBytes') if k in result})
        _atomic(root/'hithink-live/live-service-health.json',health)
        # Keep exporter disk bounded independently of retained cloud generations.
        for child in directory.iterdir():
            if child.is_dir() and child.name!=result['generation'] and len(child.name)==64 and all(c in '0123456789abcdef' for c in child.name):
                shutil.rmtree(child)
        return health
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z0-9_]{1,120}',str(error)) else 'PUBLICATION_FAILED'
        if transport:publication_health(transport,'publication','failed','PUBLICATION_FAILED')
        _atomic(root/'hithink-live/live-service-health.json',dict(status='failed',published=False,safeErrorCode=code,attemptedAt=datetime.now(timezone.utc).isoformat()))
        return dict(status='failed',published=False,safeErrorCode=code)
    finally:os.close(lock)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,default=BASE/'data/market-dashboard')
    parser.add_argument('--store',type=Path)
    parser.add_argument('--cli',default=CLI)
    project=Path(os.environ.get('MARKET_DASHBOARD_PROJECT_ROOT',BASE.parent))
    parser.add_argument('--stock-db',type=Path,default=Path(os.environ.get('HITHINK_STOCK_DB',str(project/'data/hithink/market.duckdb'))))
    parser.add_argument('--calendar',type=Path)
    parser.add_argument('--latest-close',action='store_true')
    parser.add_argument('--max-calls',type=int,default=1200)
    parser.add_argument('--max-seconds',type=float,default=840)
    parser.add_argument('--publish-only',action='store_true')
    parser.add_argument('--collect-only',action='store_true')
    args=parser.parse_args(argv)
    if args.collect_only and args.publish_only:parser.error('choose one service role')
    try:
        if not args.publish_only:ensure_awake()
    except Exception:pass  # Report source failures separately; a sleep assertion is not a data source.
    result=run_service(args)
    print(json.dumps(result,separators=(',',':')))
    return int(result['status']=='failed')


if __name__=='__main__':raise SystemExit(main())
