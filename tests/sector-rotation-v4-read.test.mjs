import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'
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



const versions={schemaVersion:'market-dashboard-v4',sectorScoringVersion:'sector-score-v0.4',sectorUniverseVersion:'sector-universe-ths-v1',featureVersion:'sector-features-ths-v1',membershipVersion:'sector-membership-ths-v1'}
function seed(db,{id='current',date='2026-11-13',time='07:00',active=true,close=true,offset=0,mutate=()=>{}}={}) {
 const observedAt=date+'T'+time+':00.000Z'
 const rows=['industry','concept'].flatMap(universe=>Array.from({length:universe==='industry'?90:390},(_,n)=>({
 id:(universe==='industry'?'881':'885')+String(n).padStart(3,'0')+'.TI',name:(universe==='industry'?'行业':'概念')+n,universe,
 strength:n%3===0?50:80,opportunity:n%3===0?80:50,risk:n%3===2?80:20,completeness:90,
 ranks:{strength:n+1,opportunity:n+1,risk:n+1},heatState:'active',coldStart:false,validCloses:60,
 improvementEvidence:4,membershipMode:n%2?'point_in_time_snapshot':'current_members_backfill',conceptRole:universe==='industry'?null:n<25?'core':n<45?'dynamic':'candidate',missing:[],
 components:{strength:{value:80,coverage:1,missing:[],privatePath:'/Users/secret'}},metrics:{return1d:2,privatePath:'/Users/secret',password:123},privatePath:'/Users/secret',constituents:['SECRET'],rankKeys:{strength:80+n/1000,opportunity:80+n/1000,risk:80+n/1000}
 })))
 const statements=[db.prepare(`INSERT INTO sector_rotation_v04_manifests(batch_id,observed_at,market_date,session,official_close,schema_version,scoring_version,universe_version,feature_version,membership_version,industry_count,concept_count,chunk_count,digest,manifest_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`).bind(id,observedAt,date,close?'close':'intraday',close?1:0,...Object.values(versions),90,390,1,'0'.repeat(64),'{}',observedAt),db.prepare('INSERT INTO sector_rotation_v04_chunks VALUES(?,?,?,?,?)').bind(id,0,'0'.repeat(64),1,'[]')]
 for(const r of rows){mutate(r);for(const a of ['strength','opportunity','risk'])if(r[a]!==null)r[a]-=offset;statements.push(db.prepare('INSERT INTO sector_rotation_v04_sectors VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)').bind(id,0,r.universe,r.id,r.name,r.strength,r.opportunity,r.risk,r.completeness,r.ranks.strength,r.ranks.opportunity,r.ranks.risk,JSON.stringify(r)))}
 if(active)statements.push(db.prepare("UPDATE sector_rotation_v04_manifests SET status='active' WHERE batch_id=?").bind(id))
 return db.batch(statements)
}
async function get(endpoint,db,query='') {const {onRequestGet}=await import('../functions/api/sector-rotation/v4/'+endpoint+'.js');return onRequestGet({request:new Request('https://example.test/api/sector-rotation/v4/'+endpoint+query),env:{MARKET_DB:db}})}
test('latest projects compact homepage, safe details, all versions and previous official close changes',async t=>{
 const db=database(t);await seed(db,{id:'prior',date:'2026-11-12',offset:5});await seed(db);await seed(db,{id:'partial',date:'2026-11-14',active:false})
 const response=await get('latest',db);assert.equal(response.status,200);const p=await response.json()
 for(const [k,v]of Object.entries(versions))assert.equal(p[k],v)
 assert.equal(p.sourceMode,'hithink');assert.equal(p.batchId,'current');assert.equal(p.approximateHistory,true)
 for(const u of ['industry','concept'])for(const view of ['potential','main','risk'])assert.equal(p[u][view].length,10)
 assert.equal(p.concept.core.length,25);assert.equal(p.concept.dynamic.length,10)
 assert.ok(p.concept.dynamic.every(r=>r.conceptRole!=='core'))
 assert.deepEqual(p.industry.main[0].change1d,{strength:5,opportunity:5,risk:5})
 assert.ok(!JSON.stringify(p).includes('SECRET'));assert.ok(!JSON.stringify(p).includes('/Users'));assert.ok(!JSON.stringify(p).includes('rankKeys'));assert.ok(!JSON.stringify(p).includes('password'))
})
test('all endpoints hide staging and never consult v3; errors are stable',async t=>{
 const db=database(t);await seed(db,{active:false})
 for(const [endpoint,q]of [['latest',''],['catalog','?universe=industry'],['history','?universe=industry&axis=strength'],['detail','?universe=industry&id=881001.TI']]){const r=await get(endpoint,db,q);assert.equal(r.status,404);assert.deepEqual(await r.json(),{error:'NO_SNAPSHOT'})}
 const r=await get('latest',{prepare(){throw Error('/Users/secret token')}});assert.equal(r.status,503);assert.deepEqual(await r.json(),{error:'STORAGE_UNAVAILABLE'})
})
test('catalog paginates all industries and concepts and searches names or literal codes with filters',async t=>{
 const db=database(t);await seed(db)
 let p=await (await get('catalog',db,'?universe=industry&page=2&pageSize=50')).json();assert.equal(p.total,90);assert.equal(p.sectors.length,40)
 p=await(await get('catalog',db,'?universe=concept&page=4&pageSize=100')).json();assert.equal(p.total,390);assert.equal(p.sectors.length,90)
 p=await(await get('catalog',db,'?universe=concept&q=885389.TI')).json();assert.equal(p.total,1);assert.equal(p.sectors[0].ranks.strength,390)
 p=await(await get('catalog',db,'?universe=concept&role=core')).json();assert.equal(p.total,25)
 p=await(await get('catalog',db,'?universe=industry&view=potential')).json();assert.equal(p.total,30)
 p=await(await get('catalog',db,'?universe=concept&q=%25')).json();assert.equal(p.total,0)
})
test('history leads with current live trading date then prior closes in descending order',async t=>{
 const db=database(t);await seed(db,{id:'old',date:'2026-11-12',offset:5});await seed(db,{id:'early',time:'06:59',offset:3});await seed(db);await seed(db,{id:'intraday',date:'2026-11-16',close:false});await seed(db,{id:'staging',date:'2026-11-17',active:false})
 const h=await(await get('history',db,'?universe=concept&axis=strength')).json();assert.deepEqual(h.dates,['2026-11-16','2026-11-13','2026-11-12']);assert.equal(h.liveDate,'2026-11-16');assert.equal(h.rows.length,390);assert.equal(h.rows[0].values[1].score,50)
 const one=await(await get('history',db,'?universe=concept&axis=strength&days=1')).json();assert.deepEqual(one.dates,['2026-11-16'])
 const {validateHistory}=await import('../src/features/sector-rotation-v4/model.mjs');assert.equal(validateHistory(h,{universe:'concept',axis:'strength'}),h)
 assert.throws(()=>validateHistory({...h,dates:[...h.dates].reverse()},{universe:'concept',axis:'strength'}),/INVALID_SCHEMA/)
 const d=await(await get('detail',db,'?universe=concept&id=885389.TI')).json();assert.equal(d.history.length,4);assert.equal(d.history.at(-1).session,'intraday');assert.equal(d.history.at(-1).ranks.strength,390)
 assert.ok(!JSON.stringify(d).includes('/Users'))
})
test('strict query validation rejects duplicate unknown invalid identities pagination and axis input',async t=>{
 const db=database(t)
 for(const [e,qs]of Object.entries({latest:['?version=v3'],catalog:['?universe=industry&page=0','?universe=concept&pageSize=101','?universe=concept&q=a&q=b','?universe=industry&role=core','?universe=concept&view=oops'],history:['?universe=concept&axis=strength&days=16','?universe=concept&axis=oops'],detail:['?universe=industry&id=884001.TI','?universe=concept&id=885001.TI&days=61']}))for(const q of qs)assert.equal((await get(e,db,q)).status,400)
})
test('daily-return history ranks actual percentages independently of score ranks',async t=>{
 const db=database(t);await seed(db,{close:false,mutate:r=>{r.metrics={return1d:r.id.endsWith('000.TI')?2.55:r.id.endsWith('001.TI')?1.78:null}}})
 const response=await get('history',db,'?universe=concept&axis=return1d');assert.equal(response.status,200)
 const h=await response.json();assert.equal(h.rows[0].values[0].score,2.55);assert.equal(h.rows[0].values[0].rank,1);assert.equal(h.rows[1].values[0].rank,2);assert.equal(h.rows[2].values[0].rank,null)
 const {validateHistory}=await import('../src/features/sector-rotation-v4/model.mjs');assert.equal(validateHistory(h,{universe:'concept',axis:'return1d'}),h)
})
test('exact five-version filters apply to every read and prior baseline',async t=>{
 for(const column of ['schema_version','scoring_version','universe_version','feature_version','membership_version']){
 const db=database(t);await seed(db)
 db.execute(`PRAGMA ignore_check_constraints=ON; UPDATE sector_rotation_v04_manifests SET ${column}='incompatible';`,[],true)
 for(const [e,q]of [['latest',''],['catalog','?universe=industry'],['history','?universe=concept&axis=risk'],['detail','?universe=industry&id=881001.TI']])assert.equal((await get(e,db,q)).status,404)
 }
})
test('four independent improvement families remain valid publish rows',async()=>{
 const {validateV4Row}=await import('../functions/_lib/sector-rotation-v4.js')
 const r={id:'881001.TI',name:'行业',universe:'industry',strength:80,opportunity:50,risk:20,completeness:90,ranks:{strength:1,opportunity:1,risk:1},heatState:'active',coldStart:false,validCloses:60,improvementEvidence:4,membershipMode:'current_members_backfill',conceptRole:null,missing:[]}
 assert.equal(validateV4Row(r,{industryCount:90}),r)
})

test('prior close excludes incompatible versions and same-day snapshots and missing scores never pad lists',async t=>{
 const db=database(t);await seed(db,{id:'prior',date:'2026-11-12',offset:5})
 db.execute("PRAGMA ignore_check_constraints=ON; UPDATE sector_rotation_v04_manifests SET feature_version='old' WHERE batch_id='prior';",[],true)
 await seed(db,{id:'same-day-early',time:'06:00',offset:3})
 await seed(db,{mutate:r=>{if(r.universe==='concept'){r.strength=null;r.opportunity=null;r.risk=null;r.completeness=0}}})
 const p=await(await get('latest',db)).json()
 assert.deepEqual(p.industry.main[0].change1d,{strength:null,opportunity:null,risk:null})
 assert.equal(p.concept.core[0].strength,null);assert.equal(p.concept.dynamic.length,0);assert.equal(p.concept.main.length,0);assert.equal(p.concept.potential.length,0);assert.equal(p.concept.core.length,25)
 const missing=await get('detail',db,'?universe=concept&id=886999.TI');assert.equal(missing.status,404)
})

test('homepage dynamic selection and catalog roles agree on the same immutable snapshot',async t=>{
 const db=database(t);await seed(db)
 const latest=await(await get('latest',db)).json()
 const dynamic=await(await get('catalog',db,'?universe=concept&role=dynamic')).json()
 assert.equal(dynamic.total,10)
 assert.deepEqual(dynamic.sectors.map(r=>r.id).sort(),latest.concept.dynamic.map(r=>r.id).sort())
 assert.ok(latest.concept.dynamic.every(r=>r.conceptRole==='dynamic'))
 const candidates=await(await get('catalog',db,'?universe=concept&role=candidate&pageSize=100')).json()
 assert.equal(candidates.total,355)
 const detail=await(await get('detail',db,'?universe=concept&id='+latest.concept.dynamic[0].id)).json()
 assert.equal(detail.history.at(-1).conceptRole,'dynamic')
})

test('detail canonicalizes corrected batches per timestamp before date limits and validates in the frontend',async t=>{
 const db=database(t)
 await seed(db,{id:'prior-z',date:'2026-11-12',offset:4})
 await seed(db,{id:'prior-a',date:'2026-11-12',offset:8})
 await seed(db,{id:'intraday',time:'06:00',close:false,offset:3})
 // Upload order must not override the same batch-ID tie break used by latest.
 await seed(db,{id:'current-z',offset:2})
 await seed(db,{id:'current-a',offset:9})
 await seed(db,{id:'current-zz-staging',active:false,offset:15})
 const latest=await(await get('latest',db)).json()
 assert.equal(latest.batchId,'current-z')
 const {validateDetail}=await import('../src/features/sector-rotation-v4/model.mjs')
 for(const [universe,id]of [['industry','881001.TI'],['concept','885001.TI']]){
  const p=await(await get('detail',db,`?universe=${universe}&id=${id}`)).json()
  assert.equal(p.history.length,3)
  assert.deepEqual(p.history.map(r=>r.strength),[76,77,78])
  assert.equal(p.batchId,latest.batchId)
  assert.deepEqual(p.history.at(-1).change1d,{strength:2,opportunity:2,risk:2})
  assert.equal(validateDetail(p,{universe,id}),p)
  const one=await(await get('detail',db,`?universe=${universe}&id=${id}&days=1`)).json()
  assert.equal(one.history.length,2)
  assert.ok(one.history.every(r=>r.marketDate==='2026-11-13'))
  assert.equal(validateDetail(one,{universe,id,days:1}),one)
 }
})

test('detail chooses canonical batches before selecting the sector date window',async t=>{
 const db=database(t)
 await seed(db,{id:'prior',date:'2026-11-12',offset:4})
 await seed(db,{id:'current-a',offset:9})
 await seed(db,{id:'current-z',mutate:r=>{if(r.id==='881001.TI')r.id='881999.TI'}})
 const p=await(await get('detail',db,'?universe=industry&id=881001.TI&days=1')).json()
 assert.equal(p.history.length,1)
 assert.equal(p.history[0].marketDate,'2026-11-12')
 assert.equal(p.history[0].strength,76)
})
