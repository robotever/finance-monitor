<template>
 <section class="etf-observation" aria-labelledby="etf-observation-title" :aria-busy="loading">
  <header class="etf-heading">
   <div><h3 id="etf-observation-title">沪深300 ETF 资金观察</h3><span class="etf-scope">核心4只 · 日频</span></div>
   <div class="etf-actions"><time :datetime="data?.date ?? undefined">清算 {{ data?.date ?? '待更新' }}</time><button type="button" :disabled="loading" aria-label="刷新ETF资金观察" @click="refresh">{{ loading ? '刷新中…' : '刷新' }}</button></div>
  </header>
  <p v-if="error || data?.cached" class="etf-notice" role="status">{{ error || '当前显示已保存数据，来源日期与获取时间保留原值。' }}</p>
  <div v-if="data" class="etf-columns">
   <div class="etf-capital">
    <p class="etf-table-caption">份额与份额变化 <span>亿份</span></p>
    <div class="etf-table-wrap"><table>
     <caption class="sr-only">核心4只沪深300 ETF 的最新份额、1日、5日和20日份额变化</caption>
     <thead><tr><th scope="col">ETF</th><th scope="col">份额</th><th scope="col">1日</th><th scope="col">5日</th><th scope="col">20日</th></tr></thead>
     <tbody><tr v-for="fund in data.funds" :key="fund.code"><th scope="row"><span>{{ fund.name }}</span><small>{{ fund.code }} · {{ fund.date ?? '日期缺失' }}</small></th><td>{{ amount(fund.shares) }}</td><td :class="direction(fund.change1d)">{{ amount(fund.change1d, true) }}</td><td :class="direction(fund.change5d)">{{ amount(fund.change5d, true) }}</td><td :class="direction(fund.change20d)">{{ amount(fund.change20d, true) }}</td></tr></tbody>
    </table></div>
    <div class="etf-flows" aria-label="核心4只ETF估算净申赎，单位亿元"><div v-for="flow in flows" :key="flow.label"><span>{{ flow.label }}估算净申赎</span><strong :class="direction(flow.value)">{{ amount(flow.value, true) }}<small>亿元</small></strong></div></div>
    <p class="etf-total">核心4只净资产 <strong>{{ amount(data.assetsCny) }}</strong> 亿元 <span>· 不跨基金加总份额</span></p>
   </div>
   <div ref="chartElement" class="etf-chart" :class="{ 'etf-chart--expanded': expanded }" :role="expanded ? 'dialog' : undefined" :aria-modal="expanded ? 'true' : undefined" aria-label="核心4只ETF资产占沪深300流通市值比例" @keydown.esc="closeExpanded">
    <div class="etf-chart-heading"><h4>ETF规模 / 沪深300流通市值</h4><div><strong>{{ percent(data.ratioPct) }}</strong><button ref="expandButton" type="button" :aria-label="expanded ? '退出图表全屏' : '全屏查看图表'" @click="toggleExpanded">{{ expanded ? '收起' : '放大' }}</button></div></div>
    <div class="etf-chart-toolbar"><div class="etf-ranges" aria-label="图表时间范围"><button v-for="range in ranges" :key="range.id" type="button" :aria-pressed="activeRange === range.id" @click="selectRange(range.id)">{{ range.label }}</button></div><div class="etf-zoom"><button type="button" aria-label="向前移动图表" :disabled="windowStart <= 0" @click="pan(-1)">←</button><button type="button" aria-label="缩小图表" :disabled="windowSize >= points.length" @click="zoom(1.5)">−</button><button type="button" aria-label="放大图表" :disabled="windowSize <= 5" @click="zoom(0.67)">＋</button><button type="button" aria-label="向后移动图表" :disabled="windowEnd >= points.length" @click="pan(1)">→</button></div></div>
    <div v-if="validPoints.length" class="etf-plot" @wheel.prevent="onWheel">
     <svg viewBox="0 0 640 230" role="img" tabindex="0" aria-label="日频资产占流通市值比例曲线；左右键选择日期，加减键缩放" @pointermove="hover" @pointerleave="hoverIndex = null" @keydown="chartKey">
      <g v-for="tick in yTicks" :key="tick.value"><line x1="53" :y1="tick.y" x2="624" :y2="tick.y" class="etf-grid"/><text x="46" :y="tick.y + 4" text-anchor="end">{{ tick.value.toFixed(2) }}%</text></g>
      <path :d="linePath" class="etf-line"/>
      <template v-if="selectedPoint && selectedPoint.ratioPct !== null"><line :x1="pointX(selectedIndex)" y1="20" :x2="pointX(selectedIndex)" y2="192" class="etf-crosshair"/><circle :cx="pointX(selectedIndex)" :cy="pointY(selectedPoint.ratioPct)" r="4" class="etf-dot"/></template>
      <text x="53" y="220">{{ visiblePoints[0]?.date }}</text><text x="624" y="220" text-anchor="end">{{ visiblePoints.at(-1)?.date }}</text>
     </svg>
     <div class="etf-chart-readout" aria-live="polite"><template v-if="selectedPoint"><time>{{ selectedPoint.date }}</time><strong>{{ percent(selectedPoint.ratioPct) }}</strong><span>资产 {{ amount(selectedPoint.assetsCny) }} 亿元</span></template></div>
    </div>
    <div v-else class="etf-chart-empty" role="status">{{ points.length ? '所选区间缺少同日净值或流通市值，比例暂不显示。' : '尚无可核验的比例历史；净值或流通市值缺失时不补零。' }}</div>
    <p class="etf-coverage">{{ coverage }} · 仅展示实际覆盖；滚轮或 ＋ / − 缩放，箭头平移</p>
   </div>
  </div>
  <div v-else class="etf-empty" role="status">{{ loading ? '正在读取日频ETF数据…' : 'ETF数据暂未取得' }}<button v-if="!loading" type="button" @click="refresh">重试</button></div>
  <details class="etf-method"><summary>数据来源与计算口径</summary><p>范围固定为华泰柏瑞510300、易方达510310、华夏510330、嘉实159919，共核心4只沪深300 ETF，不代表全市场ETF。上交所、深交所份额按日清算，T+1确认，不是盘中成交或实时申赎；各基金清算日期见表内。</p><p>资产 = 各基金份额 × 同日单位净值，按人民币汇总；比例 = 核心4只资产 ÷ 同日沪深300普通流通市值。分母为流通市值，不是自由流通市值。净申赎用每日份额变化 × 同日净值估算，5日/20日为逐日估算之和，不等于区间资产变化。</p><p>缺失净值、份额或同日分母时保留缺失，不补零。份额变化无法识别持有人身份，不可当作“国家队”买卖；估算净申赎也不等于二级市场主力资金流。</p><p v-if="data?.generatedAt">数据获取时间：<time :datetime="data.generatedAt">{{ formatTime(data.generatedAt) }}</time>；此时间不代替清算日期。</p><p v-for="note in data?.notes ?? []" :key="note">{{ note }}</p></details>
 </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { deriveEtfObservation } from '@/features/etf-observation/model.mjs'

type Fund = { code: string; name: string; exchange: string; date: string | null; shares: number | null; change1d: number | null; change5d: number | null; change20d: number | null; nav: number | null; assetsCny: number | null; flow1d: number | null; flow5d: number | null; flow20d: number | null }
type Point = { date: string; assetsCny: number | null; capCny: number | null; ratioPct: number | null; estimatedFlowCny: number | null; fundCount: number }
type Observation = { date: string | null; generatedAt: string; funds: Fund[]; series: Point[]; ratioPct: number | null; assetsCny: number | null; flow1d: number | null; flow5d: number | null; flow20d: number | null; cached?: boolean; notes?: string[]; scope: string }
type Range = '1m' | '3m' | '6m' | '1y' | 'all' | 'custom'
const ranges: { id: Range; label: string; months: number }[] = [{ id: '1m', label: '1月', months: 1 }, { id: '3m', label: '3月', months: 3 }, { id: '6m', label: '6月', months: 6 }, { id: '1y', label: '1年', months: 12 }, { id: 'all', label: '全部', months: 0 }]
const data = shallowRef<Observation | null>(null), loading = ref(false), error = ref('')
const activeRange = ref<Range>('3m'), windowStart = ref(0), windowEnd = ref(0), hoverIndex = ref<number | null>(null)
const expanded = ref(false), chartElement = ref<HTMLElement>(), expandButton = ref<HTMLButtonElement>()
let alive = true, controller: AbortController | undefined, timer: ReturnType<typeof setInterval> | undefined
const points = computed(() => data.value?.series ?? [])
const windowSize = computed(() => windowEnd.value - windowStart.value)
const visiblePoints = computed(() => points.value.slice(windowStart.value, windowEnd.value))
const validPoints = computed(() => visiblePoints.value.filter(point => point.ratioPct !== null && Number.isFinite(point.ratioPct)))
const coverage = computed(() => points.value.length ? `覆盖 ${points.value[0]?.date} — ${points.value.at(-1)?.date}` : '历史覆盖待更新')
const flows = computed(() => [{ label: '1日', value: data.value?.flow1d ?? null }, { label: '5日', value: data.value?.flow5d ?? null }, { label: '20日', value: data.value?.flow20d ?? null }])
const bounds = computed(() => {
 const values = validPoints.value.map(point => point.ratioPct as number)
 const low = Math.min(...values), high = Math.max(...values), padding = Math.max((high - low) * 0.18, 0.005)
 return { low: Math.max(0, low - padding), high: high + padding }
})
const yTicks = computed(() => Array.from({ length: 4 }, (_, i) => { const value = bounds.value.low + (bounds.value.high - bounds.value.low) * i / 3; return { value, y: pointY(value) } }))
const selectedIndex = computed(() => Math.min(Math.max(hoverIndex.value ?? visiblePoints.value.length - 1, 0), visiblePoints.value.length - 1))
const selectedPoint = computed(() => visiblePoints.value[selectedIndex.value])
const linePath = computed(() => {
 let path = '', connected = false
 visiblePoints.value.forEach((point, i) => {
  if (point.ratioPct === null || !Number.isFinite(point.ratioPct)) { connected = false; return }
  path += `${connected ? 'L' : 'M'}${pointX(i).toFixed(2)},${pointY(point.ratioPct).toFixed(2)} `
  connected = true
 })
 return path
})
function amount(value: number | null | undefined, signed = false) { if (value == null || !Number.isFinite(value)) return '—'; return `${signed && value > 0 ? '+' : ''}${new Intl.NumberFormat('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2, useGrouping: false }).format(value / 1e8)}` }
function percent(value: number | null | undefined) { return value == null || !Number.isFinite(value) ? '—' : `${value.toFixed(3)}%` }
function direction(value: number | null | undefined) { return value == null ? '' : value > 0 ? 'etf-positive' : value < 0 ? 'etf-negative' : '' }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date) + ' 北京时间' }
function pointX(index: number) { return visiblePoints.value.length < 2 ? 338 : 53 + index * 571 / (visiblePoints.value.length - 1) }
function pointY(value: number) { return 192 - (value - bounds.value.low) * 172 / (bounds.value.high - bounds.value.low) }
function selectRange(range: Range) {
 activeRange.value = range; windowEnd.value = points.value.length; hoverIndex.value = null
 const months = ranges.find(item => item.id === range)?.months ?? 0
 const last = points.value.at(-1)
 if (!months || !last) { windowStart.value = 0; return }
 const cutoff = new Date(`${last.date}T00:00:00Z`); cutoff.setUTCMonth(cutoff.getUTCMonth() - months)
 const first = points.value.findIndex(point => point.date >= cutoff.toISOString().slice(0, 10))
 windowStart.value = Math.max(0, first)
}
function zoom(factor: number) {
 if (!points.value.length) return
 const size = Math.min(points.value.length, Math.max(Math.min(5, points.value.length), Math.round(windowSize.value * factor)))
 const center = windowStart.value + windowSize.value / 2
 windowStart.value = Math.max(0, Math.min(points.value.length - size, Math.round(center - size / 2)))
 windowEnd.value = windowStart.value + size; activeRange.value = 'custom'; hoverIndex.value = null
}
function pan(direction: number) {
 const size = windowSize.value
 windowStart.value = Math.max(0, Math.min(points.value.length - size, windowStart.value + direction * Math.max(1, Math.round(size / 3))))
 windowEnd.value = windowStart.value + size; activeRange.value = 'custom'; hoverIndex.value = null
}
function onWheel(event: WheelEvent) { if (event.deltaY) zoom(event.deltaY > 0 ? 1.25 : 0.8) }
function hover(event: PointerEvent) {
 const svg = event.currentTarget as SVGElement, rect = svg.getBoundingClientRect()
 const fraction = ((event.clientX - rect.left) * 640 / rect.width - 53) / 571
 hoverIndex.value = Math.max(0, Math.min(visiblePoints.value.length - 1, Math.round(fraction * (visiblePoints.value.length - 1))))
}
function chartKey(event: KeyboardEvent) {
 if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); hoverIndex.value = Math.max(0, Math.min(visiblePoints.value.length - 1, selectedIndex.value + (event.key === 'ArrowLeft' ? -1 : 1))) }
 if (['+', '=', '-'].includes(event.key)) { event.preventDefault(); zoom(event.key === '-' ? 1.5 : 0.67) }
}
async function toggleExpanded() { expanded.value = !expanded.value; await nextTick(); if (expanded.value) chartElement.value?.querySelector<HTMLButtonElement>('button')?.focus(); else expandButton.value?.focus() }
function closeExpanded() { if (expanded.value) void toggleExpanded() }
async function refresh() {
 if (loading.value) return
 loading.value = true; controller = new AbortController()
 const timeout = setTimeout(() => controller?.abort(), 32000)
 try {
  const response = await fetch('/api/market-radar/etf', { signal: controller.signal, cache: 'no-store' })
  if (!response.ok) throw new Error('UNAVAILABLE')
  const result = deriveEtfObservation(await response.json()) as Observation
  if (!result || !Array.isArray(result.funds) || !Array.isArray(result.series)) throw new Error('INVALID_ETF')
  if (alive) { data.value = result; error.value = ''; selectRange(activeRange.value === 'custom' ? '3m' : activeRange.value) }
 } catch {
  if (alive) error.value = data.value ? '本次更新失败；保留上次已取得数据与原始日期，请留意清算时间。' : 'ETF来源暂不可用，请稍后重试。'
 } finally { clearTimeout(timeout); if (alive) loading.value = false }
}
function visible() { if (!document.hidden) void refresh() }
function trapFocus(event: KeyboardEvent) {
 if (!expanded.value || event.key !== 'Tab') return
 const controls = chartElement.value?.querySelectorAll<HTMLElement>('button:not(:disabled), svg[tabindex="0"]')
 if (!controls?.length) return
 const first = controls[0], last = controls[controls.length - 1]
 if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus() }
 else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus() }
}
watch(expanded, value => { if (value) document.addEventListener('keydown', trapFocus); else document.removeEventListener('keydown', trapFocus) })
defineExpose({ refresh })
onMounted(() => { void refresh(); timer = setInterval(visible, 300000); document.addEventListener('visibilitychange', visible) })
onUnmounted(() => { alive = false; controller?.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', visible); document.removeEventListener('keydown', trapFocus) })
</script>

<style scoped>
.etf-observation{min-width:0;color:#c6d9e8;border-top:1px solid #263f53;padding-top:13px;margin-top:13px;font-variant-numeric:tabular-nums}.etf-heading,.etf-heading>div,.etf-actions,.etf-chart-heading,.etf-chart-heading>div,.etf-chart-toolbar,.etf-ranges,.etf-zoom{display:flex;align-items:center;gap:8px}.etf-heading,.etf-chart-heading,.etf-chart-toolbar{justify-content:space-between}.etf-heading{flex-wrap:wrap;margin-bottom:10px}.etf-heading h3{font-size:13px;font-weight:600;margin:0;color:#d5e5ef}.etf-scope,.etf-actions time{color:#829fb4;font-size:10px}.etf-actions{margin-left:auto}.etf-observation button{background:#122b3d;border:1px solid #2c4a60;border-radius:4px;color:#9ebed2;padding:3px 7px;font-size:10px;cursor:pointer;white-space:nowrap}.etf-observation button:hover{border-color:#62b9d2;color:#d7f1fa}.etf-observation button:focus-visible,.etf-observation svg:focus-visible{outline:2px solid #6ac8e8;outline-offset:2px}.etf-observation button:disabled{opacity:.4;cursor:default}.etf-observation button[aria-pressed="true"]{background:#22506a;color:#d5f6ff;border-color:#5195b0}.etf-columns{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);gap:15px}.etf-capital,.etf-chart{min-width:0}.etf-table-caption{display:flex;justify-content:space-between;font-size:11px;color:#a5bfd1;margin:3px 0 7px}.etf-table-caption span{color:#718fa5}.etf-table-wrap{width:100%;overflow-x:auto}table{border-collapse:collapse;table-layout:fixed;width:100%;font-size:11px}th,td{padding:8px 3px;text-align:right;white-space:nowrap;border-bottom:1px solid #233b4d}thead th{font-size:10px;font-weight:400;color:#7e9eb4}th:first-child{width:36%;text-align:left;padding-left:0}tbody th{font-weight:400;white-space:normal}tbody th span{display:block;font-size:11px;line-height:1.5}tbody th small{display:block;font-size:9px;color:#7594a9;line-height:1.6;white-space:nowrap}.etf-flows{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:7px;margin-top:12px}.etf-flows>div{display:flex;flex-direction:column;gap:6px;border:1px solid #263f53;background:#102738;padding:8px;border-radius:5px}.etf-flows span{font-size:9px;color:#87a6bb}.etf-flows strong{font-size:14px;font-weight:500;white-space:nowrap}.etf-flows strong small{font-size:9px;color:#7e9eb4;margin-left:4px}.etf-total{font-size:10px;color:#8eacc0;line-height:1.8;margin:9px 0 0}.etf-total strong{color:#c6dfe9;font-weight:500}.etf-total span{font-size:9px;color:#6f8da3}.etf-positive{color:#ef9294}.etf-negative{color:#71c6aa}.etf-chart{border:1px solid #294257;border-radius:6px;background:#102637;padding:10px}.etf-chart-heading h4{font-size:11px;font-weight:400;margin:0;color:#a2bdce}.etf-chart-heading strong{font-size:16px;color:#78d4e8;font-weight:500}.etf-chart-heading button{padding:2px 5px}.etf-chart-toolbar{margin-top:10px;gap:6px;flex-wrap:wrap}.etf-ranges,.etf-zoom{gap:3px}.etf-ranges button,.etf-zoom button{padding:3px 6px}.etf-plot svg{display:block;width:100%;height:auto;min-height:160px;touch-action:pan-y}.etf-plot svg text{fill:#7d9db2;font-size:10px}.etf-grid{stroke:#254253;stroke-width:1;stroke-dasharray:3 4}.etf-line{fill:none;stroke:#69cbe2;stroke-width:2;stroke-linejoin:round;vector-effect:non-scaling-stroke}.etf-crosshair{stroke:#9ab7cc;stroke-dasharray:3 4;stroke-width:1}.etf-dot{fill:#9de7f4;stroke:#102637;stroke-width:2}.etf-chart-readout{min-height:20px;display:flex;justify-content:center;align-items:center;gap:9px;font-size:10px;color:#8facbd;flex-wrap:wrap}.etf-chart-readout strong{color:#9be4f4;font-weight:500}.etf-coverage{font-size:9px;color:#718fa5;line-height:1.7;margin:7px 0 0}.etf-chart-empty,.etf-empty{display:flex;align-items:center;justify-content:center;gap:10px;min-height:170px;text-align:center;font-size:11px;color:#89a5b8;line-height:1.9;padding:16px}.etf-notice{margin:0 0 10px;color:#d5b986;font-size:10px;line-height:1.7}.etf-method{margin-top:12px;border-top:1px solid #243e52;padding-top:8px;font-size:10px;color:#80a0b6}.etf-method summary{cursor:pointer}.etf-method p{margin:8px 0;line-height:1.9}.etf-chart--expanded{position:fixed;inset:7vh 5vw;z-index:1000;box-shadow:0 0 0 100vmax #04101de8;overflow:auto;padding:20px;display:flex;flex-direction:column}.etf-chart--expanded .etf-plot{flex:1;display:flex;flex-direction:column;justify-content:center;min-height:0}.etf-chart--expanded svg{max-height:62vh}.sr-only{position:absolute;width:1px;height:1px;padding:0;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(max-width:900px){.etf-columns{grid-template-columns:minmax(0,1fr)}}@media(max-width:450px){.etf-heading>div:first-child{flex-wrap:wrap;gap:5px}.etf-heading{gap:7px}.etf-actions{width:100%;justify-content:flex-end}.etf-chart{padding:8px}.etf-chart-heading{gap:5px}.etf-chart-heading h4{font-size:10px}.etf-chart-heading strong{font-size:14px}.etf-flows>div{padding:7px 5px}.etf-flows strong{font-size:13px}.etf-flows strong small{margin-left:2px;font-size:8px}th,td{font-size:10px;padding:7px 2px}tbody th span{font-size:10px}tbody th small{font-size:8px}.etf-chart--expanded{inset:3vh 3vw;padding:10px}.etf-chart-toolbar{gap:7px}.etf-zoom{margin-left:auto}.etf-chart-readout{font-size:9px;gap:6px}}
</style>
