import { jsonResponse,errorResponse } from '../../_lib/market-dashboard.js'
export async function onRequestGet({env}) {
 if(!env.MARKET_DB)return errorResponse('SERVICE_UNAVAILABLE',503)
 try {
 const row=await env.MARKET_DB.prepare('SELECT g.manifest_json FROM sector_live_active a JOIN sector_live_generations g ON g.generation=a.generation WHERE a.id=1 AND g.activated_at IS NOT NULL').first()
 if(!row)return errorResponse('NO_SNAPSHOT',404)
 const health=await env.MARKET_DB.prepare('SELECT status_json FROM sector_live_health WHERE id=1').first()
 return jsonResponse({...JSON.parse(row.manifest_json),publishHealth:health?JSON.parse(health.status_json):null})
 }catch{return errorResponse('SERVICE_UNAVAILABLE',503)}
}
