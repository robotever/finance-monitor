import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,writeFile,readFile,readdir,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
const modulePath='../tools/market_dashboard/local_research_data.mjs'
const now=Date.now()+1000
const date=new Date(now-86400000).toISOString().slice(0,10)
async function fixture(t){const root=await mkdtemp(join(tmpdir(),'local-research-'));t.after(()=>rm(root,{recursive:true,force:true}));return root}
async function factory(){return (await import(modulePath)).createLocalResearchData}
function inputs(){return {schemaVersion:'radar-inputs-v1',observedAt:new Date(now-10000).toISOString(),marketDate:date,objects:Object.fromEntries(['ashare','large','small','value','growth','dividend','tech'].map(id=>[id,{id,scope:id,sources:['MX'],membershipAsOf:null,history:[{date,up:30,down:60,flat:10,turnover:1e9,mainNetFlow:id==='ashare'?-1e7:null,fundMatched:null,fundExpected:null,membershipMode:'provider-aggregate'}]}]))}}
const unavailable=async()=>{throw Error('private network details')}
test('offline empty storage returns unknown risk and source failures without network access',async t=>{
 const root=await fixture(t),create=await factory();let calls=0
 const local=create({stateRoot:root,radarInputsPath:join(root,'missing.json'),now,offline:true,fetcher:async()=>{calls++;throw Error()}})
 const result=await local.risk()
 assert.equal(result.state,'unknown');assert.equal(result.assessable,0);assert.equal(result.sourceErrors,12);assert.equal(calls,0)
 assert.ok(result.sources.every(s=>s.lastSuccessAt===null&&s.status==='failed'))
 assert.equal(result.localMode.offline,true)
})
test('successful public source survives restart and offline mode retains dates while marking failure',async t=>{
 const root=await fixture(t),create=await factory()
 const fetcher=async url=>url.includes('VIX_History.csv')?new Response(`DATE,OPEN,HIGH,LOW,CLOSE\n${date.slice(5,7)}/${date.slice(8)}/${date.slice(0,4)},12,12,12,12\n`):unavailable()
 const online=await create({stateRoot:root,now,fetcher}).risk(),first=online.sources.find(s=>s.id==='vix')
 assert.equal(first.status,'ok');assert.equal(first.observedAt,date);assert.ok(Number.isFinite(first.lastSuccessAt))
 const offline=await create({stateRoot:root,now,offline:true,fetcher:unavailable}).risk(),cached=offline.sources.find(s=>s.id==='vix')
 assert.equal(cached.status,'failed');assert.equal(cached.cached,true);assert.equal(cached.observedAt,date);assert.equal(cached.lastSuccessAt,first.lastSuccessAt)
 assert.equal(offline.cards[0].state,'unknown');assert.equal(offline.cards[0].metrics[0].value,12)
 assert.ok(!JSON.stringify(offline).includes('private network details'))
})
test('radar consumes validated local breadth and signed funds without cloud database',async t=>{
 const root=await fixture(t),create=await factory(),path=join(root,'inputs.json'),payload=inputs()
 await writeFile(path,JSON.stringify(payload))
 const fetcher=async url=>{if(!url.includes('fqkline'))return unavailable();const code=new URL(url).searchParams.get('param').split(',')[0];return Response.json({code:0,data:{[code]:{day:Array.from({length:65},(_,i)=>[new Date(Date.parse(date)-86400000*(64-i)).toISOString().slice(0,10),'100',String(100+i),'100','100','1000'])}}})}
 const radar=await create({stateRoot:root,radarInputsPath:path,now,fetcher}).radar()
 assert.equal(radar.inputBatch.marketDate,date)
 const row=radar.ashare
 assert.equal(row.inputEvidence.mainNetFlow,-1e7);assert.equal(row.inputEvidence.flat,10);assert.deepEqual(row.inputEvidence.sources,['MX'])
 await writeFile(path,JSON.stringify({...payload,token:'do-not-expose'}))
 const invalid=await create({stateRoot:root,radarInputsPath:path,now,offline:true}).radar()
 assert.equal(invalid.inputBatch,null);assert.equal(invalid.localMode.inputsStatus,'invalid');assert.ok(!JSON.stringify(invalid).includes('do-not-expose'))
})
test('disk cache keys cannot escape source directory and corrupted sequences are ignored',async t=>{
 const root=await fixture(t),{createDiskSourceCache}=await import(modulePath),cache=createDiskSourceCache(root)
 await assert.rejects(()=>cache.put(new Request('https://local.test/arbitrary/../../escape'),Response.json({})),/INVALID_SOURCE_CACHE_KEY/)
 const key=new Request('https://local.test/api/cross-market/source-cache/cross-market-risk-v1/vix')
 await cache.put(key,Response.json({id:'vix',lastSuccessAt:now-10000,data:{vix:[{date,value:12}]}}))
 assert.equal((await (await cache.match(key)).json()).data.vix[0].value,12)
 const files=await readdir(root);assert.equal(files.length,1)
 const stored=JSON.parse(await readFile(join(root,files[0]),'utf8'));stored.payload.data.vix[0].value='secret-invalid'
 await writeFile(join(root,files[0]),JSON.stringify(stored));assert.equal(await cache.match(key),undefined)
})
test('failed online refresh preserves old source observations and reports cached rather than live',async t=>{
 const root=await fixture(t),{createLocalResearchData,createDiskSourceCache}=await import(modulePath)
 const cache=createDiskSourceCache(join(root,'research-source-cache'))
 const oldDate=new Date(now-40*86400000).toISOString().slice(0,10),lastSuccessAt=now-600000
 await cache.put(new Request('http://finance-monitor.local/api/cross-market/source-cache/cross-market-risk-v1/vix'),Response.json({id:'vix',lastSuccessAt,data:{vix:[{date:oldDate,value:12}]}}))
 const risk=await createLocalResearchData({stateRoot:root,now,fetcher:unavailable}).risk()
 assert.equal(risk.localStatus.mode,'cached');assert.equal(risk.localStatus.lastSuccessAt,lastSuccessAt)
 assert.equal(risk.cards[0].state,'unknown');assert.equal(risk.cards[0].metrics[0].stale,true)
 assert.equal(risk.sources.find(s=>s.id==='vix').observedAt,oldDate)
})
