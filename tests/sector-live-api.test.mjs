import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { gzipSync } from 'node:zlib'
import { onRequestPost } from '../functions/api/sector-live/publish.js'
import { onRequestGet as manifest } from '../functions/api/sector-live/manifest.js'
import { onRequestGet as document } from '../functions/api/sector-live/document.js'
const migrations = [new URL('../migrations/0004_sector_live_documents.sql', import.meta.url)]
test('active document preserves gzip on the wire and streams JSON for identity clients',async()=>{
 const value={history:[{id:'885001.TI',name:'测试板块'}]},bytes=gzipSync(JSON.stringify(value))
 const db={prepare(){return{bind(){return this},async first(){return{activated_at:'2026-11-17T08:00:00Z'}},async all(){return{results:[{gzip_base64:bytes.toString('base64')}]}}}}}
 const url='https://example.test?generation='+'a'.repeat(64)+'&key=detail-885001.TI'
 const zipped=await document({request:new Request(url,{headers:{'Accept-Encoding':'gzip, br'}}),env:{MARKET_DB:db}})
 assert.equal(zipped.headers.get('Content-Encoding'),'gzip');assert.deepEqual(Buffer.from(await zipped.arrayBuffer()),bytes)
 const identity=await document({request:new Request(url),env:{MARKET_DB:db}})
 assert.deepEqual(await identity.json(),value)
})
test('detail summaries retain coverage and serve full members only for the requested date',async()=>{
 const members=n=>({total:n,validCount:n,rows:Array.from({length:n},(_,i)=>({code:String(i)}))})
 const value={history:[{marketDate:'2026-11-17'}],constituentsByDate:{'2026-11-17':members(20),'2026-11-16':members(30)}}
 const bytes=gzipSync(JSON.stringify(value)),db={prepare(){return{bind(){return this},async first(){return{activated_at:'2026-11-17T08:00:00Z'}},async all(){return{results:[{gzip_base64:bytes.toString('base64')}]}}}}}
 const url='https://example.test?generation='+'a'.repeat(64)+'&key=detail-885001.TI'
 const summary=await(await document({request:new Request(url+'&view=summary'),env:{MARKET_DB:db}})).json()
 assert.equal(summary.constituentsByDate['2026-11-16'].rows.length,10);assert.equal(summary.constituentsByDate['2026-11-16'].total,30)
 const all=await(await document({request:new Request(url+'&view=members&date=2026-11-16'),env:{MARKET_DB:db}})).json()
 assert.equal(all.rows.length,30);assert.equal((await document({request:new Request(url+'&view=members&date=2026-11-15'),env:{MARKET_DB:db}})).status,404)
})
function database(t) {
  const directory = mkdtempSync(join(tmpdir(), 'rotation-d1-'))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  const file = join(directory, 'db.sqlite')
  const execute = (sql, params = [], script = false) => JSON.parse(execFileSync('python3', ['-c', `
import json, sqlite3, sys
request = json.load(sys.stdin)
with sqlite3.connect(sys.argv[1]) as connection:
    connection.row_factory = sqlite3.Row
    if request['script']:
        connection.executescript(request['sql'])
        result = {'results': [], 'meta': {'changes': connection.total_changes}}
    else:
        cursor = connection.execute(request['sql'], request['params'])
        result = {'results': [dict(row) for row in cursor.fetchall()], 'meta': {'changes': max(cursor.rowcount, 0)}}
print(json.dumps(result))
`, file], { input: JSON.stringify({ sql, params, script }), encoding: 'utf8', stdio: ['pipe','pipe','pipe'] }))
  for (const migration of migrations) execute(readFileSync(migration, 'utf8'), [], true)
  const statement = (sql, params = []) => ({
    sql, params,
    bind: (...values) => statement(sql, values),
    run: async () => execute(sql, params),
    first: async () => execute(sql, params).results[0] ?? null,
    all: async () => execute(sql, params),
  })
  return {
    execute,
    prepare: sql => statement(sql),
    async batch(statements) {
      return JSON.parse(execFileSync('python3', ['-c', `
import json, sqlite3, sys
request = json.load(sys.stdin)
results = []
with sqlite3.connect(sys.argv[1]) as connection:
    connection.row_factory = sqlite3.Row
    for statement in request:
        cursor = connection.execute(statement['sql'], statement['params'])
        results.append({'results': [dict(row) for row in cursor.fetchall()], 'meta': {'changes': max(cursor.rowcount, 0)}})
print(json.dumps(results))
`, file], { input: JSON.stringify(statements.map(({ sql, params }) => ({ sql, params }))), encoding: 'utf8', stdio: ['pipe','pipe','pipe'] }))
    },
  }
}
const sha = value => createHash('sha256').update(value).digest('hex')
function fixture(observedAt='2026-11-17T08:00:00Z') {
 const keys=['latest','catalog-industry','catalog-concept',...['industry','concept'].flatMap(u=>['return1d','strength','opportunity','risk'].map(m=>`history-${u}-${m}`)),...Array.from({length:90},(_,i)=>`detail-881${String(i).padStart(3,'0')}.TI`),...Array.from({length:390},(_,i)=>`detail-885${String(i).padStart(3,'0')}.TI`)]
 const documents=keys.map(key=>{const bytes=gzipSync(JSON.stringify({key,rows:[]}));return {key,gzipBase64:bytes.toString('base64'),digest:sha(bytes)}})
 const digest=sha(documents.map(d=>d.key+':'+d.digest).sort().join('\n'))
 const generation=sha(observedAt)
 return {documents,begin:{action:'begin',generation,documentCount:491,digest,manifest:{generation,observedAt,marketDate:'2026-11-17',mode:'live',automaticUpdates:true,exportedAt:observedAt}}}
}
function context(db,url='https://example.test',body=null,token='test') { return {env:{MARKET_DB:db,MARKET_DASHBOARD_PUBLISH_TOKEN:'test'},request:new Request(url,body===null?{}:{method:'POST',headers:{Authorization:`Bearer ${token}`},body:JSON.stringify(body)})} }
const post=(db,body,token)=>onRequestPost(context(db,undefined,body,token))
async function upload(db,f) { assert.equal((await post(db,f.begin)).status,201); assert.equal((await post(db,{action:'documents',generation:f.begin.generation,documents:f.documents})).status,201) }
const activate=(db,f)=>post(db,{action:'activate',generation:f.begin.generation})
test('atomic staging, decompressed reads, immutable retries and older observation protection',async t=>{
 const db=database(t),f=fixture()
 assert.equal((await post(db,f.begin,'wrong')).status,401)
 assert.equal((await post(db,f.begin)).status,201)
 assert.equal((await post(db,f.begin)).status,200)
 assert.equal((await post(db,{...f.begin,digest:'0'.repeat(64)})).status,409)
 assert.equal((await activate(db,f)).status,409)
 assert.equal((await manifest(context(db))).status,404)
 const read=()=>document(context(db,`https://example.test?generation=${f.begin.generation}&key=latest`))
 assert.equal((await read()).status,404)
 assert.equal((await post(db,{action:'documents',generation:f.begin.generation,documents:f.documents})).status,201)
 assert.equal((await read()).status,404)
 assert.equal((await activate(db,f)).status,200)
 assert.equal((await activate(db,f)).status,200)
 assert.deepEqual(await (await read()).json(),{key:'latest',rows:[]})
 assert.equal((await (await manifest(context(db))).json()).generation,f.begin.generation)
 const old=fixture('2026-11-17T07:00:00Z');await upload(db,old);assert.equal((await activate(db,old)).status,409)
 assert.equal((await (await manifest(context(db))).json()).generation,f.begin.generation)
})
test('digest, gzip, document keys and private content fail closed',async t=>{
 const db=database(t),f=fixture();await post(db,f.begin)
 const send=d=>post(db,{action:'documents',generation:f.begin.generation,documents:[d]})
 assert.equal((await send({...f.documents[0],digest:'0'.repeat(64)})).status,400)
 assert.equal((await send({...f.documents[0],key:'detail-999000.TI'})).status,400)
 const bytes=gzipSync(JSON.stringify({apiKey:'private'}))
 assert.equal((await send({key:'latest',digest:sha(bytes),gzipBase64:bytes.toString('base64')})).status,400)
 assert.equal((await send({key:'latest',digest:sha('abc'),gzipBase64:Buffer.from('abc').toString('base64')})).status,400)
 assert.equal((await activate(db,f)).status,409)
})
test('multipart documents verify complete gzip before becoming publishable; health is finite',async t=>{
 const db=database(t),f=fixture();await post(db,f.begin)
 const full=gzipSync(JSON.stringify({rows:['示例'.repeat(300)]})),digest=sha(full),split=Math.floor(full.length/2)
 const parts=[full.subarray(0,split),full.subarray(split)].map((bytes,partIndex)=>({key:'latest',gzipBase64:bytes.toString('base64'),digest,partIndex,partCount:2,partDigest:sha(bytes)}))
 const send=documents=>post(db,{action:'documents',generation:f.begin.generation,documents})
 assert.equal((await send([parts[0]])).status,201)
 assert.equal(db.execute('SELECT COUNT(*) n FROM sector_live_documents').results[0].n,0)
 assert.equal((await send([parts[1]])).status,201)
 assert.equal(db.execute('SELECT COUNT(*) n FROM sector_live_documents').results[0].n,1)
 assert.equal((await send([parts[1]])).status,200)
 assert.equal((await send([{...parts[1],digest:'0'.repeat(64)}])).status,409)
 assert.equal((await post(db,{action:'health',status:{phase:'collection',state:'failed',safeErrorCode:'SOURCE_UNAVAILABLE',attemptedAt:'2026-11-17T07:00:00Z'}})).status,200)
 assert.equal((await post(db,{action:'health',status:{phase:'collection',state:'failed',safeErrorCode:'/Users/private',attemptedAt:'2026-11-17T07:00:00Z'}})).status,400)
})
test('activation checks aggregate digest and all identities, retains four activated generations',async t=>{
 const db=database(t),f=fixture()
 await post(db,f.begin)
 await db.batch(f.documents.map(d=>db.prepare('INSERT INTO sector_live_documents(generation,document_key,digest) VALUES(?,?,?)').bind(f.begin.generation,d.key,d.digest)))
 db.execute('UPDATE sector_live_generations SET digest=? WHERE generation=?',['0'.repeat(64),f.begin.generation])
 assert.equal((await activate(db,f)).status,409)
 db.execute('UPDATE sector_live_generations SET digest=? WHERE generation=?',[f.begin.digest,f.begin.generation])
 assert.equal((await activate(db,f)).status,200)
 for(let i=1;i<=4;i++) {
  const next=fixture(`2026-11-17T08:0${i}:00Z`);await post(db,next.begin)
  db.execute('INSERT INTO sector_live_documents(generation,document_key,digest) SELECT ?,document_key,digest FROM sector_live_documents WHERE generation=?',[next.begin.generation,f.begin.generation])
  assert.equal((await activate(db,next)).status,200)
 }
 assert.equal(db.execute('SELECT COUNT(*) n FROM sector_live_generations WHERE activated_at IS NOT NULL').results[0].n,4)
 assert.equal((await document(context(db,`https://example.test?generation=${f.begin.generation}&key=latest`))).status,404)
})
