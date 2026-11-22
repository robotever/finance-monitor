import test from 'node:test'
import assert from 'node:assert/strict'
import {validateInputs,readInputs} from '../functions/_lib/radar-inputs.js'
import {onRequestPost} from '../functions/api/market-radar/inputs.js'
const now=Date.parse('2026-11-22T10:00:00Z')
const ids=['ashare','large','small','value','growth','dividend','tech']
function payload(){return {schemaVersion:'radar-inputs-v1',observedAt:'2026-11-22T09:00:00Z',marketDate:'2026-11-20',objects:Object.fromEntries(ids.map(id=>[id,{id,scope:id,sources:['MX'],membershipAsOf:null,history:[{date:'2026-11-20',up:30,down:60,flat:10,turnover:1e9,mainNetFlow:id==='ashare'?-1e7:null,fundMatched:null,fundExpected:null,membershipMode:'provider-aggregate'}]}]))}}
test('inputs retain signed funds, flat stocks and actual observation dates',()=>{const p=payload();assert.equal(validateInputs(p,now),p);assert.equal(p.objects.ashare.history[0].mainNetFlow,-1e7)})
test('invalid count, future date, mismatched basket coverage and untrusted extras are rejected',()=>{
 for(const change of [p=>p.objects.ashare.history[0].up=-1,p=>p.marketDate='2026-12-01',p=>p.objects.tech.history[0].mainNetFlow=20,p=>p.token='secret',p=>p.objects.ashare.history.push(p.objects.ashare.history[0]),p=>p.objects.ashare.history[0].mainNetFlow='10亿']){
  const p=payload();change(p);assert.throws(()=>validateInputs(p,now))
 }
 const p=payload();Object.assign(p.objects.tech.history[0],{mainNetFlow:10,membershipMode:'current-members',fundMatched:49,fundExpected:50});assert.throws(()=>validateInputs(p,now))
})
test('partial objects can retain breadth without inventing money values',()=>{const p=payload();p.objects.value.history=[];assert.equal(validateInputs(p,now).objects.value.history.length,0)})
test('reader validates stored rows and fails closed on malformed inputs',async()=>{
 const db={prepare:()=>({first:async()=>({payload_json:JSON.stringify(payload())})})};assert.equal((await readInputs(db,now)).schemaVersion,'radar-inputs-v1')
 assert.equal(await readInputs({prepare:()=>({first:async()=>({payload_json:'{}'})})},now),null)
})
test('unauthorized writes never touch D1',async()=>{
 let writes=0;const env={MARKET_DASHBOARD_PUBLISH_TOKEN:'test-secret',MARKET_DB:{prepare(){writes++;throw Error()}}}
 const r=await onRequestPost({request:new Request('https://example.test/api/market-radar/inputs',{method:'POST',body:'{}'}),env});assert.equal(r.status,401);assert.equal(writes,0)
})
test('timestamps are canonicalized so database ordering compares real time',()=>{const p=payload();p.observedAt='2026-11-22T17:00:00+08:00';assert.equal(validateInputs(p,now).observedAt,'2026-11-22T09:00:00.000Z')})
test('current-member reconstruction requires an explicit membership date',()=>{const p=payload();Object.assign(p.objects.tech.history[0],{mainNetFlow:1,membershipMode:'current-members',fundMatched:100,fundExpected:100});assert.throws(()=>validateInputs(p,now))})
test('independent verified public backup is explicitly tagged, never labelled MX',()=>{const p=payload();p.objects.small.sources=['Hithink','MX','Eastmoney'];assert.deepEqual(validateInputs(p,now).objects.small.sources,['Hithink','MX','Eastmoney'])})
test('D1 latest query selects actual newest observation across legacy timezone formats',async()=>{
 const {INPUTS_QUERY}=await import('../functions/_lib/radar-inputs.js')
 const {execFileSync}=await import('node:child_process')
 const script='import sqlite3,sys,json\nc=sqlite3.connect(":memory:")\nc.execute("CREATE TABLE radar_input_batches(observed_at TEXT,market_date TEXT,payload_json TEXT)")\nc.executemany("INSERT INTO radar_input_batches VALUES(?,?,?)",[("2026-11-22T12:42:00+08:00","2026-11-20","old"),("2026-11-22T05:15:00.000Z","2026-11-20","new")])\nprint(c.execute(json.load(sys.stdin)).fetchone()[0])'
 assert.equal(execFileSync('python3',['-c',script],{input:JSON.stringify(INPUTS_QUERY),encoding:'utf8'}).trim(),'new')
})
test('radar wire limit fits its validated history budget while legacy reader stays bounded',async()=>{
 const {readBoundedJson}=await import('../functions/_lib/market-dashboard.js')
 const p=payload();p.observedAt=new Date(Date.now()-60000).toISOString()
 const body=' '.repeat(263000)+JSON.stringify(p)
 await assert.rejects(()=>readBoundedJson(new Request('https://example.test',{method:'POST',body})),/PAYLOAD_TOO_LARGE/)
 const db={prepare:()=>({first:async()=>null,bind(){return {run:async()=>({})}}})}
 const result=await onRequestPost({request:new Request('https://example.test',{method:'POST',body,headers:{Authorization:'Bearer test-secret'}}),env:{MARKET_DB:db,MARKET_DASHBOARD_PUBLISH_TOKEN:'test-secret'}})
 assert.equal(result.status,200)
})
