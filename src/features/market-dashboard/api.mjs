import { validatePayload, validSectorIdentity, timestamp as preciseTimestamp } from '../../../functions/_lib/market-dashboard.js'
import { acceptanceFetch } from './acceptance.mjs'

// The build gate is inlined so ordinary bundles cannot select the offline adapter.
const acceptanceBuild = import.meta.env?.MODE === 'sector-acceptance' && import.meta.env?.VITE_SECTOR_ROTATION_ACCEPTANCE === 'true'
const defaultFetcher = (...args) => acceptanceBuild ? acceptanceFetch(...args) : fetch(...args)

// Public derived-data contract, paired with Task 3 publisher / Task 4 Pages API.
const AXES = ['strength', 'heat', 'risk']
const STYLES = ['000300.SH', '000852.SH', 'H30356.CSI', '399006.SZ', '000922.CSI', '000688.SH']
const INDUSTRIES = Array.from({ length: 37 }, (_, i) => 100 + i)
  .filter(code => code !== 117 && code !== 118).map(code => `882${code}.WI`)
const WINDOWS = ['1d', '5d', '20d', '90d']
const STAGES = ['冰点', '修复', '震荡', '扩张', '过热', '退潮']
const UNAVAILABLE = ['missingObservation', 'missingCurrentScores', 'missingTradingCalendar', 'missingTargetTradingDate']
const record = value => value !== null && typeof value === 'object' && !Array.isArray(value)
const shape = (value, required, optional = []) => record(value) && required.every(key => Object.hasOwn(value, key))
  && Object.keys(value).every(key => required.includes(key) || optional.includes(key))
const number = (value, min = 0, max = 100) => typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
const strings = value => Array.isArray(value) && value.every(item => typeof item === 'string' && item.length <= 200)
const noSelection = value => !['selectionScore', 'selectedOn', 'retainedTradingDays'].some(key => Object.hasOwn(value, key))
const calendarDate = value => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return false
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3])
  return year >= 1 && month >= 1 && month <= 12 && day >= 1
    && day <= new Date(Date.UTC(year, month, 0)).getUTCDate()
}

function timestamp(value) {
  if (typeof value !== 'string') return false
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(value)
  if (!match) return false
  const [, y, m, d, h, minute, s, offset] = match
  const year = Number(y), month = Number(m), day = Number(d)
  const days = new Date(Date.UTC(year, month, 0)).getUTCDate()
  if (year < 1 || month < 1 || month > 12 || day < 1 || day > days || Number(h) > 23 || Number(minute) > 59 || Number(s) > 59
    || offset !== 'Z' && (Number(offset.slice(1, 3)) > 23 || Number(offset.slice(4)) > 59)) return false
  const date = new Date(value.replace(' ', 'T'))
  return Number.isFinite(date.getTime()) && date.getUTCFullYear() >= 1 && date.getUTCFullYear() <= 9999
}
function validObservation(value) {
  return timestamp(value.observedAt) && typeof value.marketDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.marketDate)
    && value.marketDate === new Date(Date.parse(value.observedAt.replace(' ', 'T')) + 8 * 3600000).toISOString().slice(0, 10)
    && ['intraday', 'close'].includes(value.session) && value.scoringVersion === 'market-score-v0.1'
}
function validScores(value) {
  return record(value) && AXES.every(axis => value[axis] === null || Number.isInteger(value[axis]) && number(value[axis]))
    && AXES.some(axis => value[axis] !== null) && number(value.completeness) && value.completeness > 0
}
function validChange(value) {
  return value === null || shape(value, AXES) && AXES.every(axis => value[axis] === null || number(value[axis], -100, 100))
}
function validObject(value) {
  return shape(value, ['id', ...AXES, 'completeness', 'missing', 'contributors', 'sourceTimestamps', 'change1d', 'change5d'],
    ['name', 'frequency', 'observedAt', 'stage', 'comparisonFallback', 'comparisonUnavailable',
      'selectionScore', 'selectedOn', 'retainedTradingDays'])
    && validScores(value) && strings(value.missing)
    && (!Object.hasOwn(value, 'name') || typeof value.name === 'string' && value.name.length <= 100)
    && (!Object.hasOwn(value, 'frequency') || ['intraday', 'daily', 'monthly'].includes(value.frequency))
    && (!Object.hasOwn(value, 'observedAt') || timestamp(value.observedAt))
    && (value.stage == null || value.completeness >= 50 && STAGES.includes(value.stage))
    && validChange(value.change1d) && validChange(value.change5d)
    && Array.isArray(value.sourceTimestamps) && value.sourceTimestamps.length > 0
    && value.sourceTimestamps.every(source => shape(source, ['source', 'timestamp'])
      && ['Wind', 'FRED', 'MX', 'Derived'].includes(source.source) && timestamp(source.timestamp))
    && Array.isArray(value.contributors) && value.contributors.length <= 3
    && value.contributors.every(item => shape(item, ['label', 'impact'], ['evidence'])
      && typeof item.label === 'string' && item.label.length <= 200 && number(item.impact, -100, 100)
      && (!Object.hasOwn(item, 'evidence') || typeof item.evidence === 'string' && item.evidence.length <= 200))
    && (!Object.hasOwn(value, 'comparisonFallback') || value.comparisonFallback === 'close')
    && (!Object.hasOwn(value, 'comparisonUnavailable') || shape(value.comparisonUnavailable, [], ['change1d', 'change5d'])
      && Object.values(value.comparisonUnavailable).every(reason => UNAVAILABLE.includes(reason)))
}
function validConcepts(value, validator, compact = false) {
  if (!shape(value, ['selectionVersion', 'scoringVersion', 'selectedAt', 'core', 'dynamic'])
    || value.selectionVersion !== 'concept-selection-v0.1' || value.scoringVersion !== 'concept-score-v0.1'
    || !timestamp(value.selectedAt) || !Array.isArray(value.core) || value.core.length !== 25
    || !Array.isArray(value.dynamic) || value.dynamic.length !== 10) return false
  const ids = [...value.core, ...value.dynamic].map(item => item?.id)
  if (new Set(ids).size !== 35 || !ids.every(id => typeof id === 'string' && /^884\d{2,4}\.WI$/.test(id))) return false
  if (!value.core.every(item => validator(item) && noSelection(item))) return false
  return value.dynamic.every(item => validator(item) && (compact || number(item.selectionScore)
    && calendarDate(item.selectedOn)
    && Number.isInteger(item.retainedTradingDays) && item.retainedTradingDays >= 1))
}
function validObjects(value, validator) {
  return record(value.global) && value.global.id === 'global' && validator(value.global)
    && record(value.aShare) && value.aShare.id === 'a-share' && validator(value.aShare)
    && [['styles', STYLES], ['industries', INDUSTRIES]].every(([key, ids]) => Array.isArray(value[key])
      && value[key].length === ids.length && new Set(value[key].map(item => item?.id)).size === ids.length
      && value[key].every(item => ids.includes(item?.id) && validator(item)))
}
function validLatest(value) {
  if (!shape(value, ['schemaVersion', 'scoringVersion', 'observedAt', 'marketDate', 'session', 'global', 'aShare', 'styles', 'industries', 'concepts', 'dataStatus'], ['sourceMode'])
    || value.schemaVersion !== 'market-dashboard-v2' || !validObservation(value)
    || !validObjects(value, item => validObject(item) && noSelection(item))
    || !validConcepts(value.concepts, validObject)) return false
  const status = value.dataStatus
  const objects = [value.global, value.aShare, ...value.styles, ...value.industries,
    ...value.concepts.core, ...value.concepts.dynamic]
  if (!shape(status, ['completeness', 'stale', 'missing']) || !number(status.completeness) || typeof status.stale !== 'boolean'
    || !strings(status.missing) || status.completeness !== Math.floor(objects.reduce((sum, item) => sum + item.completeness, 0) / 78 + 0.5)
    || status.completeness <= 0) return false
  if (!Object.hasOwn(value, 'sourceMode')) return true
  const modes = value.sourceMode
  return shape(modes, ['breadth', 'styles', 'industries', 'concepts', 'conceptDiscovery', 'global'])
    && ['breadth', 'styles', 'industries', 'concepts'].every(key => modes[key] === 'wind')
    && modes.conceptDiscovery === 'mx' && record(modes.global)
    && Object.entries(modes.global).every(([key, provider]) => /^[\p{L}\p{N}]+$/u.test(key) && ['fred', 'wind', 'mx'].includes(provider))
}
function validHistory(value, window) {
  return shape(value, ['window', 'snapshots']) && value.window === window && Array.isArray(value.snapshots) && value.snapshots.length > 0
    && value.snapshots.every((snapshot, i) => shape(snapshot, ['observedAt', 'marketDate', 'session', 'scoringVersion', 'global', 'aShare', 'styles', 'industries', 'concepts'])
      && validObservation(snapshot) && validObjects(snapshot, object => shape(object, ['id', ...AXES, 'completeness']) && validScores(object))
      && validConcepts(snapshot.concepts, object => shape(object, ['id', ...AXES, 'completeness']) && validScores(object), true)
      && (i === 0 || Date.parse(snapshot.observedAt) >= Date.parse(value.snapshots[i - 1].observedAt)))
}
const messages = {
  NO_SNAPSHOT: '暂无有效快照', HTTP_ERROR: '服务暂不可用', INVALID_JSON: '响应不是有效 JSON', INVALID_SCHEMA: '快照格式无效',
  INVALID_QUERY: '板块查询参数无效', TIMEOUT: '请求超时', ABORTED: '请求已取消', NETWORK_ERROR: '网络请求失败', INVALID_WINDOW: '历史窗口无效',
}
function failure(code, status) {
  return { data: null, error: { code, message: messages[code], ...(status === undefined ? {} : { status }) } }
}

async function load(url, validate, fetcher, options) {
  if (options.signal?.aborted) return failure('ABORTED')
  const controller = new AbortController()
  let timer, stop, stopCode
  const stopped = new Promise(resolve => { stop = resolve })
  const cancel = code => {
    stopCode = code
    stop(failure(code))
    controller.abort()
  }
  const onAbort = () => cancel('ABORTED')
  options.signal?.addEventListener('abort', onAbort, { once: true })
  timer = setTimeout(() => cancel('TIMEOUT'), options.timeoutMs ?? 12000)
  try {
    const request = (async () => {
      try {
        const response = await fetcher(url, { signal: controller.signal })
        if (!response.ok) {
          if (response.status === 404) {
            const body = await response.json().catch(() => null)
            if (body?.error === 'NO_SNAPSHOT') return failure('NO_SNAPSHOT', 404)
          }
          return failure('HTTP_ERROR', response.status)
        }
        let body
        try { body = await response.json() }
        catch { return failure(stopCode ?? 'INVALID_JSON') }
        try { return validate(body) ? { data: body, error: null } : failure('INVALID_SCHEMA') }
        catch { return failure('INVALID_SCHEMA') }
      } catch { return failure(stopCode ?? 'NETWORK_ERROR') }
    })()
    return await Promise.race([request, stopped])
  } finally {
    clearTimeout(timer)
    options.signal?.removeEventListener('abort', onAbort)
  }
}

// These independent results can be combined with Promise.all; history failure never clears latest.
export function loadMarketDashboard(fetcher = defaultFetcher, options = {}) {
  const schemaVersion = options.schemaVersion === undefined ? 'market-dashboard-v2' : options.schemaVersion
  if (!['market-dashboard-v2', 'market-dashboard-v3'].includes(schemaVersion)) return Promise.resolve(failure('INVALID_QUERY'))
  return load(`/api/market-dashboard/latest?schemaVersion=${schemaVersion}`, schemaVersion === 'market-dashboard-v3' ? validV3Latest : validLatest, fetcher, options)
}
export function loadMarketHistory(window, fetcher = defaultFetcher, options = {}) {
  if (!WINDOWS.includes(window)) return Promise.resolve(failure('INVALID_WINDOW'))
  const schemaVersion = options.schemaVersion === undefined ? 'market-dashboard-v2' : options.schemaVersion
  if (!['market-dashboard-v2', 'market-dashboard-v3'].includes(schemaVersion)) return Promise.resolve(failure('INVALID_QUERY'))
  return load(`/api/market-dashboard/history?window=${window}&schemaVersion=${schemaVersion}`, body => schemaVersion === 'market-dashboard-v3' ? validV3History(body, window) : validHistory(body, window), fetcher, options)
}

const SECTOR_AXES = ['strength', 'opportunity', 'risk']
const BOARD_AXES = ['strength', 'opportunity']
const HEAT_STATES = ['cold', 'neutral', 'warming', 'active', 'crowded']
const SECTOR_VERSION = 'sector-score-v0.2'
const UNIVERSE_VERSION = 'sector-universe-v0.1'
const integer = (value, min, max) => Number.isInteger(value) && number(value, min, max)
const safeCode = value => typeof value === 'string' && value.length <= 200 && /^[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*$/.test(value)
const codes = value => Array.isArray(value) && value.every(safeCode)
const validVersions = value => value.scoringVersion === SECTOR_VERSION && value.universeVersion === UNIVERSE_VERSION
const name = value => typeof value === 'string' && value.length <= 100
const validSectorScores = value => SECTOR_AXES.every(axis => value[axis] === null || integer(value[axis], 0, 100))
  && integer(value.completeness, 0, 100) && (value.heatState === null || HEAT_STATES.includes(value.heatState))
function validRanks(value, universe) {
  return shape(value, SECTOR_AXES) && SECTOR_AXES.every(axis => value[axis] === null || integer(value[axis], 1, universe === 'industry' ? 35 : 75))
}
function validBoard(value, universe) {
  return shape(value, BOARD_AXES) && BOARD_AXES.every(axis => {
    const board = value[axis], bound = universe === 'industry' ? 34 : 74
    return shape(board, ['axis', 'topTenStreak', 'topTenCount15d', 'rankChange']) && board.axis === axis
      && integer(board.topTenStreak, 0, 1000000) && integer(board.topTenCount15d, 0, 15)
      && (board.rankChange === null || integer(board.rankChange, -bound, bound))
  })
}
const SECTOR_ROW_KEYS = ['id', 'name', ...SECTOR_AXES, 'heatState', 'completeness', 'coldStart', 'ranks', 'leaderboard']
function validSectorRow(value, universe, latest = false) {
  return shape(value, [...SECTOR_ROW_KEYS, ...(latest ? ['change1d'] : [])])
    && validSectorIdentity(universe, value.id) && name(value.name) && validSectorScores(value)
    && typeof value.coldStart === 'boolean' && validRanks(value.ranks, universe) && validBoard(value.leaderboard, universe)
    && (!latest || shape(value.change1d, SECTOR_AXES) && SECTOR_AXES.every(axis => value.change1d[axis] === null || number(value.change1d[axis], -100, 100)))
}
function validSectorObservation(value) {
  return timestamp(value.observedAt) && calendarDate(value.marketDate)
    && value.marketDate === new Date(Date.parse(value.observedAt.replace(' ', 'T')) + 8 * 3600000).toISOString().slice(0, 10)
    && ['intraday', 'close'].includes(value.session)
}
function validV3Latest(value) {
  if (value?.schemaVersion !== 'market-dashboard-v3') return false
  // This pure validator also checks the lossless encoded audit, evidence gates and exact 110 identities.
  try { validatePayload(value); return true } catch { return false }
}
function validV3History(value, window) {
  const compactLegacy = obj => shape(obj, ['id', ...AXES, 'completeness']) && validScores(obj)
  const compactSector = (obj, universe) => shape(obj, ['id', ...SECTOR_AXES, 'heatState', 'completeness', 'ranks'])
    && validSectorIdentity(universe, obj.id) && validSectorScores(obj) && validRanks(obj.ranks, universe)
  const unique = rows => new Set(rows.map(obj => obj.id)).size === rows.length
  return shape(value, ['window', 'snapshots']) && value.window === window && Array.isArray(value.snapshots) && value.snapshots.length > 0
    && value.snapshots.every((snapshot, i) => {
      if (!shape(snapshot, ['observedAt', 'marketDate', 'session', 'schemaVersion', 'scoringVersion', 'sectorScoringVersion',
        'sectorUniverseVersion', 'global', 'aShare', 'styles', 'industries', 'concepts'])
        || snapshot.schemaVersion !== 'market-dashboard-v3' || snapshot.sectorScoringVersion !== SECTOR_VERSION
        || snapshot.sectorUniverseVersion !== UNIVERSE_VERSION || !validObservation(snapshot)
        || !compactLegacy(snapshot.global) || snapshot.global.id !== 'global' || !compactLegacy(snapshot.aShare) || snapshot.aShare.id !== 'a-share'
        || !Array.isArray(snapshot.styles) || snapshot.styles.length !== 6 || !unique(snapshot.styles)
        || !snapshot.styles.every(obj => STYLES.includes(obj.id) && compactLegacy(obj))
        || !Array.isArray(snapshot.industries) || snapshot.industries.length !== 35 || !unique(snapshot.industries)
        || !snapshot.industries.every(obj => compactSector(obj, 'industry'))) return false
      const concepts = snapshot.concepts
      return shape(concepts, ['selectionVersion', 'scoringVersion', 'selectionScoringVersion', 'selectedAt', 'core', 'dynamic'])
        && concepts.selectionVersion === 'concept-selection-v0.1' && concepts.scoringVersion === SECTOR_VERSION
        && concepts.selectionScoringVersion === 'concept-score-v0.1' && timestamp(concepts.selectedAt)
        && Date.parse(concepts.selectedAt) <= Date.parse(snapshot.observedAt)
        && Array.isArray(concepts.core) && concepts.core.length === 25 && Array.isArray(concepts.dynamic) && concepts.dynamic.length === 10
        && unique([...concepts.core, ...concepts.dynamic]) && concepts.core.every(obj => CORE_CONCEPTS.includes(obj.id) && compactSector(obj, 'concept'))
        && concepts.dynamic.every(obj => !CORE_CONCEPTS.includes(obj.id) && compactSector(obj, 'concept'))
        && (i === 0 || preciseTimestamp(snapshot.observedAt).utc >= preciseTimestamp(value.snapshots[i - 1].observedAt).utc)
    })
}
const CORE_CONCEPTS = ['884201.WI','8841678.WI','8841889.WI','884091.WI','8841665.WI','8841349.WI','8841337.WI','8841294.WI','8841237.WI','8841256.WI',
  '8841699.WI','884766.WI','8841635.WI','8841750.WI','8841739.WI','8841671.WI','884790.WI','884114.WI','884190.WI','884086.WI',
  '8841877.WI','8841875.WI','8841049.WI','8841718.WI','884142.WI']
function validRotationLatest(value, options) {
  return shape(value, ['observedAt', 'marketDate', 'session', 'universe', 'view', 'scoringVersion', 'universeVersion', 'sectors'])
    && validSectorObservation(value) && validVersions(value) && value.universe === options.universe && value.view === options.view
    && Array.isArray(value.sectors) && value.sectors.length <= (options.universe === 'industry' ? 35 : 75)
    && new Set(value.sectors.map(row => row?.id)).size === value.sectors.length
    && value.sectors.every(row => validSectorRow(row, options.universe, true))
}
function validRotationHistory(value, options) {
  return shape(value, ['universe', 'axis', 'days', 'dates', 'scoringVersion', 'universeVersion', 'rows'])
    && validVersions(value) && value.universe === options.universe && value.axis === options.axis && value.days === options.days
    && Array.isArray(value.dates) && value.dates.length > 0 && value.dates.length <= options.days
    && value.dates.every((date, i) => calendarDate(date) && (i === 0 || date > value.dates[i - 1]))
    && Array.isArray(value.rows) && value.rows.length <= (options.universe === 'industry' ? 35 : 75)
    && new Set(value.rows.map(row => row?.id)).size === value.rows.length
    && value.rows.every(row => shape(row, ['id', 'name', 'values']) && validSectorIdentity(options.universe, row.id) && name(row.name)
      && Array.isArray(row.values) && row.values.length === value.dates.length
      && row.values.every((point, i) => shape(point, ['marketDate', 'score', 'rank']) && point.marketDate === value.dates[i]
        && (point.score === null || integer(point.score, 0, 100))
        && (point.rank === null || integer(point.rank, 1, options.universe === 'industry' ? 35 : 75))))
    && value.dates.every((_, i) => {
      const ranks = value.rows.map(row => row.values[i].rank).filter(rank => rank !== null)
      return new Set(ranks).size === ranks.length
    })
}
const COMPONENT_PARTS = {
  priceTrend: ['return1d','return5d','return20d'], funding: ['flow1d','flow5d','flow20d'],
  activity: ['turnover','marketShare','concentration','acceleration'], persistence: ['meanPercentile','topTenStreak'],
  position: ['position60d','position250d'], fundsImprovement: ['historical20d','delta5d'], breadthImprovement: ['delta5d','improvingDays'],
  momentumImprovement: ['shortAcceleration','mediumAcceleration'], activityWarming: ['current','delta5d'],
  downsideDiffusion: ['current','delta5d'], fundsWithdrawal: ['funding','delta5d'],
  trendDeterioration: ['return5d','return20d','slope5d'], crowding: ['activity','acceleration'],
}
const COMPONENT_NAMES = [...Object.keys(COMPONENT_PARTS), 'breadth', 'concentration', 'activityMean5d', 'divergence']
function validComponent(value, componentName, depth = 0) {
  if (depth > 5 || !shape(value, ['value', 'coverage', 'missing'], ['usedWeight','totalWeight','effectiveWeight','percentile','parts'])
    || !(value.value === null || number(value.value)) || !number(value.coverage, 0, 1) || !codes(value.missing)
    || !['usedWeight','totalWeight','effectiveWeight'].every(key => !Object.hasOwn(value, key) || value[key] === null || number(value[key], 0, Number.MAX_VALUE))
    || !(!Object.hasOwn(value, 'percentile') || value.percentile === null || number(value.percentile))) return false
  const parts = COMPONENT_PARTS[componentName]
  if (!Object.hasOwn(value, 'parts')) return !parts || componentName === 'crowding'
  return !!parts && shape(value.parts, parts) && ['usedWeight','totalWeight','effectiveWeight'].every(key => Object.hasOwn(value, key)) && parts.every(part => validComponent(value.parts[part],
    componentName === 'activityWarming' && part === 'current' ? 'activity' : part, depth + 1))
}
function validDetailRow(row, options) {
  const auditKeys = ['observedAt', 'marketDate', 'session', 'officialClose', 'components', 'missing', 'contributors', 'provenance', 'scoringVersion', 'universeVersion']
  if (!shape(row, [...SECTOR_ROW_KEYS, ...auditKeys]) || row.id !== options.id || !validVersions(row) || !validSectorObservation(row)) return false
  const compact = Object.fromEntries(SECTOR_ROW_KEYS.map(key => [key, row[key]]))
  if (!validSectorRow(compact, options.universe) || typeof row.officialClose !== 'boolean' || row.officialClose !== (row.session === 'close')
    || !shape(row.components, COMPONENT_NAMES)
    || !Object.entries(row.components).every(([key, value]) => COMPONENT_NAMES.includes(key) && validComponent(value, key))
    || !codes(row.missing) || !Array.isArray(row.contributors)
    || !row.contributors.every(item => shape(item, ['axis', 'component', 'value', 'weight', 'impact'])
      && SECTOR_AXES.includes(item.axis) && COMPONENT_NAMES.includes(item.component) && number(item.value)
      && number(item.weight) && number(item.impact, -100, 100))) return false
  const source = row.provenance
  if (!shape(source, ['source', 'observedAt', 'marketDate', 'session', 'officialClose', 'sectorScoringVersion', 'sectorUniverseVersion'])
    || source.source !== 'Wind' || !timestamp(source.observedAt) || source.marketDate !== row.marketDate || source.session !== row.session
    || source.officialClose !== row.officialClose || source.sectorScoringVersion !== SECTOR_VERSION || source.sectorUniverseVersion !== UNIVERSE_VERSION) return false
  const collectedTime = preciseTimestamp(row.observedAt), suppliedTime = preciseTimestamp(source.observedAt)
  const collected = collectedTime.millis, supplied = suppliedTime.millis
  const earliest = new Date(collected - 30 * 60000).toISOString().replace('Z', `${collectedTime.utc.slice(-4, -1)}Z`)
  return suppliedTime.utc <= collectedTime.utc && suppliedTime.utc >= earliest
    && new Date(supplied + 8 * 3600000).toISOString().slice(0, 10) === row.marketDate
    && (!row.officialClose || suppliedTime.utc >= preciseTimestamp(`${row.marketDate}T15:00:00+08:00`).utc && collectedTime.utc <= preciseTimestamp(`${row.marketDate}T15:30:00+08:00`).utc)
}
function validRotationDetail(value, options) {
  return shape(value, ['universe', 'id', 'days', 'scoringVersion', 'universeVersion', 'history']) && validVersions(value)
    && value.universe === options.universe && value.id === options.id && value.days === options.days
    && Array.isArray(value.history) && value.history.length > 0 && new Set(value.history.map(row => row.marketDate)).size <= options.days
    && value.history.every((row, i) => validDetailRow(row, options)
      && (i === 0 || preciseTimestamp(row.observedAt).utc > preciseTimestamp(value.history[i - 1].observedAt).utc))
}
function rotationLoad(endpoint, options, validate, query) {
  return load(`/api/sector-rotation/${endpoint}?${new URLSearchParams(query)}`, body => {
    try { return validate(body, options) } catch { return false }
  }, options.fetcher ?? defaultFetcher, options)
}
export function loadSectorRotationLatest(options = {}) {
  if (!['industry', 'concept'].includes(options.universe) || !['potential', 'main', 'risk'].includes(options.view)) return Promise.resolve(failure('INVALID_QUERY'))
  return rotationLoad('latest', options, validRotationLatest, { universe: options.universe, view: options.view })
}
export function loadSectorRotationHistory(options = {}) {
  const selected = { ...options, days: options.days ?? 15 }
  if (!['industry', 'concept'].includes(selected.universe) || !BOARD_AXES.includes(selected.axis) || !integer(selected.days, 1, 15)) return Promise.resolve(failure('INVALID_QUERY'))
  return rotationLoad('history', selected, validRotationHistory, { universe: selected.universe, axis: selected.axis, days: String(selected.days) })
}
export function loadSectorRotationDetail(options = {}) {
  const selected = { ...options, days: options.days ?? 60 }
  if (!validSectorIdentity(selected.universe, selected.id) || !integer(selected.days, 1, 60)) return Promise.resolve(failure('INVALID_QUERY'))
  return rotationLoad('detail', selected, validRotationDetail, { universe: selected.universe, id: selected.id, days: String(selected.days) })
}
