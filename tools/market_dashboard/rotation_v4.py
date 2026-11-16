"""Pure Hithink sector-score-v0.3 features, scoring and continuity.

No provider, filesystem, SQLite or clock calls. Daily mappings use the private
store's snake_case names; returned score rows use the independent v4 public
contract. Breadth completeness is *effective* coverage from Task 6 (including
its approximation/staleness discount); it is never discounted a second time.
Returns are percentages, shares fractions, normalized scores 0..100.

Rulings where the design leaves formulas unspecified: historical position uses
index close percentiles (60 minimum 20 observations, 250 requires 250); activity
is participation. Improvement streak counts consecutive positive breadth changes,
not the number of positive days in a disconnected window. Relative turn is the
change in sector-minus-benchmark 5/20 day return over five closes. No supplied
benchmark means missing relative strength, never an invented zero benchmark.
"""
import math
from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter

from .rotation import (_combine, _difference, _finite, _leaf, _mean, _number,
                       _percentile, _ratio, position_curve, rank_sector_scores)

SCORE_VERSION = 'sector-score-v0.3'
UNIVERSE_VERSION = 'sector-universe-ths-v1'
FEATURE_VERSION = 'sector-features-ths-v1'
MEMBERSHIP_VERSION = 'sector-membership-ths-v1'


def validate_v4_config(config):
    """Reject incomplete versions, nonfinite weights and every non-100 sum."""
    if (config.get('scoreVersion') != SCORE_VERSION or config.get('universeVersion') != UNIVERSE_VERSION
            or config.get('featureVersion') != FEATURE_VERSION or config.get('membershipVersion') != MEMBERSHIP_VERSION):
        raise ValueError('INCOMPARABLE_SECTOR_VERSION')
    settings = config.get('scoring', {})
    if settings.get('version') != SCORE_VERSION:
        raise ValueError('INVALID_SCORING_VERSION')
    if set(settings.get('weights', {})) != {'strength','opportunity','risk'}:
        raise ValueError('INVALID_SCORING_WEIGHTS')
    used = {key for weights in settings['weights'].values() for key in weights}
    if set(settings.get('componentWeights', {})) != used:
        raise ValueError('INVALID_SCORING_WEIGHTS')
    for section in ('weights','componentWeights'):
        for weights in settings[section].values():
            if (not weights or any(not _number(v) or v <= 0 for v in weights.values())
                    or math.fsum(weights.values()) != 100):
                raise ValueError('INVALID_SCORING_WEIGHTS')
    return settings


def _rows(rows, sector_id, day):
    result = [dict(r) for r in rows if (sector_id is None or r['sector_id'] == sector_id)
              and (day is None or r['market_date'] <= day)]
    if len({(r['sector_id'],r['market_date']) for r in result}) != len(result):
        raise ValueError('DUPLICATE_SECTOR_CLOSE')
    return sorted(result,key=lambda r:r['market_date'])


def _return(points, offset=0, period=1):
    end=len(points)-1-offset; start=end-period
    if start<0: return None
    left,right=points[start].get('close'),points[end].get('close')
    return (right/left-1)*100 if _number(left) and left>0 and _number(right) else None


def _strict_mean(values, count):
    return _mean(values) if len(values)==count and all(_number(v) for v in values) else None


def top_decile_continuity(history):
    """Trailing 15 dated closes; missing ranks break evidence, never count false."""
    rows=sorted(history,key=lambda r:r['marketDate'])[-15:]
    if len({r['marketDate'] for r in rows})!=len(rows): raise ValueError('DUPLICATE_SECTOR_CLOSE')
    flags=[]
    for row in rows:
        m=row.get('metrics',{}); rank=m.get('strengthRank'); size=m.get('universeSize')
        flags.append(rank<=max(1,math.ceil(size*.1)) if _number(rank) and rank>=1 and _number(size) and size>=rank else None)
    count=sum(flags) if flags and all(f is not None for f in flags) else None
    streak=0 if flags else None
    for flag in reversed(flags):
        if flag is None: streak=None; break
        if not flag: break
        streak+=1
    return dict(topDecileStreak=streak,topDecileCount15d=count)



def _dependency_arrival(row):
    """Return verified input availability; explicit unknown never falls back."""
    if not isinstance(row, dict) or row.get('availabilityStatus') in ('unknown','reconstructed') or row.get('reconstructed') is True:
        return None
    arrivals=[]
    for key in ('observed_at_ms','available_at_ms','observedAt','availableAt'):
        if key not in row:
            continue
        value=row[key]
        try:
            if key.endswith('_ms'):
                if not _number(value) or value<0: return None
                arrival=datetime.fromtimestamp(value/1000,ZoneInfo('Asia/Shanghai'))
            else:
                arrival=datetime.fromisoformat(value)
                if arrival.tzinfo is None: return None
            arrivals.append(arrival)
        except (TypeError,ValueError,OverflowError,OSError):
            return None
    return max(arrivals) if arrivals else None


def _availability(dependencies):
    """Every contributing input must have known availability, not just the index."""
    arrivals=[_dependency_arrival(row) for row in dependencies]
    if not arrivals or any(value is None for value in arrivals):
        return dict(observedAt=None,availableAt=None,availabilityStatus='unknown')
    latest=max(arrivals).astimezone(ZoneInfo('Asia/Shanghai')).isoformat()
    return dict(observedAt=latest,availableAt=latest,availabilityStatus='verified')


def build_v4_features(index_rows, breadth_rows, *, sector_id=None, market_date=None,
                      market_amounts=None, benchmark_rows=(), prior_scores=(), universe=None):
    """Build one dated feature row from bounded official history and breadth.

    ``market_amounts`` maps market date to full A-share turnover, either a
    number (unknown arrival) or {turnover, observed_at_ms, [available_at_ms]}.
    Arrival provenance is required for every contributing input. Optional
    ``prior_scores`` supplies already derived historical participation/strength
    and full-universe ranks. Future observations are excluded before all windows.
    Missing observations are retained as gaps, never zero or forward-filled.
    """
    indexes=_rows(index_rows,sector_id,market_date)
    if not indexes: raise ValueError('MISSING_INDEX_HISTORY')
    identities={r['sector_id'] for r in indexes}
    if len(identities)!=1: raise ValueError('INVALID_SECTOR_IDENTITY')
    identity=next(iter(identities)); today=indexes[-1]['market_date']
    for r in indexes:
        if not _number(r.get('close')) or r['close']<=0: raise ValueError('INVALID_INDEX_CLOSE')
    breadth={r['market_date']:r for r in _rows(breadth_rows,identity,today)}
    b=breadth.get(today,{})
    past=sorted([r for r in prior_scores if r.get('id')==identity and r.get('marketDate','')<today
                 and r.get('sectorScoringVersion')==SCORE_VERSION
                 and r.get('sectorUniverseVersion')==UNIVERSE_VERSION],key=lambda r:r['marketDate'])
    continuity=top_decile_continuity(past)
    m={f'return{p}d':_return(indexes,period=p) for p in (1,5,20)}
    m.update({key:_finite(b.get(field)) for key,field in {
        'advancingShare':'advancing_share','decliningShare':'declining_share','medianReturn':'median_return',
        'strongStockShare':'strong_stock_share','volumeExpansionShare':'volume_expansion_share',
        'top5TurnoverShare':'top5_turnover_share','top1ContributionShare':'top1_contribution_share'}.items()})
    normal={'normalization':dict(winsorLower=.05,winsorUpper=.95)}
    for window in (60,250):
        values=[r['close'] for r in indexes[-window:]]
        m[f'position{window}d']=_percentile(values,indexes[-1]['close'],normal) if len(values)>=(20 if window==60 else 250) else None
    turns=[r.get('turnover') for r in indexes[-20:]]
    m['turnover']=_finite(indexes[-1].get('turnover'))
    m['turnoverPercentile']=_percentile(turns,m['turnover'],normal) if len(turns)==20 and all(_number(v) for v in turns) else None
    market_amount=(market_amounts or {}).get(today)
    m['turnoverMarketShare']=_ratio(m['turnover'],market_amount.get('turnover') if isinstance(market_amount,dict) else market_amount)
    m['shortAcceleration']=_difference(m['return1d'],m['return5d']/5 if m['return5d'] is not None else None)
    m['mediumAcceleration']=_difference(m['return5d']/5 if m['return5d'] is not None else None,m['return20d']/20 if m['return20d'] is not None else None)
    recent=[breadth.get(r['market_date'],{}) for r in indexes[-6:]]
    for output,field in (('breadthDelta5d','advancing_share'),('downsideDelta5d','declining_share')):
        values=[r.get(field) for r in recent]
        m[output]=_difference(values[-1],_strict_mean(values[:-1],5)) if values else None
    sequence=[r.get('advancing_share') for r in recent]
    streak=None
    if len(sequence)==6 and all(_number(v) for v in sequence):
        streak=0
        for left,right in reversed(list(zip(sequence,sequence[1:]))):
            if right<=left: break
            streak+=1
    m['breadthImprovingDays']=streak
    benchmark=sorted([dict(r) for r in benchmark_rows if r['market_date']<=today],key=lambda r:r['market_date'])
    # Exact date alignment prevents a missing benchmark close shifting the horizon.
    benchmark_by_day={r['market_date']:r for r in benchmark}
    aligned=[benchmark_by_day.get(i['market_date'],{}) for i in indexes]
    for period in (5,20):
        relative=_difference(m[f'return{period}d'],_return(aligned,period=period))
        old=_difference(_return(indexes,offset=5,period=period),_return(aligned,offset=5,period=period))
        m[f'relativeStrength{period}d']=relative
        m[f'relativeTurn{period}d']=_difference(relative,old)
    for key in ('participation','activityPercentile','strengthPercentile'):
        m[key]=None
    m['participationDelta5d']=None
    strengths=[r.get('metrics',{}).get('strengthPercentile') for r in past[-15:]]
    m['meanStrengthPercentile']=_mean(strengths) if len(strengths)>=3 and all(_number(v) for v in strengths) else None
    m['strengthSlope5d']=None
    m.update(continuity)
    cov=b.get('completeness',0.)
    if not _number(cov) or not 0<=cov<=1: raise ValueError('INVALID_BREADTH_COVERAGE')
    # Price windows, six-date breadth history, benchmark horizons and derived
    # prior strengths all contribute to this feature. Unknown arrivals remain
    # unknown even when another input has a plausible same-day timestamp.
    dependencies=indexes[-250:]+[r for r in recent if r]+past[-15:]
    if not b: dependencies.append({})
    dependencies.extend(r for r in aligned[-26:] if r)
    if market_amount is not None:
        dependencies.append(market_amount if isinstance(market_amount,dict) else {})
    availability=_availability(dependencies)
    # Missing a breadth observation is explicit, with no invented membership mode.
    return dict(**availability,id=identity,sector_id=identity,universe=universe or ('industry' if identity.startswith('881') else 'concept'),marketDate=today,market_date=today,
                featureVersion=FEATURE_VERSION,sectorScoringVersion=SCORE_VERSION,
                sectorUniverseVersion=UNIVERSE_VERSION,membershipVersion=MEMBERSHIP_VERSION,
                membershipMode=b.get('membership_mode'),breadthCompleteness=cov,
                validCloses=len(indexes),metrics=m,
                positionCoverage={str(w):min(1,len(indexes)/w) for w in (60,250)})


_SNAKE={'return1d':'return_1d','return5d':'return_5d','return20d':'return_20d',
        'advancingShare':'advancing_share','decliningShare':'declining_share','medianReturn':'median_return',
        'strongStockShare':'strong_stock_share','turnoverPercentile':'turnover_percentile',
        'turnoverMarketShare':'turnover_market_share','volumeExpansionShare':'volume_expansion_share',
        'position60d':'position_60d','position250d':'position_250d','breadthDelta5d':'breadth_delta_5d',
        'breadthImprovingDays':'breadth_improving_days','shortAcceleration':'short_acceleration',
        'mediumAcceleration':'medium_acceleration','participation':'participation',
        'participationDelta5d':'participation_delta_5d','relativeStrength5d':'relative_strength_5d',
        'relativeStrength20d':'relative_strength_20d','downsideDelta5d':'downside_delta_5d',
        'strengthSlope5d':'strength_slope_5d','activityPercentile':'activity_percentile',
        'activityAcceleration':'activity_acceleration','top5TurnoverShare':'top5_turnover_share',
        'top1ContributionShare':'top1_contribution_share'}


def _canonical(row):
    r=dict(row)
    r.setdefault('id',r.get('sector_id')); r.setdefault('marketDate',r.get('market_date'))
    r.setdefault('membershipMode',r.get('membership_mode'))
    r.setdefault('breadthCompleteness',r.get('completeness',0))
    if 'metrics' not in r: r['metrics']={key:_finite(r.get(field)) for key,field in _SNAKE.items()}
    else: r['metrics']=dict(r['metrics'])
    return r


def _prepare_participation(rows, prior_closes, norm, settings, universe):
    for row in rows:
        mm=row['metrics']; parts={}
        for key in settings['componentWeights']['participation']:
            value=mm.get(key) if key=='turnoverPercentile' else _percentile([r['metrics'].get(key) for r in rows],mm.get(key),norm)
            parts[key]=_leaf(value,row.get('breadthCompleteness',0) if key=='volumeExpansionShare' else 1.)
        mm['participation']=_combine(parts,settings['componentWeights']['participation'])['value']
        mm['activityPercentile']=mm['participation']
        previous=sorted([r for r in prior_closes if r.get('id')==row['id'] and r.get('universe')==universe
                         and r.get('marketDate','')<row['marketDate'] and r.get('session')=='close'
                         and r.get('sectorScoringVersion')==SCORE_VERSION and r.get('sectorUniverseVersion')==UNIVERSE_VERSION],key=lambda r:r['marketDate'])
        if mm.get('participationDelta5d') is None:
            mm['participationDelta5d']=_difference(mm['participation'],_strict_mean([r.get('metrics',{}).get('participation') for r in previous[-5:]],5))
        mm['activityAcceleration']=mm.get('participationDelta5d')
        for period in (5,20):
            key=f'relativeTurn{period}d'
            if mm.get(key) is None and len(previous)>=5:
                mm[key]=_difference(mm.get(f'relativeStrength{period}d'),previous[-5].get('metrics',{}).get(f'relativeStrength{period}d'))
        # Prepare slope for every peer before cross-sectional normalization.
        if mm.get('strengthSlope5d') is None and len(previous)>=5:
            components={}
            for name in ('priceTrend','breadth','participation'):
                parts={}
                for key in settings['componentWeights'][name]:
                    value=mm.get(key) if key=='turnoverPercentile' else _percentile([r['metrics'].get(key) for r in rows],mm.get(key),norm)
                    parts[key]=_leaf(value,row.get('breadthCompleteness',0) if name=='breadth' or key=='volumeExpansionShare' else 1.)
                components[name]=_combine(parts,settings['componentWeights'][name])
            history=[r.get('metrics',{}).get('strengthPercentile') for r in previous[-15:]]
            mean=_mean(history) if len(history)>=3 and all(_number(v) for v in history) else mm.get('meanStrengthPercentile')
            streak=top_decile_continuity(previous)['topDecileStreak']
            coverage=min(1,len(previous)/15)
            components['persistence']=_combine({'meanPercentile':_leaf(mean,coverage),
                'topDecileStreak':_leaf(streak/15*100 if _number(streak) else None,coverage)},settings['componentWeights']['persistence'])
            current_strength=_combine(components,settings['weights']['strength'])['value']
            delta=_difference(current_strength,previous[-5].get('_rawScores',{}).get('strength'))
            mm['strengthSlope5d']=delta/5 if delta is not None else None
    return rows


def score_v4_sector(current, prior_closes, universe_current, config, *, _prepared=None):
    """Score three independent axes, retaining complete component audit trails."""
    settings=validate_v4_config(config)
    if _prepared is not None:
        current=next(r for r in _prepared if r['id']==current['id'] and r['universe']==current['universe'])
        universe_current=_prepared
    current=_canonical(current)
    for key,expected in (('sectorScoringVersion',SCORE_VERSION),('sectorUniverseVersion',UNIVERSE_VERSION),('featureVersion',FEATURE_VERSION)):
        if key in current and current[key]!=expected: raise ValueError('INCOMPARABLE_SECTOR_VERSION')
    universe=current.get('universe')
    if universe not in ('industry','concept') or not current.get('id'): raise ValueError('INVALID_SECTOR_IDENTITY')
    rows=[_canonical(r) for r in universe_current if r.get('universe')==universe]
    ids=[r['id'] for r in rows]
    if len(ids)!=len(set(ids)) or current['id'] not in ids: raise ValueError('INVALID_SECTOR_UNIVERSE')
    if any(r['marketDate']!=current['marketDate'] for r in rows): raise ValueError('INCOMPARABLE_SECTOR_DATE')
    for row in rows:
        for key,expected in (('sectorScoringVersion',SCORE_VERSION),('sectorUniverseVersion',UNIVERSE_VERSION),('featureVersion',FEATURE_VERSION)):
            if key in row and row[key]!=expected: raise ValueError('INCOMPARABLE_SECTOR_VERSION')
    rows=[current if r['id']==current['id'] else r for r in rows]
    past=sorted([r for r in prior_closes if r.get('id')==current['id'] and r.get('universe')==universe
                 and r.get('marketDate','')<current['marketDate'] and r.get('session')=='close'
                 and r.get('sectorScoringVersion')==SCORE_VERSION and r.get('sectorUniverseVersion')==UNIVERSE_VERSION],key=lambda r:r['marketDate'])
    if len({r['marketDate'] for r in past})!=len(past): raise ValueError('DUPLICATE_SECTOR_CLOSE')
    norm={'normalization':settings['normalization']}
    if _prepared is None:
        _prepare_participation(rows,prior_closes,norm,settings,universe)
    m=current['metrics']; c={}
    for period in (5,20):
        key=f'relativeTurn{period}d'
        if m.get(key) is None and len(past)>=5:
            m[key]=_difference(m.get(f'relativeStrength{period}d'),past[-5].get('metrics',{}).get(f'relativeStrength{period}d'))
    coverage=current.get('breadthCompleteness',0)
    if not _number(coverage) or not 0<=coverage<=1: raise ValueError('INVALID_BREADTH_COVERAGE')
    def cross(key,reverse=False):
        return _percentile([r['metrics'].get(key) for r in rows],m.get(key),norm,reverse)
    def leaf(key,*,breadth=False,reverse=False,direct=False):
        return _leaf(m.get(key) if direct else cross(key,reverse),coverage if breadth else 1.)
    def combine(name,parts): c[name]=_combine(parts,settings['componentWeights'][name])
    combine('priceTrend',{key:leaf(key) for key in settings['componentWeights']['priceTrend']})
    combine('breadth',{key:leaf(key,breadth=True) for key in settings['componentWeights']['breadth']})
    combine('participation',{key:leaf(key,breadth=key=='volumeExpansionShare',direct=key=='turnoverPercentile') for key in settings['componentWeights']['participation']})
    m['participation']=c['participation']['value']; m['activityPercentile']=m['participation']
    # Historical activity belongs to each date's own universe, never today's rank.
    old_values=[p.get('metrics',{}).get('participation') for p in past[-5:]]
    if m.get('participationDelta5d') is None: m['participationDelta5d']=_difference(m['participation'],_strict_mean(old_values,5))
    m['activityAcceleration']=m.get('participationDelta5d')
    continuity=top_decile_continuity(past)
    for key,value in continuity.items():
        if value is not None or key not in m: m[key]=value
    strengths=[r.get('metrics',{}).get('strengthPercentile') for r in past[-15:]]
    average=_mean(strengths) if len(strengths)>=3 and all(_number(v) for v in strengths) else m.get('meanStrengthPercentile')
    history_cov=min(1,len(past)/15)
    combine('persistence',{'meanPercentile':_leaf(average,history_cov),
                          'topDecileStreak':_leaf(m.get('topDecileStreak')/15*100 if _number(m.get('topDecileStreak')) else None,history_cov)})
    strength=_combine(c,settings['weights']['strength'])['value']
    if m.get('strengthSlope5d') is None and len(past)>=5:
        delta=_difference(strength,past[-5].get('_rawScores',{}).get('strength'))
        m['strengthSlope5d']=delta/5 if delta is not None else None
    combine('position',{key:_leaf(position_curve(m.get(key)),current.get('positionCoverage',{}).get(key[8:-1],1)) for key in settings['componentWeights']['position']})
    combine('breadthImprovement',{'delta5d':leaf('breadthDelta5d',breadth=True),
                                 'improvingDays':_leaf(m.get('breadthImprovingDays')/5*100 if _number(m.get('breadthImprovingDays')) else None,coverage)})
    combine('momentumImprovement',{key:leaf(key) for key in settings['componentWeights']['momentumImprovement']})
    combine('participationWarming',{'current':c['participation'],'delta5d':_leaf(_percentile([_canonical(r)['metrics'].get('participationDelta5d') for r in rows],m.get('participationDelta5d'),norm))})
    if _number(m['participation']) and m['participation']>=settings['heat']['crowdedAt']: c['participationWarming']['value']=0.
    combine('relativeTurn',{key:leaf(key) for key in settings['componentWeights']['relativeTurn']})
    combine('downsideDiffusion',{'current':leaf('decliningShare',breadth=True),'delta5d':leaf('downsideDelta5d',breadth=True)})
    combine('trendDeterioration',{'return5d':leaf('return5d',reverse=True),'return20d':leaf('return20d',reverse=True),'slope5d':leaf('strengthSlope5d',reverse=True)})
    price=c['priceTrend']['value']
    combine('divergence',{name:_leaf(max(0.,price-value) if _number(price) and _number(value) else None,coverage)
                          for name,value in [('indexBreadth',cross('advancingShare')),('indexMedian',cross('medianReturn'))]})
    combine('crowding',{'activity':c['participation'],'acceleration':leaf('activityAcceleration')})
    if not _number(m['participation']): c['crowding']=_leaf(None)
    elif m['participation']<settings['heat']['activeAt']: c['crowding']=_leaf(0.,c['participation']['coverage'])
    combine('concentration',{key:leaf(key,breadth=True) for key in settings['componentWeights']['concentration']})
    axes={axis:_combine(c,weights) for axis,weights in settings['weights'].items()}; raw={a:v['value'] for a,v in axes.items()}
    # Breadth, momentum, participation and relative turn are independent families;
    # two momentum legs alone count once. Low position never counts as evidence.
    positives={'breadthImprovement':_number(m.get('breadthDelta5d')) and m['breadthDelta5d']>0,
               'momentumImprovement':any(_number(m.get(k)) and m[k]>0 for k in ('shortAcceleration','mediumAcceleration')),
               'participationWarming':_number(m.get('participationDelta5d')) and m['participationDelta5d']>0,
               'relativeTurn':any(_number(m.get(k)) and m[k]>0 for k in ('relativeTurn5d','relativeTurn20d'))}
    gates=settings['gates']
    evidence=sum(positive and _number(c[key]['value']) and c[key]['value']>=gates['improvementThreshold'] for key,positive in positives.items())
    valid=current.get('validCloses',len(past))
    if raw['opportunity'] is not None:
        if evidence<gates['requiredImprovementComponents']: raw['opportunity']=min(raw['opportunity'],gates['unconfirmedOpportunityCap'])
        if valid<gates['minimumCloses'] or axes['opportunity']['coverage']*100<gates['minimumOpportunityCompleteness']: raw['opportunity']=None
    result={key:current[key] for key in ('id','name','universe','marketDate','session','observedAt','officialClose','availableAt') if key in current}
    heat=None; activity=m['participation']
    if _number(activity) and c['participation']['coverage']*100>=settings['heat']['minimumCompleteness']:
        heat='crowded' if activity>=90 else 'active' if activity>=70 else 'cold' if activity<30 else None
        if heat is None and _number(m.get('participationDelta5d')) and m['participationDelta5d']>=15: heat='warming'
    result.update({axis:math.floor(v+.5) if v is not None else None for axis,v in raw.items()})
    dependencies=list(rows)
    for identity in ids:
        dependencies.extend(sorted([row for row in prior_closes
            if row.get('id')==identity and row.get('universe')==universe
            and row.get('marketDate','')<current['marketDate'] and row.get('session')=='close'
            and row.get('sectorScoringVersion')==SCORE_VERSION and row.get('sectorUniverseVersion')==UNIVERSE_VERSION],
            key=lambda row:row['marketDate'])[-15:])
    result.update(_availability(dependencies))
    result.update(schemaVersion='market-dashboard-v4',sectorScoringVersion=SCORE_VERSION,sectorUniverseVersion=UNIVERSE_VERSION,
                  featureVersion=FEATURE_VERSION,membershipVersion=MEMBERSHIP_VERSION,membershipMode=current.get('membershipMode'),
                  source='Hithink',_rawScores=raw,components=c,metrics=m,heatState=heat,validCloses=valid,
                  coldStart=valid<gates['coldStartCloses'],improvementEvidence=evidence,
                  axisCompleteness={a:v['coverage']*100 for a,v in axes.items()},
                  completeness=math.floor(_mean([v['coverage'] for v in axes.values()])*100+.5),
                  missing=[f'{key}.{reason}' for key,component in c.items() for reason in component['missing']])
    return result



def score_v4_sectors(rows, prior_closes, config):
    """Batch score a complete dated universe, normalizing participation once."""
    settings=validate_v4_config(config)
    prepared=[]
    for universe in ('industry','concept'):
        selected=[_canonical(r) for r in rows if r.get('universe')==universe]
        _prepare_participation(selected,prior_closes,{'normalization':settings['normalization']},settings,universe)
        prepared.extend(selected)
    if len(prepared)!=len(rows): raise ValueError('INVALID_SECTOR_UNIVERSE')
    return [score_v4_sector(row,prior_closes,prepared,config,_prepared=prepared) for row in rows]


def rank_v4_universe(rows, axis='strength'):
    """Stable independent-universe ranks with top-decile, never top-ten fields."""
    sizes=Counter(row.get('universe') for row in rows)
    result=rank_sector_scores(rows,axis)
    output=[]
    for row in result:
        row={**row,'metrics':dict(row.get('metrics',{}))}; size=sizes[row['universe']]
        if axis=='strength':
            rank=row['ranks'][axis]
            row['metrics'].update(strengthRank=rank,universeSize=size,
                                  strengthPercentile=(size-rank+.5)/size*100 if rank else None,
                                  inTopDecile=rank<=max(1,math.ceil(size*.1)) if rank else None)
        output.append(row)
    return output


def replay_v4(index_rows, breadth_rows, sector_definitions, config, *,
              official_dates=None, market_amounts=None, benchmark_rows=()):
    """Replay daily closes forward without I/O, fitting or fabricated arrival times.

    Definitions are catalog-derived ``id,name,universe`` mappings. Returns every
    available dated sector, with no invented rows for absent official indexes.
    All contributing inputs must carry verified arrival provenance. The latest
    arrival becomes observedAt/availableAt; absent provenance remains unknown,
    so reconstructed history cannot masquerade as a timely forecast.
    """
    validate_v4_config(config)
    definitions={r['id']:dict(r) for r in sector_definitions}
    if len(definitions)!=len(sector_definitions): raise ValueError('DUPLICATE_SECTOR_IDENTITY')
    indexes={identity:[] for identity in definitions}; breadth={identity:[] for identity in definitions}
    for row in index_rows:
        if row['sector_id'] in indexes: indexes[row['sector_id']].append(dict(row))
    for row in breadth_rows:
        if row['sector_id'] in breadth: breadth[row['sector_id']].append(dict(row))
    dates=sorted(set(official_dates) if official_dates is not None else {r['market_date'] for r in index_rows})
    result=[]
    for day in dates:
        current=[]
        for identity,definition in sorted(definitions.items()):
            observation=next((r for r in indexes[identity] if r['market_date']==day),None)
            if observation is None: continue
            f=build_v4_features(indexes[identity],breadth[identity],market_date=day,
                                market_amounts=market_amounts,benchmark_rows=benchmark_rows,
                                prior_scores=result,universe=definition['universe'])
            f.update(name=definition.get('name',identity),session='close',officialClose=True)
            current.append(f)
        scores=score_v4_sectors(current,result,config)
        for axis in ('strength','opportunity','risk'): scores=rank_v4_universe(scores,axis)
        result.extend(sorted(scores,key=lambda r:(r['universe'],r['id'])))
    return result
