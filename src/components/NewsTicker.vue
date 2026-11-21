<template>
 <section class="news-tape" aria-label="最新财经快讯">
  <span class="news-tape__label"><i class="status-dot"/> 快讯</span>
  <div class="news-tape__window" @mouseenter="hovered=true" @mouseleave="hovered=false" @focusin="focused=true" @focusout="focused=false">
   <div v-if="items.length" ref="trackRef" class="news-tape__track" :style="{transform:`translateX(${offset}px)`}">
    <div v-for="copy in 2" :key="copy" class="news-tape__group" :aria-hidden="copy===2?true:undefined">
     <a v-for="item in items.slice(0,20)" :key="item.id" :href="item.url" target="_blank" rel="noopener noreferrer" :tabindex="copy===2?-1:0"><time>{{ time(item.publishedAt) }}</time><span class="news-tape__source">{{item.sourceName}}</span><span><template v-if="item.categoryLabel">[{{item.categoryLabel}}] </template>{{item.title}}</span></a>
    </div>
   </div>
   <span v-else class="news-tape__empty">{{loading?'正在连接财经快讯…':'最近2小时暂无新快讯'}}<template v-if="error"> · {{error}}</template></span>
  </div>
  <button type="button" class="quiet-button" :aria-pressed="paused" :aria-label="paused?'播放顶部快讯':'暂停顶部快讯'" @click="paused=!paused">{{paused?'播放':'暂停'}}</button>
 </section>
</template>
<script setup lang="ts">
import {ref,onMounted,onUnmounted} from 'vue'
import {advanceNewsOffset} from '@/features/live-news/scroll.mjs'
import type {LiveNewsItem} from '@/features/live-news/model.mjs'
defineProps<{items:LiveNewsItem[];loading?:boolean;error?:string}>()
const paused=ref(false),hovered=ref(false),focused=ref(false),offset=ref(0),trackRef=ref<HTMLElement|null>(null)
let frame=0,lastFrame:number|null=null
function animate(now:number){
 const elapsed=lastFrame===null?0:now-lastFrame;lastFrame=now
 if(!paused.value&&!hovered.value&&!focused.value&&trackRef.value){
  const group=trackRef.value.firstElementChild as HTMLElement|null
  offset.value=advanceNewsOffset(offset.value,elapsed,group?.offsetWidth??0)
 }
 frame=requestAnimationFrame(animate)
}
onMounted(()=>{frame=requestAnimationFrame(animate)})
onUnmounted(()=>cancelAnimationFrame(frame))
const time=(ms:number)=>new Date(ms).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'})
</script>
