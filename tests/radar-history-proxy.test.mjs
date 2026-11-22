import test from 'node:test'
import assert from 'node:assert/strict'
import {onRequestGet} from '../functions/api/market-radar/fund-history.js'
const secret='synthetic-only'
test('history transport requires existing publication authorization',async()=>{const r=await onRequestGet({request:new Request('https://example.test/api/market-radar/fund-history?code=600519.SH'),env:{MARKET_DASHBOARD_PUBLISH_TOKEN:secret}});assert.equal(r.status,401)})
test('history transport only accepts one validated stock identity',async()=>{for(const qs of ['code=https://example.test','code=600519.SH&code=000001.SZ','code=600519.SH&url=https://example.test']){const r=await onRequestGet({request:new Request('https://example.test/api/market-radar/fund-history?'+qs,{headers:{Authorization:'Bearer '+secret}}),env:{MARKET_DASHBOARD_PUBLISH_TOKEN:secret}});assert.equal(r.status,400)}})
test('upstream rate limit is preserved and publisher credential is never forwarded',async()=>{
 const old=globalThis.fetch
 try{globalThis.fetch=async(url,options)=>{assert.equal(options.headers.Authorization,undefined);return new Response('',{status:429})}
 const r=await onRequestGet({request:new Request('https://example.test/api/market-radar/fund-history?code=600519.SH',{headers:{Authorization:'Bearer '+secret}}),env:{MARKET_DASHBOARD_PUBLISH_TOKEN:secret}});assert.equal(r.status,429)
 }finally{globalThis.fetch=old}
})
