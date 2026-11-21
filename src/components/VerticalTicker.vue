<template>
 <section class="live-rail terminal-panel" aria-labelledby="live-rail-title">
  <header class="terminal-panel__header"><div><p class="eyebrow">LIVE INTELLIGENCE</p><h2 id="live-rail-title">财经快讯 <i class="status-dot"/></h2></div><button type="button" class="quiet-button" :aria-pressed="paused" @click="paused=!paused">{{paused?'播放滚动':'暂停滚动'}}</button></header>
  <div class="live-rail__status"><span>最近2小时 · {{store.tickerItems.length}}条</span><button type="button" class="quiet-button" :disabled="store.liveLoading" @click="store.fetchLive()">{{store.liveLoading?'更新中':'刷新快讯'}}</button></div>
  <p v-if="store.liveError" class="live-rail__notice" role="status">{{store.liveError}}</p>
  <div v-if="store.tickerItems.length" class="live-rail__window" :class="{'is-static':paused}" @mouseenter="hovered=true" @mouseleave="hovered=false">
   <div ref="trackRef" class="live-rail__track" :style="{transform:`translateY(${paused?0:offset}px)`}">
    <div v-for="copy in 2" :key="copy" class="live-rail__group" :aria-hidden="copy===2?true:undefined">
     <a v-for="item in store.tickerItems" :key="item.id" :href="item.url" target="_blank" rel="noopener noreferrer" :tabindex="copy===2?-1:0" :title="item.title + (item.sources?.length ? '\n' + item.sources.join(' · ') : '')" class="live-story" :class="{'is-important':item.important}"><div class="live-story__meta"><time :datetime="new Date(item.publishedAt).toISOString()">{{time(item.publishedAt)}}</time><span>{{item.sourceName}}</span></div><p>{{item.title}}</p></a>
    </div>
   </div>
  </div>
  <div v-else class="terminal-empty" role="status"><i class="status-dot"/><h3>{{store.liveLoading?'正在连接快讯源':'最近2小时暂无新快讯'}}</h3><p>新消息会自动出现，不使用旧新闻填充。</p></div>
  <footer class="live-rail__footer"><span>北京时间 · 60秒检查 · {{paused?'已暂停':hovered?'悬停暂停':'滚动中'}}</span><details><summary>信源 {{store.liveHealthyCount}} / {{store.liveSources.length||2}}</summary><p v-for="source in store.liveSources" :key="source.id">{{source.name}} · {{source.status==='ok'?'已连接':source.status==='empty'?'暂无数据':'暂不可用'}}<template v-if="source.newestAt"> · 最新 {{time(source.newestAt)}}</template></p><p v-if="store.liveCheckedAt">最近检查 {{time(store.liveCheckedAt)}}</p></details></footer>
 </section>
</template>
<script setup lang="ts">
import {ref,onMounted,onUnmounted} from 'vue'
import {advanceNewsOffset} from '@/features/live-news/scroll.mjs'
import {useNewsStore} from '@/stores/news'
const store=useNewsStore(),paused=ref(false),hovered=ref(false),offset=ref(0),trackRef=ref<HTMLElement|null>(null)
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
