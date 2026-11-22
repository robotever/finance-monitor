import {authorized,errorResponse,jsonResponse} from '../../_lib/market-dashboard.js'
import {upstreamText} from '../../_lib/upstream.js'
export async function onRequestGet({request,env}){
 if(!env.MARKET_DASHBOARD_PUBLISH_TOKEN)return errorResponse('SERVICE_UNAVAILABLE',503)
 if(!await authorized(request,env.MARKET_DASHBOARD_PUBLISH_TOKEN))return errorResponse('UNAUTHORIZED',401)
 const q=new URL(request.url).searchParams,code=q.get('code')
 if(q.getAll('code').length!==1||[...q.keys()].some(k=>k!=='code')||!/^\d{6}\.(SH|SZ|BJ)$/.test(code??''))return errorResponse('INVALID_IDENTITY',400)
 const p=new URLSearchParams({secid:(code.endsWith('.SH')?'1.':'0.')+code.slice(0,6),lmt:'10',klt:'101',fields1:'f1,f2,f3,f7',fields2:Array.from({length:15},(_,i)=>'f'+(51+i)).join(','),ut:'b2884a393a59ad64002292a3e90d46a5'})
 let blockedStatus=null
 const fetcher=async(url,options)=>{const response=await fetch(url,options);if([403,429].includes(response.status)){blockedStatus=response.status;throw Error('SOURCE_STOPPED')}return response}
 try{
  const raw=JSON.parse(await upstreamText('https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get?'+p,{fetcher,headers:{'User-Agent':'Mozilla/5.0','Referer':'https://data.eastmoney.com/'},maxBytes:200000}))
  if(raw.rc!==0||raw.data?.code!==code.slice(0,6)||raw.data?.market!==(code.endsWith('.SH')?1:0)||!Array.isArray(raw.data?.klines)||raw.data.klines.length>150)return errorResponse('INVALID_SOURCE',502)
  return jsonResponse(raw)
 }catch{return errorResponse('UPSTREAM_UNAVAILABLE',blockedStatus??502)}
}
