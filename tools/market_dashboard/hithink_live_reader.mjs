import {createSnapshotReader} from './hithink_snapshot_reader.mjs'

// A generation becomes visible only after every requested document is available.
export function createLiveReader(fetcher=globalThis.fetch,{timeoutMs=12000,detailTimeoutMs=90000}={}){
 async function timedFetch(url,options={},limitMs=timeoutMs){
  const controller=new AbortController();let timer
  try{return await Promise.race([
   (async()=>{const r=await fetcher(url,{...options,signal:controller.signal});const data=r.ok?await r.json():null;return {ok:r.ok,status:r.status,json:async()=>data}})(),
   new Promise((_,reject)=>{timer=setTimeout(()=>{controller.abort();reject(Error('LIVE_UNAVAILABLE'))},limitMs)})
  ])}finally{clearTimeout(timer)}
 }
 const fallback=createSnapshotReader(timedFetch),cache=new Map(),generations=[]
 function prune(){
  for(const id of cache.keys())if(!generations.includes(id.split(':')[0]))cache.delete(id)
 }
 let active=null,pending=null,status={mode:'loading',refreshFailed:false}
 function keyFor(url){
  const [kind,query='']=url.split('?'),p=new URLSearchParams(query),u=p.get('universe')
  if(kind==='latest')return 'latest'
  if(!['concept','industry'].includes(u))throw Error('INVALID_QUERY')
  if(kind==='catalog')return `catalog-${u}`
  if(kind==='history'&&['return1d','strength','opportunity','risk'].includes(p.get('axis')))return `history-${u}-${p.get('axis')}`
  if(kind==='detail'&&/^88[156]\d{3}\.TI$/.test(p.get('id')??''))return `detail-${p.get('id')}`
  throw Error('INVALID_QUERY')
 }
 async function document(generation,key){
  const id=generation+':'+key
  if(!cache.has(id))cache.set(id,(async()=>{
   const p=new URLSearchParams({generation,key});if(key.startsWith('detail-'))p.set('view','summary')
   const r=await timedFetch('/api/sector-live/document?'+p,{cache:'no-store'},key.startsWith('detail-')?detailTimeoutMs:timeoutMs)
   if(!r.ok)throw Error('LIVE_UNAVAILABLE')
   const data=await r.json()
   if(!data||typeof data!=='object'||Array.isArray(data))throw Error('LIVE_UNAVAILABLE')
   return data
  })().catch(e=>{cache.delete(id);throw e}))
  return cache.get(id)
 }
 async function refresh(urls=['latest']){
  if(pending)return pending
  pending=(async()=>{try{
   const r=await timedFetch('/api/sector-live/manifest',{cache:'no-store'})
   if(r.status===404&&!active){await Promise.all(urls.map(fallback));status={mode:'fallback',refreshFailed:false};return status}
   if(!r.ok)throw Error('LIVE_UNAVAILABLE')
   const m=await r.json()
   if(!/^[a-f0-9]{64}$/.test(m?.generation??'')||m.mode!=='live'||m.automaticUpdates!==true)throw Error('LIVE_UNAVAILABLE')
   await Promise.all(urls.map(url=>document(m.generation,keyFor(url))))
   active=m;status={...m,refreshFailed:false};
   const index=generations.indexOf(m.generation);if(index>=0)generations.splice(index,1)
   generations.push(m.generation);if(generations.length>2)generations.shift();prune();return status
  }catch(e){prune();status={...status,refreshFailed:true};throw Error('LIVE_UNAVAILABLE')}finally{pending=null}})()
  return pending
 }
 async function request(url){
  const key=keyFor(url),generation=active?.generation
  if(!generation){if(status.mode!=='fallback')await refresh([url]);if(!active)return fallback(url)}
  const data=await document(generation??active.generation,key)
  if(!key.startsWith('catalog-'))return data
  const p=new URLSearchParams(url.split('?')[1]),q=p.get('q')??'',page=Number(p.get('page')??1),pageSize=Number(p.get('pageSize')??50)
  if(!Number.isInteger(page)||page<1||!Number.isInteger(pageSize)||pageSize<1||pageSize>100||q.length>100)throw Error('INVALID_QUERY')
  const rows=data.sectors.filter(r=>r.name.toLowerCase().includes(q.toLowerCase())||r.id.toLowerCase().includes(q.toLowerCase()))
  return {...data,q,page,pageSize,total:rows.length,sectors:rows.slice((page-1)*pageSize,page*pageSize)}
 }
 request.refresh=refresh
 request.getStatus=()=>({...status})
 request.constituents=async(id,date)=>{
  if(!/^88[156]\d{3}\.TI$/.test(id)||!/^\d{4}-\d{2}-\d{2}$/.test(date)||!active)throw Error('LIVE_UNAVAILABLE')
  const generation=active.generation,p=new URLSearchParams({generation,key:'detail-'+id,view:'members',date})
  const r=await timedFetch('/api/sector-live/document?'+p,{cache:'no-store'},detailTimeoutMs)
  if(!r.ok)throw Error('LIVE_UNAVAILABLE')
  const data=await r.json();if(!Array.isArray(data?.rows))throw Error('LIVE_UNAVAILABLE')
  return {generation,data}
 }
 return request
}
