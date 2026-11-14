<template>
  <dialog ref="dialog" class="sector-rotation-detail" aria-labelledby="rotation-detail-title" @cancel.prevent="emit('close')" @click="backdrop" @keydown="trapFocus">
    <header class="sector-rotation-detail__header"><div><h3 id="rotation-detail-title">{{ name ?? detail?.id ?? '板块详情' }}</h3><p>实际可得 {{ closes.length }} 个正式收盘日 · 最多60日</p></div><button ref="closeButton" type="button" class="market-button" aria-label="关闭板块详情" autofocus @click="emit('close')">关闭 ×</button></header>
    <div v-if="selectedCell && selectedObservation" class="sector-rotation-detail__selection"><h4>选中 {{ selectedCell.marketDate }} · {{ selectedAxis === 'opportunity' ? '机会' : '强度' }}榜第{{ selectedCell.rank }}名</h4><p>当日三项评分：强度 {{ selectedObservation.strength ?? '—' }} · 机会 {{ selectedObservation.opportunity ?? '—' }} · 风险 {{ selectedObservation.risk ?? '—' }}</p><p>当日排名：强度 {{ selectedObservation.ranks.strength ?? '—' }} · 机会 {{ selectedObservation.ranks.opportunity ?? '—' }} · 风险 {{ selectedObservation.ranks.risk ?? '—' }}</p><p>强度榜近15日{{ selectedObservation.leaderboard.strength.topTenCount15d }}次 · 机会榜近15日{{ selectedObservation.leaderboard.opportunity.topTenCount15d }}次（正式收盘）</p><p>分数变化 — · 详情接口未提供可比变化，不作推算</p></div>
    <p v-if="loading" role="status">详情加载中…</p><p v-else-if="error" class="market-notice" role="alert">{{ error }}</p>
    <template v-else-if="detail">
      <p v-if="selectedCell && !selectedObservation" class="market-notice">选中 {{ selectedCell.marketDate }} · {{ selectedAxis === 'opportunity' ? '机会' : '强度' }}榜第{{ selectedCell.rank }}名 · {{ selectedCell.score ?? '—' }}分 · 涨跌 — · 其余评分与名次见当日记录；所选收盘日审计暂不可用</p>
      <p class="sector-rotation__meta">分数与排名仅展示实际可得日期，缺失以 — 表示</p>
      <div class="sector-rotation__matrix-scroll" tabindex="0" aria-label="横向滚动60日评分与排名轨迹"><table aria-label="正式收盘评分与排名轨迹"><thead><tr><th scope="col">日期</th><th v-for="axis in axes" :key="axis" scope="col">{{ detail.axisLabels[axis] }} / 排名</th><th scope="col">热度状态</th></tr></thead><tbody><tr v-for="point in closes" :key="point.observedAt" :data-detail-close="point.marketDate"><th scope="row">{{ point.marketDate }}</th><td v-for="axis in axes" :key="axis"><strong>{{ point[axis] ?? '—' }}</strong> / {{ point.ranks[axis] ?? '—' }}</td><td>{{ point.heatStateLabel }}</td></tr></tbody></table></div>
      <p v-if="!closes.length" class="market-empty">暂无正式收盘轨迹</p>
      <template v-if="audit"><p class="sector-rotation__meta">审计口径：{{ selectedObservation?.marketDate ?? audit.provenance.marketDate ?? '最新可得观测' }}</p><h4>贡献因素</h4><ul><li v-for="factor in audit.contributors" :key="`${factor.axis}-${factor.component}`">{{ detail.axisLabels[factor.axis] }} · {{ componentLabel(factor.component) }} · 组件 {{ factor.value }} · 权重 {{ factor.weight }} · 贡献 {{ factor.impact }}</li></ul><p v-if="!audit.contributors.length">暂无贡献因素</p>
        <h4>标准化组件</h4><details v-for="(component, key) in audit.components" :key="key"><summary>{{ componentLabel(String(key)) }} · {{ component.value ?? '—' }} · 覆盖 {{ Math.round(component.coverage * 100) }}%</summary><p>有效权重 {{ component.effectiveWeight ?? '—' }} · 使用权重 {{ component.usedWeight ?? '—' }} / {{ component.totalWeight ?? '—' }} · 百分位 {{ component.percentile ?? '—' }}</p><p v-if="component.missing.length">缺失原因：{{ component.missing.join('、') }}</p><ul v-if="component.parts"><li v-for="(part, partKey) in component.parts" :key="partKey">{{ partKey }}：{{ part.value ?? '—' }} · 覆盖 {{ Math.round(part.coverage * 100) }}%<span v-if="part.missing.length"> · {{ part.missing.join('、') }}</span></li></ul></details>
        <h4>缺失项与来源</h4><p>{{ audit.missing.length ? audit.missing.join('、') : '无已报告缺失项' }}</p><p>{{ audit.provenance.source }} · 来源时间 <time :datetime="audit.provenance.observedAt">{{ audit.provenance.observedAt }}</time></p>
      </template>
      <p class="sector-rotation__meta">{{ detail.scoringVersion }} / {{ detail.universeVersion }}</p>
    </template><p v-else-if="!loading">暂无有效详情</p>
  </dialog>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import type { SectorDetailView, SectorMatrixCell, SectorLeaderboardAxis, SectorDetailRow } from '@/features/market-dashboard/types'
const props = defineProps<{ open: boolean; detail?: SectorDetailView | null; name?: string; loading?: boolean; error?: string; selectedCell?: SectorMatrixCell; selectedAxis?: SectorLeaderboardAxis; observations?: SectorDetailRow[] }>()
const emit = defineEmits<{ close: [] }>()
const dialog = ref<HTMLDialogElement>(), closeButton = ref<HTMLButtonElement>()
let previousFocus: HTMLElement | null = null
let previousBoard: HTMLElement | null = null
let previousFocusKey: string | undefined
const selectedObservation = computed(() => props.observations?.filter(point => point.officialClose && point.marketDate === props.selectedCell?.marketDate).at(-1))
const audit = computed(() => selectedObservation.value ?? props.detail?.audit)
const axes = ['strength','opportunity','risk'] as const
const closes = computed(() => [...new Map((props.detail?.series ?? []).filter(point => point.officialClose).map(point => [point.marketDate, point])).values()].slice(-60))
const names: Record<string, string> = { priceTrend: '相对价格趋势', funding: '资金承接', breadth: '上涨广度', persistence: '趋势持续', position: '历史相对位置', fundsImprovement: '资金边际改善', breadthImprovement: '广度拐点', momentumImprovement: '动能改善', activityWarming: '活跃度升温', downsideDiffusion: '下跌扩散', fundsWithdrawal: '资金撤离', trendDeterioration: '趋势恶化', divergence: '价量资金背离', crowding: '拥挤回撤', activity: '活动度', concentration: '集中度', activityMean5d: '5日活动均值' }
function componentLabel(key: string) { return names[key] ?? key }
function restoreFocus() {
  let target = previousFocus?.isConnected ? previousFocus : null
  if (!target && previousBoard?.isConnected) {
    target = [...previousBoard.querySelectorAll<HTMLElement>('[data-rotation-focus]')]
      .find(element => element.dataset.rotationFocus === previousFocusKey) ??
      previousBoard.querySelector<HTMLElement>('[role="tab"][aria-selected="true"][aria-controls="rotation-current"]')
  }
  target?.focus()
  previousFocus = null; previousBoard = null; previousFocusKey = undefined
}
watch(() => props.open, async open => {
  await nextTick()
  if (open && dialog.value && !dialog.value.open) {
    previousFocus = document.activeElement as HTMLElement
    previousBoard = previousFocus.closest<HTMLElement>('.sector-rotation')
    previousFocusKey = previousFocus.dataset.rotationFocus
    dialog.value.showModal(); closeButton.value?.focus()
  }
  else if (!open && dialog.value?.open) { dialog.value.close(); restoreFocus() }
}, { immediate: true })
function trapFocus(event: KeyboardEvent) {
  if (event.key !== 'Tab' || !dialog.value) return
  const controls = [...dialog.value.querySelectorAll<HTMLElement>('button:not([disabled]), summary, [tabindex="0"]')].filter(element => element.getClientRects().length > 0)
  const first = controls[0], last = controls.at(-1)
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
function backdrop(event: MouseEvent) { if (event.target === dialog.value) { const rect = dialog.value!.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) emit('close') } }
onBeforeUnmount(restoreFocus)
</script>
