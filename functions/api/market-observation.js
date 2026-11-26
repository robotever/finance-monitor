import {authorized,readBoundedJson,errorResponse,jsonResponse} from '../_lib/market-dashboard.js'
import {readMarketObservation} from '../_lib/market-observation.js'
import {validateMarketObservation} from '../../src/features/market-observation/model.mjs'
export async function onRequestGet({env}){const p=await readMarketObservation(env.MARKET_DB);return p?jsonResponse(p):errorResponse('MARKET_OBSERVATION_UNAVAILABLE',503)}
export async function onRequestPost({request,env}){
 if(!env.MARKET_DB||!env.MARKET_DASHBOARD_PUBLISH_TOKEN)return errorResponse('SERVICE_UNAVAILABLE',503)
 try{if(!await authorized(request,env.MARKET_DASHBOARD_PUBLISH_TOKEN))return errorResponse('UNAUTHORIZED',401)}catch{return errorResponse('UNAUTHORIZED',401)}
 let p;try{p=validateMarketObservation(await readBoundedJson(request,1000000))}catch{return errorResponse('INVALID_MARKET_OBSERVATION',400)}
 try{
  const old=await readMarketObservation(env.MARKET_DB)
  if(old&&(p.marketDate<old.marketDate||Date.parse(p.snapshotAt)<Date.parse(old.snapshotAt)||Date.parse(p.observedAt)<Date.parse(old.observedAt)))return errorResponse('OBSOLETE_MARKET_OBSERVATION',409)
  const r=await env.MARKET_DB.prepare('INSERT INTO market_observation_latest(id,market_date,snapshot_at,observed_at,payload_json) VALUES(1,?,?,?,?) ON CONFLICT(id) DO UPDATE SET market_date=excluded.market_date,snapshot_at=excluded.snapshot_at,observed_at=excluded.observed_at,payload_json=excluded.payload_json WHERE excluded.market_date>=market_observation_latest.market_date AND julianday(excluded.snapshot_at)>=julianday(market_observation_latest.snapshot_at) AND julianday(excluded.observed_at)>=julianday(market_observation_latest.observed_at)').bind(p.marketDate,p.snapshotAt,p.observedAt,JSON.stringify(p)).run()
  if(r.meta?.changes===0)return errorResponse('OBSOLETE_MARKET_OBSERVATION',409)
  if(r.success===false)return errorResponse('STORAGE_UNAVAILABLE',503)
  return jsonResponse({ok:true,marketDate:p.marketDate,snapshotAt:p.snapshotAt})
 }catch{return errorResponse('STORAGE_UNAVAILABLE',503)}
}
