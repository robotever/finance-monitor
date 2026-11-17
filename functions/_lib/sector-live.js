import { timestamp } from './market-dashboard.js'
export const HEX = /^[a-f0-9]{64}$/
const mandatory = ['latest','catalog-industry','catalog-concept', ...['industry','concept'].flatMap(u => ['return1d','strength','opportunity','risk'].map(m => `history-${u}-${m}`))]
export function validKey(key) { return typeof key === 'string' && (mandatory.includes(key) || /^detail-(881\d{3}|88[56]\d{3})\.TI$/.test(key)) }
export function check(value, code='INVALID_PAYLOAD') { if (!value) throw new Error(code) }
export async function sha(bytes) { return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(n=>n.toString(16).padStart(2,'0')).join('') }
export async function boundedJson(request) {
 const reader=request.body?.getReader();check(reader,'INVALID_JSON');const parts=[];let size=0
 while(true) {const {done,value}=await reader.read();if(done)break;size+=value.byteLength;if(size>1048576){await reader.cancel();throw new Error('PAYLOAD_TOO_LARGE')}parts.push(value)}
 const bytes=new Uint8Array(size);let i=0;for(const part of parts){bytes.set(part,i);i+=part.length}return JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes))
}
export function validateBegin(body) {
 check(HEX.test(body.generation) && HEX.test(body.digest) && body.documentCount===491)
 const m=body.manifest
 check(m && Object.keys(m).sort().join(',')==='automaticUpdates,exportedAt,generation,marketDate,mode,observedAt')
 check(m.generation===body.generation && m.mode==='live' && m.automaticUpdates===true && /^\d{4}-\d{2}-\d{2}$/.test(m.marketDate))
 timestamp(`${m.marketDate}T00:00:00Z`); const observed=timestamp(m.observedAt);timestamp(m.exportedAt)
 check(observed.millis<=Date.now()+300000)
 return {manifest:JSON.stringify(m),observed:new Date(observed.millis).toISOString()}
}
export function decode64(value) {
 check(typeof value==='string' && value.length>0 && value.length<=960000 && /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(value))
 const bytes=Uint8Array.from(atob(value),c=>c.charCodeAt(0));check(bytes.length<=700*1024);return bytes
}
function inspect(value,depth=0,seenKeys=new Set(),seenStrings=new Set()) {
 check(depth<100)
 if(typeof value==='string'&&!seenStrings.has(value)) {
  check(!/(?:Bearer\s+[A-Za-z0-9._-]+|\/(?:Users|home|private|tmp)\/|[A-Za-z]:\\|sk-[A-Za-z0-9]{16}|[?&](?:api_?key|access_?token|token|password|secret)=|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY)/i.test(value));seenStrings.add(value)
 }
 if(value && typeof value==='object') for(const key in value) {
  if(!seenKeys.has(key)){check(!/(?:api.?key|access.?token|refresh.?token|authorization|password|secret|credential|cookie|private.?key|local.?path|file.?path)/i.test(key));seenKeys.add(key)}
  inspect(value[key],depth+1,seenKeys,seenStrings)
 }
}
export async function inflate(bytes) {
 check(bytes[0]===31 && bytes[1]===139)
 const reader=new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip')).getReader();const parts=[];let size=0
 while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>32*1024*1024){await reader.cancel();throw new Error('INVALID_PAYLOAD')}parts.push(value)}
 const output=new Uint8Array(size);let offset=0;for(const part of parts){output.set(part,offset);offset+=part.length}
 const text=new TextDecoder('utf-8',{fatal:true}).decode(output);const value=JSON.parse(text);check(value && typeof value==='object');inspect(value);return text
}
export function concatenate(parts) {const chunks=parts.map(p=>decode64(p.gzip_base64));const n=chunks.reduce((a,b)=>a+b.length,0);check(n<=16*700*1024);const out=new Uint8Array(n);let offset=0;for(const c of chunks){out.set(c,offset);offset+=c.length}return out}
export async function completeDocument(db,generation,key,validatedSingle=false) {
 const {results:parts}=await db.prepare('SELECT * FROM sector_live_parts WHERE generation=? AND document_key=? ORDER BY part_index').bind(generation,key).all()
 if(!parts.length || parts.length!==parts[0].part_count)return false
 check(parts.every((p,i)=>p.part_index===i && p.digest===parts[0].digest && p.part_count===parts.length),'DOCUMENT_CONFLICT')
 const bytes=concatenate(parts);check(await sha(bytes)===parts[0].digest);if(!(validatedSingle&&parts.length===1))await inflate(bytes)
 await db.prepare('INSERT OR IGNORE INTO sector_live_documents(generation,document_key,digest) VALUES(?,?,?)').bind(generation,key,parts[0].digest).run();return true
}
export function validateKeys(documents) {
 const keys=documents.map(d=>d.document_key);check(keys.length===491 && new Set(keys).size===491 && mandatory.every(k=>keys.includes(k)) && keys.every(validKey),'INCOMPLETE_GENERATION')
 check(keys.filter(k=>/^detail-881/.test(k)).length===90 && keys.filter(k=>/^detail-88[56]/.test(k)).length===390,'INCOMPLETE_GENERATION')
}
