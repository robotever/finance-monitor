import { errorResponse } from '../../_lib/market-dashboard.js'
import { HEX,validKey,concatenate,readDocument,dailySources,mergeDailyDetails } from '../../_lib/sector-live.js'
export async function onRequestGet({request,env}) {
 const params=new URL(request.url).searchParams,generation=params.get('generation'),key=params.get('key')
 if(params.getAll('generation').length!==1 || params.getAll('key').length!==1 || !HEX.test(generation??'') || !validKey(key))return errorResponse('INVALID_PAYLOAD',400)
 const view=params.get('view'),day=params.get('date')
 if([...params.keys()].some(k=>!['generation','key','view','date'].includes(k))||params.getAll('view').length>1||params.getAll('date').length>1)return errorResponse('INVALID_PAYLOAD',400)
 if(view!==null&&(!key.startsWith('detail-')||!['summary','members'].includes(view)||view==='members'&&!/^\d{4}-\d{2}-\d{2}$/.test(day??'')))return errorResponse('INVALID_PAYLOAD',400)
 if(!env.MARKET_DB)return errorResponse('SERVICE_UNAVAILABLE',503)
 try {
 const row=await env.MARKET_DB.prepare('SELECT generation,manifest_json,observed_at,activated_at FROM sector_live_generations WHERE generation=? AND activated_at IS NOT NULL').bind(generation).first()
 if(!row)return errorResponse('NO_SNAPSHOT',404)
 const {results}=await env.MARKET_DB.prepare('SELECT * FROM sector_live_parts WHERE generation=? AND document_key=? ORDER BY part_index').bind(generation,key).all()
 if(!results.length)return errorResponse('NO_SNAPSHOT',404)
 const bytes=concatenate(results),headers={'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Vary':'Accept-Encoding'}
 const acceptsGzip=/\bgzip\b/i.test(request.headers.get('Accept-Encoding')??'')
 const jsonView=value=>{
  const text=JSON.stringify(value)
  return acceptsGzip?new Response(new Blob([text]).stream().pipeThrough(new CompressionStream('gzip')),{headers:{...headers,'Content-Encoding':'gzip'},encodeBody:'manual'}):new Response(text,{headers})
 }
 const manifest=row.manifest_json?JSON.parse(row.manifest_json):{}
 if(manifest.storageMode==='daily-v1' && key.startsWith('detail-')) {
  const current=JSON.parse(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text())
  if(view==='members' && current.constituentsByDate?.[day])return jsonView(current.constituentsByDate[day])
  const sources=await dailySources(env.MARKET_DB,row,manifest)
  if(view==='members') {
   const source=sources.find(source=>JSON.parse(source.manifest_json).marketDate===day)
   const detail=await readDocument(env.MARKET_DB,source?.generation??manifest.historyBaseGeneration,key)
   const members=detail?.constituentsByDate?.[day]
   return members?jsonView(members):errorResponse('NO_SNAPSHOT',404)
  }
  const base=await readDocument(env.MARKET_DB,manifest.historyBaseGeneration,key)
  if(!base)return errorResponse('NO_SNAPSHOT',404)
  const details=[]
  for(const source of sources)details.push(source.generation===generation?current:await readDocument(env.MARKET_DB,source.generation,key))
  const value=mergeDailyDetails(base,details,current,manifest.marketDate)
  if(view==='summary')value.constituentsByDate=Object.fromEntries(Object.entries(value.constituentsByDate).map(([date,m])=>[date,{...m,rows:m.rows.slice(0,10)}]))
  return jsonView(value)
 }
 if(view){
  const text=await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).text(),value=JSON.parse(text)
  if(view==='members'){
   const members=value.constituentsByDate?.[day]
   if(!members)return errorResponse('NO_SNAPSHOT',404)
   return jsonView(members)
  }
  value.constituentsByDate=Object.fromEntries(Object.entries(value.constituentsByDate??{}).map(([date,m])=>[date,{...m,rows:m.rows.slice(0,10)}]))
  return jsonView(value)
 }
 // Active documents already passed hash, JSON and privacy validation. Serve
 // their original gzip directly; large constituent histories need not be
 // inflated, parsed and revalidated on every browser read.
 if(acceptsGzip)return new Response(bytes,{headers:{...headers,'Content-Encoding':'gzip'},encodeBody:'manual'})
 return new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')),{headers})
 }catch{return errorResponse('SERVICE_UNAVAILABLE',503)}
}
