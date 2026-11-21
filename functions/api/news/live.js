import {upstreamText} from '../../_lib/upstream.js'
import {collectNews} from '../../../src/features/live-news/model.mjs'
const FEEDS={
 wallstreetcn:'https://api-one.wallstcn.com/apiv1/content/lives?channel=global-channel&limit=100',
 jin10:'https://www.jin10.com/flash_newest.js',
 mktnews:'https://api.mktnews.net/api/flash?type=0&limit=100',
}
export async function loadFeed(source,fetcher=fetch){
 let text=await upstreamText(FEEDS[source],{fetcher,headers:{'User-Agent':'Mozilla/5.0','Accept':'application/json, text/javascript, */*','Referer':source==='jin10'?'https://www.jin10.com/':source==='wallstreetcn'?'https://wallstreetcn.com/':'https://mktnews.net/'}})
 if(source==='jin10')text=text.replace(/^\s*var\s+newest\s*=\s*/,'').replace(/;\s*$/,'')
 return JSON.parse(text)
}
export async function onRequestGet({request,waitUntil}){
 const url=new URL(request.url);url.search=''
 const cache=globalThis.caches?.default,cacheKey=new Request(url.toString())
 const cached=cache?await cache.match(cacheKey):null
 if(cached)return cached
 const data=await collectNews(id=>loadFeed(id),Date.now(),['wallstreetcn','jin10'])
 const response=Response.json(data,{headers:{'Cache-Control':data.sources.some(s=>s.status==='ok')?'public, max-age=20':'no-store','X-Content-Type-Options':'nosniff'}})
 if(cache&&data.sources.some(s=>s.status==='ok'))waitUntil(cache.put(cacheKey,response.clone()))
 return response
}
