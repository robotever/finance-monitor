import { authorized, jsonResponse, errorResponse, timestamp } from '../../_lib/market-dashboard.js'
import { HEX, check, boundedJson, validateBegin, validKey, decode64, sha, completeDocument, validateKeys, inflate, obsoleteGenerations } from '../../_lib/sector-live.js'
export async function onRequestPost({request,env}) {
 const token=env.MARKET_DASHBOARD_PUBLISH_TOKEN
 if(!token || !env.MARKET_DB)return errorResponse('SERVICE_UNAVAILABLE',503)
 try {if(!await authorized(request,token))return errorResponse('UNAUTHORIZED',401)}catch{return errorResponse('SERVICE_UNAVAILABLE',503)}
 const db=env.MARKET_DB
 try {
  const body=await boundedJson(request)
  if(body.action==='health') {
   const s=body.status;check(s && ['collection','publication'].includes(s.phase) && ['failed','success'].includes(s.state) && (s.safeErrorCode===null || ['COLLECTION_FAILED','PUBLICATION_FAILED','SOURCE_UNAVAILABLE','NETWORK_ERROR','TIMEOUT','INVALID_PAYLOAD','NO_SNAPSHOT'].includes(s.safeErrorCode)))
   timestamp(s.attemptedAt);check(Object.keys(s).sort().join(',')==='attemptedAt,phase,safeErrorCode,state')
   await db.prepare('INSERT INTO sector_live_health(id,status_json) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET status_json=excluded.status_json').bind(JSON.stringify(s)).run();return jsonResponse({ok:true})
  }
  check(HEX.test(body.generation))
  if(body.action==='begin') {
   const m=validateBegin(body)
   if(body.manifest.storageMode==='daily-v1') {
    check(await sha(new TextEncoder().encode('daily-v1\n'+body.manifest.sourceGeneration))===body.generation)
    const base=await db.prepare('SELECT manifest_json,observed_at FROM sector_live_generations WHERE generation=? AND activated_at IS NOT NULL').bind(body.manifest.historyBaseGeneration).first()
    check(base && !JSON.parse(base.manifest_json).storageMode && base.observed_at<=m.observed)
   }
   const inserted=await db.prepare('INSERT OR IGNORE INTO sector_live_generations(generation,manifest_json,observed_at,digest,document_count) VALUES(?,?,?,?,491)').bind(body.generation,m.manifest,m.observed,body.digest).run()
   const existing=await db.prepare('SELECT * FROM sector_live_generations WHERE generation=?').bind(body.generation).first()
   check(existing.manifest_json===m.manifest && existing.digest===body.digest,'GENERATION_CONFLICT')
   return jsonResponse({ok:true,generation:body.generation},inserted.meta.changes?201:200)
  }
  const generation=await db.prepare('SELECT * FROM sector_live_generations WHERE generation=?').bind(body.generation).first();check(generation,'UNKNOWN_GENERATION')
  if(body.action==='documents') {
   check(Array.isArray(body.documents) && body.documents.length>0 && body.documents.length<=491)
   const statements=[];const keys=new Set(),validatedSingle=new Set();let inserted=0
   for(const d of body.documents) {
    const index=d.partIndex??0,count=d.partCount??1,partDigest=d.partDigest??d.digest
    check(validKey(d.key) && HEX.test(d.digest) && HEX.test(partDigest) && Number.isInteger(index) && Number.isInteger(count) && count>=1 && count<=16 && index>=0 && index<count)
    const bytes=decode64(d.gzipBase64);check(await sha(bytes)===partDigest)
    if(count===1){check(partDigest===d.digest);await inflate(bytes);validatedSingle.add(d.key)}
    const existing=await db.prepare('SELECT part_digest,digest,part_count FROM sector_live_parts WHERE generation=? AND document_key=? AND part_index=?').bind(body.generation,d.key,index).first()
    if(existing)check(existing.part_digest===partDigest && existing.digest===d.digest && existing.part_count===count,'DOCUMENT_CONFLICT');else inserted++
    statements.push(db.prepare('INSERT OR IGNORE INTO sector_live_parts(generation,document_key,part_index,part_count,digest,part_digest,gzip_base64) VALUES(?,?,?,?,?,?,?)').bind(body.generation,d.key,index,count,d.digest,partDigest,d.gzipBase64));keys.add(d.key)
   }
   for(let i=0;i<statements.length;i+=90)await db.batch(statements.slice(i,i+90))
   for(const key of keys)await completeDocument(db,body.generation,key,validatedSingle.has(key))
   return jsonResponse({ok:true,generation:body.generation},inserted?201:200)
  }
  check(body.action==='activate')
  const {results:documents}=await db.prepare('SELECT document_key,digest FROM sector_live_documents WHERE generation=? ORDER BY document_key').bind(body.generation).all()
  validateKeys(documents);check(await sha(new TextEncoder().encode(documents.map(d=>`${d.document_key}:${d.digest}`).join('\n')))===generation.digest,'DIGEST_MISMATCH')
  await db.batch([
   db.prepare('INSERT INTO sector_live_active(id,generation,observed_at) VALUES(1,?,?) ON CONFLICT(id) DO UPDATE SET generation=excluded.generation,observed_at=excluded.observed_at WHERE excluded.observed_at>sector_live_active.observed_at').bind(body.generation,generation.observed_at),
   db.prepare('UPDATE sector_live_generations SET activated_at=COALESCE(activated_at,?) WHERE generation=? AND EXISTS(SELECT 1 FROM sector_live_active WHERE generation=?)').bind(new Date().toISOString(),body.generation,body.generation),
  ])
  const active=await db.prepare('SELECT generation FROM sector_live_active WHERE id=1').first();check(active?.generation===body.generation,'STALE_GENERATION')
  const obsolete=obsoleteGenerations
  await db.batch([
   db.prepare(`DELETE FROM sector_live_parts WHERE generation IN (${obsolete})`),
   db.prepare(`DELETE FROM sector_live_documents WHERE generation IN (${obsolete})`),
   db.prepare(`DELETE FROM sector_live_generations WHERE generation IN (${obsolete})`),
  ])
  return jsonResponse({ok:true,generation:body.generation})
 }catch(error){const code=error.message;const conflicts=['GENERATION_CONFLICT','DOCUMENT_CONFLICT','UNKNOWN_GENERATION','INCOMPLETE_GENERATION','DIGEST_MISMATCH','STALE_GENERATION'];return errorResponse(conflicts.includes(code)?code:code==='PAYLOAD_TOO_LARGE'?code:'INVALID_PAYLOAD',code==='PAYLOAD_TOO_LARGE'?413:conflicts.includes(code)?409:400)}
}
