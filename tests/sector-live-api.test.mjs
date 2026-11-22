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
const migrations = ['0004_sector_live_documents.sql','0005_sector_live_daily_index.sql'].map(name=>new URL('../migrations/'+name,import.meta.url))
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

// Seed complete document identities with one SQLite transaction. Network transport,
// gzip integrity and staging are exercised above; archive tests focus on time semantics.
async function seed(db,observedAt,{base=null,day=observedAt.slice(0,10),label=day,days=[day],activated=true}={}) {
 const f=fixture(observedAt)
 if(base) {
  const sourceGeneration=sha(observedAt)
  f.begin.generation=sha('daily-v1\n'+sourceGeneration)
  Object.assign(f.begin.manifest,{generation:f.begin.generation,storageMode:'daily-v1',sourceGeneration,historyBaseGeneration:base})
 }
 f.begin.manifest.marketDate=day
 assert.equal((await post(db,f.begin)).status,201)
 const value={batchId:f.begin.generation,history:days.map(marketDate=>({marketDate,label})),constituentsByDate:Object.fromEntries(days.map(date=>[date,{total:25,validCount:25,rows:Array.from({length:25},(_,i)=>({code:String(i),label}))}]))}
 const bytes=gzipSync(JSON.stringify(value)),digest=sha(bytes)
 const statements=f.documents.map(d=>db.prepare('INSERT INTO sector_live_documents(generation,document_key,digest) VALUES(?,?,?)').bind(f.begin.generation,d.key,d.digest))
 statements.push(db.prepare('INSERT INTO sector_live_parts(generation,document_key,part_index,part_count,digest,part_digest,gzip_base64) VALUES(?,?,0,1,?,?,?)').bind(f.begin.generation,'detail-885001.TI',digest,digest,bytes.toString('base64')))
 if(activated)statements.push(db.prepare('UPDATE sector_live_generations SET activated_at=? WHERE generation=?').bind(observedAt,f.begin.generation))
 await db.batch(statements)
 return f
}
const detailRead=(db,f,query='')=>document(context(db,`https://example.test?generation=${f.begin.generation}&key=detail-885001.TI${query}`))
test('daily begin validates exact optional trio, immutable identity and activated legacy baseline',async t=>{
 const db=database(t),base=await seed(db,'2026-11-15T00:00:00Z'),f=fixture('2026-11-16T00:00:00Z')
 const sourceGeneration=sha('daily source'),generation=sha('daily-v1\n'+sourceGeneration)
 Object.assign(f.begin,{generation});Object.assign(f.begin.manifest,{generation,storageMode:'daily-v1',sourceGeneration,historyBaseGeneration:base.begin.generation})
 assert.equal((await post(db,f.begin)).status,201)
 const invalid=structuredClone(f.begin);delete invalid.manifest.sourceGeneration
 assert.equal((await post(db,invalid)).status,400)
 assert.equal((await post(db,{...f.begin,generation:'f'.repeat(64),manifest:{...f.begin.manifest,generation:'f'.repeat(64)}})).status,400)
 const missing=structuredClone(f.begin);missing.manifest.historyBaseGeneration='0'.repeat(64)
 assert.equal((await post(db,missing)).status,400)
 const daily=await seed(db,'2026-11-16T01:00:00Z',{base:base.begin.generation})
 const chained=structuredClone(f.begin);chained.manifest.historyBaseGeneration=daily.begin.generation
 assert.equal((await post(db,chained)).status,400)
})
test('daily details expand baseline and daily dates while pinned readers never see future revisions',async t=>{
 const db=database(t),base=await seed(db,'2026-11-15T15:00:00Z',{days:['2026-11-14','2026-11-15'],label:'baseline'})
 const early=await seed(db,'2026-11-16T01:00:00Z',{base:base.begin.generation,label:'early16'})
 const late=await seed(db,'2026-11-16T02:00:00Z',{base:base.begin.generation,label:'close16'})
 const next=await seed(db,'2026-11-17T01:00:00Z',{base:base.begin.generation,label:'current17'})
 const full=await(await detailRead(db,next)).json()
 assert.deepEqual(full.history.map(p=>p.marketDate),['2026-11-14','2026-11-15','2026-11-16','2026-11-17'])
 assert.equal(full.history.find(p=>p.marketDate==='2026-11-16').label,'close16')
 assert.equal(full.batchId,next.begin.generation)
 const summary=await(await detailRead(db,next,'&view=summary')).json()
 assert.equal(summary.constituentsByDate['2026-11-16'].rows.length,10)
 assert.equal(summary.constituentsByDate['2026-11-16'].total,25)
 const members=await(await detailRead(db,next,'&view=members&date=2026-11-16')).json()
 assert.equal(members.rows.length,25);assert.equal(members.rows[0].label,'close16')
 assert.equal((await(await detailRead(db,early)).json()).history.at(-1).label,'early16')
 assert.equal((await detailRead(db,early,'&view=members&date=2026-11-17')).status,404)
 assert.equal((await(await detailRead(db,next,'&view=members&date=2026-11-15')).json()).rows[0].label,'baseline')
 assert.equal((await(await detailRead(db,late)).json()).history.at(-1).label,'close16')
})
test('daily retention keeps date closes and pinned legacy baseline through intraday rotations',async t=>{
 const db=database(t),base=await seed(db,'2026-10-28T00:00:00Z'),daily=[]
 // Dates remain in the past even when tests run on November 17.
 for(let i=1;i<=17;i++)daily.push(await seed(db,`2026-11-${String(i).padStart(2,'0')}T00:00:00Z`,{base:base.begin.generation}))
 const current=daily.at(-1)
 const oldestBefore=await(await detailRead(db,daily[2])).json()
 assert.equal((await activate(db,current)).status,200)
 assert.ok(db.execute('SELECT generation FROM sector_live_generations WHERE generation=?',[base.begin.generation]).results.length)
 assert.equal(db.execute("SELECT COUNT(*) n FROM sector_live_generations WHERE json_extract(manifest_json,'$.storageMode')='daily-v1'").results[0].n,17)
 assert.deepEqual((await(await detailRead(db,daily[2])).json()).history,oldestBefore.history)
 let next
 for(let i=1;i<=6;i++) {
  next=await seed(db,`2026-11-17T00:0${i}:00Z`,{base:base.begin.generation})
  assert.equal((await activate(db,next)).status,200)
 }
 assert.equal(db.execute('SELECT generation FROM sector_live_generations WHERE generation=?',[current.begin.generation]).results.length,0)
 assert.ok(db.execute('SELECT generation FROM sector_live_generations WHERE generation=?',[daily[2].begin.generation]).results.length)
 const detail=await(await detailRead(db,next)).json()
 assert.equal(detail.history.length,15);assert.equal(detail.history[0].marketDate,'2026-11-03')
 assert.equal((await(await manifest(context(db))).json()).storageMode,'daily-v1')
})
test('daily history stays inside its scoring baseline across a version cutover',async t=>{
 const {dailySources}=await import('../functions/_lib/sector-live.js')
 const db=database(t),base='b'.repeat(64),oldBase='a'.repeat(64)
 const insert=(id,date,historyBaseGeneration)=>{
  const manifest={storageMode:'daily-v1',historyBaseGeneration,marketDate:date}
  db.execute('INSERT INTO sector_live_generations(generation,manifest_json,observed_at,digest,document_count,activated_at) VALUES(?,?,?,?,491,?)',[id,JSON.stringify(manifest),date+'T07:00:00.000Z','d'.repeat(64),date+'T08:00:00.000Z'])
  return manifest
 }
 insert('1'.repeat(64),'2026-11-18',oldBase)
 insert('2'.repeat(64),'2026-11-19',oldBase)
 const manifest=insert('3'.repeat(64),'2026-11-20',base)
 const request={generation:'3'.repeat(64),observed_at:'2026-11-20T07:00:00.000Z'}
 const sources=await dailySources(db,request,manifest)
 assert.deepEqual(sources.map(x=>x.generation),[request.generation])
 insert('4'.repeat(64),'2026-11-19',base)
 assert.deepEqual((await dailySources(db,request,manifest)).map(x=>x.generation),['4'.repeat(64),request.generation])
})
test('retention preserves daily dependencies from both scoring baselines',async t=>{
 const {obsoleteGenerations}=await import('../functions/_lib/sector-live.js')
 const db=database(t),oldBase='a'.repeat(64),base='b'.repeat(64)
 const insert=(id,day,historyBaseGeneration)=>db.execute('INSERT INTO sector_live_generations(generation,manifest_json,observed_at,digest,document_count,activated_at) VALUES(?,?,?,?,491,?)',[id,JSON.stringify({storageMode:'daily-v1',historyBaseGeneration,marketDate:day}),day+'T07:00:00.000Z','d'.repeat(64),day+'T08:00:00.000Z'])
 const oldDay='f'.repeat(64),newDay='2'.repeat(64),active='3'.repeat(64)
 insert(oldDay,'2026-11-19',oldBase);insert(newDay,'2026-11-19',base);insert(active,'2026-11-20',base)
 for(const id of ['6','7','8','9'])insert(id.repeat(64),'2026-11-20',oldBase)
 db.execute('INSERT INTO sector_live_active(id,generation,observed_at) VALUES(1,?,?)',[active,'2026-11-20T07:00:00.000Z'])
 const obsolete=db.execute(obsoleteGenerations).results.map(r=>r.generation)
 assert.ok(!obsolete.includes(oldDay));assert.ok(!obsolete.includes(newDay))
})
test('same-observation score revision requires explicit active-generation comparison and never permits older data',async t=>{
 const db=database(t),first=fixture('2026-11-17T08:00:00Z')
 await post(db,first.begin)
 await db.batch(first.documents.map(d=>db.prepare('INSERT INTO sector_live_documents(generation,document_key,digest) VALUES(?,?,?)').bind(first.begin.generation,d.key,d.digest)))
 assert.equal((await activate(db,first)).status,200)
 const revision=fixture('2026-11-17T08:00:00Z');revision.begin.generation=sha('explicit scoring revision');revision.begin.manifest.generation=revision.begin.generation
 await post(db,revision.begin)
 db.execute('INSERT INTO sector_live_documents(generation,document_key,digest) SELECT ?,document_key,digest FROM sector_live_documents WHERE generation=?',[revision.begin.generation,first.begin.generation])
 assert.equal((await activate(db,revision)).status,409)
 assert.equal((await post(db,{action:'activate',generation:revision.begin.generation,expectedActiveGeneration:'0'.repeat(64)})).status,409)
 assert.equal((await post(db,{action:'activate',generation:revision.begin.generation,expectedActiveGeneration:first.begin.generation})).status,200)
 const older=fixture('2026-11-17T07:00:00Z');await post(db,older.begin)
 db.execute('INSERT INTO sector_live_documents(generation,document_key,digest) SELECT ?,document_key,digest FROM sector_live_documents WHERE generation=?',[older.begin.generation,revision.begin.generation])
 assert.equal((await post(db,{action:'activate',generation:older.begin.generation,expectedActiveGeneration:revision.begin.generation})).status,409)
 assert.equal(db.execute('SELECT generation FROM sector_live_active WHERE id=1').results[0].generation,revision.begin.generation)
})
