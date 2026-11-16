import { authorized, jsonResponse, errorResponse } from './market-dashboard.js'

export const V4_VERSIONS = Object.freeze({schemaVersion:'market-dashboard-v4',sectorScoringVersion:'sector-score-v0.3',sectorUniverseVersion:'sector-universe-ths-v1',featureVersion:'sector-features-ths-v1',membershipVersion:'sector-membership-ths-v1'})
export const V4_MAX_BYTES = 131072
const axes = ['strength','opportunity','risk']
const record = v => v !== null && typeof v === 'object' && !Array.isArray(v)
const integer = (v,min,max) => Number.isInteger(v) && v>=min && v<=max
const finite = v => typeof v === 'number' && Number.isFinite(v)
const shape = (v,required,optional=[]) => record(v) && required.every(k=>Object.hasOwn(v,k)) && Object.keys(v).every(k=>required.includes(k)||optional.includes(k))
const safeText = (v,max=200) => typeof v==='string' && v.length<=max && !/[\u0000-\u001f]/.test(v) && !/\/Users\/|\/home\/|Bearer |authorization|api[_-]?key|token|password/i.test(v)
function check(v) { if(!v) throw new Error('INVALID_PAYLOAD') }
const batchId = v => typeof v==='string' && /^[a-zA-Z0-9_-]{1,100}$/.test(v)
const digest = v => typeof v==='string' && /^[a-f0-9]{64}$/.test(v)
export async function sha256(value) { return [...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(value)))].map(v=>v.toString(16).padStart(2,'0')).join('') }
export function validateV4Manifest(p) {
 check(shape(p,['batchId',...Object.keys(V4_VERSIONS),'sourceMode','observedAt','marketDate','session','officialClose','industryCount','conceptCount','chunkCount','digest']))
 check(batchId(p.batchId) && Object.entries(V4_VERSIONS).every(([k,v])=>p[k]===v) && p.sourceMode==='hithink')
 const time=Date.parse(p.observedAt)
 check(Number.isFinite(time) && new Date(time).toISOString()===p.observedAt && time<=Date.now()+300000)
 check(/^\d{4}-\d{2}-\d{2}$/.test(p.marketDate) && new Date(time+8*3600000).toISOString().slice(0,10)===p.marketDate)
 check(['intraday','close'].includes(p.session) && typeof p.officialClose==='boolean' && p.officialClose===(p.session==='close'))
 check(p.industryCount===90 && integer(p.conceptCount,1,10000) && integer(p.chunkCount,Math.ceil((90+p.conceptCount)/50),90+p.conceptCount) && digest(p.digest))
 return p
}
function scalarMap(v) { return record(v) && Object.entries(v).every(([k,x])=>/^[a-zA-Z][a-zA-Z0-9]*$/.test(k) && (x===null || typeof x==='boolean'||finite(x))) }
function component(v,depth=0) {
 if(depth>4 || !shape(v,['value','coverage','missing'],['usedWeight','totalWeight','effectiveWeight','parts'])) return false
 if(!(v.value===null||finite(v.value)&&v.value>=0&&v.value<=100) || !finite(v.coverage)||v.coverage<0||v.coverage>1 || !Array.isArray(v.missing)||!v.missing.every(x=>safeText(x))) return false
 if(['usedWeight','totalWeight','effectiveWeight'].some(k=>k in v&&(!finite(v[k])||v[k]<0||v[k]>100))) return false
 return !('parts' in v) || record(v.parts)&&Object.entries(v.parts).every(([k,x])=>/^[a-zA-Z][a-zA-Z0-9]*$/.test(k)&&component(x,depth+1))
}
export function validateV4Row(r,m) {
 check(shape(r,['id','name','universe',...axes,'completeness','ranks','heatState','coldStart','validCloses','improvementEvidence','membershipMode','conceptRole','missing'],['components','metrics','axisCompleteness','rankKeys']))
 check(['industry','concept'].includes(r.universe) && (r.universe==='industry'?/^881\d{3}\.TI$/:/^88[56]\d{3}\.TI$/).test(r.id) && safeText(r.name,100) && r.name.length>0)
 check(axes.every(a=>r[a]===null||integer(r[a],0,100)) && integer(r.completeness,0,100))
 const count=r.universe==='industry'?m.industryCount:m.conceptCount
 check(shape(r.ranks,axes) && axes.every(a=>r.ranks[a]===null||integer(r.ranks[a],1,count)))
 check([null,'cold','neutral','warming','active','crowded'].includes(r.heatState) && typeof r.coldStart==='boolean' && integer(r.validCloses,0,100000) && integer(r.improvementEvidence,0,3))
 check(['current_members_backfill','point_in_time_snapshot'].includes(r.membershipMode) && [null,'core','dynamic','candidate'].includes(r.conceptRole) && (r.universe==='concept'||r.conceptRole===null))
 check(Array.isArray(r.missing) && r.missing.length<=200 && r.missing.every(x=>safeText(x)))
 for(const key of ['metrics','axisCompleteness','rankKeys']) if(key in r) check(scalarMap(r[key]))
 if('components' in r) check(record(r.components)&&Object.entries(r.components).every(([k,v])=>/^[a-zA-Z][a-zA-Z0-9]*$/.test(k)&&component(v)))
 return r
}
export async function v4PublishRequest(request,env,action) {
 const token=env.MARKET_DASHBOARD_PUBLISH_TOKEN
 if(typeof token!=='string'||!token) return errorResponse('SERVICE_UNAVAILABLE',503)
 try { if(!await authorized(request,token)) return errorResponse('UNAUTHORIZED',401) } catch {return errorResponse('SERVICE_UNAVAILABLE',503)}
 if(env.HITHINK_PUBLIC_RELEASE_AUTHORIZATION!=='verified') return errorResponse('PUBLIC_RELEASE_NOT_AUTHORIZED',403)
 let p
 try {
  const reader=request.body?.getReader(); if(!reader) throw Error('INVALID_JSON')
  const chunks=[];let size=0
  try {while(true){const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>V4_MAX_BYTES){await reader.cancel();throw Error('PAYLOAD_TOO_LARGE')} chunks.push(value)}} finally {reader.releaseLock()}
  const bytes=new Uint8Array(size);let offset=0;for(const c of chunks){bytes.set(c,offset);offset+=c.byteLength}
  p=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes))
 } catch(e) {return errorResponse(e.message==='PAYLOAD_TOO_LARGE'?'PAYLOAD_TOO_LARGE':'INVALID_JSON',e.message==='PAYLOAD_TOO_LARGE'?413:400)}
 try {return await action(p,env.MARKET_DB)} catch(e) {
  if(e.message==='INVALID_PAYLOAD')return errorResponse('INVALID_PAYLOAD',400)
  if(e.message==='BATCH_CONFLICT')return errorResponse('BATCH_CONFLICT',409)
  return errorResponse('STORAGE_UNAVAILABLE',503)
 }
}
export const requireBatch = p => {check(shape(p,['batchId'])&&batchId(p.batchId));return p.batchId}
export async function getV4Manifest(db,id) {return db.prepare('SELECT * FROM sector_rotation_v4_manifests WHERE batch_id = ?').bind(id).first()}
export async function createV4Manifest(p,db) {
 validateV4Manifest(p)
 const serialized=JSON.stringify(Object.fromEntries(Object.keys(p).sort().map(k=>[k,p[k]])))
 const result=await db.prepare(`INSERT INTO sector_rotation_v4_manifests
 (batch_id,observed_at,market_date,session,official_close,schema_version,scoring_version,universe_version,feature_version,membership_version,industry_count,concept_count,chunk_count,digest,manifest_json,created_at)
 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(batch_id) DO NOTHING`).bind(p.batchId,p.observedAt,p.marketDate,p.session,p.officialClose?1:0,p.schemaVersion,p.sectorScoringVersion,p.sectorUniverseVersion,p.featureVersion,p.membershipVersion,p.industryCount,p.conceptCount,p.chunkCount,p.digest,serialized,new Date().toISOString()).run()
 const stored=await getV4Manifest(db,p.batchId)
 if(stored.manifest_json!==serialized)throw Error('BATCH_CONFLICT')
 return jsonResponse({ok:true,batchId:p.batchId,duplicate:result.meta.changes===0},result.meta.changes?201:200)
}
export async function uploadV4Chunk(p,db) {
 check(shape(p,['batchId','index','rowsJson','digest'])&&batchId(p.batchId)&&integer(p.index,0,10089)&&typeof p.rowsJson==='string'&&digest(p.digest))
 check(await sha256(p.rowsJson)===p.digest)
 let rows;try{rows=JSON.parse(p.rowsJson)}catch{throw Error('INVALID_PAYLOAD')}
 check(Array.isArray(rows)&&rows.length>0&&rows.length<=50)
 const m=await getV4Manifest(db,p.batchId);if(!m)throw Error('BATCH_CONFLICT')
 check(p.index<m.chunk_count)
 const manifest=validateV4Manifest(JSON.parse(m.manifest_json));rows.forEach(r=>validateV4Row(r,manifest))
 check(new Set(rows.map(r=>r.universe+':'+r.id)).size===rows.length)
 const old=await db.prepare('SELECT * FROM sector_rotation_v4_chunks WHERE batch_id=? AND chunk_index=?').bind(p.batchId,p.index).first()
 if(old){if(old.digest!==p.digest||old.rows_json!==p.rowsJson)throw Error('BATCH_CONFLICT');return jsonResponse({ok:true,duplicate:true})}
 if(m.status!=='staging')throw Error('BATCH_CONFLICT')
 const overlap=await db.prepare('SELECT sector_id,universe FROM sector_rotation_v4_sectors WHERE batch_id=?').bind(p.batchId).all()
 if(overlap.results.some(s=>rows.some(r=>r.id===s.sector_id&&r.universe===s.universe)))throw Error('BATCH_CONFLICT')
 const statements=[db.prepare('INSERT INTO sector_rotation_v4_chunks(batch_id,chunk_index,digest,row_count,rows_json) VALUES(?,?,?,?,?)').bind(p.batchId,p.index,p.digest,rows.length,p.rowsJson)]
 for(const r of rows)statements.push(db.prepare(`INSERT INTO sector_rotation_v4_sectors(batch_id,chunk_index,universe,sector_id,sector_name,strength,opportunity,risk,completeness,strength_rank,opportunity_rank,risk_rank,row_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)`).bind(p.batchId,p.index,r.universe,r.id,r.name,r.strength,r.opportunity,r.risk,r.completeness,r.ranks.strength,r.ranks.opportunity,r.ranks.risk,JSON.stringify(r)))
 try {await db.batch(statements)}catch(error){
  const retry=await db.prepare('SELECT digest,rows_json FROM sector_rotation_v4_chunks WHERE batch_id=? AND chunk_index=?').bind(p.batchId,p.index).first()
  if(retry?.digest===p.digest&&retry.rows_json===p.rowsJson)return jsonResponse({ok:true,duplicate:true})
  if(retry || /constraint|BATCH_FROZEN/i.test(error.message))throw Error('BATCH_CONFLICT')
  throw error
 }
 return jsonResponse({ok:true,duplicate:false},201)
}
export async function activateV4Manifest(p,db) {
 const id=requireBatch(p),m=await getV4Manifest(db,id);if(!m)throw Error('BATCH_CONFLICT')
 if(m.status==='active')return jsonResponse({ok:true,duplicate:true})
 const manifest=validateV4Manifest(JSON.parse(m.manifest_json))
 const chunks=(await db.prepare('SELECT * FROM sector_rotation_v4_chunks WHERE batch_id=? ORDER BY chunk_index').bind(id).all()).results
 if(chunks.length!==m.chunk_count)throw Error('BATCH_CONFLICT')
 const identities=new Set();let industries=0,concepts=0
 for(const [index,c] of chunks.entries()){
  if(c.chunk_index!==index||await sha256(c.rows_json)!==c.digest)throw Error('BATCH_CONFLICT')
  const rows=JSON.parse(c.rows_json);if(rows.length!==c.row_count)throw Error('BATCH_CONFLICT')
  for(const r of rows){validateV4Row(r,manifest);const key=r.universe+':'+r.id;if(identities.has(key))throw Error('BATCH_CONFLICT');identities.add(key);if(r.universe==='industry')industries++;else concepts++}
 }
 if(industries!==m.industry_count||concepts!==m.concept_count||await sha256(chunks.map(c=>c.digest).join('\n'))!==m.digest)throw Error('BATCH_CONFLICT')
 // Chunks/rows are append-only. Rechecking counts in this one atomic SQL statement
 // closes the gap between asynchronous digest validation and publication.
 const result=await db.prepare(`UPDATE sector_rotation_v4_manifests SET status='active',activated_at=?
 WHERE batch_id=? AND status='staging'
 AND (SELECT COUNT(*) FROM sector_rotation_v4_chunks WHERE batch_id=?)=chunk_count
 AND (SELECT SUM(row_count) FROM sector_rotation_v4_chunks WHERE batch_id=?)=industry_count+concept_count
 AND (SELECT COUNT(*) FROM sector_rotation_v4_sectors WHERE batch_id=? AND universe='industry')=industry_count
 AND (SELECT COUNT(*) FROM sector_rotation_v4_sectors WHERE batch_id=? AND universe='concept')=concept_count`).bind(new Date().toISOString(),id,id,id,id,id).run()
 if(!result.meta.changes&&(await getV4Manifest(db,id)).status!=='active')throw Error('BATCH_CONFLICT')
 return jsonResponse({ok:true,duplicate:!result.meta.changes})
}
