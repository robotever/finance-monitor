import test from 'node:test'
import assert from 'node:assert/strict'
import {parseRadarBars,completedBars,indexScoreSeries,globalScoreSeries,deriveRadar,INDEXES,RADAR_VERSION} from '../src/features/market-radar/model.mjs'
const now=Date.parse('2026-11-22T10:00:00Z')
function bars(n=120,fn=i=>100+i*.1){return Array.from({length:n},(_,i)=>({date:new Date(Date.UTC(2026,6,24+i)).toISOString().slice(0,10),close:fn(i),volume:1000}))}
test('index identities disclose the new value proxy and never alias the old universe',()=>{
 assert.equal(INDEXES.find(x=>x.id==='value').code,'sh000919')
 assert.equal(INDEXES.find(x=>x.id==='ashare').code,'sh000985')
 assert.ok(INDEXES.every(x=>x.code!=='sz399919'))
})
test('parser rejects invalid/blank values and deduplicates actual dates',()=>{
 const data={code:0,data:{sh000985:{day:[['2026-11-20','1','100','2','1','1000'],['2026-11-20','1','101','2','1',''],['2026-02-30','1','99','2','1','10']]}}}
 const rows=parseRadarBars(data,'sh000985');assert.equal(rows.length,1);assert.equal(rows[0].close,101);assert.equal(rows[0].volume,null)
 assert.throws(()=>parseRadarBars({code:1},'sh000985'))
})
test('unfinished daily bars are excluded in each market timezone',()=>{
 const rows=[{date:'2026-11-20',close:100,volume:1000},{date:'2026-11-23',close:99,volume:20}]
 assert.equal(completedBars(rows,'china',Date.parse('2026-11-23T02:00:00Z')).at(-1).date,'2026-11-20')
 assert.equal(completedBars(rows,'china',Date.parse('2026-11-23T08:00:00Z')).at(-1).date,'2026-11-23')
 assert.equal(completedBars(rows,'us',Date.parse('2026-11-23T18:00:00Z')).at(-1).date,'2026-11-20')
 assert.equal(completedBars(rows,'us',Date.parse('2026-11-23T23:00:00Z')).at(-1).date,'2026-11-23')
})
test('flat observed prices are neutral trend and low risk; tied volume rank is neutral',()=>{
 const rows=indexScoreSeries(bars(120,()=>100))
 const last=rows.at(-1);assert.equal(last.strength,50);assert.equal(last.heat,50);assert.equal(last.risk,0)
})
test('missing volume cannot become a cold score or alter trend/risk weights',()=>{
 const last=indexScoreSeries(bars().map(x=>({...x,volume:null}))).at(-1)
 assert.equal(last.heat,null);assert.ok(Number.isFinite(last.strength));assert.ok(Number.isFinite(last.risk))
 assert.equal(indexScoreSeries(bars(25)).length,0)
})
test('style relative performance requires exact benchmark comparison dates',()=>{
 const rows=bars(),benchmark=rows.map(x=>({...x,close:100}))
 assert.ok(indexScoreSeries(rows,benchmark).at(-1).strength>50)
 const missing=benchmark.filter(x=>x.date!==rows.at(-6).date)
 assert.equal(indexScoreSeries(rows,missing).at(-1).strength,null)
})
test('a historical score is invariant to future prices and future volume',()=>{
 const all=bars(120),prefix=all.slice(0,100),past=indexScoreSeries(prefix).at(-1)
 const future=[...prefix,...all.slice(100).map(x=>({...x,close:10000,volume:900000}))]
 assert.deepEqual(indexScoreSeries(future).find(x=>x.date===past.date),past)
})
test('same-version historical scores immediately provide valid one/five-period changes',()=>{
 const data=Object.fromEntries(INDEXES.map(x=>[x.id,{status:'ok',bars:bars()}]))
 const radar=deriveRadar(data,{},now)
 assert.equal(radar.version,RADAR_VERSION);assert.equal(radar.ashare.history.length,20)
 assert.ok(radar.ashare.change1d&&radar.ashare.change5d);assert.ok(radar.styles.every(s=>s.change5d))
 assert.equal(radar.ashare.date,'2026-11-20')
})
test('failed or obsolete sources never become healthy current scores',()=>{
 const data=Object.fromEntries(INDEXES.map(x=>[x.id,{status:'ok',bars:bars()}]));data.small.status='failed'
 let radar=deriveRadar(data,{},now);assert.equal(radar.styles.find(x=>x.id==='small').strength,null)
 radar=deriveRadar({ashare:{status:'ok',bars:bars().map(x=>({...x,date:x.date.replace('2026','2019')}))}},{},now)
 assert.equal(radar.ashare.status,'stale');assert.equal(radar.ashare.strength,null)
})
test('global daily scores require every declared core signal and do not consume future macro rows',()=>{
 const p=bars(),series={sp500:p.map(x=>({date:x.date,value:x.close})),vix:p.map(x=>({date:x.date,value:20})),us10y:p.map(x=>({date:x.date,value:4})),real10y:p.map(x=>({date:x.date,value:2})),dollar:p.map(x=>({date:x.date,value:100}))}
 const scored=globalScoreSeries(series);assert.ok(scored.length>20)
 assert.equal(globalScoreSeries({...series,dollar:[]}).length,0)
 const t=scored.at(-20),altered={...series,vix:series.vix.map(x=>x.date>t.date?{...x,value:99}:x)}
 assert.deepEqual(globalScoreSeries(altered).find(x=>x.date===t.date),t)
})

test('fixed source lookup refuses arbitrary destinations and isolates provider failure',async()=>{
 const {loadRadarIndex,buildMarketRadar}=await import('../functions/_lib/market-radar.js')
 await assert.rejects(()=>loadRadarIndex('https://elsewhere.test'),/INVALID_RADAR_INDEX/)
 const data=await buildMarketRadar({now,loadIndex:async id=>({id,status:id==='small'?'failed':'ok',bars:bars()}),loadMacro:async()=>{throw Error('private error')}})
 assert.equal(data.styles.find(x=>x.id==='small').strength,null)
 assert.ok(data.sourceErrors>0);assert.ok(!JSON.stringify(data).includes('private error'))
})
test('global invalid zero-price input cannot coerce a missing score into zero',()=>{
 const p=bars(),base=Object.fromEntries(['sp500','vix','us10y','real10y','dollar'].map(id=>[id,p.map(x=>({date:x.date,value:id==='dollar'?0:100}))]))
 assert.equal(globalScoreSeries(base).length,0)
})
test('Nov18 cannot be current on Nov22; session freshness respects closed exchanges',()=>{
 const data=Object.fromEntries(INDEXES.map(x=>[x.id,{status:'ok',bars:bars().filter(r=>r.date<='2026-11-18')}]))
 assert.equal(deriveRadar(data,{},now).ashare.status,'stale')
 assert.equal(deriveRadar(data,{},now).ashare.strength,null)
})
test('official holiday calendars preserve the last completed session and fail closed when unverified',async()=>{
 const {expectedCompletedSession}=await import('../src/features/market-radar/calendar.mjs')
 assert.equal(expectedCompletedSession('china',{date:'2026-10-07',minute:1000}),'2026-09-30')
 assert.equal(expectedCompletedSession('china',{date:'2026-11-23',minute:600}),'2026-11-20')
 assert.equal(expectedCompletedSession('china',{date:'2026-11-23',minute:960}),'2026-11-23')
 assert.equal(expectedCompletedSession('us',{date:'2026-11-26',minute:1300}),'2026-11-25')
 assert.equal(expectedCompletedSession('global',{date:'2026-11-11',minute:1300}),'2026-11-10')
 assert.equal(expectedCompletedSession('china',{date:'2027-02-10',minute:1000}),null)
})
test('radar treasury lookback includes the previous year after March without changing default risk requests',async()=>{
 const {fetchRiskSource}=await import('../functions/_lib/cross-market-risk.js')
 const urls=[];const fetcher=async url=>{urls.push(String(url));return new Response('<entry><m:properties><d:NEW_DATE>2027-02-26T00:00:00</d:NEW_DATE><d:BC_10YEAR>4</d:BC_10YEAR></m:properties></entry>')}
 await fetchRiskSource('treasury',{fetcher,now:Date.parse('2027-03-01'),historyYears:2})
 assert.ok(urls.some(u=>u.includes('2026')));assert.ok(urls.some(u=>u.includes('2027')))
 urls.length=0;await fetchRiskSource('treasury',{fetcher,now:Date.parse('2027-03-01')})
 assert.equal(urls.length,1)
})

test('style missing a session never compares different five-session windows',()=>{
 const benchmark=bars(),style=benchmark.filter(x=>x.date!==benchmark.at(-3).date)
 assert.equal(indexScoreSeries(style,benchmark).at(-1).strength,null)
})
test('real breadth and signed funds affect v2 scores without removing price factors',()=>{
 const prices=bars(120,()=>100),date=prices.at(-1).date
 const evidence={history:[{date,up:80,down:10,flat:10,turnover:1e9,mainNetFlow:5e7,fundMatched:null,fundExpected:null,membershipMode:'provider-aggregate'}]}
 const positive=indexScoreSeries(prices,undefined,25,evidence).at(-1)
 const negative=indexScoreSeries(prices,undefined,25,{history:[{...evidence.history[0],up:10,down:80,mainNetFlow:-5e7}]}).at(-1)
 assert.ok(positive.strength>negative.strength);assert.ok(positive.risk<negative.risk)
 assert.ok(positive.factors.strength.some(f=>f.key==='ma60'))
 assert.ok(positive.factors.strength.some(f=>f.key==='advancingShare'))
 assert.ok(positive.factors.strength.some(f=>f.key==='fundDirection'))
 assert.equal(positive.factors.strength.reduce((sum,f)=>sum+f.weight,0),100)
})
test('missing or off-date funds never renormalize required factors or reuse old dates',()=>{
 const prices=bars(),date=prices.at(-1).date,r={date,up:30,down:60,flat:10,turnover:1e9,mainNetFlow:null,fundMatched:null,fundExpected:null,membershipMode:'provider-aggregate'}
 const p=indexScoreSeries(prices,undefined,25,{history:[r]}).at(-1)
 assert.equal(p.strength,null);assert.equal(p.risk,null);assert.ok(Number.isFinite(p.heat))
 assert.equal(indexScoreSeries(prices,undefined,25,{history:[{...r,date:'2026-11-19',mainNetFlow:1e7}]}).at(-1).strength,null)
})
test('incomplete member funds cannot enter scores even if a sum is present',()=>{
 const prices=bars(),r={date:prices.at(-1).date,up:30,down:60,flat:10,turnover:1e9,mainNetFlow:1e7,fundMatched:99,fundExpected:100,membershipMode:'current-members'}
 assert.equal(indexScoreSeries(prices,undefined,25,{history:[r]}).at(-1).strength,null)
})
