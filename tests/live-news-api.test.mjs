import test from 'node:test'
import assert from 'node:assert/strict'
import {loadFeed,onRequestGet} from '../functions/api/news/live.js'
import {onRequestGet as quoteGet} from '../functions/api/market-watch/quote.js'
test('feed loader parses static JSON assignment without executing JavaScript',async()=>{
 const data=await loadFeed('jin10',async()=>new Response('var newest = [{"id":1,"time":"2026-11-21 12:00:00"}];'))
 assert.equal(data[0].id,1)
 await assert.rejects(()=>loadFeed('jin10',async()=>new Response('var newest = (()=>process.exit())();')))
})
test('feed loader rejects overlarge and failed upstream responses',async()=>{
 await assert.rejects(()=>loadFeed('jin10',async()=>new Response('x'.repeat(1500001))))
 await assert.rejects(()=>loadFeed('wallstreetcn',async()=>new Response('',{status:503})))
})
test('quote endpoint is fixed allowlist and cannot become arbitrary upstream proxy',async()=>{
 const r=await quoteGet({request:new Request('https://example.com/api/market-watch/quote?instrument=https://evil.com')})
 assert.equal(r.status,400)
})
