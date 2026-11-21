import test from 'node:test'
import assert from 'node:assert/strict'
import {loadFeed,buildFinancialNews,newsCacheSeconds} from '../functions/_lib/financial-news.js'
const now=Date.parse('2026-11-21T11:30:00Z')
test('Futu source URLs use fixed finite queries and official structured search params',async()=>{
 let seen
 const data=await loadFeed('futu_company',async(url,options)=>{seen={url,options};return Response.json({code:0,data:[]})})
 const u=new URL(seen.url);assert.equal(u.hostname,'ai-news-search.futunn.com');assert.equal(u.searchParams.get('keyword'),'公司');assert.equal(u.searchParams.get('news_type'),'1');assert.equal(u.searchParams.get('sort_type'),'2');assert.equal(data.code,0)
 await assert.rejects(()=>loadFeed('https://evil.example',async()=>{throw Error('should not fetch')}))
})
test('finance API isolates bad channels, filters ordinary affairs, and shows only fresh live observations',async()=>{
 const out=await buildFinancialNews({origin:'https://example.com',now,loadNews:async id=>{
  if(id==='futu_company')return {code:0,data:[{news_id:'company1',title:'某公司业绩增长',publish_time:String((now-10000)/1000),url:'https://news.futunn.com/post/company1'}]}
  if(id==='wallstreetcn')return {data:{items:[{id:'geo',title:'俄军方击落多架无人机',display_time:(now-1000)/1000}]}}
  throw Error('offline')
 },loadQuote:async id=>({price:3500,changePercent:1.2,status:id==='shanghai'?'intraday':'closed',observedAt:new Date(now-3000).toISOString()})})
 assert.equal(out.policyVersion,'finance-v1');assert.equal(out.items.length,2);assert.equal(out.categories.market,1);assert.equal(out.categories.company,1)
 assert.ok(out.sources.some(s=>s.id==='futu_flash'&&s.status==='failed'));assert.ok(out.sources.some(s=>s.id==='futu_company'&&s.status==='ok'));assert.equal(out.items[0].source,'market_monitor')
})
test('a story published during upstream collection is not rejected as future data',async t=>{
 let clock=now;t.mock.method(Date,'now',()=>clock)
 const out=await buildFinancialNews({origin:'https://example.com',loadNews:async id=>{if(id!=='futu_company')throw Error('offline');clock=now+5000;return {code:0,data:[{news_id:'during',title:'某公司公布业绩',publish_time:String(clock/1000),url:'https://news.futunn.com/post/during'}]}},loadQuote:async()=>{throw Error('offline')}})
 assert.equal(out.items.length,1);assert.equal(out.fetchedAt,now+5000)
})

test('slow news channels cannot extend monitor snapshot life beyond180seconds',async t=>{
 let clock=now;t.mock.method(Date,'now',()=>clock)
 const out=await buildFinancialNews({origin:'https://example.com',loadNews:async id=>{if(id!=='futu_company')throw Error('offline');await new Promise(resolve=>setTimeout(()=>{clock=now+5000;resolve()},10));return {code:0,data:[]}},loadQuote:async()=>({price:3500,changePercent:2.3,status:'intraday',observedAt:new Date(now-178000).toISOString()})})
 assert.equal(out.items.filter(i=>i.source==='market_monitor').length,0)
})

test('cache cannot outlive the earliest monitor snapshot',()=>{
 const data={sources:[{id:'futu_flash',status:'ok'}],items:[{source:'market_monitor',publishedAt:now-179000}]}
 assert.equal(newsCacheSeconds(data,now),1)
 assert.equal(newsCacheSeconds(data,now+1000),0)
 assert.equal(newsCacheSeconds({...data,items:[]},now),20)
 assert.equal(newsCacheSeconds({...data,sources:[{id:'futu_flash',status:'failed'},{id:'market_monitor',status:'ok'}]},now),0)
})
