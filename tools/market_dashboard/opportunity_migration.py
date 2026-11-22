"""Offline v0.3 -> v0.4 opportunity-only migration, preserving source evidence."""
import argparse
from copy import deepcopy
from contextlib import ExitStack
import fcntl
import json
import math
from pathlib import Path
import statistics
from .rotation import _combine, _leaf
from .rotation_v4 import SCORE_VERSION, opportunity_position, opportunity_axis, rank_v4_universe, validate_v4_config
from .hithink_job import read_committed_snapshot, _snapshot, _commit_snapshot, _atomic, _live_guard, store_write_lock

OLD='sector-score-v0.3'

def reprice_row(row, settings):
    version=row.get('sectorScoringVersion')
    if version==SCORE_VERSION:return deepcopy(row)
    if version!=OLD:raise ValueError('UNSUPPORTED_SCORE_VERSION')
    result=deepcopy(row);c=result['components'];m=result['metrics']
    old=c['position']['parts']
    parts={k:_leaf(opportunity_position(m.get(k)),old[k].get('coverage',0)) for k in settings['componentWeights']['position']}
    c['position']=_combine(parts,settings['componentWeights']['position'])
    value,coverage=opportunity_axis(c,result['validCloses'],settings)
    result['opportunity']=math.floor(value+.5) if value is not None else None
    result['_rawScores']['opportunity']=value
    if 'rankKeys' in result:result['rankKeys']['opportunity']=value
    result['axisCompleteness']['opportunity']=coverage
    result['completeness']=math.floor(statistics.mean(result['axisCompleteness'].values())+.5)
    result['missing']=[f'{key}.{reason}' for key,component in c.items() for reason in component['missing']]
    result['sectorScoringVersion']=SCORE_VERSION
    return result


def migrate_snapshot(snapshot,config):
    settings=validate_v4_config(config)
    payloads=[snapshot['payload'],*snapshot['closeHistory']]
    versions={r.get('sectorScoringVersion') for p in payloads for r in p['rows']}
    if versions=={SCORE_VERSION}:return deepcopy(snapshot),dict(status='already_current',generation=snapshot['generation'])
    if versions!={OLD}:raise ValueError('MIXED_SCORE_VERSIONS')
    report=[]
    def convert(p):
        updated=deepcopy(p)
        updated['rows']=rank_v4_universe([reprice_row(r,settings) for r in p['rows']],'opportunity')
        old={r['id']:r for r in p['rows']}
        for r in updated['rows']:
            before=old[r['id']]
            for k in ['strength','risk','metrics','observedAt','availableAt','officialClose','historicalReconstruction','membershipMode']:
                if r.get(k)!=before.get(k):raise ValueError('UNRELATED_SCORE_OR_EVIDENCE_CHANGED')
            for a in ['strength','risk']:
                if r['_rawScores'][a]!=before['_rawScores'][a] or r['ranks'][a]!=before['ranks'][a]:raise ValueError('UNRELATED_RANK_CHANGED')
        for universe in ['industry','concept']:
            rows=[r for r in updated['rows'] if r['universe']==universe]
            vals=lambda xs:[r['opportunity'] for r in xs if r['opportunity'] is not None]
            ov=vals([r for r in p['rows'] if r['universe']==universe]);nv=vals(rows)
            report.append(dict(date=p['marketDate'],universe=universe,count=len(rows),oldMean=statistics.mean(ov) if ov else None,newMean=statistics.mean(nv) if nv else None,newMin=min(nv) if nv else None,newMax=max(nv) if nv else None,valid=len(nv)))
        return updated
    payload=convert(snapshot['payload']);history=[convert(p) for p in snapshot['closeHistory']]
    from .hithink_job import build_publish_chunks
    value=_snapshot(payload,build_publish_chunks(payload['rows']),snapshot['state'],history,snapshot['health'])
    return value,dict(status='candidate',sourceGeneration=snapshot['generation'],generation=value['generation'],scoreVersion=SCORE_VERSION,dates=report,sourceCalls=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--commit',action='store_true')
    parser.add_argument('--history-base-generation',help='already verified full v0.4 publication; atomically switch daily base under service locks')
    args=parser.parse_args();args.output=args.output.resolve();root=args.state_root.resolve();local=root/'hithink-live'
    config=json.loads((Path(__file__).resolve().parents[2]/'config/hithink-sector-dashboard.json').read_text())
    before=read_committed_snapshot(local);candidate,report=migrate_snapshot(before,config)
    args.output.mkdir(parents=True,exist_ok=True)
    _atomic(args.output/'candidate.json',candidate);_atomic(args.output/'report.json',report)
    if args.commit and report['status']!='already_current':
        with ExitStack() as stack:
            # Prevent concurrent publisher/collector visibility changes, then reuse the original commit protocol.
            for name in ['sector-live-service.lock','sector-live-collector.lock']:
                f=stack.enter_context(open(root/name,'a+'));fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
            stack.enter_context(_live_guard(root));stack.enter_context(store_write_lock(root))
            current=read_committed_snapshot(local)
            if current['generation']!=before['generation']:raise ValueError('SOURCE_CHANGED_REBUILD_CANDIDATE')
            _atomic(args.output/'rollback-snapshot.json',current)
            operation=Path(__file__).resolve().parents[2]/'config/sector-live-operation.json'
            prior_settings=None
            if args.history_base_generation:
                if args.history_base_generation!=candidate['generation']:raise ValueError('HISTORY_BASE_MISMATCH')
                prior_settings=json.loads(operation.read_text())
                _atomic(args.output/'rollback-operation.json',prior_settings)
                _atomic(operation,dict(storageMode='daily-v1',historyBaseGeneration=args.history_base_generation))
            try:
                committed=_commit_snapshot(local,candidate['payload'],candidate['chunks'],candidate['state'],candidate['closeHistory'],candidate['health'])
            except BaseException:
                visible=read_committed_snapshot(local)
                if prior_settings is not None and visible['generation']!=candidate['generation']:_atomic(operation,prior_settings)
                raise
            if committed['generation']!=candidate['generation']:raise ValueError('COMMIT_MISMATCH')
        report['status']='committed';_atomic(args.output/'report.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='dates'},separators=(',',':')))

if __name__=='__main__':main()
