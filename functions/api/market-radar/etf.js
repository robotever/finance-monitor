import {authorized,readBoundedJson,errorResponse,jsonResponse} from '../../_lib/market-dashboard.js'
import {validateEtfBundle} from '../../../src/features/etf-observation/model.mjs'
import {readEtfObservation,publicationDate} from '../../_lib/etf-observation.js'
export async function onRequestGet({env}){
 const data=await readEtfObservation(env.MARKET_DB)
 return data?jsonResponse(data):errorResponse('ETF_OBSERVATION_UNAVAILABLE',503)
}
export async function onRequestPost({request,env}){
 if(!env.MARKET_DB||!env.MARKET_DASHBOARD_PUBLISH_TOKEN)return errorResponse('SERVICE_UNAVAILABLE',503)
 try{if(!await authorized(request,env.MARKET_DASHBOARD_PUBLISH_TOKEN))return errorResponse('UNAUTHORIZED',401)}catch{return errorResponse('UNAUTHORIZED',401)}
 let data,date
 try{data=validateEtfBundle(await readBoundedJson(request,1500000));date=publicationDate(data)}catch{return errorResponse('INVALID_ETF_OBSERVATION',400)}
 try{
  const old=await readEtfObservation(env.MARKET_DB)
  if(old&&(date<publicationDate(old)||Date.parse(data.generatedAt)<Date.parse(old.generatedAt)))return errorResponse('OBSOLETE_ETF_OBSERVATION',409)
  const result=await env.MARKET_DB.prepare('INSERT INTO etf_observation_latest(id,observed_at,market_date,payload_json) VALUES(1,?,?,?) ON CONFLICT(id) DO UPDATE SET observed_at=excluded.observed_at,market_date=excluded.market_date,payload_json=excluded.payload_json WHERE excluded.market_date>=etf_observation_latest.market_date AND julianday(excluded.observed_at)>=julianday(etf_observation_latest.observed_at)').bind(data.generatedAt,date,JSON.stringify(data)).run()
  if(result.meta?.changes===0)return errorResponse('OBSOLETE_ETF_OBSERVATION',409)
  if(result.success===false)return errorResponse('STORAGE_UNAVAILABLE',503)
  return jsonResponse({ok:true,marketDate:date})
 }catch{return errorResponse('STORAGE_UNAVAILABLE',503)}
}
