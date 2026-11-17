import test from 'node:test'
import assert from 'node:assert/strict'
import { localSnapshot, localHistory, localDetail } from '../tools/market_dashboard/hithink_preview_data.mjs'

const row=(risk)=>({id:'881001.TI',name:'行业',universe:'industry',strength:55,opportunity:50,risk,completeness:90,ranks:{strength:1,opportunity:1,risk:1},heatState:null,conceptRole:null,membershipMode:'point_in_time_snapshot'})
const payload=(day,risk,reconstructed=true)=>({marketDate:day,historicalReconstruction:reconstructed,officialClose:false,rows:[{...row(risk),observedAt:'2026-11-17T01:45:00.000Z'}]})
const chunks=p=>[{rowsJson:JSON.stringify(p.rows)}]
function bundle(){const old=payload('2026-11-13',10),last=payload('2026-11-16',25),current=payload('2026-11-17',40,false);return {payload:current,chunks:chunks(current),closeHistory:[old,last],historyChunks:{[old.marketDate]:chunks(old),[last.marketDate]:chunks(last)}}}
test('live date leads descending matrix, with prior close ranks unchanged and no fabricated dates',()=>{
 const b=bundle(),p=localHistory(b,'industry','risk');assert.deepEqual(p.dates,['2026-11-17','2026-11-16','2026-11-13']);assert.deepEqual(p.rows[0].values.map(v=>v.score),[40,25,10]);assert.equal(p.rows[0].values[0].rank,1);assert.equal(p.liveDate,'2026-11-17');assert.equal(b.closeHistory.length,2)
 b.payload=b.closeHistory[1];b.chunks=chunks(b.payload);assert.deepEqual(localHistory(b,'industry','risk').dates,['2026-11-16','2026-11-13'])
})
test('risk rise is computed before selecting lists and uses previous market date, not intraday refresh',()=>{
 const b=bundle(),p=localSnapshot(b);assert.equal(p.industry.risk.length,1);assert.equal(p.industry.risk[0].change1d.risk,15);assert.equal(p.historicalReconstruction,false);assert.equal(p.marketDate,'2026-11-17');assert.equal(p.observedAt,'2026-11-17T01:45:00.000Z')
 b.payload.rows[0].risk=42;b.chunks=chunks(b.payload);assert.equal(localSnapshot(b).industry.risk[0].change1d.risk,17)
})
test('daily return ranks independently of strength, preserves percent units and missing values',()=>{
 const b=bundle(),a=b.payload.rows[0];a.metrics={return1d:2.55};a.strength=10
 b.payload.rows.push({...a,id:'881002.TI',strength:99,metrics:{return1d:1.78}},{...a,id:'881003.TI',metrics:{return1d:null}});b.chunks=chunks(b.payload)
 const h=localHistory(b,'industry','return1d');assert.equal(h.rows.find(r=>r.id===a.id).values[0].score,2.55);assert.equal(h.rows.find(r=>r.id===a.id).values[0].rank,1);assert.equal(h.rows.find(r=>r.id==='881002.TI').values[0].rank,2);assert.equal(h.rows.find(r=>r.id==='881003.TI').values[0].rank,null)
})
test('detail adds real component breakdown without mutating scores or exposing private fields',()=>{
 const b=bundle(),r=b.payload.rows[0];r.metrics={return1d:2.55};b.chunks=chunks(b.payload)
 r.components={priceTrend:{value:70,coverage:.8,missing:['return5d.missingInput'],privatePath:'/private/secret',parts:{return1d:{value:80,coverage:1,missing:[],password:'secret'}}}};r._rawScores={strength:55.123}
 const d=localDetail(b,new URLSearchParams({universe:'industry',id:r.id}),{strength:{priceTrend:30}}),point=d.history.at(-1)
 assert.equal(point.components.priceTrend.value,70);assert.equal(point.components.priceTrend.parts.return1d.value,80);assert.equal(point.strength,55);assert.equal(point.returnRank,1);assert.equal(d.scoringWeights.strength.priceTrend,30)
 assert.ok(!JSON.stringify(point.components).includes('secret'));assert.ok(!JSON.stringify(point).includes('_rawScores'));assert.equal(r.components.priceTrend.privatePath,'/private/secret')
})
