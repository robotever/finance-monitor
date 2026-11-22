import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createLocalHttp,createProxyCache} from '../tools/market_dashboard/local_home_http.mjs'
test('direct transport rejects loopback, credentials and unknown hosts before networking',async()=>{
 const fetcher=createLocalHttp({offline:true})
 await assert.rejects(()=>fetcher('http://127.0.0.1:9999'),/UPSTREAM/)
 await assert.rejects(()=>fetcher('https://user:password@www.cls.cn/'),/UPSTREAM/)
 await assert.rejects(()=>fetcher('https://example.invalid/'),/UPSTREAM/)
})
test('fixed-source proxy cache survives restart and preserves fetch time while marking fallback',async t=>{
 const root=await mkdtemp(join(tmpdir(),'local-http-'));t.after(()=>rm(root,{recursive:true,force:true}))
 const online=createProxyCache({stateRoot:root,fetcher:async()=>new Response('original feed',{headers:{'Content-Type':'text/xml'}}),now:()=>1000})
 const first=await online.get('ftchinese','http://www.ftchinese.com/rss/news');assert.equal(await first.text(),'original feed')
 const offline=createProxyCache({stateRoot:root,fetcher:async()=>{throw Error('offline')},now:()=>999999})
 const cached=await offline.get('ftchinese','http://www.ftchinese.com/rss/news');assert.equal(await cached.text(),'original feed');assert.equal(cached.headers.get('X-Local-Cached'),'true');assert.equal(cached.headers.get('X-Local-Fetched-At'),'1000')
 assert.equal(offline.status('ftchinese').cached,true)
})
