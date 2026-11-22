<template>
 <section class="live-rail terminal-panel" aria-labelledby="live-rail-title">
  <header class="terminal-panel__header"><h2 id="live-rail-title">财经快讯</h2><div class="live-rail__actions"><button type="button" class="quiet-button" :disabled="store.liveLoading" @click="store.fetchLive()">{{store.liveLoading?'更新中':'刷新'}}</button><button type="button" class="quiet-button" :aria-pressed="paused" @click="paused=!paused">{{paused?'播放':'暂停'}}</button></div></header>
  <nav class="news-category-tabs" aria-label="快讯分类"><button v-for="tab in categoryTabs" :key="tab.id" type="button" :aria-pressed="store.selectedNewsCategory===tab.id" :class="{active:store.selectedNewsCategory===tab.id}" @click="store.selectedNewsCategory=tab.id">{{tab.label}}</button></nav>
  <p v-if="store.liveError" class="live-rail__notice" role="status">{{store.liveError}}</p>
  <div v-if="store.tickerItems.length" class="live-rail__window" :class="{'is-static':paused}" @mouseenter="hovered=true" @mouseleave="hovered=false">
   <div ref="trackRef" class="live-rail__track" :style="{transform:`translateY(${paused?0:offset}px)`}">
    <div v-for="copy in 2" :key="copy" class="live-rail__group" :aria-hidden="copy===2?true:undefined">
     <a v-for="item in store.tickerItems" :key="item.id" :href="item.url" target="_blank" rel="noopener noreferrer" :tabindex="copy===2?-1:0" :title="item.title + (item.sources?.length ? '\n' + item.sources.join(' · ') : '')" class="live-story" :class="{'is-important':item.important}"><div class="live-story__meta"><time :datetime="new Date(item.publishedAt).toISOString()">{{time(item.publishedAt)}}</time><span>{{item.sourceName}}</span></div><p><b class="live-story__category" v-if="item.categoryLabel">{{item.categoryLabel}}</b>{{item.title}}</p></a>
    </div>
   </div>
  </div>
  <div v-else class="terminal-empty" role="status"><i class="status-dot"/><h3>{{store.liveLoading?'正在连接快讯源':store.selectedNewsCategory==='all'?'最近2小时暂无财经快讯':'当前分类暂无新快讯'}}</h3></div>
  <footer class="live-rail__footer"><details v-if="store.localArchiveItems.length"><summary>离线快讯存档 · {{store.localArchiveItems.length}}条</summary><p>以下消息已超过两小时，不参与实时滚动。</p><p v-for="item in store.localArchiveItems" :key="item.id"><time>{{new Date(item.publishedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'})}}</time> · {{item.sourceName}} · <a :href="item.url" target="_blank" rel="noopener noreferrer">{{item.title}}</a></p></details><details><summary>来源状态</summary><p v-for="source in store.liveSources" :key="source.id">{{source.name}} · {{source.status==='ok'?'已连接':source.status==='empty'?'暂无数据':'暂不可用'}}<template v-if="source.note"> · {{source.note}}</template><template v-if="source.newestAt"> · 最新 {{time(source.newestAt)}}</template></p><p v-if="store.liveCheckedAt">最近检查 {{time(store.liveCheckedAt)}}</p></details></footer>
 </section>
</template>
<script setup lang="ts">
import {ref,onMounted,onUnmounted} from 'vue'
import type {NewsCategory} from '@/features/live-news/policy.mjs'
import {advanceNewsOffset} from '@/features/live-news/scroll.mjs'
import {useNewsStore} from '@/stores/news'
const store=useNewsStore(),paused=ref(false),hovered=ref(false),offset=ref(0),trackRef=ref<HTMLElement|null>(null)
const categoryTabs:{id:NewsCategory|'all';label:string}[]=[{id:'all',label:'全部'},{id:'company',label:'公司'},{id:'industry',label:'行业'},{id:'market',label:'异动'},{id:'macro',label:'宏观'}]
let frame=0,lastFrame:number|null=null
function animate(now:number){
 const elapsed=lastFrame===null?0:now-lastFrame;lastFrame=now
 if(!paused.value&&!hovered.value&&trackRef.value){
  const group=trackRef.value.firstElementChild as HTMLElement|null
  offset.value=advanceNewsOffset(offset.value,elapsed,group?.offsetHeight??0)
 }
 frame=requestAnimationFrame(animate)
}
onMounted(()=>{frame=requestAnimationFrame(animate)})
onUnmounted(()=>cancelAnimationFrame(frame))
const time=(ms:number)=>new Date(ms).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit'})
</script>
