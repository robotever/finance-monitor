const MINUTE = 60000
const DAY = 86400000
// Daily tolerance is deliberately conservative (weekends / holidays); callers may tighten it.
export const DEFAULT_STALE_AFTER_MS = Object.freeze({ intraday: 30 * MINUTE, daily: 20 * DAY, monthly: 75 * DAY })
const LABELS = { strength: ['弱', '中性', '强'], heat: ['冷', '正常', '热'], risk: ['低', '中等', '高'] }
const finite = value => typeof value === 'number' && Number.isFinite(value)
const byId = (a, b) => a.id < b.id ? -1 : a.id > b.id ? 1 : 0
function scoreLabel(axis, value) { return finite(value) ? LABELS[axis][value < 30 ? 0 : value < 70 ? 1 : 2] : '暂无数据' }
function beijing(time) {
  const date = new Date(time + 8 * 3600000)
  return { date: date.toISOString().slice(0, 10), weekday: date.getUTCDay(),
    minute: date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60 + date.getUTCMilliseconds() / MINUTE }
}
function context(payload, now, options) {
  const time = now.getTime()
  const local = beijing(time)
  // Without an explicit exchange calendar, weekdays are only a scheduling approximation.
  const tradingDay = options.tradingDates ? options.tradingDates.includes(local.date) : local.weekday > 0 && local.weekday < 6
  const trading = tradingDay && (local.minute >= 570 && local.minute < 690 || local.minute >= 780 && local.minute < 900)
  const observed = beijing(Date.parse(payload.observedAt))
  const confirmedClose = payload.session === 'close' && payload.marketDate === local.date
    && observed.date === local.date && observed.minute >= 900
  return { time, trading, missingClose: tradingDay && local.minute > 930 && !confirmedClose,
    thresholds: { ...DEFAULT_STALE_AFTER_MS, ...options.staleAfterMs }, forcedStale: payload.dataStatus.stale }
}
function freshness(timestamp, frequency, ctx, oldestSourceAt) {
  const ageMs = Math.max(0, ctx.time - Date.parse(timestamp))
  const delayed = frequency === 'intraday' ? ctx.trading && ageMs > ctx.thresholds.intraday : ageMs > ctx.thresholds[frequency]
  const missingClose = frequency === 'intraday' && ctx.missingClose
  const stale = ctx.forcedStale || delayed || missingClose
  return { stale, ageMs, missingClose, label: ctx.forcedStale ? '数据滞后' : missingClose ? '缺少收盘确认' : stale ? '数据滞后' : '正常',
    ...(oldestSourceAt === undefined ? {} : { oldestSourceAt }) }
}
function comparisonBadge(object, key) {
  const reason = object.comparisonUnavailable?.[key]
  if (reason === 'missingTradingCalendar') return '缺少交易日历'
  if (reason === 'missingTargetTradingDate') return '缺少目标交易日'
  if (object[key] == null || reason) return '暂无可比快照'
  return object.comparisonFallback === 'close' ? '至少一项使用收盘回退' : '同口径比较'
}
function improvement(object) {
  const five = object.change5d?.strength, one = object.change1d?.strength
  if (finite(five)) return { improvementValue: five, improvementWindow: '5d', improvementLabel: '5日强度改善' }
  if (finite(one)) return { improvementValue: one, improvementWindow: '1d', improvementLabel: '1日强度改善（回退）' }
  return { improvementValue: null, improvementWindow: null, improvementLabel: '暂无可比快照' }
}
function descending(axis) {
  return (a, b) => {
    const left = a[axis], right = b[axis]
    if (!finite(left)) return finite(right) ? 1 : byId(a, b)
    if (!finite(right)) return -1
    return right - left || byId(a, b)
  }
}
// Rankings include all objects; consumers can take the first five and render unavailable entries honestly.
export function rankIndustries(industries) {
  const entries = industries.map(object => ({ ...object, ...improvement(object) }))
  return { strength: [...entries].sort(descending('strength')), heat: [...entries].sort(descending('heat')),
    risk: [...entries].sort(descending('risk')), improvement: [...entries].sort(descending('improvementValue')) }
}
export const rankConcepts = rankIndustries
export function deriveMarketDashboardView(payload, now = new Date(), options = {}) {
  if (payload.schemaVersion !== 'market-dashboard-v2') throw new TypeError('The legacy market view requires v2')
  const ctx = context(payload, now, options)
  const present = object => {
    const sources = object.sourceTimestamps.map(source => source.timestamp)
    const oldestSourceAt = [...sources].sort((a, b) => Date.parse(a) - Date.parse(b))[0] ?? null
    const stage = object.completeness < 50 ? null : object.stage ?? null
    return { ...object, stage, stageLabel: stage ?? (object.completeness < 50 ? '证据不足' : '暂无阶段结论'),
      scoreLabels: Object.fromEntries(Object.keys(LABELS).map(axis => [axis, scoreLabel(axis, object[axis])])),
      evidenceInsufficient: object.completeness < 70, evidenceLabel: object.completeness < 70 ? '证据不足' : '证据充分',
      freshness: freshness(object.observedAt ?? payload.observedAt, object.frequency ?? 'intraday', ctx, oldestSourceAt),
      comparisonBadges: { change1d: comparisonBadge(object, 'change1d'), change5d: comparisonBadge(object, 'change5d') }, ...improvement(object) }
  }
  const industries = payload.industries.map(present).sort(byId)
  const coreConcepts = payload.concepts.core.map(present)
  const dynamicConcepts = payload.concepts.dynamic.map(present)
  return { ...payload, global: present(payload.global), aShare: present(payload.aShare), styles: payload.styles.map(present),
    industries, coreConcepts, dynamicConcepts,
    conceptRankings: { core: rankConcepts(coreConcepts), dynamic: rankConcepts(dynamicConcepts) },
    freshness: freshness(payload.observedAt, 'intraday', ctx), rankings: rankIndustries(industries) }
}

const SECTOR_LABELS = { strength: '强度', opportunity: '机会', risk: '风险' }
const HEAT_LABELS = { cold: '冷清', neutral: '正常', warming: '升温', active: '活跃', crowded: '拥挤' }
const VIEW_LABELS = { potential: '潜在轮动', main: '主线确认', risk: '风险升温' }
function inSectorView(row, view) {
  if (view === 'potential') return row.completeness >= 70 && finite(row.opportunity) && row.opportunity >= 70
    && finite(row.strength) && row.strength < 70 && finite(row.risk) && row.risk < 70 && row.heatState !== 'crowded'
  if (view === 'main') return row.completeness >= 70 && finite(row.strength) && row.strength >= 70 && finite(row.risk) && row.risk < 70
  return finite(row.risk) && row.risk >= 70 || finite(row.change1d?.risk) && row.change1d.risk >= 10 || row.heatState === 'crowded'
}
function sectorComparator(view) {
  const axes = view === 'potential' ? ['opportunity', 'strengthChange1d'] : view === 'main' ? ['strength', 'opportunity'] : ['risk', 'riskChange1d']
  return (a, b) => {
    for (const axis of axes) {
      const left = axis.endsWith('Change1d') ? a.change1d?.[axis.slice(0, -8)] : a[axis]
      const right = axis.endsWith('Change1d') ? b.change1d?.[axis.slice(0, -8)] : b[axis]
      if (!finite(left) && finite(right)) return 1
      if (finite(left) && !finite(right)) return -1
      if (finite(left) && finite(right) && left !== right) return right - left
    }
    return byId(a, b)
  }
}
function presentSector(row) {
  const value = structuredClone(row)
  return { ...value, heatStateLabel: HEAT_LABELS[row.heatState] ?? '暂无数据',
    scoreLabels: { strength: scoreLabel('strength', row.strength), opportunity: finite(row.opportunity)
      ? row.opportunity < 30 ? '低' : row.opportunity < 70 ? '中等' : '高' : '暂无数据', risk: scoreLabel('risk', row.risk) },
    coldStartLabel: row.coldStart ? '冷启动' : null,
    evidenceInsufficient: row.completeness < 70, evidenceLabel: row.completeness < 70 ? '证据不足' : '证据充分',
    leaderboardLabels: Object.fromEntries(['strength', 'opportunity'].map(axis => {
      const board = row.leaderboard[axis]
      return [axis, `${SECTOR_LABELS[axis]}榜（正式收盘）连续${board.topTenStreak}日 · 近15日${board.topTenCount15d}次`]
    })) }
}
function rotationMatrix(history, topN) {
  const dates = history?.dates.slice(-15) ?? []
  const cellsByDate = new Map(dates.map(date => [date, new Map()]))
  for (const row of history?.rows ?? []) for (const point of row.values) {
    const cells = cellsByDate.get(point.marketDate)
    if (!cells || !finite(point.rank) || !finite(point.score) || point.rank > topN) continue
    cells.set(point.rank, { id: row.id, name: row.name, marketDate: point.marketDate, score: point.score, rank: point.rank,
      dailyReturn: null, change1d: null })
  }
  const axis = history?.axis ?? null
  return { axis, axisLabel: axis ? `${SECTOR_LABELS[axis]}榜` : '暂无历史', dates,
    insufficientHistory: dates.length < 15, historyLabel: dates.length < 15 ? `历史不足15日（已有${dates.length}日）` : '正式收盘历史',
    rows: Array.from({ length: topN }, (_, i) => ({ rank: i + 1, cells: dates.map(date => cellsByDate.get(date).get(i + 1) ?? null) })) }
}
function rotationDetail(detail) {
  if (!detail) return null
  // Detail contains only actual observations. Missing dates and scores are never interpolated.
  const rows = [...detail.history].sort((a, b) => Date.parse(a.observedAt) - Date.parse(b.observedAt))
  const latest = rows.at(-1)
  return { id: detail.id, universe: detail.universe, scoringVersion: detail.scoringVersion, universeVersion: detail.universeVersion,
    axisLabels: { ...SECTOR_LABELS }, series: rows.map(row => ({ observedAt: row.observedAt, marketDate: row.marketDate,
      session: row.session, officialClose: row.officialClose, strength: row.strength, opportunity: row.opportunity, risk: row.risk,
      heatState: row.heatState, heatStateLabel: HEAT_LABELS[row.heatState] ?? '暂无数据', ranks: structuredClone(row.ranks) })),
    audit: latest ? structuredClone({ components: latest.components, missing: latest.missing, contributors: latest.contributors,
      provenance: latest.provenance, scoringVersion: latest.scoringVersion, universeVersion: latest.universeVersion }) : null }
}
/** Inputs must first pass the v3 loaders. Compact endpoint order carries unrounded tie breaks. */
export function deriveSectorRotationView(latest, history = null, options = {}) {
  const responses = latest.sectors ? { [latest.view]: latest } : latest
  const primary = responses.potential ?? responses.main ?? responses.risk
  if (!primary) throw new TypeError('A validated latest response is required')
  for (const response of Object.values(responses)) {
    if (['universe', 'scoringVersion', 'universeVersion', 'marketDate', 'observedAt', 'session'].some(key => response[key] !== primary[key])) {
      throw new TypeError('Latest responses must share one observation and version')
    }
  }
  if (history && ['universe', 'scoringVersion', 'universeVersion'].some(key => history[key] !== primary[key])) throw new TypeError('History version or universe mismatch')
  if (options.detail && ['universe', 'scoringVersion', 'universeVersion'].some(key => options.detail[key] !== primary[key])) throw new TypeError('Detail version or universe mismatch')
  const seen = new Map()
  for (const response of Object.values(responses)) for (const row of response.sectors) if (!seen.has(row.id)) seen.set(row.id, row)
  const rows = [...seen.values()].map(presentSector).sort(byId)
  const lists = Object.fromEntries(Object.keys(VIEW_LABELS).map(view => [view,
    // Preserve supplied server order: rounded public scores cannot reconstruct exact ranking ties.
    responses[view] ? responses[view].sectors.filter(row => inSectorView(row, view)).map(presentSector)
      : rows.filter(row => inSectorView(row, view)).sort(sectorComparator(view))]))
  const now = options.now ?? new Date()
  const ctx = context({ ...primary, dataStatus: { stale: options.stale ?? false } }, now, options)
  const topN = Number.isInteger(options.topN) && options.topN >= 1 && options.topN <= 10 ? options.topN : 10
  return { ...lists, rows, completeViews: Object.keys(VIEW_LABELS).filter(view => responses[view]), universe: primary.universe, observedAt: primary.observedAt, marketDate: primary.marketDate,
    scoringVersion: primary.scoringVersion, universeVersion: primary.universeVersion, viewLabels: { ...VIEW_LABELS },
    sessionLabel: primary.session === 'close' ? '正式收盘' : '盘中观察', freshness: freshness(primary.observedAt, 'intraday', ctx),
    matrix: rotationMatrix(history, topN), detail: rotationDetail(options.detail) }
}
