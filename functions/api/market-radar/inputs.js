import {authorized,readBoundedJson,errorResponse,jsonResponse} from '../../_lib/market-dashboard.js'
import {validateInputs,readInputs} from '../../_lib/radar-inputs.js'
export async function onRequestGet({env}){
 const p=await readInputs(env.MARKET_DB)
 return p?jsonResponse(p):errorResponse('INPUTS_UNAVAILABLE',503)
}
export async function onRequestPost({request,env}){
 if(!env.MARKET_DB||!env.MARKET_DASHBOARD_PUBLISH_TOKEN)return errorResponse('SERVICE_UNAVAILABLE',503)
 try{if(!await authorized(request,env.MARKET_DASHBOARD_PUBLISH_TOKEN))return errorResponse('UNAUTHORIZED',401)}catch{return errorResponse('UNAUTHORIZED',401)}
 let p
 try{p=validateInputs(await readBoundedJson(request,600000))}catch{return errorResponse('INVALID_RADAR_INPUTS',400)}
 try{
  const latest=await readInputs(env.MARKET_DB)
  if(latest&&(p.marketDate<latest.marketDate||p.marketDate===latest.marketDate&&Date.parse(p.observedAt)<Date.parse(latest.observedAt)))return errorResponse('OBSOLETE_INPUTS',409)
  await env.MARKET_DB.prepare('INSERT INTO radar_input_batches(observed_at,market_date,payload_json) VALUES(?,?,?) ON CONFLICT(observed_at) DO NOTHING').bind(p.observedAt,p.marketDate,JSON.stringify(p)).run()
  return jsonResponse({ok:true,marketDate:p.marketDate})
 }catch{return errorResponse('STORAGE_UNAVAILABLE',503)}
}
