// Read only exported view documents. Never call a provider from the browser.
export function createSnapshotReader(fetcher=globalThis.fetch){
 let manifestPromise
 const cached=new Map()
 async function read(path){
  if(!cached.has(path))cached.set(path,(async()=>{
   const r=await fetcher(path,{cache:'no-cache'})
   if(!r.ok)throw Error('SNAPSHOT_UNAVAILABLE')
   try{return await r.json()}catch{throw Error('SNAPSHOT_UNAVAILABLE')}
  })().catch(error=>{cached.delete(path);throw error}))
  return cached.get(path)
 }
 return async function request(url){
  const [kind,query='']=url.split('?'),p=new URLSearchParams(query),universe=p.get('universe')
  if(!['latest','catalog','history','detail'].includes(kind)||kind!=='latest'&&!['industry','concept'].includes(universe))throw Error('INVALID_QUERY')
  const id=p.get('id'),axis=p.get('axis')
  if(kind==='detail'&&!/^88[156]\d{3}\.TI$/.test(id??''))throw Error('INVALID_QUERY')
  if(kind==='history'&&!['return1d','strength','opportunity','risk'].includes(axis))throw Error('INVALID_QUERY')
  manifestPromise??=read('/data/sector-research/manifest.json').catch(error=>{manifestPromise=null;throw error})
  const manifest=await manifestPromise
  if(!/^[a-zA-Z0-9_-]{1,100}$/.test(manifest.generation??''))throw Error('SNAPSHOT_UNAVAILABLE')
  const filename=kind==='latest'?'latest':kind==='catalog'?`catalog-${universe}`:kind==='history'?`history-${universe}-${axis}`:`detail-${id}`
  const data=await read(`/data/sector-research/${manifest.generation}/${filename}.json`)
  if(kind!=='catalog')return data
  const q=p.get('q')??'',page=Number(p.get('page')??1),pageSize=Number(p.get('pageSize')??50)
  if(!Number.isInteger(page)||page<1||!Number.isInteger(pageSize)||pageSize<1||pageSize>100||q.length>100)throw Error('INVALID_QUERY')
  const matched=data.sectors.filter(r=>r.name.toLowerCase().includes(q.toLowerCase())||r.id.toLowerCase().includes(q.toLowerCase()))
  return {...data,q,page,pageSize,total:matched.length,sectors:matched.slice((page-1)*pageSize,page*pageSize)}
 }
}
