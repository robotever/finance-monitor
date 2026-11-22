<template>
 <header class="app-header"><RouterLink to="/" class="app-brand" aria-label="Finance Monitor 首页"><span class="app-brand__mark">F<span>·</span></span><h1>FINANCE<span> MONITOR</span></h1><small v-if="localHome" class="app-local-label">本地</small></RouterLink></header>
 <NewsTicker v-if="route.name==='home'" :items="store.tickerItems" :loading="store.liveLoading" :error="store.liveError"/>
</template>
<script setup lang="ts">
import {useRoute} from 'vue-router'
import {useNewsStore} from '@/stores/news'
import NewsTicker from './NewsTicker.vue'
const store=useNewsStore(),route=useRoute()
const localHome=import.meta.env.VITE_LOCAL_HOME==='true'
</script>

<style scoped>.app-local-label{font-size:10px;letter-spacing:0;color:#8ba3bb;border:1px solid #2b5269;border-radius:4px;padding:2px 5px;margin:0}</style>
