import test from 'node:test'
import assert from 'node:assert/strict'
import { localSnapshot, localHistory } from '../tools/market_dashboard/hithink_preview_data.mjs'

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
