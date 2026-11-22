<template>
 <div class="research-home">
  <nav class="home-intro home-intro--compact" aria-label="研究入口"><a class="sector-entry" href="/sectors/research"><strong>板块研究看板</strong><b>进入 →</b></a></nav>
  <main class="home-layout"><div class="home-content"><FixedMarketCharts/><MarketResearchRadar/><details id="cross-market-risk" class="home-research-detail terminal-panel" open><summary><span>跨市场风险监控</span><span aria-hidden="true">⌄</span></summary><CrossMarketRisk/></details><section class="source-reading" aria-labelledby="source-reading-title"><header class="section-heading"><h2 id="source-reading-title">资讯阅读</h2></header><div class="news-grid"><NewsCard v-for="source in NEWS_SOURCES" :key="source.id" :source="source" :data="store.getNews(source.id)" @refresh="store.fetchSource(source.id)"/></div></section></div><aside class="home-ticker" :style="{'--live-news-rows':Math.max(1,Math.min(12,store.tickerItems.length))}"><VerticalTicker/></aside></main>
 </div>
</template>
<script setup lang="ts">
import {useNewsStore} from '@/stores/news'
import {NEWS_SOURCES} from '@/api/sources'
import NewsCard from '@/components/NewsCard.vue'
import VerticalTicker from '@/components/VerticalTicker.vue'
import FixedMarketCharts from '@/components/FixedMarketCharts.vue'
import CrossMarketRisk from '@/components/CrossMarketRisk.vue'
import MarketResearchRadar from '@/components/MarketResearchRadar.vue'
const store=useNewsStore()
</script>
