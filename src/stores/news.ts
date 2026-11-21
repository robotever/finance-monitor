import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { NEWS_SOURCES } from '@/api/sources'
import { loadNewsSource } from '@/api'
import {freshNews,activeNews, type LiveNewsItem, type LiveSource, type LiveNewsResponse} from '@/features/live-news/model.mjs'
import type { NewsData } from '@/types'
export const useNewsStore = defineStore('news', () => {
 const newsData=ref<Map<string,NewsData>>(new Map()),darkMode=ref(true)
 const liveItems=ref<LiveNewsItem[]>([]),liveSources=ref<LiveSource[]>([]),liveLoading=ref(false),liveError=ref(''),liveFetchedAt=ref(0),liveCheckedAt=ref(0),clock=ref(Date.now())
 let refreshInterval:ReturnType<typeof setInterval>|undefined,liveInterval:ReturnType<typeof setInterval>|undefined,clockInterval:ReturnType<typeof setInterval>|undefined
 const tickerItems=computed(()=>activeNews(liveItems.value,clock.value))
 const liveHealthyCount=computed(()=>liveSources.value.filter(s=>s.status==='ok').length)
 function getNews(id:string):NewsData{return newsData.value.get(id)??{source:id,items:[],updatedAt:0,loading:true}}
 async function fetchSource(id:string){if(newsData.value.get(id)?.loading)return;newsData.value.set(id,{...getNews(id),loading:true});newsData.value.set(id,await loadNewsSource(id))}
 async function fetchAll(){await Promise.allSettled(NEWS_SOURCES.map(s=>fetchSource(s.id)))}
 async function fetchLive(){
  if(liveLoading.value)return
  liveLoading.value=true
  try{
   const response=await fetch('/api/news/live',{signal:AbortSignal.timeout(15000)})
   if(!response.ok)throw Error('快讯连接失败')
   const data=await response.json() as LiveNewsResponse
   if(!Array.isArray(data.items)||!Array.isArray(data.sources)||!Number.isFinite(data.fetchedAt))throw Error('快讯数据格式异常')
   liveItems.value=freshNews([...data.items,...liveItems.value],Date.now());liveSources.value=data.sources;liveFetchedAt.value=data.fetchedAt;liveCheckedAt.value=Date.now()
   liveError.value=data.sources.every(s=>s.status!=='ok')?'快讯源暂不可用，保留未过期消息':''
  }catch{liveError.value='快讯刷新失败，保留未过期消息'}finally{clock.value=Date.now();liveLoading.value=false}
 }
 function toggleDark(){darkMode.value=!darkMode.value;document.documentElement.classList.toggle('dark',darkMode.value)}
 function startAutoRefresh(){if(refreshInterval)return;refreshInterval=setInterval(fetchAll,300000);liveInterval=setInterval(fetchLive,60000);clockInterval=setInterval(()=>{clock.value=Date.now()},10000)}
 function stopAutoRefresh(){clearInterval(refreshInterval);clearInterval(liveInterval);clearInterval(clockInterval);refreshInterval=undefined}
 return {newsData,darkMode,getNews,fetchSource,fetchAll,toggleDark,startAutoRefresh,stopAutoRefresh,tickerItems,fetchLive,liveSources,liveLoading,liveError,liveFetchedAt,liveCheckedAt,liveHealthyCount,clock}
})
