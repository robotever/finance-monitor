<template>
  <section class="market-dashboard fv-card" aria-labelledby="market-dashboard-title" :aria-busy="loading" :data-environment="acceptanceEnabled ? 'sector-acceptance' : productionObservationEnabled ? 'sector-observation' : undefined">
    <div v-if="acceptanceEnabled" class="sector-acceptance-banner" role="note">临时验收环境 · 全部为测试数据 · 不代表真实市场信号</div>
    <div v-if="productionObservationEnabled" class="sector-acceptance-banner" role="note">真实数据观察期 · 评分方法尚未完成历史验证 · 不构成交易信号</div>
    <header class="market-dashboard__header">
      <div><div class="market-dashboard__eyebrow">MARKET RESEARCH / 全市场研究</div><h2 id="market-dashboard-title">市场研究雷达 <span>{{ acceptanceEnabled ? '临时验收 · 测试数据' : productionObservationEnabled ? '真实数据观察 · 板块强度 · 机会 · 风险' : v3Active ? '影子预览 · 板块强度 · 机会 · 风险' : 'v0.1 / 试运行 · 强度 · 热度 · 风险' }}</span></h2></div>
      <button type="button" class="market-button" :disabled="loading" @click="refresh">{{ loading ? '加载中…' : '刷新研究数据' }}</button>
    </header>
    <div class="market-status" aria-live="polite">
      <template v-if="dashboard">
        <time :datetime="dashboard.observedAt">{{ formatDate(dashboard.observedAt) }} 北京时间</time>
        <span>{{ dashboard.session === 'close' ? '收盘确认' : '盘中快照' }}</span>
        <span :class="{ 'market-badge is-missing': dashboard.dataStatus.completeness < 70 }">完整度 {{ dashboard.dataStatus.completeness }}%<template v-if="dashboard.dataStatus.completeness < 70"> · 证据不足</template></span>
        <span class="market-badge" :class="{ 'is-stale': dashboard.freshness.stale }">{{ dashboard.freshness.label }}</span>
        <span class="market-status__version">{{ v3Active ? v3Latest?.schemaVersion : dashboard.schemaVersion }} / {{ dashboard.scoringVersion }}</span>
      </template>
      <span v-else>{{ loading ? '正在读取最新研究快照…' : '等待有效研究快照' }}</span>
    </div>
    <div v-if="latestError && !v3Active" class="market-notice market-dashboard__notice" role="status"><strong>{{ dashboard ? '刷新失败 · 保留本次会话最后成功快照' : latestError.code === 'NO_SNAPSHOT' ? '暂无研究快照' : '研究数据暂不可用' }}</strong><span>{{ latestError.message }}<template v-if="dashboard"> · 最后成功读取 {{ formatDate(lastSuccessAt) }}</template></span></div>
    <details v-if="dashboard?.dataStatus.missing.length" class="market-notice market-dashboard__missing"><summary>输入缺失 {{ dashboard.dataStatus.missing.length }} 项 · 展开查看</summary><p>{{ dashboard.dataStatus.missing.join('、') }}</p></details>
    <div class="market-dashboard__body">
      <div class="market-primary-grid">
        <MarketScoreCard title="全局环境" :item="dashboard?.global" :observed-at="dashboard?.observedAt" :loading="loading" :error="latestError?.message" />
        <MarketScoreCard title="A 股市场" :item="dashboard?.aShare" :observed-at="dashboard?.observedAt" :loading="loading" :error="latestError?.message" />
      </div>
      <template v-if="dashboard">
        <div class="market-history" aria-label="五日窗口强度历史">
          <div class="market-history__label">强度轨迹 <span>5日窗口 · {{ history?.snapshots.length ?? 0 }} 个观测</span></div>
          <p v-if="historyError" class="market-notice">历史数据暂不可用 · {{ historyError.message }}<template v-if="history"> · 图示保留上次成功历史</template></p>
          <div v-if="history" class="market-history__series"><figure v-for="series in historySeries" :key="series.key"><figcaption>{{ series.label }}</figcaption><div class="market-history__bars"><span v-for="(point, index) in history.snapshots" :key="index" :title="`${formatDate(point.observedAt)}：${point[series.key].strength ?? '—'}`" :class="{ 'is-missing': point[series.key].strength == null }" :style="{ height: `${point[series.key].strength ?? 0}%` }" /></div></figure></div>
          <p v-else-if="!historyError">{{ loading ? '历史加载中…' : '暂无历史轨迹' }}</p>
        </div>
        <MarketStyleGrid :items="dashboard.styles" :observed-at="dashboard.observedAt" />
        <HithinkSectorBoard v-if="v4Active && v4Latest" :latest="v4Latest" :now="now" :error="v4Error" />
        <p v-else-if="hithinkEnabled && v4Error" class="market-notice" role="status">{{ v4Error }} · 保留现有板块视图</p>
        <SectorRotationBoard v-if="v3Active && !v4Active" :latest="rotationLatest" :history="rotationHistory" :loading="rotationLoading" :error="rotationError" @change="changeRotation" @select-sector="openSector" />
        <IndustryHeatmap v-if="v3Active && !v4Active" :rotation-items="v3Industries" @select-sector="openSector" :observed-at="v3Latest!.observedAt" />
        <ConceptRadar v-if="v3Active && !v4Active" :rotation-items="v3Concepts" :rotation-core="v3CoreConcepts" :rotation-dynamic="v3DynamicConcepts" @select-sector="openSector" :observed-at="v3Latest!.observedAt" />
        <IndustryHeatmap v-if="!v3Active && !v4Active" :items="dashboard.industries" :rankings="dashboard.rankings" :observed-at="dashboard.observedAt" />
        <ConceptRadar v-if="!v3Active && !v4Active" :core="dashboard.coreConcepts" :dynamic="dashboard.dynamicConcepts" :rankings="dashboard.conceptRankings" :selected-at="dashboard.concepts.selectedAt" :observed-at="dashboard.observedAt" />
      </template>
      <div v-else-if="!loading" class="market-empty"><h3>研究面板等待首次有效数据</h3><p>全局环境、A 股、六类风格与 35 个行业将在快照可用后显示。</p><button class="market-button" type="button" @click="refresh">重新读取</button></div>
    </div>
    <SectorRotationDetail v-if="v3Active && !v4Active" :open="detailOpen" :acceptance-environment="acceptanceEnabled" :detail="detailView" :name="detailName" :loading="detailLoading" :error="detailError" :observations="detailPayload?.history" :selected-cell="selectedCell" :selected-axis="rotationSelection.axis" @close="closeDetail" />
    <footer class="market-dashboard__footer"><span>统一评分 0–100 · 高强度不等于低风险</span><span>缺失项以 — 表示 · 研究参考，非买卖建议</span></footer>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { loadMarketDashboard, loadMarketHistory, loadSectorRotationLatest, loadSectorRotationHistory, loadSectorRotationDetail } from '@/features/market-dashboard/api.mjs'
import { acceptanceFetch, isSectorAcceptanceMode } from '@/features/market-dashboard/acceptance.mjs'
import { deriveMarketDashboardView, deriveSectorRotationView } from '@/features/market-dashboard/model.mjs'
import type { MarketDashboardPayload, MarketHistoryPayload, MarketHistoryV3Payload, MarketLoadError } from '@/features/market-dashboard/types'
import MarketScoreCard from './MarketScoreCard.vue'
import MarketStyleGrid from './MarketStyleGrid.vue'
import IndustryHeatmap from './IndustryHeatmap.vue'
import ConceptRadar from './ConceptRadar.vue'
import SectorRotationBoard from './SectorRotationBoard.vue'
import HithinkSectorBoard from './sector-rotation/HithinkSectorBoard.vue'
import { loadHithinkLatest } from '@/features/sector-rotation-v4/api.mjs'
import { selectSectorAdapter } from '@/features/sector-rotation-v4/model.mjs'
import type { Latest as HithinkLatest } from '@/features/sector-rotation-v4/types'
import SectorRotationDetail from './SectorRotationDetail.vue'
import type { MarketDashboardV3Payload, SectorRotationLatest, SectorRotationHistory, SectorRotationDetail as DetailPayload, SectorUniverse, SectorView, SectorLeaderboardAxis, SectorMatrixCell } from '@/features/market-dashboard/types'
const acceptanceEnabled = import.meta.env.MODE === 'sector-acceptance' && isSectorAcceptanceMode()
const hithinkEnabled = import.meta.env.VITE_HITHINK_SECTOR_V4 === 'true' && !acceptanceEnabled
const v4Latest = shallowRef<HithinkLatest | null>(null)
const v4Error = ref('')
const v4Active = computed(() => selectSectorAdapter(hithinkEnabled, v4Latest.value) === 'v4')
async function refreshHithink(signal: AbortSignal) {
  if (!hithinkEnabled) return
  const result = await loadHithinkLatest({ signal })
  if (disposed || signal.aborted) return
  v4Error.value = result.error?.message ?? ''
  if (result.data) v4Latest.value = result.data
  else if (result.error?.code === 'NO_SNAPSHOT' || result.error?.code === 'INVALID_SCHEMA') v4Latest.value = null
}
const dashboardFetch = acceptanceEnabled ? acceptanceFetch : undefined
const productionObservationEnabled = import.meta.env.MODE === 'production-rotation'
// Local shadow remains release-gated; production-rotation is an explicit observation build.
const shadowEnabled = import.meta.env.VITE_SECTOR_ROTATION_RELEASE === 'true'
  && import.meta.env.MODE === 'rotation-shadow'
  && typeof window !== 'undefined' && ['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)
const v3Latest = shallowRef<MarketDashboardV3Payload | null>(null)
const rotationEnabled = acceptanceEnabled || productionObservationEnabled || shadowEnabled
const v3Active = computed(() => !!v3Latest.value && (acceptanceEnabled || productionObservationEnabled
  || shadowEnabled && v3Latest.value.sectorRotation.releaseEligible === true))
const rotationLatest = shallowRef<SectorRotationLatest | null>(null)
const rotationHistory = shallowRef<SectorRotationHistory | null>(null)
const rotationLoading = ref(false), rotationError = ref('')
const rotationSelection = ref<{ universe: SectorUniverse; view: SectorView; axis: SectorLeaderboardAxis }>({ universe: 'concept', view: 'potential', axis: 'strength' })
function projectedRows(universe: SectorUniverse) {
  const payload = v3Latest.value
  if (!payload) return []
  const rows = universe === 'industry' ? payload.industries : [...payload.concepts.dynamic, ...payload.concepts.core]
  return deriveSectorRotationView({ universe, view: 'potential', observedAt: payload.observedAt, marketDate: payload.marketDate, session: payload.session,
    scoringVersion: payload.sectorScoringVersion, universeVersion: payload.sectorUniverseVersion,
    sectors: rows.map(row => ({ ...row, change1d: { strength: null, opportunity: null, risk: null } })) }).rows
}
const v3Industries = computed(() => projectedRows('industry')), v3Concepts = computed(() => projectedRows('concept'))
function conceptSelection(kind: 'core' | 'dynamic') {
  const rows = new Map(v3Concepts.value.map(row => [row.id, row]))
  return (v3Latest.value?.concepts[kind] ?? []).flatMap(item => rows.has(item.id) ? [rows.get(item.id)!] : [])
}
const v3CoreConcepts = computed(() => conceptSelection('core'))
const v3DynamicConcepts = computed(() => conceptSelection('dynamic'))
let rotationController: AbortController | undefined, detailController: AbortController | undefined
const detailOpen = ref(false), detailLoading = ref(false), detailName = ref(''), detailError = ref('')
const detailPayload = shallowRef<DetailPayload | null>(null), selectedCell = shallowRef<SectorMatrixCell>()
const detailView = computed(() => {
  if (!detailPayload.value || !v3Latest.value) return null
  try { return deriveSectorRotationView({ observedAt: v3Latest.value.observedAt, marketDate: v3Latest.value.marketDate, session: v3Latest.value.session, view: 'potential', universe: detailPayload.value.universe,
    scoringVersion: v3Latest.value.sectorScoringVersion, universeVersion: v3Latest.value.sectorUniverseVersion, sectors: [] }, null, { detail: detailPayload.value }).detail } catch { return null }
})
async function changeRotation(selection = rotationSelection.value) {
  if (!v3Active.value || v4Active.value) return
  rotationSelection.value = selection
  rotationController?.abort()
  const request = new AbortController(); rotationController = request
  rotationLoading.value = true; rotationError.value = ''; rotationLatest.value = null; rotationHistory.value = null
  const options = { ...selection, signal: request.signal, fetcher: dashboardFetch }
  const [current, past] = await Promise.all([loadSectorRotationLatest(options), loadSectorRotationHistory(options)])
  if (disposed || request.signal.aborted) return
  rotationLoading.value = false
  if (current.data) {
    try { deriveSectorRotationView(current.data, past.data); rotationLatest.value = current.data; rotationHistory.value = past.data }
    catch { rotationError.value = '数据版本不一致，请刷新后重试' }
  } else rotationError.value = current.error?.message ?? '暂无有效轮动数据'
  if (past.error) rotationError.value ||= `历史暂不可用 · ${past.error.message}`
}
async function openSector(selection: { universe: SectorUniverse; id: string; name: string; cell?: SectorMatrixCell }) {
  detailController?.abort()
  const request = new AbortController(); detailController = request
  detailName.value = selection.name; selectedCell.value = selection.cell; detailPayload.value = null
  detailError.value = ''; detailLoading.value = true; detailOpen.value = true
  const result = await loadSectorRotationDetail({ ...selection, signal: request.signal, fetcher: dashboardFetch })
  if (disposed || request.signal.aborted) return
  detailLoading.value = false; detailPayload.value = result.data
  detailError.value = result.error?.message ?? ''
  if (result.data && !detailView.value) detailError.value = '详情版本不一致，请重新打开'
}
function closeDetail() { detailOpen.value = false; detailController?.abort() }
async function refreshShadow(signal: AbortSignal) {
  if (!rotationEnabled) return
  const result = await loadMarketDashboard(dashboardFetch, { signal, schemaVersion: 'market-dashboard-v3' })
  if (disposed || signal.aborted) return
  v3Latest.value = result.data
  if (acceptanceEnabled) latestError.value = result.error
  if (v3Active.value) await changeRotation()
  else { closeDetail(); detailPayload.value = null; rotationController?.abort(); rotationLatest.value = null; rotationHistory.value = null }
}

const latest = shallowRef<MarketDashboardPayload | null>(null)
const history = shallowRef<MarketHistoryPayload | MarketHistoryV3Payload | null>(null)
const latestError = ref<MarketLoadError | null>(null)
const historyError = ref<MarketLoadError | null>(null)
const lastSuccessAt = ref('')
const now = ref(new Date())
const loading = ref(true)
const dashboard = computed(() => {
  const v3 = v3Active.value ? v3Latest.value : null
  if (!v3) return latest.value ? deriveMarketDashboardView(latest.value, now.value) : undefined
  // The v3 contract intentionally retains these three legacy object families.
  // Project only those families; sector rows never enter the legacy presenter.
  return deriveMarketDashboardView({ schemaVersion: 'market-dashboard-v2', scoringVersion: v3.scoringVersion,
    observedAt: v3.observedAt, marketDate: v3.marketDate, session: v3.session, dataStatus: v3.dataStatus,
    global: v3.global, aShare: v3.aShare, styles: v3.styles, industries: [],
    concepts: { selectionVersion: v3.concepts.selectionVersion, scoringVersion: 'concept-score-v0.1',
      selectedAt: v3.concepts.selectedAt, core: [], dynamic: [] } }, now.value)
})
const historySeries = [{ key: 'global', label: '全球' }, { key: 'aShare', label: 'A 股' }] as const
let controller: AbortController | undefined
let freshnessTimer: ReturnType<typeof setInterval> | undefined
let refreshTimer: ReturnType<typeof setInterval> | undefined
let disposed = false
async function refresh() {
  if (controller) return
  controller = new AbortController()
  loading.value = true
  const options = { signal: controller.signal }
  // Keep the independent latest result responsive even if history times out.
  await Promise.all([
    refreshHithink(controller.signal).then(() => refreshShadow(options.signal)),
    ...(acceptanceEnabled ? [] : [loadMarketDashboard(dashboardFetch, options).then(result => {
      if (disposed) return
      latestError.value = result.error
      if (result.data) { latest.value = result.data; lastSuccessAt.value = new Date().toISOString() }
      now.value = new Date()
    })]),
    loadMarketHistory('5d', dashboardFetch, { ...options, schemaVersion: acceptanceEnabled ? 'market-dashboard-v3' : 'market-dashboard-v2' }).then(result => {
      if (disposed) return
      historyError.value = result.error
      if (result.data) history.value = result.data
    }),
  ])
  controller = undefined
  if (!disposed) loading.value = false
}
function formatDate(value: string) {
  return new Date(value).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false })
}
onMounted(() => {
  refresh()
  freshnessTimer = setInterval(() => { now.value = new Date() }, 60_000)
  refreshTimer = setInterval(refresh, 5 * 60_000)
})
onUnmounted(() => { disposed = true; controller?.abort(); rotationController?.abort(); detailController?.abort(); clearInterval(freshnessTimer); clearInterval(refreshTimer) })
</script>
