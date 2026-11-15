<template>
  <section class="sector-rotation" aria-labelledby="rotation-title" :aria-busy="loading">
    <div class="market-section-heading"><div><h3 id="rotation-title">板块轮动 <span>SECTOR ROTATION</span></h3><p>强度看确认 · 机会看改善 · 风险独立观察</p></div><span class="market-badge">{{ model?.sessionLabel ?? '等待数据' }}</span></div>
    <div class="sector-rotation__tabs" role="tablist" aria-label="板块分类">
      <button v-for="tab in universes" :id="`rotation-universe-${tab.key}`" :key="tab.key" type="button" role="tab" :aria-selected="universe === tab.key" aria-controls="rotation-panel" :tabindex="universe === tab.key ? 0 : -1" @click="selectUniverse(tab.key)" @keydown="tabKey($event, universes.map(t => t.key), universe, selectUniverse)">{{ tab.label }}</button>
    </div>
    <div id="rotation-panel" role="tabpanel" :aria-labelledby="`rotation-universe-${universe}`">
      <div class="sector-rotation__tabs" role="tablist" aria-label="今日观察视图">
        <button v-for="tab in views" :id="`rotation-view-${tab.key}`" :key="tab.key" type="button" role="tab" :aria-selected="activeView === tab.key" aria-controls="rotation-current" :tabindex="activeView === tab.key ? 0 : -1" @click="selectView(tab.key)" @keydown="tabKey($event, views.map(t => t.key), activeView, selectView)">{{ tab.label }}</button>
      </div>
      <div id="rotation-current" role="tabpanel" :aria-labelledby="`rotation-view-${activeView}`" aria-live="polite">
        <p class="sector-rotation__basis">{{ basis[activeView] }} · 顺序沿用服务端排名</p>
        <p v-if="error" class="market-notice" role="status">{{ error }}</p>
        <p v-if="!currentReady" class="market-empty">正在等待{{ viewLabel }}数据</p>
        <p v-else-if="!rows.length" class="market-empty">暂无符合条件的板块</p>
        <div v-else class="sector-rotation__current">
          <article v-for="item in rows" :key="item.id" class="sector-rotation__row">
            <header><button type="button" class="sector-rotation__name" :data-sector="item.id" :data-rotation-focus="JSON.stringify([universe, 'current', activeView, item.id])" @click="selectSector(item.id, item.name)">{{ item.name }}</button><span class="market-badge" :class="`heat-${item.heatState}`">{{ item.heatStateLabel }}</span></header>
            <p class="sector-rotation__return">当日涨跌 — <span>暂无涨跌数据</span></p>
            <div class="sector-rotation__scores"><div v-for="score in axes" :key="score.key"><span>{{ score.label }}</span><strong>{{ item[score.key] ?? '—' }}</strong></div></div>
            <p class="sector-rotation__meta">{{ rankLabel(item.leaderboard[streakAxis].rankChange) }} · 完整度 {{ item.completeness }}% · {{ item.evidenceLabel }}<span v-if="item.coldStartLabel"> · {{ item.coldStartLabel }}</span></p>
            <p class="sector-rotation__meta">{{ item.leaderboardLabels[streakAxis] }}</p>
          </article>
        </div>
      </div>
      <div class="market-section-heading sector-rotation__history-heading"><h4>历史轮动 <span>最近15个正式收盘日 · 前10名</span></h4><div class="sector-rotation__tabs" role="group" aria-label="历史评分维度"><button v-for="option in matrixAxes" :key="option.key" type="button" :aria-pressed="axis === option.key" @click="selectAxis(option.key)">{{ option.label }}</button></div></div>
      <p class="sector-rotation__meta">{{ matrixReady ? model?.matrix.historyLabel : '历史加载中或暂无有效历史' }} · 颜色仅表示状态；涨跌缺失不补值</p>
      <div class="sector-rotation__matrix-scroll" tabindex="0" aria-label="横向滚动历史轮动矩阵">
        <table v-if="matrixReady" class="sector-rotation__matrix" :aria-label="`${model!.matrix.axisLabel}近15个正式收盘日`"><thead><tr><th scope="col">名次</th><th v-for="date in model!.matrix.dates" :key="date" scope="col">{{ date }}</th></tr></thead><tbody><tr v-for="rank in model!.matrix.rows" :key="rank.rank"><th scope="row">{{ rank.rank }}</th><td v-for="(cell, index) in rank.cells" :key="index"><button v-if="cell" type="button" :data-rotation-focus="JSON.stringify([universe, 'history', axis, cell.marketDate, cell.id])" :aria-label="`${cell.name}，${cell.marketDate}，第${rank.rank}名，${model!.matrix.axisLabel}${cell.score ?? '暂无数据'}分，涨跌暂无数据，打开详情`" @click="selectSector(cell.id, cell.name, cell)"><span>{{ cell.name }}</span><strong>{{ cell.score ?? '—' }} 分</strong><small>涨跌 —</small></button><span v-else class="sector-rotation__missing">—</span></td></tr></tbody></table>
        <p v-else class="market-empty">暂无可比的正式收盘历史</p>
      </div>
      <p v-if="model" class="sector-rotation__meta">{{ model.freshness.label }} · {{ model.scoringVersion }} / {{ model.universeVersion }}</p>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, ref } from 'vue'
import { deriveSectorRotationView } from '@/features/market-dashboard/model.mjs'
import type { SectorLatestResponses, SectorRotationLatest, SectorRotationHistory, SectorUniverse, SectorView, SectorLeaderboardAxis, SectorMatrixCell } from '@/features/market-dashboard/types'
const props = defineProps<{ latest?: SectorRotationLatest | SectorLatestResponses | null; history?: SectorRotationHistory | null; initialUniverse?: SectorUniverse; initialView?: SectorView; loading?: boolean; error?: string }>()
const emit = defineEmits<{ 'select-sector': [selection: { universe: SectorUniverse; id: string; name: string; cell?: SectorMatrixCell }]; change: [selection: { universe: SectorUniverse; view: SectorView; axis: SectorLeaderboardAxis }] }>()
const universe = ref<SectorUniverse>(props.initialUniverse ?? 'concept'), activeView = ref<SectorView>(props.initialView ?? 'potential'), axis = ref<SectorLeaderboardAxis>('strength')
const universes = [{ key: 'industry', label: '行业' }, { key: 'concept', label: '概念' }] as const
const views = [{ key: 'potential', label: '潜在轮动' }, { key: 'main', label: '主线确认' }, { key: 'risk', label: '风险升温' }] as const
const axes = [{ key: 'strength', label: '强度' }, { key: 'opportunity', label: '机会' }, { key: 'risk', label: '风险' }] as const
const matrixAxes = axes.slice(0, 2)
const basis = { potential: '机会≥70 · 强度<70 · 风险<70 · 非拥挤 · 完整度≥70%', main: '强度≥70 · 风险<70 · 完整度≥70%', risk: '风险≥70，或1日上升≥10分，或拥挤' }
const model = computed(() => {
  if (!props.latest) return null
  try { return deriveSectorRotationView(props.latest, props.history ?? null) } catch { return null }
})
const currentReady = computed(() => model.value?.universe === universe.value && model.value.completeViews.includes(activeView.value))
const matrixReady = computed(() => model.value?.universe === universe.value && props.history?.axis === axis.value && !!model.value.matrix.dates.length)
const rows = computed(() => currentReady.value ? model.value![activeView.value] : [])
const viewLabel = computed(() => views.find(tab => tab.key === activeView.value)!.label)
const streakAxis = computed(() => activeView.value === 'potential' ? 'opportunity' : 'strength')
function changed() { emit('change', { universe: universe.value, view: activeView.value, axis: axis.value }) }
function selectUniverse(value: string) { universe.value = value as SectorUniverse; changed() }
function selectView(value: string) { activeView.value = value as SectorView; changed() }
function selectAxis(value: string) { axis.value = value as SectorLeaderboardAxis; changed() }
function selectSector(id: string, name: string, cell?: SectorMatrixCell) { emit('select-sector', { universe: universe.value, id, name, ...(cell ? { cell } : {}) }) }
function rankLabel(value: number | null) { return value == null ? '暂无可比排名' : value > 0 ? `排名上升${value}` : value < 0 ? `排名下降${Math.abs(value)}` : '排名持平' }
function tabKey(event: KeyboardEvent, keys: readonly string[], current: string, select: (key: string) => void) {
  if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return
  event.preventDefault()
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? keys.length - 1 : (keys.indexOf(current) + (event.key === 'ArrowRight' ? 1 : -1) + keys.length) % keys.length
  select(keys[index]!)
  const buttons = (event.currentTarget as HTMLElement).parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]')
  buttons[index]?.focus()
}
</script>
