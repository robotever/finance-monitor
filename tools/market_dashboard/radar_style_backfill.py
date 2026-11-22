"""Pure, conservative reconstruction of style inputs from current constituents."""
import copy
from datetime import date
import math
import re

STYLE_IDS=['large','small','value','growth','dividend','tech']
BREADTH=('up','down','flat')


def _date(value):
    if not isinstance(value,str) or date.fromisoformat(value).isoformat()!=value:raise ValueError('Invalid backfill date')
    return value


def _number(value,positive=False,nonnegative=False):
    return isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value) and abs(value)<=1e16 and (not positive or value>0) and (not nonnegative or value>=0)


def _evidence(excluded,day,style):
    value=excluded.get(day,[])
    if isinstance(value,dict):value=value.get(style,value.get('members',[]))
    if isinstance(value,dict):value=value.get('members',[])
    if not isinstance(value,(list,tuple,set)):raise ValueError('Invalid dated exclusion evidence')
    return set(value)


def _compute(style,day,previous,codes,panel,duplicates,flows,excluded):
    proof=_evidence(excluded,day,style)&set(codes)
    removed=set(proof);reasons=[];missing_panel=[];missing_previous=[];missing_flow=[];matched=0
    up=down=flat=0;amount=net=0
    for code in codes:
        row=panel.get((code,day))
        if (code,day) in duplicates:reasons.append('duplicate local panel row: '+code)
        if (code,day) not in duplicates and row is not None and _number(row.get('volume'),nonnegative=True) and _number(row.get('turnover'),nonnegative=True) and row['volume']==0 and row['turnover']==0:
            removed.add(code)
        if code in removed:
            funding=flows.get(code,{}).get(day)
            if isinstance(funding,dict) and funding.get('date')==day and _number(funding.get('mainNetFlow')) and funding['mainNetFlow']!=0:
                reasons.append('排除与非零资金矛盾: '+code)
            if row is not None and (_number(row.get('volume'),positive=True) or _number(row.get('turnover'),positive=True)):reasons.append('exclusion contradicts local trading: '+code)
            continue
        if row is None or (code,day) in duplicates:
            missing_panel.append(code)
        else:
            volume=row.get('volume');turnover=row.get('turnover');close=row.get('close')
            if not _number(volume,positive=True) or not _number(turnover,positive=True) or not _number(close,positive=True):
                missing_panel.append(code)
            else:amount+=turnover
        funding=flows.get(code,{}).get(day)
        valid_fund=isinstance(funding,dict) and funding.get('date')==day and _number(funding.get('mainNetFlow'))
        if valid_fund and ('largeNetFlow' in funding or 'superNetFlow' in funding):
            large=funding.get('largeNetFlow');super_large=funding.get('superNetFlow')
            valid_fund=_number(large) and _number(super_large) and abs(funding['mainNetFlow']-large-super_large)<=max(100,abs(funding['mainNetFlow'])*1e-6)
        if not valid_fund:missing_flow.append(code)
        else:
            matched+=1;net+=funding['mainNetFlow']
            if row is not None and _number(row.get('turnover'),positive=True) and abs(funding['mainNetFlow'])>row['turnover']*1.05:reasons.append('member funding/turnover ratio invalid: '+code)
        prior=panel.get((code,previous)) if previous else None
        if prior is None or (code,previous) in duplicates or not _number(prior.get('close'),positive=True):missing_previous.append(code)
        elif row is not None and _number(row.get('close'),positive=True):
            up+=int(row['close']>prior['close']);down+=int(row['close']<prior['close']);flat+=int(row['close']==prior['close'])
    expected=len(codes)-len(removed)
    if missing_panel:reasons.append('missing or invalid same-day local panel')
    if missing_flow:reasons.append('missing or invalid same-day funding')
    if missing_previous:reasons.append('missing exact previous trading-day close')
    if expected<=0 or not _number(amount,positive=True) or not _number(net):reasons.append('no verified active basket or invalid aggregate magnitude')
    if expected>0 and up+down+flat!=expected:reasons.append('incomplete breadth')
    if abs(net)>amount*1.05:reasons.append('basket funding/turnover ratio invalid')
    verified=not reasons and matched==expected
    detail={'status':'verified' if verified else 'failed','matched':matched,'expected':expected,'excluded':len(removed),'excludedCodes':sorted(removed),'missing':sorted(set(missing_panel+missing_flow+missing_previous)),'missingPanel':sorted(missing_panel),'missingFlow':sorted(missing_flow),'missingPrevious':sorted(missing_previous),'previousDate':previous,'reasons':reasons,'breadth':{'up':up,'down':down,'flat':flat}}
    p={'date':day,'up':up,'down':down,'flat':flat,'turnover':amount,'mainNetFlow':net,'fundMatched':matched,'fundExpected':expected,'membershipMode':'current-members'}
    return p,detail


def _control(computed,baseline,total):
    reasons=[];result={'ready':False,'reasons':reasons}
    if not isinstance(baseline,dict) or not _number(baseline.get('mainNetFlow')) or not _number(baseline.get('turnover'),positive=True):
        reasons.append('missing validated latest baseline');return result
    net_delta=computed['mainNetFlow']-baseline['mainNetFlow'];amount_delta=computed['turnover']-baseline['turnover']
    result.update(mainNetFlowDelta=net_delta,turnoverDelta=amount_delta,mainNetFlowTolerance=max(1000000,abs(baseline['mainNetFlow'])*0.001),turnoverTolerance=baseline['turnover']*0.001)
    if abs(net_delta)>result['mainNetFlowTolerance']:reasons.append('latest funding control mismatch')
    if abs(amount_delta)>result['turnoverTolerance']:reasons.append('latest turnover control mismatch')
    if any(type(baseline.get(k)) is not int or baseline[k]<0 for k in BREADTH) or not 0<sum(baseline.get(k) or 0 for k in BREADTH)<=total:
        reasons.append('invalid baseline breadth')
    else:result['breadthDelta']={key:computed[key]-baseline[key] for key in BREADTH}
    if baseline.get('fundExpected')!=computed['fundExpected'] or baseline.get('fundMatched')!=computed['fundExpected']:reasons.append('latest active-membership control mismatch')
    result['ready']=not reasons
    return result


def backfill_bundle(base,members,panel,flows,dates,excluded_by_date):
    """Return (deep-copied bundle, per-style/day verification report), without I/O.

    dates are the actual consecutive target trading sessions. The panel must also
    contain the preceding session; its global date establishes the first target's
    prior session. A missing individual row never permits using an older close.
    """
    targets=[_date(day) for day in dates]
    if not targets or targets!=sorted(set(targets)) or targets[-1]!=base['marketDate']:raise ValueError('Targets must end at the validated market date')
    index={};duplicates=set();calendar=set(targets)
    for row in panel:
        key=(row['code'],_date(row['date']));calendar.add(key[1])
        if key in index:duplicates.add(key)
        else:index[key]=row
    calendar=sorted(calendar)
    previous={day:max((d for d in calendar if d<day),default=None) for day in targets}
    out=copy.deepcopy(base);report={'ready':False,'dates':targets,'styles':{}}
    for style in STYLE_IDS:
        original=base['objects'][style];obj=out['objects'][style];config=members.get(style,{})
        entry={'ready':False,'dates':{},'control':{'ready':False,'reasons':[]}};report['styles'][style]=entry
        codes=config.get('members',[])
        try:
            if not isinstance(codes,list) or not codes or len(set(codes))!=len(codes) or any(not isinstance(c,str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)',c) for c in codes):raise ValueError('Invalid complete membership')
            as_of=_date(config['asOf'])
            if config.get('source') not in ('Hithink','CSI'):raise ValueError('Unverified membership source')
        except (ValueError,KeyError,TypeError) as error:
            entry['control']['reasons']=[str(error)]
            for day in targets:entry['dates'][day]={'status':'failed','matched':0,'expected':len(codes) if isinstance(codes,list) else None,'excluded':0,'missing':codes if isinstance(codes,list) else [],'reasons':['invalid membership metadata']}
            continue
        points={}
        for day in targets:
            p,detail=_compute(style,day,previous[day],codes,index,duplicates,flows,excluded_by_date)
            points[day]=p;entry['dates'][day]=detail
        latest=targets[-1];baseline=next((p for p in original['history'] if p['date']==latest),None)
        if entry['dates'][latest]['status']=='verified':entry['control']=_control(points[latest],baseline,len(codes))
        else:entry['control']['reasons']=['latest computed basket is incomplete']
        control_ready=entry['control']['ready']
        note='；当前成员历史重建（近似，非严格时点成份）'
        scope=obj['scope'] if '当前成员历史重建' in obj['scope'] else obj['scope']+note
        if len(scope)>=200:
            control_ready=False;entry['control']['ready']=False;entry['control']['reasons'].append('scope disclosure exceeds contract length')
        merged={p['date']:copy.deepcopy(p) for p in original['history']};published=0
        for day in targets:
            detail=entry['dates'][day]
            if day==latest:
                if detail['status']=='verified':detail['status']='control' if control_ready else 'control-failed'
                continue
            if detail['status']=='verified' and control_ready:merged[day]=points[day];published+=1
            elif detail['status']=='verified':detail['status']='control-failed';detail['reasons'].append('latest control did not pass; existing point preserved')
        if published:
            obj['history']=[merged[day] for day in sorted(merged)][-320:]
            obj['sources']=sorted(set(obj['sources'])|{'Eastmoney','Hithink',config['source']})
            obj['membershipAsOf']=max(as_of,obj.get('membershipAsOf') or as_of);obj['scope']=scope
        entry['ready']=control_ready and all(detail['status'] in ('verified','control') for detail in entry['dates'].values())
    report['ready']=all(entry['ready'] for entry in report['styles'].values())
    report['whole']={'ready':report['ready'],'stylesReady':sum(entry['ready'] for entry in report['styles'].values()),'stylesExpected':len(STYLE_IDS)}
    return out,report
