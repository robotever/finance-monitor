<template>
  <div>
  <nav class="home-primary-nav" aria-label="看板导航">
    <a class="sector-entry-card" href="/sectors/research">
      <span class="sector-entry-card__copy"><strong>板块研究看板</strong><span>行业与概念 · 历史轮动 · 强度 / 机会 / 风险 · 成分股涨幅榜</span><small>发布快照 · 数据时间以板块页面为准</small></span>
      <span class="sector-entry-card__action">进入板块看板 →</span>
    </a>
  </nav>
  <main class="home-layout">
    <div class="home-content">
      <MarketResearchDashboard :show-sectors="false" />
      <DebtRiskDashboard />
      <div class="news-grid">
      <div
        v-for="source in NEWS_SOURCES"
        :key="source.id"
        class="news-grid__item"
      >
        <NewsCard
          :source="source"
          :data="store.getNews(source.id)"
          @refresh="store.fetchSource(source.id)"
        />
      </div>
      <div class="news-grid__footer">
        NewsMonitor · 每5分钟自动刷新
      </div>
      </div>
    </div>

  <aside class="home-ticker">
    <VerticalTicker />
  </aside>
  </main>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { useNewsStore } from '@/stores/news'
import { NEWS_SOURCES } from '@/api/sources'
import NewsCard from '@/components/NewsCard.vue'
import VerticalTicker from '@/components/VerticalTicker.vue'
import DebtRiskDashboard from '@/components/DebtRiskDashboard.vue'
import MarketResearchDashboard from '@/components/MarketResearchDashboard.vue'

const store = useNewsStore()
onMounted(() => { store.fetchAll(); store.startAutoRefresh() })
</script>

<style scoped>
.home-primary-nav{padding:12px 12px 0}
.sector-entry-card{display:flex;align-items:center;justify-content:space-between;gap:20px;padding:18px 22px;border:2px solid #40b8ce;border-radius:12px;background:linear-gradient(110deg,#103744,#102330 75%);box-shadow:0 5px 22px #0004;color:#e6f9ff;text-decoration:none}
.sector-entry-card:hover{border-color:#8de8f6;background:#123b49;color:#fff}
.sector-entry-card:focus-visible{outline:3px solid #fff;outline-offset:3px}
.sector-entry-card__copy{display:grid;gap:6px}.sector-entry-card strong{font-size:23px;line-height:1.3}.sector-entry-card__copy>span{font-size:13px;color:#b6dce8}.sector-entry-card small{font-size:11px;color:#8eafbc}
.sector-entry-card__action{flex-shrink:0;padding:13px 20px;border-radius:8px;background:#65d8e9;color:#062633;font-size:15px;font-weight:700}
@media(max-width:600px){.home-primary-nav{padding:8px 8px 0}.sector-entry-card{padding:15px;align-items:stretch;flex-direction:column;gap:12px}.sector-entry-card strong{font-size:21px}.sector-entry-card__copy>span{font-size:12px;line-height:1.6}.sector-entry-card__action{text-align:center}}
</style>
