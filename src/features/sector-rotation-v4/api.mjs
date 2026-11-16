import {validateLatest,validateCatalog,validateHistory,validateDetail,catalogQuery} from './model.mjs'
const messages={NO_SNAPSHOT:'暂无同花顺有效快照',INVALID_SCHEMA:'同花顺数据版本或格式不一致',INVALID_QUERY:'查询条件无效',HTTP_ERROR:'板块数据服务暂不可用',NETWORK_ERROR:'板块数据连接失败',TIMEOUT:'板块数据读取超时',ABORTED:'请求已取消'}
const failure=code=>({data:null,error:{code,message:messages[code]}})
async function load(endpoint,query,validate,o) {
 if(o.signal?.aborted)return failure('ABORTED')
 const controller=new AbortController();let cancel,reason
 const stopped=new Promise(resolve=>{cancel=code=>{reason=code;controller.abort();resolve(failure(code))}})
 const onAbort=()=>cancel('ABORTED');o.signal?.addEventListener('abort',onAbort,{once:true})
 const timer=setTimeout(()=>cancel('TIMEOUT'),o.timeoutMs??12000)
 try{return await Promise.race([stopped,(async()=>{
 try {const response=await(o.fetcher??globalThis.fetch)(`/api/sector-rotation/v4/${endpoint}${query.size?'?'+query:''}`,{signal:controller.signal});if(!response.ok){const body=await response.json().catch(()=>null);return failure(response.status===404&&body?.error==='NO_SNAPSHOT'?'NO_SNAPSHOT':'HTTP_ERROR')}
 try {return {data:validate(await response.json(),o),error:null}} catch{return failure('INVALID_SCHEMA')}
 }catch{return failure(reason??'NETWORK_ERROR')}
 })()])}finally{clearTimeout(timer);o.signal?.removeEventListener('abort',onAbort)}
}
export const loadHithinkLatest=(o={})=>load('latest',new URLSearchParams(),validateLatest,o)
export function loadHithinkCatalog(o={}) {try{return load('catalog',catalogQuery(o),validateCatalog,o)}catch{return Promise.resolve(failure('INVALID_QUERY'))}}
export function loadHithinkHistory(o={}) {
 if(!['industry','concept'].includes(o.universe)||!['strength','opportunity','risk'].includes(o.axis)||!Number.isInteger(o.days??15)||(o.days??15)<1||(o.days??15)>15)return Promise.resolve(failure('INVALID_QUERY'))
 return load('history',new URLSearchParams({universe:o.universe,axis:o.axis,days:String(o.days??15)}),validateHistory,o)
}
export function loadHithinkDetail(o={}) {
 if(!['industry','concept'].includes(o.universe)||!(o.universe==='industry'?/^881\d{3}\.TI$/:/^88[56]\d{3}\.TI$/).test(o.id)||!Number.isInteger(o.days??60)||(o.days??60)<1||(o.days??60)>60)return Promise.resolve(failure('INVALID_QUERY'))
 return load('detail',new URLSearchParams({universe:o.universe,id:o.id,days:String(o.days??60)}),validateDetail,o)
}
