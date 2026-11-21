<template>
 <header class="app-header"><RouterLink to="/" class="app-brand" aria-label="Finance Monitor 首页"><span class="app-brand__mark">F<span>·</span></span><h1>FINANCE<span> MONITOR</span></h1></RouterLink></header>
 <NewsTicker :items="store.tickerItems" :loading="store.liveLoading" :error="store.liveError"/>
</template>
<script setup lang="ts">
import {useNewsStore} from '@/stores/news'
import NewsTicker from './NewsTicker.vue'
const store=useNewsStore()
</script>
