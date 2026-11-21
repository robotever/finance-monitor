import {buildCrossMarketRisk,loadRiskSource} from '../../_lib/cross-market-risk.js'
export async function onRequestGet({request,waitUntil}){
 const origin=new URL(request.url).origin,cache=globalThis.caches?.default
 const data=await buildCrossMarketRisk({loadSource:id=>loadRiskSource(id,{cache,origin,waitUntil})})
 return Response.json(data,{headers:{'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}})
}
