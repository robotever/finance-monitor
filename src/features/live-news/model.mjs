export const NEWS_WINDOW_MS=2*60*60*1000
export const SOURCE_NAMES={wallstreetcn:'华尔街见闻',jin10:'金十数据',mktnews:'MktNews'}
export function parsePublishedAt(value){
 if(value==null||value===''||typeof value==='boolean')return null
 if(typeof value==='number'||/^\d{10,13}$/.test(String(value))){const n=Number(value),ms=n<1e12?n*1000:n;return Number.isFinite(ms)&&ms>=946684800000?ms:null}
 const text=String(value).trim()
 if(!/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(text))return null
 const zoned=/Z$|[+-]\d\d:\d\d$/.test(text)?text:text.replace(' ','T')+'+08:00'
 const ms=Date.parse(zoned);return Number.isFinite(ms)?ms:null
}
const plain=text=>String(text??'').replace(/<[^>]*>/g,'').replace(/&nbsp;/g,' ').replace(/&amp;/g,'&').replace(/&quot;/g,'"').replace(/\s+/g,' ').trim()
const canonicalUrl=value=>{try{const u=new URL(value);if(!['http:','https:'].includes(u.protocol))return null;u.hash='';for(const k of [...u.searchParams.keys()])if(/^utm_/i.test(k)||['fbclid','gclid'].includes(k))u.searchParams.delete(k);u.searchParams.sort();return u.toString()}catch{return null}}
const identity=text=>plain(text).replace(/^【快讯】/,'').replace(/[\p{P}\p{S}\s]/gu,'').toLowerCase()
export function activeNews(items,now=Date.now()){
 return items.filter(i=>typeof i.publishedAt==='number'&&Number.isFinite(i.publishedAt)&&i.publishedAt<=now&&now-i.publishedAt<=NEWS_WINDOW_MS)
}
export function freshNews(items,now=Date.now()){
 const result=[],candidates=[],seen=new Map(),seenUrl=new Map()
 for(const item of activeNews(items,now).sort((a,b)=>b.publishedAt-a.publishedAt)){
  if(!item.title)continue
  const url=canonicalUrl(item.url);if(!url)continue
  const key=identity(item.title),old=seen.get(key)??seenUrl.get(url)??candidates.find(c=>c.row.source!==item.source&&Math.abs(c.row.publishedAt-item.publishedAt)<1200000&&Math.min(key.length,c.key.length)>=20&&(key.includes(c.key)||c.key.includes(key)))?.row
  if(old){old.sources=[...new Set([...old.sources,item.sourceName])];continue}
  if(result.length>=100)continue
  const row={...item,sources:[...(item.sources??[item.sourceName])]};result.push(row);candidates.push({row,key});seen.set(key,row);seenUrl.set(url,row)
 }
 return result
}
export function normalizeFeed(source,data){
 const rows=source==='wallstreetcn'?data?.data?.items:source==='jin10'?data:data?.data
 if(!Array.isArray(rows))throw Error('INVALID_FEED')
 return rows.filter(k=>source!=='jin10'||!k.channel?.includes(5)).map(k=>{
  const title=plain(source==='wallstreetcn'?(k.title||k.content_text):(k.data?.title||k.data?.content)),publishedAt=parsePublishedAt(source==='wallstreetcn'?k.display_time:k.time)
  const url=source==='wallstreetcn'?(k.uri||`https://wallstreetcn.com/livenews/${encodeURIComponent(k.id)}`):source==='jin10'?`https://flash.jin10.com/detail/${encodeURIComponent(k.id)}`:`https://mktnews.net/flashDetail.html?id=${encodeURIComponent(k.id)}`
  return {id:`${source}:${k.id}`,title:title.slice(0,1200),url,source,sourceName:SOURCE_NAMES[source],publishedAt,important:source==='wallstreetcn'?Number(k.score)>1:Boolean(k.important)}
 }).filter(k=>k.title&&k.publishedAt!==null&&/^https:\/\//.test(k.url))
}
export async function collectNews(loader,now=Date.now(),sources=Object.keys(SOURCE_NAMES)){
 const results=await Promise.all(sources.map(async source=>{try{const items=normalizeFeed(source,await loader(source));const newestAt=items.length?Math.max(...items.map(i=>i.publishedAt)):null;return {items,status:{id:source,name:SOURCE_NAMES[source],status:items.length?'ok':'empty',newestAt}}}catch{return {items:[],status:{id:source,name:SOURCE_NAMES[source],status:'failed',newestAt:null}}}}))
 return {items:freshNews(results.flatMap(r=>r.items),now),sources:results.map(r=>r.status),fetchedAt:now}
}
