import test from 'node:test'
import assert from 'node:assert/strict'
import {parseVix,parseTreasury,parseNfci,parseNyFed,parseFx,parseEquity} from '../src/features/cross-market-risk/parsers.mjs'
import {normalizeSeries,alignSpread,metricSummary,buildRiskModel} from '../src/features/cross-market-risk/model.mjs'
const now=Date.parse('2026-11-21T12:00:00Z')
const points=(values,offset=0)=>values.map((value,i)=>({date:`2026-11-${String(15+i+offset).padStart(2,'0')}`,value}))
test('numeric parser rejects blank/missing values and impossible dates rather than fabricating zero',()=>{
 assert.deepEqual(parseVix('DATE,OPEN,HIGH,LOW,CLOSE\n11/20/2026,1,1,1,22\n11/19/2026,1,1,1,\n02/30/2026,1,1,1,9'),[{date:'2026-11-20',value:22}])
 assert.deepEqual(normalizeSeries([{date:'2026-11-20',value:0},{date:'2026-11-21',value:null},{date:'2026-11-22',value:20},{date:'2026-02-30',value:4}],now),[{date:'2026-11-20',value:0}])
})
test('official XML preserves negative real yields, skips null and uses the observation date',()=>{
 const xml='<m:properties><d:NEW_DATE>2026-11-20T00:00:00</d:NEW_DATE><d:TC_10YEAR>-0.2</d:TC_10YEAR><d:BC_2YEAR m:null="true" /></m:properties>'
 assert.deepEqual(parseTreasury(xml,{real10y:'TC_10YEAR',us2y:'BC_2YEAR'}),{real10y:[{date:'2026-11-20',value:-.2}],us2y:[]})
})
test('NFCI credit is parsed separately and weekly dates are retained',()=>{
 const d=parseNfci('Friday_of_Week,NFCI,ANFCI,Risk,Credit,Leverage\n11/13/2026,-.2,-.3,.1,.4,.2')
 assert.equal(d.nfci[0].value,-.2);assert.equal(d.credit[0].value,.4)
 assert.equal(d.nfci[0].date,'2026-11-13')
})
test('NY Fed only accepts the requested reference rate and blank is not zero',()=>{
 assert.deepEqual(parseNyFed({refRates:[{effectiveDate:'2026-11-19',type:'SOFR',percentRate:3.9},{effectiveDate:'2026-11-19',type:'EFFR',percentRate:3.8},{effectiveDate:'2026-11-18',type:'SOFR',percentRate:''}]},'SOFR'),[{date:'2026-11-19',value:3.9}])
})
test('market history parsers reject invalid price and keep actual daily close values',()=>{
 assert.equal(parseFx('var _data=("2026-11-19,1,2,3,6.7|2026-11-20,1,2,3,");').length,1)
 assert.equal(parseEquity({code:0,data:{sh000001:{day:[['2026-11-20','1','3500']]}}},'sh000001')[0].value,3500)
 assert.throws(()=>parseEquity({code:1},'sh000001'))
})
test('spread aligns exact dates and converts percentage points to basis points',()=>{
 assert.deepEqual(alignSpread(points([4,4.2]),points([3.9],1)),[{date:'2026-11-16',value:30}])
 assert.deepEqual(alignSpread(points([4]),points([3.9],1)),[])
})
test('insufficient history has no made-up change and short histories have no percentile',()=>{
 const s=metricSummary(points([20]),{id:'vix',unit:'点'},now)
 assert.equal(s.change5,null);assert.equal(s.percentile,null)
 assert.equal(metricSummary(points([1,2,3,4,5,6]),{id:'dollar',unit:'点'},now).return5,500)
})
test('all absent data is unknown, never a low-risk score',()=>{
 const d=buildRiskModel({},[],now)
 assert.equal(d.cards.length,6);assert.equal(d.assessable,0);assert.equal(d.state,'unknown')
 assert.ok(d.cards.every(c=>c.state==='unknown'))
})
test('VIX thresholds and momentum are explicit; a failed or stale source is not healthy',()=>{
 assert.equal(buildRiskModel({vix:points([20,21,22,23,24,30])},[],now).cards[0].state,'stress')
 assert.equal(buildRiskModel({vix:points([10,10,10,10,10,15])},[],now).cards[0].state,'watch')
 assert.equal(buildRiskModel({vix:points([12,12,12,12,12,12])},['vix'],now).cards[0].state,'unknown')
 assert.equal(buildRiskModel({vix:[{date:'2026-10-01',value:12}]},[],now).cards[0].state,'unknown')
})
test('funding requires sustained high same-day basis for the strongest state',()=>{
 const effr=points([4,4,4,4,4,4])
 assert.equal(buildRiskModel({sofr:points([4,4,4,4,4,4.3]),effr},[],now).cards[4].state,'watch')
 assert.equal(buildRiskModel({sofr:points([4,4,4,4.3,4.3,4.3]),effr},[],now).cards[4].state,'stress')
})
test('equity contagion requires at least two markets and a common trading-date window',()=>{
 const falling=points([100,99,98,97,96,94])
 assert.equal(buildRiskModel({shanghai:falling},[],now).cards[5].state,'unknown')
 const d=buildRiskModel({shanghai:falling,hstech:falling,nasdaq:points([100,100,100,100,100,101])},[],now)
 assert.equal(d.cards[5].state,'stress');assert.equal(d.cards[5].coverage,'3/3市场')
 const noCommon=points([100,99,98,97,96,94],6)
 assert.equal(buildRiskModel({shanghai:falling,hstech:noCommon},[],now).cards[5].state,'unknown')
})
test('weekly data has its own freshness window and no daily frequency label',()=>{
 const d=buildRiskModel({nfci:[{date:'2026-11-13',value:.1}]},[],now).cards[2]
 assert.equal(d.state,'watch');assert.equal(d.metrics[0].frequency,'周频')
 assert.equal(buildRiskModel({nfci:[{date:'2026-10-30',value:.1}]},[],now).cards[2].state,'unknown')
})

test('fixed source adapters reject unlisted sources; partial failure does not discard other evidence',async()=>{
 const {fetchRiskSource,buildCrossMarketRisk}=await import('../functions/_lib/cross-market-risk.js')
 await assert.rejects(()=>fetchRiskSource('https://attacker.test'),/INVALID_RISK_SOURCE/)
 const data=await buildCrossMarketRisk({now,loadSource:async id=>id==='vix'?{id,name:'Cboe',status:'ok',data:{vix:points([25,25,26,29,31,35])},lastSuccessAt:now}:Promise.reject(Error('SOURCE_UNAVAILABLE'))})
 assert.equal(data.cards[0].state,'stress');assert.equal(data.sourceErrors,11);assert.equal(data.assessable,1)
 assert.ok(data.sources.every(s=>!('data' in s)))
})
test('source cache falls back to last successful observations but flags refresh failure',async()=>{
 const {loadRiskSource}=await import('../functions/_lib/cross-market-risk.js')
 const saved={lastSuccessAt:now-600000,data:{vix:points([12,12,12,12,12,12])}}
 const cache={match:async()=>Response.json(saved),put:async()=>assert.fail('failed refresh must not overwrite good cache')}
 const r=await loadRiskSource('vix',{cache,now,fetcher:async()=>{throw Error('private diagnostics')}})
 assert.equal(r.status,'failed');assert.equal(r.cached,true);assert.deepEqual(r.data,saved.data)
 assert.ok(!JSON.stringify(r).includes('private diagnostics'))
})

test('fresh individual market tails cannot revive an obsolete common-date window',()=>{
 const old=[15,16,17,18,19,20].map((day,i)=>({date:`2026-10-${day}`,value:100-i*2}))
 const d=buildRiskModel({shanghai:[...old,{date:'2026-11-19',value:95}],hstech:[...old,{date:'2026-11-20',value:95}],nasdaq:[...old,{date:'2026-11-21',value:95}]},[],now)
 assert.equal(d.cards[5].state,'unknown');assert.equal(d.cards[5].partial,true)
 assert.ok(d.cards[5].metrics.every(m=>m.stale))
})
test('missing decision signals cannot turn a partially observed group green; known pressure is retained',()=>{
 const flat=points([100,100,100,100,100,100])
 assert.equal(buildRiskModel({dollar:flat},['cnh','jpy'],now).cards[3].state,'unknown')
 assert.equal(buildRiskModel({us10y:flat},['real10y'],now).cards[1].state,'unknown')
 assert.equal(buildRiskModel({shanghai:flat,hstech:flat},['nasdaq'],now).cards[5].state,'unknown')
 assert.equal(buildRiskModel({dollar:points([100,100,100,100,100,104])},['cnh','jpy'],now).cards[3].state,'stress')
})
