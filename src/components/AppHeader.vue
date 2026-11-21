<template>
 <header class="app-header"><RouterLink to="/" class="app-brand" aria-label="Finance Monitor 首页"><span class="app-brand__mark">F<span>·</span></span><div><strong>FINANCE<span> MONITOR</span></strong><small>全市场研究终端</small></div></RouterLink><div class="app-header__right"><span class="header-clock">{{time}}</span><span class="header-zone">北京时间</span><button type="button" class="terminal-button" :disabled="store.liveLoading" @click="refresh">{{store.liveLoading?'连接中…':'刷新资讯'}}</button></div></header>
 <NewsTicker :items="store.tickerItems" :loading="store.liveLoading" :error="store.liveError"/>
</template>
<script setup lang="ts">
import {computed} from 'vue'
import {useNewsStore} from '@/stores/news'
import NewsTicker from './NewsTicker.vue'
const store=useNewsStore()
const time=computed(()=>new Date(store.clock).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit'}))
function refresh(){void store.fetchAll();void store.fetchLive()}
</script>
