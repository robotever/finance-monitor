import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
const migrations = ['0001_market_dashboard.sql','0002_sector_rotation.sql','0003_hithink_sector_rotation_v4.sql','0007_sector_score_v04.sql'].map(n=>new URL('../migrations/'+n,import.meta.url))
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
const versions = {schemaVersion:'market-dashboard-v4',sectorScoringVersion:'sector-score-v0.4',sectorUniverseVersion:'sector-universe-ths-v1',featureVersion:'sector-features-ths-v1',membershipVersion:'sector-membership-ths-v1'}
function row(n, universe='industry') { return {id:(universe==='industry'?'881':'885')+String(n).padStart(3,'0')+'.TI',name:'行业'+n,universe,strength:70,opportunity:30,risk:20,completeness:80,ranks:{strength:n+1,opportunity:n+1,risk:n+1},heatState:'active',coldStart:false,validCloses:60,improvementEvidence:2,membershipMode:'current_members_backfill',conceptRole:null,missing:[]} }
function fixture() {
  const rows=[...Array.from({length:90},(_,n)=>row(n)),...Array.from({length:390},(_,n)=>row(n,'concept'))]
  const chunks=[]
  for(let i=0;i<rows.length;i+=50) {const rowsJson=JSON.stringify(rows.slice(i,i+50)); chunks.push({batchId:'test-batch',index:chunks.length,rowsJson,digest:sha(rowsJson)})}
  const manifest={batchId:'test-batch',...versions,sourceMode:'hithink',observedAt:'2026-11-13T07:00:00.000Z',marketDate:'2026-11-13',session:'close',officialClose:true,industryCount:90,conceptCount:390,chunkCount:chunks.length,digest:sha(chunks.map(c=>c.digest).join('\n'))}
  return {rows,chunks,manifest}
}
async function post(name,body,db,extra={}) { const {onRequestPost}=await import('../functions/api/sector-rotation/v4/'+name+'.js'); return onRequestPost({request:new Request('https://example.test/api/sector-rotation/v4/'+name,{method:'POST',headers:{Authorization:'Bearer test-token'},body:JSON.stringify(body)}),env:{MARKET_DB:db,MARKET_DASHBOARD_PUBLISH_TOKEN:'test-token',HITHINK_PUBLIC_RELEASE_AUTHORIZATION:'verified',...extra}}) }
async function upload(db,f) { assert.equal((await post('manifest',f.manifest,db)).status,201); for(const c of f.chunks) assert.equal((await post('chunk',c,db)).status,201) }

test('staged batches are invisible through every interruption, then activate exactly once with rank 390',async t=>{
 const db=database(t),f=fixture(); assert.equal((await post('manifest',f.manifest,db)).status,201)
 for(const c of f.chunks) { assert.equal((await post('chunk',c,db)).status,201); assert.equal(db.execute("SELECT count(*) AS n FROM sector_rotation_v04_sectors s JOIN sector_rotation_v04_manifests m USING(batch_id) WHERE m.status='active'").results[0].n,0); if(c.index<f.chunks.length-1) assert.equal((await post('activate',{batchId:f.manifest.batchId},db)).status,409) }
 assert.equal((await post('activate',{batchId:f.manifest.batchId},db)).status,200)
 assert.equal(db.execute("SELECT count(*) AS n FROM sector_rotation_v04_sectors s JOIN sector_rotation_v04_manifests m USING(batch_id) WHERE m.status='active'").results[0].n,480)
 assert.equal(db.execute('SELECT MAX(strength_rank) AS r FROM sector_rotation_v04_sectors').results[0].r,390)
 assert.equal((await post('activate',{batchId:f.manifest.batchId},db)).status,200)
 assert.equal((await post('chunk',f.chunks[0],db)).status,200)
 assert.equal(db.execute('SELECT count(*) AS n FROM sector_rotation_snapshots').results[0].n,0)
})
test('immutable manifest/chunk retries and checksum/count/version rejection',async t=>{
 const db=database(t),f=fixture()
 assert.equal((await post('manifest',{...f.manifest,schemaVersion:'market-dashboard-v3'},db)).status,400)
 assert.equal((await post('manifest',f.manifest,db)).status,201)
 assert.equal((await post('manifest',f.manifest,db)).status,200)
 assert.equal((await post('manifest',{...f.manifest,conceptCount:389},db)).status,409)
 assert.equal((await post('chunk',{...f.chunks[0],digest:'0'.repeat(64)},db)).status,400)
 assert.equal((await post('chunk',f.chunks[0],db)).status,201)
 assert.equal((await post('chunk',f.chunks[0],db)).status,200)
 const c={...f.chunks[0],rowsJson:JSON.stringify([row(88)])}; c.digest=sha(c.rowsJson)
 assert.equal((await post('chunk',c,db)).status,409)
 assert.equal((await post('activate',{batchId:f.manifest.batchId},db)).status,409)
})
test('duplicates across chunks, excessive ranks, private fields, body limits and missing authorization fail closed',async t=>{
 const db=database(t),f=fixture(); await post('manifest',f.manifest,db)
 assert.equal((await post('chunk',f.chunks[0],db)).status,201)
 const send=async rows=>{const rowsJson=JSON.stringify(rows);return post('chunk',{batchId:'test-batch',index:1,rowsJson,digest:sha(rowsJson)},db)}
 assert.equal((await send([row(0)])).status,409)
 assert.equal((await send([{...row(89),ranks:{strength:91,opportunity:1,risk:1}}])).status,400)
 assert.equal((await send([{...row(89),constituents:['000001.SZ']}])).status,400)
 assert.equal((await send(Array.from({length:51},(_,n)=>row(n)))).status,400)
 assert.equal((await post('chunk',{padding:'x'.repeat(131072)},db)).status,413)
 assert.equal((await post('manifest',f.manifest,db,{HITHINK_PUBLIC_RELEASE_AUTHORIZATION:'unknown'})).status,403)
 assert.equal((await post('manifest',f.manifest,db,{MARKET_DASHBOARD_PUBLISH_TOKEN:''})).status,503)
})
test('wrong total digest and per-universe counts never activate',async t=>{
 for(const change of [{digest:'0'.repeat(64)},{conceptCount:391}]) {
 const db=database(t),f=fixture(); Object.assign(f.manifest,change); await upload(db,f)
 assert.equal((await post('activate',{batchId:'test-batch'},db)).status,409)
 assert.equal(db.execute("SELECT status FROM sector_rotation_v04_manifests").results[0].status,'staging')
 }
})

test('migration is repeatable and frozen rows cannot be inserted, updated or deleted',async t=>{
 const db=database(t),f=fixture(); db.execute(readFileSync(migrations[2],'utf8'),[],true)
 await upload(db,f); await post('activate',{batchId:'test-batch'},db)
 for(const sql of ["UPDATE sector_rotation_v04_sectors SET strength=1 WHERE batch_id='test-batch'", "DELETE FROM sector_rotation_v04_sectors WHERE batch_id='test-batch'", "DELETE FROM sector_rotation_v04_chunks WHERE batch_id='test-batch'", "INSERT INTO sector_rotation_v04_chunks VALUES('test-batch',99,'"+'0'.repeat(64)+"',1,'[]')"]) assert.throws(()=>db.execute(sql))
 assert.equal(db.execute('SELECT count(*) AS n FROM sector_rotation_v04_sectors').results[0].n,480)
})
test('failed chunk batch rolls back every row and the chunk receipt',async t=>{
 const db=database(t),f=fixture(); await post('manifest',f.manifest,db)
 const failing={...db,batch:statements=>db.batch([...statements,db.prepare('INSERT INTO nonexistent_table VALUES(1)')])}
 assert.equal((await post('chunk',f.chunks[0],failing)).status,503)
 assert.equal(db.execute('SELECT count(*) AS n FROM sector_rotation_v04_chunks').results[0].n,0)
 assert.equal(db.execute('SELECT count(*) AS n FROM sector_rotation_v04_sectors').results[0].n,0)
 assert.equal((await post('chunk',f.chunks[0],db)).status,201)
})
test('bad bearer and malformed schemas/dates are rejected without writes',async t=>{
 const db=database(t),f=fixture()
 const {onRequestPost}=await import('../functions/api/sector-rotation/v4/manifest.js')
 const env={MARKET_DB:db,MARKET_DASHBOARD_PUBLISH_TOKEN:'test-token',HITHINK_PUBLIC_RELEASE_AUTHORIZATION:'verified'}
 assert.equal((await onRequestPost({request:new Request('https://example.test',{method:'POST',headers:{Authorization:'Bearer wrong'},body:JSON.stringify(f.manifest)}),env})).status,401)
 for(const change of [{marketDate:'2026-11-12'},{officialClose:false},{featureVersion:'sector-features-v3'},{sourceMode:'wind'},{privatePath:'/Users/private'}])assert.equal((await post('manifest',{...f.manifest,...change},db)).status,400)
 assert.equal(db.execute('SELECT count(*) AS n FROM sector_rotation_v04_manifests').results[0].n,0)
})
