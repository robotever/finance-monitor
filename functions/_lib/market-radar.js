import {upstreamText} from './upstream.js'
import {loadRiskSource} from './cross-market-risk.js'
import {INDEXES,RADAR_VERSION,parseRadarBars,completedBars,deriveRadar} from '../../src/features/market-radar/model.mjs'
export const RADAR_MACRO=['vix','treasury','real','dollar']
export async function loadRadarIndex(id,{cache,origin='https://newsmonitor.pages.dev',fetcher=fetch,now=Date.now(),waitUntil}={}){
 const def=INDEXES.find(x=>x.id===id);if(!def)throw Error('INVALID_RADAR_INDEX')
 const key=new Request(new URL('/api/market-radar/cache/'+RADAR_VERSION+'/'+id,origin))
 let old=null
 try{const r=await cache?.match(key);old=r?await r.json():null}catch{}
 if(old&&(!Array.isArray(old.bars)||!Number.isFinite(old.lastSuccessAt)||old.lastSuccessAt>now))old=null
 if(old&&now-old.lastSuccessAt<300000)return {...old,status:'ok',cached:true}
 try{
  const text=await upstreamText('https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+def.code+',day,,,320,qfq',{fetcher,maxBytes:500000,headers:{'User-Agent':'Mozilla/5.0 (FinanceMonitor)','Referer':'https://gu.qq.com/'}})
  const bars=completedBars(parseRadarBars(JSON.parse(text),def.code),def.market,now)
  if(!bars.length)throw Error('NO_RADAR_HISTORY')
  const data={id,name:def.indexName??def.name,code:def.code,status:'ok',bars,lastSuccessAt:Date.now()}
  if(cache){const p=cache.put(key,Response.json(data,{headers:{'Cache-Control':'public,max-age=604800'}})).catch(()=>{});if(waitUntil)waitUntil(p);else await p}
  return data
 }catch{return {id,name:def.indexName??def.name,code:def.code,status:'failed',bars:old?.bars??[],lastSuccessAt:old?.lastSuccessAt??null,cached:Boolean(old),safeErrorCode:'INDEX_UNAVAILABLE'}}
}
export async function buildMarketRadar({loadIndex,loadMacro,now}={}){
 const defs=[...INDEXES.map(d=>({kind:'index',id:d.id})),...RADAR_MACRO.map(id=>({kind:'macro',id}))],results=new Array(defs.length);let next=0
 async function worker(){while(next<defs.length){const i=next++,d=defs[i];try{results[i]=await(d.kind==='index'?loadIndex(d.id):loadMacro(d.id))}catch{results[i]={id:d.id,status:'failed',bars:[],data:{},safeErrorCode:'SOURCE_UNAVAILABLE'}}}}
 await Promise.all(Array.from({length:4},worker))
 const index=Object.fromEntries(INDEXES.map((d,i)=>[d.id,results[i]])),macro=results.slice(INDEXES.length),series=Object.assign({},...macro.map(x=>x.data??{})),failed=macro.some(x=>x.status!=='ok')
 const data=deriveRadar(index,{series,failed},now??Date.now())
 return {...data,sources:results.map((r,i)=>({id:defs[i].id,name:r.name??defs[i].id,status:r.status,observedAt:defs[i].kind==='index'?r.bars?.at(-1)?.date??null:Object.values(r.data??{}).flatMap(rows=>rows.map(p=>p.date)).sort().at(-1)??null,lastSuccessAt:r.lastSuccessAt??null,cached:r.cached??false})),sourceErrors:results.filter(x=>x.status!=='ok').length}
}
export async function radarResponse({request,waitUntil,cache=globalThis.caches?.default}){
 const origin=new URL(request.url).origin
 const data=await buildMarketRadar({loadIndex:id=>loadRadarIndex(id,{origin,cache,waitUntil}),loadMacro:id=>loadRiskSource(id,{origin,cache,waitUntil,historyYears:2})})
 return Response.json(data,{headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}})
}
