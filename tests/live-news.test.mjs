import test from 'node:test'
import assert from 'node:assert/strict'
import { parsePublishedAt, freshNews, normalizeFeed, collectNews } from '../src/features/live-news/model.mjs'
const now=Date.parse('2026-11-21T04:00:00Z')
const item=(title,time,source='jin10')=>({id:title,title,url:'https://example.com/'+encodeURIComponent(title),publishedAt:time,source,sourceName:source})
test('publication timestamp parses seconds, milliseconds and explicit China time without using fetch time',()=>{
 assert.equal(parsePublishedAt(now/1000),now)
 assert.equal(parsePublishedAt('2026-11-21 12:00:00'),now)
 assert.equal(parsePublishedAt('2026-11-21T04:00:00Z'),now)
 for(const value of [null,undefined,'12:00','yesterday','',0])assert.equal(parsePublishedAt(value),null)
})
test('shared stream sorts, expires without fetch and rejects unknown or future dates',()=>{
 const values=[item('old',now-7200001),item('latest',now-1000),item('earlier',now-3000),item('future',now+60000),item('missing',null)]
 assert.deepEqual(freshNews(values,now).map(i=>i.title),['latest','earlier'])
 assert.equal(freshNews(values,now+7260001).length,0)
})
test('cross-source duplicates are collapsed with corroborating sources preserved',()=>{
 const a=item('【快讯】央行公布利率决定。',now-1000),b=item('央行公布利率决定',now-2000,'wallstreetcn')
 const result=freshNews([a,b],now)
 assert.equal(result.length,1);assert.equal(result[0].sources.length,2)
})
test('adapters preserve real times and plain full headlines',()=>{
 const w=normalizeFeed('wallstreetcn',{data:{items:[{id:1,title:'',content_text:'央行公布决定',display_time:now/1000,uri:'https://wallstreetcn.com/livenews/1'}]}})
 assert.equal(w[0].publishedAt,now);assert.equal(w[0].title,'央行公布决定')
 const j=normalizeFeed('jin10',[{id:2,time:'2026-11-21 12:00:00',data:{content:'【利率】<b>央行</b>公布决定'},important:1}])
 assert.equal(j[0].title,'【利率】央行公布决定');assert.equal(j[0].publishedAt,now)
 assert.equal(normalizeFeed('jin10',[{id:3,data:{content:'无时间'}}]).length,0)
})
test('source failure is isolated and stale source cannot create live items',async()=>{
 const result=await collectNews(async id=>{if(id==='jin10')throw Error('offline');return {data:{items:[{id:1,title:'新消息',display_time:(now-2000)/1000,uri:'https://wallstreetcn.com/livenews/1'}]}}},now,['jin10','wallstreetcn'])
 assert.equal(result.items.length,1);assert.equal(result.sources[0].status,'failed');assert.equal(result.sources[1].status,'ok')
})
test('headline plus syndicated full text collapse when precise headline is contained and time is close',()=>{
 const title='中信证券：预计全国性机制电价政策有望在2027年推出'
 const result=freshNews([item('【'+title+'】'+title+'，更多市场分析。',now-1000),item(title,now-60000,'wallstreetcn')],now)
 assert.equal(result.length,1);assert.equal(result[0].sources.length,2)
})
test('semantic URL query ids distinguish stories while tracking parameters do not',()=>{
 const a={...item('不同的新闻一',now-1000,'mktnews'),url:'https://mktnews.net/flashDetail.html?id=first&utm_source=x'}
 const b={...item('不同的新闻二',now-2000,'mktnews'),url:'https://mktnews.net/flashDetail.html?id=second'}
 assert.equal(freshNews([a,b],now).length,2)
 const c={...a,id:'copy',title:'重新发布的另一个标题',url:'https://mktnews.net/flashDetail.html?utm_source=y&id=first'}
 assert.equal(freshNews([a,c],now).length,1)
})
test('malformed source links are ignored without blocking healthy news',()=>{
 const bad={...item('央行坏链接',now-1000),url:'https://'}
 assert.deepEqual(freshNews([bad,item('央行有效消息',now-2000)],now).map(i=>i.title),['央行有效消息'])
})
