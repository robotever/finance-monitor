import {INSTRUMENTS,parseMinute,parseDaily,parseDollar} from '../../../src/features/market-watch/model.mjs'
import {upstreamText} from '../../_lib/upstream.js'
export async function onRequestGet({request,waitUntil}){
 const url=new URL(request.url),instrument=INSTRUMENTS.find(i=>i.id===url.searchParams.get('instrument')&&i.provider!=='tradingview')
 if(!instrument)return Response.json({error:'INVALID_INSTRUMENT'},{status:400})
 const cache=globalThis.caches?.default,key=new Request(url.origin+url.pathname+'?instrument='+instrument.id)
 const cached=cache?await cache.match(key):null;if(cached)return cached
 try{
  let value
  if(instrument.provider==='sina'){
   const [quote,history]=await Promise.all([
    upstreamText('https://hq.sinajs.cn/list=DINIW',{headers:{'User-Agent':'Mozilla/5.0','Referer':'https://finance.sina.com.cn/'},encoding:'gb18030',maxBytes:10000}),
    upstreamText('https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_data=/NewForexService.getDayKLine?symbol=DINIW',{headers:{'Referer':'https://finance.sina.com.cn/'},maxBytes:1000000})
   ]);value=parseDollar(quote,history)
  }else{
   const endpoint=instrument.session==='daily'?'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+instrument.code+',day,,,60,qfq':'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code='+instrument.code
   const text=await upstreamText(endpoint,{headers:{'User-Agent':'Mozilla/5.0','Referer':'https://gu.qq.com/'},maxBytes:1000000})
   value=(instrument.session==='daily'?parseDaily:parseMinute)(JSON.parse(text),instrument.code)
  }
  const response=Response.json(value,{headers:{'Cache-Control':'public, max-age=20','X-Content-Type-Options':'nosniff'}})
  if(cache)waitUntil(cache.put(key,response.clone()))
  return response
 }catch{return Response.json({error:'QUOTE_UNAVAILABLE'},{status:502,headers:{'Cache-Control':'no-store'}})}
}
