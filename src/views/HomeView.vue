<template>
 <div class="research-home">
  <section class="home-intro"><div><p class="eyebrow">MARKET INTELLIGENCE / 全市场观察</p><h1>看清市场，连接线索<span class="intro-dot">.</span></h1><p class="home-intro__subtitle">全球价格联动 · 行业与概念 · 最新财经事件</p></div><a class="sector-entry" href="/sectors/research"><span class="sector-entry__icon">↗</span><div><strong>板块研究看板</strong><span>强度 / 机会 / 风险 · 历史轮动</span></div><b>进入 →</b></a></section>
  <main class="home-layout"><div class="home-content"><FixedMarketCharts/><MarketResearchDashboard :show-sectors="false"/><details class="home-research-detail terminal-panel"><summary><span>跨市场风险监测</span><small>债务 · 信用 · 利率环境</small><span>展开研究 ↓</span></summary><DebtRiskDashboard/></details><section class="source-reading" aria-labelledby="source-reading-title"><header class="section-heading"><div><p class="eyebrow">READING DESK</p><h2 id="source-reading-title">资讯阅读 <span>按来源 · 每源最多10条</span></h2></div><span>深度文章不混入实时快讯</span></header><div class="news-grid"><NewsCard v-for="source in NEWS_SOURCES" :key="source.id" :source="source" :data="store.getNews(source.id)" @refresh="store.fetchSource(source.id)"/></div></section><footer class="home-footer"><span>FINANCE MONITOR / 市场研究工作台</span><span>快讯每60秒检查 · 来源阅读每5分钟检查</span></footer></div><aside class="home-ticker"><VerticalTicker/></aside></main>
 </div>
</template>
<script setup lang="ts">
import {useNewsStore} from '@/stores/news'
import {NEWS_SOURCES} from '@/api/sources'
import NewsCard from '@/components/NewsCard.vue'
import VerticalTicker from '@/components/VerticalTicker.vue'
import FixedMarketCharts from '@/components/FixedMarketCharts.vue'
import DebtRiskDashboard from '@/components/DebtRiskDashboard.vue'
import MarketResearchDashboard from '@/components/MarketResearchDashboard.vue'
const store=useNewsStore()
</script>
