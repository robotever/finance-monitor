import type { NewsData } from '@/types'
import {
  fetchFtchinese, fetchInvesting,
  fetchBloomberg, fetchMarketwatch, fetchSinaFinance,
  fetchWallstreetcn, fetchJin10, fetchCankaoxiaoxi, fetchMktnews, fetchGelonghui,
  fetchEastmoney,
} from './fetchers/direct'
import { getMockItems } from './mock'
import { limitNewsItems } from './news-policy.mjs'

const FETCHERS: Record<string, () => Promise<any[]>> = {
  sinafinance:  fetchSinaFinance,
  eastmoney:    fetchEastmoney,
  ftchinese:    fetchFtchinese,
  investing:    fetchInvesting,
  bloomberg:    fetchBloomberg,
  marketwatch:  fetchMarketwatch,
  wallstreetcn: fetchWallstreetcn,
  jin10:        fetchJin10,
  cankaoxiaoxi: fetchCankaoxiaoxi,
  mktnews:      fetchMktnews,
  gelonghui:    fetchGelonghui,
}

const DEMO_SOURCES = new Set<string>([])

export async function loadNewsSource(sourceId: string): Promise<NewsData> {
  if (DEMO_SOURCES.has(sourceId)) {
    return { source: sourceId, items: limitNewsItems(getMockItems(sourceId)), updatedAt: Date.now(), loading: false }
  }
  const fetcher = FETCHERS[sourceId]
  if (!fetcher) {
    return { source: sourceId, items: [], updatedAt: 0, loading: false, error: '未配置信源' }
  }
  const local=import.meta.env.VITE_LOCAL_HOME==='true',key='finance-monitor-local-news:'+sourceId
  let saved:NewsData|null=null
  if(local){try{const value=JSON.parse(localStorage.getItem(key)??'null');if(value?.source===sourceId&&Array.isArray(value.items)&&Number.isFinite(value.updatedAt))saved=value}catch{}}
  try {
    const items = await fetcher()
    let updatedAt=Date.now(),cached=false
    if(local){
      try{const r=await fetch('/api/local/source-state?source='+encodeURIComponent(sourceId),{signal:AbortSignal.timeout(3000)});if(!r.ok)throw Error();const state=await r.json();cached=Boolean(state.cached);updatedAt=Number.isFinite(state.fetchedAt)?state.fetchedAt:saved?.updatedAt??0}catch{cached=true;updatedAt=saved?.updatedAt??0}
    }
    const value:NewsData={ source: sourceId, items: limitNewsItems(items), updatedAt, loading: false, ...(cached?{cached:true}:{} ) }
    if(local){try{localStorage.setItem(key,JSON.stringify(value))}catch{}}
    return value
  } catch (err) {
    if(local&&saved?.items.length)return {...saved,loading:false,cached:true,error:'使用上次保存的新闻'}
    const msg = err instanceof Error ? err.message : '加载失败'
    console.error(`[${sourceId}]`, msg)
    return { source: sourceId, items: [], updatedAt: Date.now(), loading: false, error: msg }
  }
}
