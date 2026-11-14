// Public, derived-only contract. Keep identity/version changes paired with the local scorer.
export const SCHEMA_VERSION = 'market-dashboard-v2'
export const SCORING_VERSION = 'market-score-v0.1'
export const ROTATION_SCHEMA_VERSION = 'market-dashboard-v3'
export const SECTOR_SCORING_VERSION = 'sector-score-v0.2'
export const SECTOR_UNIVERSE_VERSION = 'sector-universe-v0.1'
export const CONCEPT_SELECTION_VERSION = 'concept-selection-v0.1'
export const CONCEPT_SCORING_VERSION = 'concept-score-v0.1'
const MAX_BODY_BYTES = 256 * 1024
const AXES = ['strength', 'heat', 'risk']
const STYLE_IDS = ['000300.SH', '000852.SH', 'H30356.CSI', '399006.SZ', '000922.CSI', '000688.SH']
const INDUSTRY_IDS = Array.from({ length: 37 }, (_, i) => 100 + i)
  .filter(code => code !== 117 && code !== 118).map(code => `882${code}.WI`)
const ROTATION_CONCEPT_IDS = [
  '884201.WI','8841678.WI','8841889.WI','884091.WI','8841665.WI','8841349.WI','8841337.WI','8841294.WI','8841237.WI','8841256.WI',
  '8841699.WI','884766.WI','8841635.WI','8841750.WI','8841739.WI','8841671.WI','884790.WI','884114.WI','884190.WI','884086.WI',
  '8841877.WI','8841875.WI','8841049.WI','8841718.WI','884142.WI','8841935.WI','8841339.WI','8841259.WI','8841018.WI','8841180.WI',
  '8841179.WI','884155.WI','884969.WI','8841890.WI','884087.WI','8841648.WI','8841006.WI','884041.WI','8841327.WI','8841340.WI',
  '884099.WI','8841087.WI','884108.WI','884133.WI','8841362.WI','8841282.WI','8841593.WI','8841192.WI','8841636.WI','8841911.WI',
  '8841260.WI','8841741.WI','8841407.WI','8841398.WI','884213.WI','8841960.WI','884131.WI','8841249.WI','8841350.WI','8841284.WI',
  '8841959.WI','884959.WI','8841432.WI','884225.WI','884821.WI','884028.WI','8841041.WI','8841442.WI','8841372.WI','884203.WI',
  '884143.WI','8841272.WI','884247.WI','8841225.WI','8841201.WI',
]
const STAGES = ['冰点', '修复', '震荡', '扩张', '过热', '退潮']
const UNAVAILABLE = ['missingObservation', 'missingCurrentScores', 'missingTradingCalendar', 'missingTargetTradingDate']

export function jsonResponse(value, status = 200, cache = 'no-store') {
  return new Response(JSON.stringify(value), { status, headers: {
    'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': cache,
  } })
}
export function errorResponse(code, status) { return jsonResponse({ error: code }, status) }
function requireValid(condition) { if (!condition) throw new Error('INVALID_PAYLOAD') }
function record(value) { return value !== null && typeof value === 'object' && !Array.isArray(value) }
function shape(value, required, optional = []) {
  return record(value) && required.every(key => Object.hasOwn(value, key)) &&
    Object.keys(value).every(key => required.includes(key) || optional.includes(key))
}
function numeric(value, min = 0, max = 100) {
  return typeof value === 'number' && Number.isFinite(value) && value >= min && value <= max
}
function strings(value) { return Array.isArray(value) && value.every(s => typeof s === 'string' && s.length <= 200) }
function integer(value, min, max) { return Number.isInteger(value) && value >= min && value <= max }
function sameInstant(left, right) { return timestamp(left).utc === timestamp(right).utc }
function exactIdentities(rows, ids) {
  return Array.isArray(rows) && rows.length === ids.length && rows.every(record) &&
    new Set(rows.map(row => row.id)).size === ids.length && rows.every(row => ids.includes(row.id))
}

function validateLegacyObject(obj) {
  requireValid(shape(obj, ['id', ...AXES, 'completeness', 'missing', 'contributors', 'sourceTimestamps', 'change1d', 'change5d'],
    ['name', 'frequency', 'observedAt', 'stage', 'comparisonFallback', 'comparisonUnavailable']))
  requireValid(integer(obj.completeness, 1, 100) && strings(obj.missing) &&
    AXES.every(axis => obj[axis] === null || integer(obj[axis], 0, 100)) && AXES.some(axis => obj[axis] !== null))
  if (Object.hasOwn(obj, 'observedAt')) timestamp(obj.observedAt)
  if (Object.hasOwn(obj, 'frequency')) requireValid(['intraday', 'daily', 'monthly'].includes(obj.frequency))
  if (Object.hasOwn(obj, 'name')) requireValid(typeof obj.name === 'string' && obj.name.length <= 100)
  requireValid(obj.stage == null || obj.completeness >= 50 && STAGES.includes(obj.stage))
  for (const key of ['change1d', 'change5d']) {
    const change = obj[key]
    requireValid(change === null || shape(change, AXES) && AXES.every(axis => change[axis] === null || numeric(change[axis], -100, 100)))
  }
  requireValid(Array.isArray(obj.sourceTimestamps) && obj.sourceTimestamps.length > 0)
  for (const source of obj.sourceTimestamps) {
    requireValid(shape(source, ['source', 'timestamp']) && ['Wind', 'FRED', 'MX', 'Derived'].includes(source.source))
    timestamp(source.timestamp)
  }
  requireValid(Array.isArray(obj.contributors) && obj.contributors.length <= 3)
  for (const contributor of obj.contributors) {
    requireValid(shape(contributor, ['label', 'impact'], ['evidence']) && typeof contributor.label === 'string' &&
      contributor.label.length <= 200 && numeric(contributor.impact, -100, 100))
    if (Object.hasOwn(contributor, 'evidence')) requireValid(typeof contributor.evidence === 'string' && contributor.evidence.length <= 200)
  }
  if (Object.hasOwn(obj, 'comparisonFallback')) requireValid(obj.comparisonFallback === 'close')
  if (Object.hasOwn(obj, 'comparisonUnavailable')) requireValid(shape(obj.comparisonUnavailable, [], ['change1d', 'change5d']) &&
    Object.values(obj.comparisonUnavailable).every(value => UNAVAILABLE.includes(value)))
}

function validateSourceMode(modes) {
  requireValid(shape(modes, ['breadth', 'styles', 'industries', 'concepts', 'conceptDiscovery', 'global']) &&
    ['breadth', 'styles', 'industries', 'concepts'].every(key => modes[key] === 'wind') &&
    modes.conceptDiscovery === 'mx' && record(modes.global))
  requireValid(Object.entries(modes.global).every(([key, value]) => /^[\p{L}\p{N}]+$/u.test(key) &&
    ['fred', 'wind', 'mx'].includes(value)))
}

// Validate calendar dates too: Date.parse alone silently accepts February 30.
export function timestamp(value) {
  requireValid(typeof value === 'string')
  const match = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value)
  requireValid(match)
  const [, year, month, day, hour, minute, second, fraction = '', offset] = match
  const days = new Date(Date.UTC(Number(year), Number(month), 0)).getUTCDate()
  requireValid(Number(year) >= 1 && Number(month) >= 1 && Number(month) <= 12 && Number(day) >= 1 && Number(day) <= days &&
    Number(hour) < 24 && Number(minute) < 60 && Number(second) < 60 &&
    (offset === 'Z' || Number(offset.slice(1, 3)) < 24 && Number(offset.slice(4)) < 60))
  const millis = Date.parse(value.replace(' ', 'T'))
  requireValid(Number.isFinite(millis))
  const normalized = new Date(millis)
  // Offsets can move a four-digit input year outside the canonical UTC domain.
  requireValid(normalized.getUTCFullYear() >= 1 && normalized.getUTCFullYear() <= 9999)
  const utc = normalized.toISOString().replace(/\.(\d{3})Z$/, `.$1${fraction.slice(3).padEnd(3, '0')}Z`)
  return { millis, utc }
}

function validateV2Payload(payload) {
  requireValid(shape(payload, ['schemaVersion', 'scoringVersion', 'observedAt', 'marketDate', 'session',
    'global', 'aShare', 'styles', 'industries', 'concepts', 'dataStatus'], ['sourceMode']))
  requireValid(payload.schemaVersion === SCHEMA_VERSION && payload.scoringVersion === SCORING_VERSION)
  const observed = timestamp(payload.observedAt)
  requireValid(typeof payload.marketDate === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(payload.marketDate) &&
    payload.marketDate === new Date(observed.millis + 8 * 3600000).toISOString().slice(0, 10))
  requireValid(['intraday', 'close'].includes(payload.session))
  requireValid(record(payload.global) && payload.global.id === 'global')
  requireValid(record(payload.aShare) && payload.aShare.id === 'a-share')
  for (const [key, ids] of [['styles', STYLE_IDS], ['industries', INDUSTRY_IDS]]) {
    const items = payload[key]
    requireValid(Array.isArray(items) && items.length === ids.length && items.every(record))
    requireValid(new Set(items.map(obj => obj.id)).size === ids.length && items.every(obj => ids.includes(obj.id)))
  }
  const concepts = payload.concepts
  requireValid(shape(concepts, ['selectionVersion', 'scoringVersion', 'selectedAt', 'core', 'dynamic']) &&
    concepts.selectionVersion === CONCEPT_SELECTION_VERSION && concepts.scoringVersion === CONCEPT_SCORING_VERSION)
  timestamp(concepts.selectedAt)
  requireValid(Array.isArray(concepts.core) && concepts.core.length === 25 && concepts.core.every(record) &&
    Array.isArray(concepts.dynamic) && concepts.dynamic.length === 10 && concepts.dynamic.every(record))
  const coreIds = concepts.core.map(obj => obj.id), dynamicIds = concepts.dynamic.map(obj => obj.id)
  requireValid([...coreIds, ...dynamicIds].every(id => typeof id === 'string' && /^884\d{2,4}\.WI$/.test(id)) &&
    new Set(coreIds).size === 25 && new Set(dynamicIds).size === 10 && !coreIds.some(id => dynamicIds.includes(id)))
  for (const obj of concepts.core) {
    requireValid(!['selectionScore', 'selectedOn', 'retainedTradingDays'].some(key => Object.hasOwn(obj, key)))
  }
  for (const obj of concepts.dynamic) {
    requireValid(numeric(obj.selectionScore) && typeof obj.selectedOn === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(obj.selectedOn) &&
      Number.isInteger(obj.retainedTradingDays) && obj.retainedTradingDays >= 1)
    const [year, month, day] = obj.selectedOn.split('-').map(Number)
    requireValid(year >= 1 && month >= 1 && month <= 12 && day >= 1 &&
      day <= new Date(Date.UTC(year, month, 0)).getUTCDate())
  }
  const objects = [payload.global, payload.aShare, ...payload.styles, ...payload.industries,
    ...concepts.core, ...concepts.dynamic]
  for (const obj of objects) {
    if (!concepts.dynamic.includes(obj)) {
      requireValid(!['selectionScore', 'selectedOn', 'retainedTradingDays'].some(key => Object.hasOwn(obj, key)))
    }
    requireValid(shape(obj, ['id', ...AXES, 'completeness', 'missing', 'contributors', 'sourceTimestamps', 'change1d', 'change5d'],
      ['name', 'frequency', 'observedAt', 'stage', 'comparisonFallback', 'comparisonUnavailable',
        'selectionScore', 'selectedOn', 'retainedTradingDays']))
    requireValid(numeric(obj.completeness) && obj.completeness > 0 && strings(obj.missing))
    requireValid(AXES.every(axis => obj[axis] === null || Number.isInteger(obj[axis]) && numeric(obj[axis])))
    requireValid(AXES.some(axis => obj[axis] !== null))
    if (Object.hasOwn(obj, 'observedAt')) timestamp(obj.observedAt)
    if (Object.hasOwn(obj, 'frequency')) requireValid(['intraday', 'daily', 'monthly'].includes(obj.frequency))
    if (Object.hasOwn(obj, 'name')) requireValid(typeof obj.name === 'string' && obj.name.length <= 100)
    requireValid(obj.stage == null || obj.completeness >= 50 && STAGES.includes(obj.stage))
    for (const key of ['change1d', 'change5d']) {
      const change = obj[key]
      requireValid(change === null || shape(change, AXES) && AXES.every(axis => change[axis] === null || numeric(change[axis], -100, 100)))
    }
    requireValid(Array.isArray(obj.sourceTimestamps) && obj.sourceTimestamps.length > 0)
    for (const source of obj.sourceTimestamps) {
      requireValid(shape(source, ['source', 'timestamp']) && ['Wind', 'FRED', 'MX', 'Derived'].includes(source.source))
      timestamp(source.timestamp)
    }
    requireValid(Array.isArray(obj.contributors) && obj.contributors.length <= 3)
    for (const contributor of obj.contributors) {
      requireValid(shape(contributor, ['label', 'impact'], ['evidence']) && typeof contributor.label === 'string' &&
        contributor.label.length <= 200 && numeric(contributor.impact, -100, 100))
      if (Object.hasOwn(contributor, 'evidence')) requireValid(typeof contributor.evidence === 'string' && contributor.evidence.length <= 200)
    }
    if (Object.hasOwn(obj, 'comparisonFallback')) requireValid(obj.comparisonFallback === 'close')
    if (Object.hasOwn(obj, 'comparisonUnavailable')) {
      requireValid(shape(obj.comparisonUnavailable, [], ['change1d', 'change5d']) &&
        Object.values(obj.comparisonUnavailable).every(value => UNAVAILABLE.includes(value)))
    }
  }
  const status = payload.dataStatus
  requireValid(shape(status, ['completeness', 'stale', 'missing']) && numeric(status.completeness) &&
    typeof status.stale === 'boolean' && strings(status.missing))
  requireValid(status.completeness > 0 && status.completeness === Math.floor(objects.reduce((sum, obj) => sum + obj.completeness, 0) / objects.length + 0.5))
  if (Object.hasOwn(payload, 'sourceMode')) {
    const modes = payload.sourceMode
    requireValid(shape(modes, ['breadth', 'styles', 'industries', 'concepts', 'conceptDiscovery', 'global']) &&
      ['breadth', 'styles', 'industries', 'concepts'].every(key => modes[key] === 'wind') &&
      modes.conceptDiscovery === 'mx' && record(modes.global))
    requireValid(Object.entries(modes.global).every(([key, value]) => /^[\p{L}\p{N}]+$/u.test(key) && ['fred', 'wind', 'mx'].includes(value)))
  }
  requireValid(new TextEncoder().encode(JSON.stringify(payload)).byteLength <= MAX_BODY_BYTES)
  return observed
}

const COMPONENT_FIELDS = ['value', 'coverage', 'missing', 'usedWeight', 'totalWeight',
  'effectiveWeight', 'percentile', 'parts']
const ROTATION_COMPONENT_NAMES = ['priceTrend','funding','breadth','activity','concentration','activityMean5d',
  'persistence','position','fundsImprovement','breadthImprovement','momentumImprovement','activityWarming',
  'downsideDiffusion','fundsWithdrawal','trendDeterioration','divergence','crowding']
const ROTATION_PART_NAMES = ['acceleration','activity','concentration','current','delta5d','flow1d','flow20d','flow5d',
  'funding','historical20d','improvingDays','marketShare','meanPercentile','mediumAcceleration','position250d',
  'position60d','return1d','return20d','return5d','shortAcceleration','slope5d','topTenStreak','turnover']
const ROTATION_COMPONENT_PARTS = {
  priceTrend: ['return1d','return5d','return20d'], funding: ['flow1d','flow5d','flow20d'],
  activity: ['turnover','marketShare','concentration','acceleration'], persistence: ['meanPercentile','topTenStreak'],
  position: ['position60d','position250d'], fundsImprovement: ['historical20d','delta5d'],
  breadthImprovement: ['delta5d','improvingDays'], momentumImprovement: ['shortAcceleration','mediumAcceleration'],
  activityWarming: ['current','delta5d'], downsideDiffusion: ['current','delta5d'],
  fundsWithdrawal: ['funding','delta5d'], trendDeterioration: ['return5d','return20d','slope5d'],
  crowding: ['activity','acceleration'],
}
const ROTATION_GATES = { minimumCloses: 20, coldStartCloses: 60, minimumOpportunityCompleteness: 70,
  improvementThreshold: 60, requiredImprovementComponents: 2, highOpportunityThreshold: 70, unconfirmedOpportunityCap: 69 }
const HEAT_STATES = ['cold', 'neutral', 'warming', 'active', 'crowded']
const FORBIDDEN_DERIVED_KEYS = new Set(['rawRows', 'rawResponse', 'authorization', 'token', '_units',
  '_timestamp', '_rawScores', 'metrics', 'history', 'indicators', 'netFlow1d', 'amount1d', 'close'])

function safeDerivedTree(value) {
  if (Array.isArray(value)) return value.every(safeDerivedTree)
  if (!record(value)) return typeof value !== 'number' || Number.isFinite(value)
  return Object.entries(value).every(([key, child]) => !FORBIDDEN_DERIVED_KEYS.has(key) && safeDerivedTree(child))
}

function validateAuditDefinitions(definitions) {
  requireValid(shape(definitions, ['weights', 'componentWeights', 'gates', 'heat']) &&
    shape(definitions.weights, ['strength', 'opportunity', 'risk']))
  const axes = {
    strength: ['priceTrend', 'funding', 'breadth', 'persistence'],
    opportunity: ['position', 'fundsImprovement', 'breadthImprovement', 'momentumImprovement', 'activityWarming'],
    risk: ['downsideDiffusion', 'fundsWithdrawal', 'trendDeterioration', 'divergence', 'crowding'],
  }
  for (const [axis, names] of Object.entries(axes)) {
    const weights = definitions.weights[axis]
    requireValid(shape(weights, names) && Object.values(weights).every(value => numeric(value, 0.000001, 100)) &&
      Math.abs(Object.values(weights).reduce((sum, value) => sum + value, 0) - 100) < 1e-9)
  }
  requireValid(record(definitions.componentWeights) && Object.keys(definitions.componentWeights).length > 0)
  for (const weights of Object.values(definitions.componentWeights)) {
    requireValid(record(weights) && Object.keys(weights).length > 0 &&
      Object.values(weights).every(value => numeric(value, 0.000001, 100)) &&
      Math.abs(Object.values(weights).reduce((sum, value) => sum + value, 0) - 100) < 1e-9)
  }
  for (const settings of [definitions.gates, definitions.heat]) {
    requireValid(record(settings) && Object.keys(settings).length > 0 &&
      Object.values(settings).every(value => typeof value === 'number' && Number.isFinite(value) && value >= 0))
  }
  requireValid(shape(definitions.gates, Object.keys(ROTATION_GATES)) &&
    Object.entries(ROTATION_GATES).every(([key, value]) => definitions.gates[key] === value))
}

// Sum bounded finite terms with an error-free expansion and a final ties-to-even
// correction, matching the producer's math.fsum rather than rounding each addition.
function preciseSum(values) {
  const partials = []
  for (let value of values) {
    let index = 0
    for (let other of partials) {
      if (Math.abs(value) < Math.abs(other)) [value, other] = [other, value]
      const high = value + other, low = other - (high - value)
      if (low) partials[index++] = low
      value = high
    }
    partials.length = index
    partials.push(value)
  }
  let index = partials.length - 1, high = partials[index] ?? 0, low = 0
  while (index > 0) {
    const value = high, other = partials[--index]
    high = value + other
    low = other - (high - value)
    if (low) break
  }
  if (index > 0 && Math.sign(low) === Math.sign(partials[index - 1])) {
    const twiceLow = low * 2, rounded = high + twiceLow
    if (rounded - high === twiceLow) high = rounded
  }
  return high
}

export function sectorRankKey(row, axis, definitions) {
  if (row[axis] === null) return null
  let total = 0, used = 0
  const terms = []
  for (const [name, weight] of Object.entries(definitions.weights[axis])) {
    const component = row.components[name], value = component?.value
    if (numeric(value) && (axis !== 'opportunity' || component.coverage > 0)) {
      total += value * weight; used += weight; terms.push([value, weight])
    }
  }
  if (!used) return row[axis]
  let score = axis === 'opportunity'
    ? preciseSum(terms.map(([value, weight]) => value * (weight / used))) : total / used
  if (axis === 'opportunity') {
    const gates = definitions.gates
    const improvements = ['fundsImprovement','breadthImprovement','momentumImprovement']
      .filter(name => numeric(row.components[name]?.value) && row.components[name].value >= gates.improvementThreshold).length
    if (improvements < gates.requiredImprovementComponents) score = Math.min(score, gates.unconfirmedOpportunityCap)
  }
  return score
}

function decodeAudit(block) {
  requireValid(block.componentEncoding === 'node-mask-v1' &&
    Array.isArray(block.componentFields) && block.componentFields.length === COMPONENT_FIELDS.length &&
    block.componentFields.every((field, index) => field === COMPONENT_FIELDS[index]))
  requireValid(strings(block.componentPartNames) && new Set(block.componentPartNames).size === block.componentPartNames.length &&
    block.componentPartNames.length === ROTATION_PART_NAMES.length &&
    ROTATION_PART_NAMES.every(name => block.componentPartNames.includes(name)) &&
    strings(block.missingReasons) && new Set(block.missingReasons).size === block.missingReasons.length &&
    block.missingReasons.every(reason => /^[A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)*$/.test(reason)) &&
    Array.isArray(block.componentNodes) && block.componentNodes.length > 0)
  const decoded = new Map(), visiting = new Set()
  const decode = index => {
    requireValid(integer(index, 0, block.componentNodes.length - 1))
    if (decoded.has(index)) return decoded.get(index)
    requireValid(!visiting.has(index)); visiting.add(index)
    const node = block.componentNodes[index]
    requireValid(Array.isArray(node) && integer(node[0], 0, 255))
    const mask = node[0], expected = COMPONENT_FIELDS.reduce((count, _, bit) => count + ((mask >> bit) & 1), 0)
    requireValid(node.length === expected + 1)
    const result = {}; let offset = 1
    for (let bit = 0; bit < COMPONENT_FIELDS.length; bit++) {
      if (!(mask & (1 << bit))) continue
      const key = COMPONENT_FIELDS[bit], value = node[offset++]
      if (key === 'missing') {
        requireValid(Array.isArray(value) && value.every(item => integer(item, 0, block.missingReasons.length - 1)))
        result[key] = value.map(item => block.missingReasons[item])
      } else if (key === 'parts') {
        requireValid(Array.isArray(value) && value.every(part => Array.isArray(part) && part.length === 2 &&
          integer(part[0], 0, block.componentPartNames.length - 1)))
        const parts = {}
        for (const [name, child] of value) {
          const keyName = block.componentPartNames[name]
          requireValid(!Object.hasOwn(parts, keyName))
          Object.defineProperty(parts, keyName, { value: decode(child), enumerable: true, writable: true, configurable: true })
        }
        result[key] = parts
      } else {
        requireValid(value === null || typeof value === 'number' && Number.isFinite(value))
        if (key === 'coverage') requireValid(value === null || value >= 0 && value <= 1)
        if (['usedWeight', 'totalWeight', 'effectiveWeight'].includes(key)) requireValid(value === null || value >= 0)
        if (['value', 'percentile'].includes(key)) requireValid(value === null || value >= 0 && value <= 100)
        result[key] = value
      }
    }
    visiting.delete(index); decoded.set(index, result); return result
  }
  block.componentNodes.forEach((_, index) => decode(index))
  return decode
}

function validateSectorSourceTime(sourceAt, collectedAt, marketDate, officialClose) {
  const source = timestamp(sourceAt), collected = timestamp(collectedAt)
  const earliest = new Date(collected.millis - 30 * 60000).toISOString()
    .replace('Z', `${collected.utc.slice(-4, -1)}Z`)
  requireValid(source.utc <= collected.utc && source.utc >= earliest &&
    new Date(source.millis + 8 * 3600000).toISOString().slice(0, 10) === marketDate)
  if (officialClose) requireValid(source.utc >= timestamp(`${marketDate}T15:00:00+08:00`).utc &&
    collected.utc <= timestamp(`${marketDate}T15:30:00+08:00`).utc)
}

function validateRotationRow(row, universe, ids, block, decode) {
  requireValid(shape(row, ['id', 'name', 'universe', 'observedAt', 'strength', 'opportunity', 'risk',
    'heatState', 'axisCompleteness', 'completeness', 'coldStart', 'validCloses', 'improvementEvidence',
    'ranks', 'leaderboard', 'officialClose', 'components', 'missing']))
  validateSectorSourceTime(row.observedAt, block.observedAt, block.marketDate, block.officialClose)
  requireValid(ids.includes(row.id) && row.universe === universe && typeof row.name === 'string' && row.name.length <= 100 &&
    row.officialClose === block.officialClose)
  for (const axis of ['strength', 'opportunity', 'risk']) {
    requireValid(row[axis] === null || integer(row[axis], 0, 100))
    const maximum = universe === 'industry' ? 35 : 75
    requireValid(row.ranks[axis] === null || integer(row.ranks[axis], 1, maximum))
  }
  requireValid(shape(row.axisCompleteness, ['strength', 'opportunity', 'risk']) &&
    Object.values(row.axisCompleteness).every(value => numeric(value)))
  requireValid(integer(row.completeness, 0, 100) && typeof row.coldStart === 'boolean' &&
    integer(row.validCloses, 0, 1000000) && integer(row.improvementEvidence, 0, 5) &&
    shape(row.ranks, ['strength', 'opportunity', 'risk']) &&
    (row.heatState === null || HEAT_STATES.includes(row.heatState)) && typeof row.officialClose === 'boolean')
  requireValid(shape(row.leaderboard, ['strength', 'opportunity']))
  for (const axis of ['strength', 'opportunity']) {
    const board = row.leaderboard[axis]
    requireValid(shape(board, ['axis', 'topTenStreak', 'topTenCount15d', 'rankChange']) && board.axis === axis &&
      integer(board.topTenStreak, 0, 1000000) && integer(board.topTenCount15d, 0, 15) &&
      (board.rankChange === null || integer(board.rankChange, -74, 74)))
  }
  requireValid(record(row.components) && Object.keys(row.components).length === ROTATION_COMPONENT_NAMES.length &&
    ROTATION_COMPONENT_NAMES.every(name => Object.hasOwn(row.components, name)) &&
    Object.values(row.components).every(index => integer(index, 0, block.componentNodes.length - 1)))
  requireValid(Array.isArray(row.missing) && row.missing.every(index => integer(index, 0, block.missingReasons.length - 1)))
  const components = Object.fromEntries(Object.entries(row.components).map(([name, index]) => [name, decode(index)]))
  const validateComponent = (component, name) => {
    requireValid(shape(component, ['value', 'coverage', 'missing'], ['usedWeight','totalWeight','effectiveWeight','percentile','parts']))
    const parts = ROTATION_COMPONENT_PARTS[name]
    // Crowding legitimately collapses to a leaf for unavailable or quiet activity.
    if (parts && !(name === 'crowding' && !Object.hasOwn(component, 'parts'))) {
      requireValid(shape(component.parts, parts) && parts.length === Object.keys(component.parts).length &&
        ['usedWeight','totalWeight','effectiveWeight'].every(key => Object.hasOwn(component, key)))
      for (const [part, child] of Object.entries(component.parts)) {
        const nested = name === 'activityWarming' && part === 'current' ? 'activity' : part
        validateComponent(child, ['activity', 'funding'].includes(nested) ? nested : null)
      }
    } else requireValid(!Object.hasOwn(component, 'parts'))
  }
  Object.entries(components).forEach(([name, component]) => validateComponent(component, name))
  requireValid(safeDerivedTree(components))
  const gates = block.auditDefinitions.gates
  const improvements = ['fundsImprovement','breadthImprovement','momentumImprovement']
    .filter(name => numeric(components[name].value) && components[name].value >= gates.improvementThreshold).length
  requireValid(row.improvementEvidence === improvements)
  if (row.opportunity !== null) {
    const opportunityCoverage = Object.entries(block.auditDefinitions.weights.opportunity)
      .reduce((sum, [name, weight]) => sum + (numeric(components[name].value) ? weight * components[name].coverage : 0), 0)
    requireValid(row.validCloses >= gates.minimumCloses &&
      row.axisCompleteness.opportunity >= gates.minimumOpportunityCompleteness &&
      opportunityCoverage >= gates.minimumOpportunityCompleteness &&
      Math.abs(opportunityCoverage - row.axisCompleteness.opportunity) < 1e-9)
    if (row.opportunity >= gates.highOpportunityThreshold) requireValid(improvements >= gates.requiredImprovementComponents)
    const raw = sectorRankKey({ ...row, components }, 'opportunity', block.auditDefinitions)
    requireValid(raw !== null && Math.floor(raw + .5) === row.opportunity)
  }
  return { ...row, components, missing: row.missing.map(index => block.missingReasons[index]) }
}

function validateRotationPayload(payload) {
  requireValid(shape(payload, ['observedAt', 'marketDate', 'session', 'schemaVersion', 'scoringVersion', 'global',
    'aShare', 'styles', 'industries', 'dataStatus', 'concepts', 'sectorScoringVersion', 'sectorUniverseVersion',
    'sectorRotation'], ['sourceMode']))
  requireValid(payload.schemaVersion === ROTATION_SCHEMA_VERSION && payload.scoringVersion === SCORING_VERSION &&
    payload.sectorScoringVersion === SECTOR_SCORING_VERSION && payload.sectorUniverseVersion === SECTOR_UNIVERSE_VERSION)
  const observed = timestamp(payload.observedAt)
  requireValid(payload.marketDate === new Date(observed.millis + 8 * 3600000).toISOString().slice(0, 10) &&
    ['intraday', 'close'].includes(payload.session))
  requireValid(record(payload.global) && payload.global.id === 'global' && record(payload.aShare) && payload.aShare.id === 'a-share' &&
    exactIdentities(payload.styles, STYLE_IDS) && exactIdentities(payload.industries, INDUSTRY_IDS))
  for (const obj of [payload.global, payload.aShare, ...payload.styles]) validateLegacyObject(obj)
  const block = payload.sectorRotation
  requireValid(shape(block, ['sectorScoringVersion', 'sectorUniverseVersion', 'observedAt', 'marketDate', 'session',
    'officialClose', 'industries', 'concepts', 'componentEncoding', 'componentFields', 'componentPartNames',
    'componentNodes', 'missingReasons', 'auditDefinitions', 'releaseEligible', 'safeCodes']))
  requireValid(block.sectorScoringVersion === SECTOR_SCORING_VERSION && block.sectorUniverseVersion === SECTOR_UNIVERSE_VERSION &&
    sameInstant(block.observedAt, payload.observedAt) && block.marketDate === payload.marketDate && block.session === payload.session &&
    block.officialClose === (payload.session === 'close') && typeof block.releaseEligible === 'boolean' && strings(block.safeCodes) &&
    exactIdentities(block.industries, INDUSTRY_IDS) && exactIdentities(block.concepts, ROTATION_CONCEPT_IDS) && safeDerivedTree(payload))
  validateAuditDefinitions(block.auditDefinitions)
  const decode = decodeAudit(block)
  const sectors = [
    ...block.industries.map(row => validateRotationRow(row, 'industry', INDUSTRY_IDS, block, decode)),
    ...block.concepts.map(row => validateRotationRow(row, 'concept', ROTATION_CONCEPT_IDS, block, decode)),
  ]
  requireValid(shape(payload.concepts, ['selectionVersion', 'scoringVersion', 'selectedAt', 'core', 'dynamic', 'selectionScoringVersion']) &&
    payload.concepts.selectionVersion === CONCEPT_SELECTION_VERSION && payload.concepts.scoringVersion === SECTOR_SCORING_VERSION &&
    payload.concepts.selectionScoringVersion === CONCEPT_SCORING_VERSION && timestamp(payload.concepts.selectedAt).millis <= observed.millis &&
    Array.isArray(payload.concepts.core) && payload.concepts.core.length === 25 &&
    Array.isArray(payload.concepts.dynamic) && payload.concepts.dynamic.length === 10)
  requireValid(exactIdentities(payload.concepts.core, ROTATION_CONCEPT_IDS.slice(0, 25)))
  const dynamicIds = payload.concepts.dynamic.map(row => row.id)
  requireValid(new Set(dynamicIds).size === 10 && dynamicIds.every(id => ROTATION_CONCEPT_IDS.includes(id)) &&
    !dynamicIds.some(id => ROTATION_CONCEPT_IDS.slice(0, 25).includes(id)))
  const projected = new Map(sectors.map(row => [row.id, row]))
  const projectionFields = ['id', 'name', 'universe', 'observedAt', 'strength', 'opportunity', 'risk', 'heatState',
    'axisCompleteness', 'completeness', 'coldStart', 'validCloses', 'improvementEvidence', 'ranks', 'leaderboard', 'officialClose']
  for (const row of [...payload.industries, ...payload.concepts.core]) {
    const full = projected.get(row.id)
    requireValid(shape(row, projectionFields) && full && Object.entries(row).every(([key, value]) =>
      JSON.stringify(value) === JSON.stringify(full[key])))
  }
  for (const row of payload.concepts.dynamic) {
    const full = projected.get(row.id)
    requireValid(shape(row, [...projectionFields, 'selectionScore', 'selectedOn', 'retainedTradingDays']) && full &&
      projectionFields.every(key => JSON.stringify(row[key]) === JSON.stringify(full[key])))
    requireValid(numeric(row.selectionScore) && typeof row.selectedOn === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(row.selectedOn) &&
      integer(row.retainedTradingDays, 1, 1000000))
  }
  requireValid(shape(payload.dataStatus, ['completeness', 'stale', 'missing']) && integer(payload.dataStatus.completeness, 1, 100) &&
    typeof payload.dataStatus.stale === 'boolean' && strings(payload.dataStatus.missing) &&
    payload.dataStatus.completeness === Math.floor([payload.global, payload.aShare, ...payload.styles, ...sectors]
      .reduce((sum, obj) => sum + obj.completeness, 0) / (8 + sectors.length) + .5))
  requireValid(new TextEncoder().encode(JSON.stringify(payload)).byteLength <= MAX_BODY_BYTES)
  if (Object.hasOwn(payload, 'sourceMode')) validateSourceMode(payload.sourceMode)
  return { ...observed, sectors }
}

export function validatePayload(payload) {
  if (record(payload) && payload.schemaVersion === ROTATION_SCHEMA_VERSION) return validateRotationPayload(payload)
  return validateV2Payload(payload)
}

export function decodeSectorRows(payload) {
  const validated = validateRotationPayload(payload)
  return validated.sectors
}

export function validSectorIdentity(universe, id) {
  return universe === 'industry' ? INDUSTRY_IDS.includes(id) : universe === 'concept' ? ROTATION_CONCEPT_IDS.includes(id) : false
}

function storedJson(value) {
  const parsed = JSON.parse(value)
  requireValid(safeDerivedTree(parsed))
  return parsed
}

export function publicSectorRow(row, audit = false) {
  requireValid(record(row) && validSectorIdentity(row.universe, row.sector_id) &&
    row.scoring_version === SECTOR_SCORING_VERSION && row.universe_version === SECTOR_UNIVERSE_VERSION)
  const maximumRank = row.universe === 'industry' ? 35 : 75
  requireValid(['strength', 'opportunity', 'risk'].every(axis => row[axis] === null || integer(row[axis], 0, 100)) &&
    integer(row.completeness, 0, 100) && ['strength_rank', 'opportunity_rank', 'risk_rank']
      .every(key => row[key] === null || integer(row[key], 1, maximumRank)))
  const ranks = { strength: row.strength_rank, opportunity: row.opportunity_rank, risk: row.risk_rank }
  const leaderboard = storedJson(row.leaderboard_json)
  requireValid(shape(leaderboard, ['strength', 'opportunity']))
  for (const axis of ['strength', 'opportunity']) {
    const board = leaderboard[axis]
    requireValid(shape(board, ['axis', 'topTenStreak', 'topTenCount15d', 'rankChange']) && board.axis === axis &&
      integer(board.topTenStreak, 0, 1000000) && integer(board.topTenCount15d, 0, 15) &&
      (board.rankChange === null || integer(board.rankChange, -74, 74)))
  }
  const result = { id: row.sector_id, name: row.sector_name, strength: row.strength,
    opportunity: row.opportunity, risk: row.risk, heatState: row.heat_state, completeness: row.completeness,
    coldStart: Boolean(row.cold_start), ranks, leaderboard }
  if (!audit) return result
  const components = storedJson(row.components_json), missing = storedJson(row.missing_json)
  const contributors = storedJson(row.contributors_json), provenance = storedJson(row.provenance_json)
  requireValid(record(components) && Object.keys(components).length > 0 && strings(missing) && Array.isArray(contributors) &&
    contributors.every(item => shape(item, ['axis', 'component', 'value', 'weight', 'impact']) &&
      ['strength', 'opportunity', 'risk'].includes(item.axis) && typeof item.component === 'string' &&
      [item.value, item.weight, item.impact].every(value => typeof value === 'number' && Number.isFinite(value))) &&
    shape(provenance, ['source', 'observedAt', 'marketDate', 'session', 'officialClose', 'sectorScoringVersion', 'sectorUniverseVersion']) &&
    provenance.source === 'Wind' && provenance.marketDate === row.market_date &&
    provenance.session === row.session && provenance.officialClose === Boolean(row.official_close) &&
    provenance.sectorScoringVersion === row.scoring_version && provenance.sectorUniverseVersion === row.universe_version)
  validateSectorSourceTime(provenance.observedAt, row.observed_at, row.market_date, Boolean(row.official_close))
  return { ...result, observedAt: row.observed_at, marketDate: row.market_date, session: row.session,
    officialClose: Boolean(row.official_close), components, missing, contributors, provenance, scoringVersion: row.scoring_version,
    universeVersion: row.universe_version }
}

export async function authorized(request, token) {
  const authorization = request.headers.get('Authorization') || ''
  const match = /^Bearer ([^\s]+)$/i.exec(authorization)
  if (!match) return false
  // Compare fixed-length SHA-256 digests. Workers supports timingSafeEqual;
  // other Web Crypto runtimes use the same fixed 32-iteration comparison.
  const encoder = new TextEncoder()
  const [supplied, expected] = await Promise.all([match[1], token].map(value => crypto.subtle.digest('SHA-256', encoder.encode(value))))
  if (typeof crypto.subtle.timingSafeEqual === 'function') return crypto.subtle.timingSafeEqual(supplied, expected)
  const left = new Uint8Array(supplied), right = new Uint8Array(expected)
  let difference = 0
  for (let i = 0; i < 32; i++) difference |= left[i] ^ right[i]
  return difference === 0
}

export async function readBoundedJson(request) {
  const reader = request.body?.getReader()
  if (!reader) throw new Error('INVALID_JSON')
  let length = 0
  const chunks = []
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      length += value.byteLength
      if (length > MAX_BODY_BYTES) {
        await reader.cancel().catch(() => {})
        throw new Error('PAYLOAD_TOO_LARGE')
      }
      chunks.push(value)
    }
  } finally { reader.releaseLock() }
  const bytes = new Uint8Array(length)
  let offset = 0
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength }
  try { return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) }
  catch { throw new Error('INVALID_JSON') }
}

export function storedPayload(row) {
  const payload = JSON.parse(row.payload_json)
  validatePayload(payload)
  return payload
}
export function compactSnapshot(row) {
  const payload = storedPayload(row)
  if (payload.schemaVersion === ROTATION_SCHEMA_VERSION) {
    const compact = obj => ({ id: obj.id, strength: obj.strength, opportunity: obj.opportunity,
      risk: obj.risk, heatState: obj.heatState, completeness: obj.completeness, ranks: obj.ranks })
    return { observedAt: timestamp(payload.observedAt).utc, marketDate: payload.marketDate, session: payload.session,
      schemaVersion: payload.schemaVersion, scoringVersion: payload.scoringVersion,
      sectorScoringVersion: payload.sectorScoringVersion, sectorUniverseVersion: payload.sectorUniverseVersion,
      global: { id: payload.global.id, strength: payload.global.strength, heat: payload.global.heat,
        risk: payload.global.risk, completeness: payload.global.completeness },
      aShare: { id: payload.aShare.id, strength: payload.aShare.strength, heat: payload.aShare.heat,
        risk: payload.aShare.risk, completeness: payload.aShare.completeness },
      styles: payload.styles.map(obj => ({ id: obj.id, strength: obj.strength, heat: obj.heat,
        risk: obj.risk, completeness: obj.completeness })), industries: payload.industries.map(compact),
      concepts: { selectionVersion: payload.concepts.selectionVersion, scoringVersion: payload.concepts.scoringVersion,
        selectionScoringVersion: payload.concepts.selectionScoringVersion, selectedAt: payload.concepts.selectedAt,
        core: payload.concepts.core.map(compact), dynamic: payload.concepts.dynamic.map(compact) } }
  }
  const compact = obj => ({ id: obj.id, strength: obj.strength, heat: obj.heat, risk: obj.risk, completeness: obj.completeness })
  return {
    observedAt: row.observed_at, marketDate: payload.marketDate, session: payload.session,
    scoringVersion: payload.scoringVersion, global: compact(payload.global), aShare: compact(payload.aShare),
    styles: payload.styles.map(compact), industries: payload.industries.map(compact),
    concepts: { selectionVersion: payload.concepts.selectionVersion,
      scoringVersion: payload.concepts.scoringVersion, selectedAt: payload.concepts.selectedAt,
      core: payload.concepts.core.map(compact), dynamic: payload.concepts.dynamic.map(compact) },
  }
}
