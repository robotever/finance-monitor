import {buildFinancialNews,loadFeed,newsCacheSeconds} from '../../_lib/financial-news.js'
import {NEWS_POLICY_VERSION} from '../../../src/features/live-news/policy.mjs'
import {onRequestGet as readQuote} from '../market-watch/quote.js'
export {loadFeed}
export async function onRequestGet({request,waitUntil}){
 const url=new URL(request.url);url.search='';url.searchParams.set('policy',NEWS_POLICY_VERSION)
 const cache=globalThis.caches?.default,cacheKey=new Request(url.toString())
 const cached=cache?await cache.match(cacheKey):null
 if(cached)return cached
 const data=await buildFinancialNews({origin:url.origin,loadQuote:async id=>{
  const response=await readQuote({request:new Request(new URL('/api/market-watch/quote?instrument='+id,url.origin)),waitUntil})
  if(!response.ok)throw Error('QUOTE_UNAVAILABLE')
  return response.json()
 }})
 const ttl=newsCacheSeconds(data)
 const response=Response.json(data,{headers:{'Cache-Control':ttl>0?'public, max-age='+ttl:'no-store','X-Content-Type-Options':'nosniff'}})
 if(cache&&ttl>0)waitUntil(cache.put(cacheKey,response.clone()))
 return response
}
