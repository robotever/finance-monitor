<template>
 <section class="live-rail terminal-panel" aria-labelledby="live-rail-title">
  <header class="terminal-panel__header"><div><p class="eyebrow">LIVE INTELLIGENCE</p><h2 id="live-rail-title">财经快讯 <i class="status-dot"/></h2></div><button type="button" class="quiet-button" :aria-pressed="paused" @click="togglePlayback">{{paused?'播放滚动':'暂停滚动'}}</button></header>
  <div class="live-rail__status"><span>最近2小时 · {{store.tickerItems.length}}条</span><button type="button" class="quiet-button" :disabled="store.liveLoading" @click="store.fetchLive()">{{store.liveLoading?'更新中':'刷新快讯'}}</button></div>
  <p v-if="store.liveError" class="live-rail__notice" role="status">{{store.liveError}}</p>
  <div v-if="store.tickerItems.length" class="live-rail__window" :class="{'is-static':paused,'is-playing':!paused&&allowMotion}" @mouseenter="hovered=true" @mouseleave="hovered=false" @focusin="focused=true" @focusout="focused=false">
   <div class="live-rail__track" :class="{'is-paused':paused||hovered||focused,'motion-allowed':allowMotion}" :style="{'--rail-duration':`${Math.max(32,store.tickerItems.length*3)}s`}">
    <div v-for="copy in 2" :key="copy" class="live-rail__group" :aria-hidden="copy===2?true:undefined">
     <a v-for="item in store.tickerItems" :key="item.id" :href="item.url" target="_blank" rel="noopener noreferrer" :tabindex="copy===2?-1:0" :title="item.title + (item.sources?.length ? '\n' + item.sources.join(' · ') : '')" class="live-story" :class="{'is-important':item.important}"><div class="live-story__meta"><time :datetime="new Date(item.publishedAt).toISOString()">{{time(item.publishedAt)}}</time><span>{{item.sourceName}}</span></div><p>{{item.title}}</p></a>
    </div>
   </div>
  </div>
  <div v-else class="terminal-empty" role="status"><i class="status-dot"/><h3>{{store.liveLoading?'正在连接快讯源':'最近2小时暂无新快讯'}}</h3><p>新消息会自动出现，不使用旧新闻填充。</p></div>
  <footer class="live-rail__footer"><span>北京时间 · 60秒检查 · {{paused?'已暂停':'滚动中'}}</span><details><summary>信源 {{store.liveHealthyCount}} / {{store.liveSources.length||2}}</summary><p v-for="source in store.liveSources" :key="source.id">{{source.name}} · {{source.status==='ok'?'已连接':source.status==='empty'?'暂无数据':'暂不可用'}}<template v-if="source.newestAt"> · 最新 {{time(source.newestAt)}}</template></p><p v-if="store.liveCheckedAt">最近检查 {{time(store.liveCheckedAt)}}</p></details></footer>
 </section>
</template>
<script setup lang="ts">
import {ref,onMounted,onUnmounted} from 'vue'
import {NEWS_MOTION_KEY,resolveNewsMotion} from '@/features/live-news/motion.mjs'
import {useNewsStore} from '@/stores/news'
const store=useNewsStore(),hovered=ref(false),focused=ref(false)
const media=window.matchMedia('(prefers-reduced-motion: reduce)')
let choice:string|null=null
try{choice=localStorage.getItem(NEWS_MOTION_KEY)}catch{/* Storage may be blocked. */}
const initial=resolveNewsMotion(choice,media.matches),paused=ref(initial.paused),allowMotion=ref(initial.allowMotion)
function togglePlayback(){paused.value=!paused.value;choice=paused.value?'pause':'play';allowMotion.value=choice==='play';try{localStorage.setItem(NEWS_MOTION_KEY,choice)}catch{/* The current session still works. */}}
function systemMotionChanged(){if(choice!=='play'&&choice!=='pause')paused.value=media.matches}
onMounted(()=>media.addEventListener('change',systemMotionChanged))
onUnmounted(()=>media.removeEventListener('change',systemMotionChanged))
const time=(ms:number)=>new Date(ms).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',second:'2-digit'})
</script>
