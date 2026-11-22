import {createHash,randomUUID} from 'node:crypto'
import {mkdir,readFile,writeFile,rename,unlink} from 'node:fs/promises'
import {join,resolve} from 'node:path'
import {buildMarketRadar,loadRadarIndex} from '../../functions/_lib/market-radar.js'
import {buildCrossMarketRisk,loadRiskSource,RISK_SOURCES} from '../../functions/_lib/cross-market-risk.js'
import {validateInputs} from '../../functions/_lib/radar-inputs.js'
import {INDEXES,RADAR_VERSION} from '../../src/features/market-radar/model.mjs'
import {RISK_VERSION} from '../../src/features/cross-market-risk/model.mjs'
import {validDate} from '../../src/features/cross-market-risk/parsers.mjs'

const DEFAULT_INPUTS='/Users/robot_ever/Codex/Financial Knowledge Repository/state/market-radar-inputs/latest.json'
const origin='http://finance-monitor.local'
const maxCacheBytes=2000000
function cacheDefinition(request){
 const url=new URL(typeof request==='string'?request:request.url)
 if(url.search||url.hash)throw Error('INVALID_SOURCE_CACHE_KEY')
 for(const def of INDEXES)if(url.pathname===`/api/market-radar/cache/${RADAR_VERSION}/${def.id}`)return {key:url.pathname,kind:'index',id:def.id}
 for(const def of RISK_SOURCES)for(const suffix of ['','/two-years'])if(url.pathname===`/api/cross-market/source-cache/${RISK_VERSION}/${def.id}${suffix}`)return {key:url.pathname,kind:'risk',id:def.id,roles:def.roles}
 throw Error('INVALID_SOURCE_CACHE_KEY')
}
function validRows(rows,value){
 let prior=''
 return Array.isArray(rows)&&rows.length<=20000&&rows.every(row=>{
  if(!row||!validDate(row.date)||row.date<=prior||!Number.isFinite(row[value]))return false
  prior=row.date
  return value!=='close'||row.close>0&&(row.volume===null||Number.isFinite(row.volume)&&row.volume>0)
 })
}
function validPayload(payload,def){
 if(!payload||payload.id!==def.id||!Number.isFinite(payload.lastSuccessAt)||payload.lastSuccessAt<0)return false
 if(def.kind==='index')return validRows(payload.bars,'close')&&payload.bars.length>0
 return payload.data&&Object.keys(payload.data).length===def.roles.length&&def.roles.every(role=>validRows(payload.data[role],'value'))&&def.roles.some(role=>payload.data[role].length)
}
/** Cache API subset; only known public source keys map to fixed hashed filenames. */
export function createDiskSourceCache(directory){
 const root=resolve(directory)
 const pathFor=key=>join(root,createHash('sha256').update(key).digest('hex')+'.json')
 return {
  async match(request){
   const def=cacheDefinition(request)
   try{
    const body=await readFile(pathFor(def.key),'utf8');if(Buffer.byteLength(body)>maxCacheBytes)return undefined
    const saved=JSON.parse(body)
    if(saved.key!==def.key||!validPayload(saved.payload,def))return undefined
    return Response.json(saved.payload)
   }catch{return undefined}
  },
  async put(request,response){
   const def=cacheDefinition(request),body=await response.text()
   if(Buffer.byteLength(body)>maxCacheBytes)throw Error('INVALID_SOURCE_CACHE_DATA')
   const payload=JSON.parse(body)
   if(!validPayload(payload,def))throw Error('INVALID_SOURCE_CACHE_DATA')
   await mkdir(root,{recursive:true})
   const target=pathFor(def.key),temporary=target+'.'+randomUUID()+'.tmp'
   try{await writeFile(temporary,JSON.stringify({key:def.key,payload}),{mode:0o600});await rename(temporary,target)}finally{await unlink(temporary).catch(()=>{})}
  },
 }
}

function localStatus(data,offline){
 const observed=data.sources.filter(source=>source.observedAt!==null)
 const times=data.sources.map(source=>source.lastSuccessAt).filter(Number.isFinite)
 const mode=!observed.length?'empty':data.sourceErrors===0?'live':observed.every(source=>source.cached)?'cached':'partial'
 return {mode,lastSuccessAt:times.length?Math.max(...times):null,...(mode==='live'?{}:{note:mode==='empty'?'本地尚无有效源数据':offline?'离线使用已保存观测；失败与滞后状态保留':'部分公开源暂不可用；保留原观测日期与失败状态'})}
}

/** Reuse the production models against local validated inputs and public source caches. */
export function createLocalResearchData({stateRoot,radarInputsPath=DEFAULT_INPUTS,fetcher=fetch,now,offline=false}={}){
 if(typeof stateRoot!=='string'||!stateRoot)throw Error('LOCAL_STATE_ROOT_REQUIRED')
 const cache=createDiskSourceCache(join(stateRoot,'research-source-cache'))
 const clock=()=>typeof now==='function'?now():now??Date.now()
 const publicFetcher=offline?async()=>{throw Error('OFFLINE')}:fetcher
 const resultStatus=result=>offline?{...result,status:'failed',cached:result.cached??false,safeErrorCode:'OFFLINE'}:result
 const source=(id,checkedAt,historyYears)=>loadRiskSource(id,{cache,origin,fetcher:publicFetcher,now:checkedAt,historyYears}).then(resultStatus)
 const index=(id,checkedAt)=>loadRadarIndex(id,{cache,origin,fetcher:publicFetcher,now:checkedAt}).then(resultStatus)
 async function readLocalInputs(checkedAt){
  try{
   const text=await readFile(radarInputsPath,'utf8')
   if(Buffer.byteLength(text)>500000)return {value:null,status:'invalid'}
   return {value:validateInputs(JSON.parse(text),checkedAt),status:'ok'}
  }catch(error){return {value:null,status:error.code==='ENOENT'?'missing':'invalid'}}
 }
 return {
  async radar(){
   const checkedAt=clock(),inputs=await readLocalInputs(checkedAt)
   const data=await buildMarketRadar({now:checkedAt,loadIndex:id=>index(id,checkedAt),loadMacro:id=>source(id,checkedAt,2),loadInputs:async()=>inputs.value})
   return {...data,localMode:{offline,inputsStatus:inputs.status},localStatus:localStatus(data,offline)}
  },
  async risk(){
   const checkedAt=clock(),data=await buildCrossMarketRisk({now:checkedAt,loadSource:id=>source(id,checkedAt)})
   return {...data,localMode:{offline},localStatus:localStatus(data,offline)}
  },
 }
}
