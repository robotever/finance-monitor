// Read-only local view. Reconstructed arrivals stay distinct from timely closes.
import { VERSIONS } from '../../src/features/sector-rotation-v4/model.mjs'
import { selectProjectedV4Lists } from '../../functions/_lib/sector-rotation-v4-read.js'
const axes=['strength','opportunity','risk']
function days(bundle){
  const map=new Map((bundle.closeHistory??[]).map(p=>[p.marketDate,p]))
  if(bundle.payload?.marketDate)map.set(bundle.payload.marketDate,bundle.payload)
  return [...map.values()].sort((a,b)=>a.marketDate.localeCompare(b.marketDate))
}
function rowsFor(bundle,p){
  const chunks=p===bundle.payload?bundle.chunks:bundle.historyChunks?.[p.marketDate]
  const projected=(chunks??[]).flatMap(c=>JSON.parse(c.rowsJson))
  const previous=days(bundle).filter(d=>d.marketDate<p.marketDate).at(-1)
  const prior=new Map((previous?.rows??[]).map(r=>[r.id,r]))
  const originals=new Map(p.rows.map(r=>[r.id,r]))
  return projected.map(r=>({...r,change1d:Object.fromEntries(axes.map(a=>[a,Number.isFinite(r[a])&&Number.isFinite(prior.get(r.id)?.[a])?r[a]-prior.get(r.id)[a]:null])),
    marketDate:p.marketDate,observedAt:originals.get(r.id)?.observedAt??null,availableAt:originals.get(r.id)?.availableAt??null,
    officialClose:p.officialClose===true,historicalReconstruction:p.historicalReconstruction===true,
    session:p.officialClose?'close':'intraday',approximateHistory:r.membershipMode==='current_members_backfill'}))
}
function metadata(bundle){
  const p=bundle.payload,rows=rowsFor(bundle,p)
  return {...VERSIONS,sourceMode:'hithink',batchId:bundle.generation??p.bucket??'local',marketDate:p.marketDate,
    observedAt:rows.map(r=>r.observedAt??'').sort().at(-1),officialClose:p.officialClose===true,
    session:p.officialClose?'close':'intraday',historicalReconstruction:p.historicalReconstruction===true,
    membershipModes:[...new Set(rows.map(r=>r.membershipMode))],approximateHistory:rows.some(r=>r.approximateHistory)}
}
export function localSnapshot(bundle){return {...metadata(bundle),...selectProjectedV4Lists(rowsFor(bundle,bundle.payload))}}
export function localHistory(bundle,universe,axis){
  const selected=days(bundle).slice(-15).reverse(),dates=selected.map(p=>p.marketDate)
  const byDay=new Map(selected.map(p=>[p.marketDate,new Map(rowsFor(bundle,p).filter(r=>r.universe===universe).map(r=>[r.id,r]))]))
  if(axis==='return1d')for(const points of byDay.values()){
    const ranked=[...points.values()].filter(r=>Number.isFinite(r.metrics?.return1d)).sort((a,b)=>b.metrics.return1d-a.metrics.return1d||a.id.localeCompare(b.id))
    for(const [i,r] of ranked.entries())points.set(r.id,{...r,return1d:r.metrics.return1d,ranks:{...r.ranks,return1d:i+1}})
  }
  const definitions=new Map(selected.flatMap(p=>p.rows.filter(r=>r.universe===universe).map(r=>[r.id,r])))
  return {...metadata(bundle),universe,axis,days:15,dates,liveDate:!bundle.payload.historicalReconstruction&&!bundle.payload.officialClose?bundle.payload.marketDate:null,
    rows:[...definitions.values()].map(r=>({id:r.id,name:r.name,values:dates.map(day=>{const point=byDay.get(day).get(r.id);return {marketDate:day,score:point?.[axis]??null,rank:point?.ranks?.[axis]??null}})}))}
}
export function localCatalog(bundle,params){
  const universe=params.get('universe')??'concept',page=Math.max(1,Number(params.get('page')??1)),pageSize=Math.max(1,Math.min(100,Number(params.get('pageSize')??50))),q=params.get('q')??''
  if(!['industry','concept'].includes(universe)||!Number.isInteger(page)||!Number.isInteger(pageSize))throw Error('INVALID_QUERY')
  const rows=rowsFor(bundle,bundle.payload).filter(r=>r.universe===universe&&(r.name.toLowerCase().includes(q.toLowerCase())||r.id.toLowerCase().includes(q.toLowerCase())))
  return {...metadata(bundle),universe,page,pageSize,q,total:rows.length,sectors:rows.slice((page-1)*pageSize,page*pageSize)}
}
export function localDetail(bundle,params){
  const universe=params.get('universe'),id=params.get('id')
  return {...metadata(bundle),universe,id,history:days(bundle).flatMap(p=>rowsFor(bundle,p).filter(r=>r.universe===universe&&r.id===id))}
}
