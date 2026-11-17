<template>
  <main class="home-layout">
    <div class="home-content">
      <a class="market-notice" href="/sectors/research">板块研究 · 新版在线验收 → 行业 / 概念 / 历史轮动 / 成分股涨幅榜（发布快照）</a>
      <MarketResearchDashboard />
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
