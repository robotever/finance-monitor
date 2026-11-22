import test from 'node:test'
import assert from 'node:assert/strict'
import {parseClsTelegraph} from '../functions/_lib/cls-news.js'
import {loadFeed,buildFinancialNews} from '../functions/_lib/financial-news.js'
import {normalizeFeed} from '../src/features/live-news/model.mjs'
const now=Date.parse('2026-11-22T11:30:00Z')
const rows=[{id:123,title:'某公司发布业绩',ctime:(now-10000)/1000,level:'B',stock_list:[{code:'600000'}]},{id:124,content:'<b>半导体行业订单增长</b>',ctime:(now-20000)/1000,level:'C'},{id:125,title:'广告公司推广',ctime:now/1000,is_ad:1},{id:126,title:'某公司过期公告',ctime:(now-3*3600000)/1000},{id:127,title:'某公司未来公告',ctime:(now+60000)/1000}]
const payload={props:{note:'braces { } and quoted \"text\"',initialState:{roll_data:rows}}}
const html=`<html><script>__NEXT_DATA__ = ${JSON.stringify(payload)};window.untrusted=true</script></html>`
test('CLS parser extracts only JSON, handles braces in strings, and never evaluates scripts',()=>{
 const result=parseClsTelegraph(html)
 assert.deepEqual(result.data,rows)
 assert.deepEqual(parseClsTelegraph(`<script id="__NEXT_DATA__" type="application/json">${JSON.stringify(payload)}</script>`),result)
 assert.throws(()=>parseClsTelegraph('<html>blocked</html>'))
 assert.throws(()=>parseClsTelegraph('<script>__NEXT_DATA__ = {"props":{}};</script>'))
 assert.equal(globalThis.untrusted,undefined)
})
test('CLS uses official fixed endpoint and preserves event time, source and original article URL',async()=>{
 let seen
 const data=await loadFeed('cls_telegraph',async(url,options)=>{seen={url,options};return new Response(html)})
 assert.equal(seen.url,'https://m.cls.cn/telegraph')
 const items=normalizeFeed('cls_telegraph',data)
 assert.equal(items.length,4);assert.equal(items[0].sourceName,'财联社');assert.equal(items[0].publishedAt,now-10000)
 assert.equal(items[0].url,'https://www.cls.cn/detail/123');assert.equal(items[0].important,true)
 assert.equal(items[0].relatedStockCount,1);assert.equal(items[1].title,'半导体行业订单增长')
})
test('CLS joins common filtering, freshness and channel failure isolation',async()=>{
 const out=await buildFinancialNews({origin:'https://example.test',now,loadNews:async id=>{if(id==='cls_telegraph')return parseClsTelegraph(html);throw Error('offline')},loadQuote:async()=>{throw Error('closed')}})
 assert.deepEqual(out.items.map(x=>x.id),['cls_telegraph:123','cls_telegraph:124'])
 assert.equal(out.sources.find(s=>s.id==='cls_telegraph').status,'ok')
 assert.ok(out.sources.some(s=>s.id==='futu_flash'&&s.status==='failed'))
})
