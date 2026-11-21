import {upstreamText} from './upstream.js'
import {normalizeFeed,freshNews,SOURCE_NAMES} from '../../src/features/live-news/model.mjs'
import {financeNewsPolicy,selectFinancialNews,marketObservation,CATEGORY_LABELS,NEWS_POLICY_VERSION,mediaUnavailable} from '../../src/features/live-news/policy.mjs'
export const NEWS_CHANNELS=['futu_flash','futu_company','futu_industry','futu_market','wallstreetcn','jin10']
const FEEDS={
 wallstreetcn:'https://api-one.wallstcn.com/apiv1/content/lives?channel=a-stock-channel&limit=100',
 jin10:'https://www.jin10.com/flash_newest.js',
 mktnews:'https://api.mktnews.net/api/flash?type=0&limit=100',
 futu_flash:'https://news.futunn.com/news-site-api/main/get-flash-list?pageSize=10',
}
const QUERIES={futu_company:'公司',futu_industry:'行业',futu_market:'异动'}
const LABELS={futu_company:'富途·公司',futu_industry:'富途·行业',futu_market:'富途·异动'}
export async function loadFeed(source,fetcher=fetch){
 let url=FEEDS[source]
 if(QUERIES[source]){const u=new URL('https://ai-news-search.futunn.com/news_search');for(const [key,value] of Object.entries({keyword:QUERIES[source],size:'20',news_type:'1',lang:'zh-CN',sort_type:'2'}))u.searchParams.set(key,value);url=u.toString()}
 if(!url)throw Error('UNSUPPORTED_SOURCE')
 const referer=source.startsWith('futu_')?'https://news.futunn.com/main/live':source==='jin10'?'https://www.jin10.com/':source==='wallstreetcn'?'https://wallstreetcn.com/':'https://mktnews.net/'
 let text=await upstreamText(url,{fetcher,headers:{'User-Agent':QUERIES[source]?'futunn-news-search/0.0.4 (NewsMonitor)':'Mozilla/5.0','Accept':'application/json, text/javascript, */*','Accept-Language':'zh-CN,zh;q=0.9','Referer':referer}})
 if(source==='jin10')text=text.replace(/^\s*var\s+newest\s*=\s*/,'').replace(/;\s*$/,'')
 return JSON.parse(text)
}
export async function buildFinancialNews({loadNews=loadFeed,loadQuote,origin,now}){
 const channelTasks=NEWS_CHANNELS.map(async id=>{
  try{
   const rows=normalizeFeed(id,await loadNews(id)),items=financeNewsPolicy(rows)
   return {items,status:{id,name:LABELS[id]??SOURCE_NAMES[id],status:rows.length?'ok':'empty',newestAt:rows.length?Math.max(...rows.map(i=>i.publishedAt)):null},filtered:rows.length-items.length}
  }catch{return {items:[],status:{id,name:LABELS[id]??SOURCE_NAMES[id],status:'failed',newestAt:null},filtered:0}}
 })
 const monitor=async()=>{
  const rows=await Promise.all(['shanghai','chinext','hstech'].map(async id=>{try{return {id,quote:await loadQuote(id)}}catch{return null}}))
  const valid=rows.filter(Boolean),items=valid.flatMap(row=>{const item=marketObservation(row.id,row.quote,origin,now??Date.now());return item?[item]:[]})
  const stamps=valid.map(row=>Date.parse(row.quote.observedAt)).filter(Number.isFinite)
  return {items,status:{id:'market_monitor',name:'系统监测·指数',status:valid.length?'ok':'failed',newestAt:stamps.length?Math.max(...stamps):null,note:items.length?'新鲜盘中报价快照':'休市、无新鲜行情或未达观察线'},filtered:0}
 }
 const results=await Promise.all([...channelTasks,monitor()])
 const completedAt=now??Date.now()
 const items=selectFinancialNews(results.flatMap(r=>r.items),completedAt)
 const categories=Object.fromEntries(Object.keys(CATEGORY_LABELS).map(category=>[category,items.filter(i=>i.category===category).length]))
 return {policyVersion:NEWS_POLICY_VERSION,items,categories,sources:results.map(r=>r.status),filteredCount:results.reduce((n,r)=>n+r.filtered,0),fetchedAt:completedAt}
}

export function newsCacheSeconds(data,now=Date.now()){
 if(mediaUnavailable(data.sources))return 0
 const remaining=data.items.filter(i=>i.source==='market_monitor').map(i=>Math.floor((i.publishedAt+180000-now)/1000))
 return Math.max(0,Math.min(20,...remaining))
}
