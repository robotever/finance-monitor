import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createLocalNews} from '../tools/market_dashboard/local_home_news.mjs'
test('news survives offline restart without refreshing timestamps; expired items move out of live stream',async t=>{
 const root=await mkdtemp(join(tmpdir(),'local-news-'));t.after(()=>rm(root,{recursive:true,force:true}))
 let now=Date.parse('2026-11-22T12:00:00Z');t.mock.method(Date,'now',()=>now)
 const payload={props:{initialState:{roll_data:[{id:123,title:'某公司发布业绩',ctime:(now-10000)/1000}]}}}
 const fetcher=async url=>{if(url==='https://m.cls.cn/telegraph')return new Response('<script>__NEXT_DATA__ = '+JSON.stringify(payload)+';</script>');throw Error('offline')}
 const live=await createLocalNews({stateRoot:root,fetcher,loadQuote:async()=>{throw Error('closed')}})()
 assert.equal(live.items.length,1);const published=live.items[0].publishedAt,success=live.fetchedAt
 now+=60000
 const fail=async()=>{throw Error('OFFLINE')}
 const cached=await createLocalNews({stateRoot:root,fetcher:fail,loadQuote:fail,offline:true})()
 assert.equal(cached.localStatus.mode,'cached');assert.equal(cached.items[0].publishedAt,published);assert.equal(cached.localStatus.lastSuccessAt,success)
 now+=3*3600000
 const expired=await createLocalNews({stateRoot:root,fetcher:fail,loadQuote:fail,offline:true})()
 assert.equal(expired.items.length,0);assert.equal(expired.archiveItems[0].publishedAt,published)
 assert.ok(expired.sources.filter(s=>s.id!=='market_monitor').every(s=>s.status==='failed'))
})
