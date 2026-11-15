// Synthetic derived scores only: fixed formulas, no captured observations or provider responses.
// The real public identities and contract version definitions are retained for strict validation.
import { compactSnapshot, decodeSectorRows } from '../../../functions/_lib/market-dashboard.js'
import config from '../../../config/market-dashboard.json' with { type: 'json' }

export const acceptanceDates = Object.freeze([
  '2026-10-26', '2026-10-27', '2026-10-28', '2026-10-29', '2026-10-30',
  '2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06',
  '2026-11-09', '2026-11-10', '2026-11-11', '2026-11-12', '2026-11-13',
])
const industryIds = Array.from({ length: 37 }, (_, i) => i + 100).filter(i => i !== 117 && i !== 118).map(i => `882${i}.WI`)
const conceptIds = [
  '884201.WI','8841678.WI','8841889.WI','884091.WI','8841665.WI','8841349.WI','8841337.WI','8841294.WI','8841237.WI','8841256.WI',
  '8841699.WI','884766.WI','8841635.WI','8841750.WI','8841739.WI','8841671.WI','884790.WI','884114.WI','884190.WI','884086.WI',
  '8841877.WI','8841875.WI','8841049.WI','8841718.WI','884142.WI','8841935.WI','8841339.WI','8841259.WI','8841018.WI','8841180.WI',
  '8841179.WI','884155.WI','884969.WI','8841890.WI','884087.WI','8841648.WI','8841006.WI','884041.WI','8841327.WI','8841340.WI',
  '884099.WI','8841087.WI','884108.WI','884133.WI','8841362.WI','8841282.WI','8841593.WI','8841192.WI','8841636.WI','8841911.WI',
  '8841260.WI','8841741.WI','8841407.WI','8841398.WI','884213.WI','8841960.WI','884131.WI','8841249.WI','8841350.WI','8841284.WI',
  '8841959.WI','884959.WI','8841432.WI','884225.WI','884821.WI','884028.WI','8841041.WI','8841442.WI','8841372.WI','884203.WI',
  '884143.WI','8841272.WI','884247.WI','8841225.WI','8841201.WI',
]
const styleIds = ['000300.SH', '000852.SH', 'H30356.CSI', '399006.SZ', '000922.CSI', '000688.SH']
const axes = ['strength', 'opportunity', 'risk']
const versions = { scoringVersion: 'sector-score-v0.2', universeVersion: 'sector-universe-v0.1' }
const componentFields = ['value', 'coverage', 'missing', 'usedWeight', 'totalWeight', 'effectiveWeight', 'percentile', 'parts']
const componentParts = {
  priceTrend: ['return1d','return5d','return20d'], funding: ['flow1d','flow5d','flow20d'],
  activity: ['turnover','marketShare','concentration','acceleration'], persistence: ['meanPercentile','topTenStreak'],
  position: ['position60d','position250d'], fundsImprovement: ['historical20d','delta5d'],
  breadthImprovement: ['delta5d','improvingDays'], momentumImprovement: ['shortAcceleration','mediumAcceleration'],
  activityWarming: ['current','delta5d'], downsideDiffusion: ['current','delta5d'],
  fundsWithdrawal: ['funding','delta5d'], trendDeterioration: ['return5d','return20d','slope5d'], crowding: ['activity','acceleration'],
}
const componentNames = [...Object.keys(componentParts), 'breadth', 'concentration', 'activityMean5d', 'divergence']
const partNames = [...new Set(Object.values(componentParts).flat())].sort()
const at = date => `${date}T07:00:00Z`
const observation = date => ({ observedAt: at(date), marketDate: date, session: 'close' })
const pick = (row, keys) => Object.fromEntries(keys.map(key => [key, row[key]]))
const publicKeys = ['id', 'name', ...axes, 'heatState', 'completeness', 'coldStart', 'ranks', 'leaderboard']
function legacy(id, i, date) {
  return { id, name: `测试对象 ${i + 1}`, strength: 55 + i % 20, heat: 45 + i % 30, risk: 20 + i % 25,
    completeness: 100, missing: [], contributors: [{ label: '合成测试因子', impact: 10 }],
    sourceTimestamps: [{ source: 'Derived', timestamp: at(date) }], change1d: null, change5d: null }
}
function component(name, value) {
  const leaf = { value, coverage: 1, missing: [] }
  if (!componentParts[name]) return leaf
  return { ...leaf, usedWeight: 100, totalWeight: 100, effectiveWeight: 100,
    parts: Object.fromEntries(componentParts[name].map(part => [part, component(name === 'activityWarming' && part === 'current' ? 'activity'
      : ['activity', 'funding'].includes(part) ? part : null, value)])) }
}
function syntheticRows(ids, universe, day) {
  const rows = ids.map((id, i) => {
    const strength = 48 + (i * 7 + day) % 45, opportunity = i === ids.length - 1 ? null : 72 + (i + day) % 20
    const risk = 20 + (i * 5 + day) % 75
    const components = Object.fromEntries(componentNames.map(name => {
      const axis = axes.find(axis => Object.hasOwn(config.sectorScoring.weights[axis], name))
      return [name, component(name, axis === 'opportunity' ? opportunity : axis === 'risk' ? risk : strength)]
    }))
    return { id, name: `测试${universe === 'industry' ? '行业' : '概念'} ${String(i + 1).padStart(2, '0')}`, universe,
      observedAt: at(acceptanceDates[day]), strength, opportunity, risk,
      heatState: risk >= 80 ? 'crowded' : i % 3 === 0 ? 'warming' : 'active',
      axisCompleteness: { strength: 100, opportunity: opportunity === null ? 0 : 100, risk: 100 },
      completeness: opportunity === null ? 80 : 100, coldStart: opportunity === null,
      validCloses: opportunity === null ? 15 : 60, improvementEvidence: opportunity === null ? 0 : 3,
      ranks: {}, leaderboard: {}, officialClose: true, components, missing: [] }
  })
  for (const axis of axes) {
    const ordered = rows.filter(row => row[axis] !== null).sort((a, b) => b[axis] - a[axis] || a.id.localeCompare(b.id))
    rows.forEach(row => { row.ranks[axis] = row[axis] === null ? null : ordered.indexOf(row) + 1 })
  }
  rows.forEach(row => {
    for (const axis of ['strength', 'opportunity']) row.leaderboard[axis] = { axis,
      topTenStreak: 0, topTenCount15d: 0, rankChange: null }
  })
  return rows
}
function makeV3(date, day) {
  const industries = syntheticRows(industryIds, 'industry', day), concepts = syntheticRows(conceptIds, 'concept', day)
  const nodes = [], nodeIndex = new Map()
  const encode = value => {
    let mask = 0
    const values = []
    componentFields.forEach((field, bit) => {
      if (!Object.hasOwn(value, field)) return
      mask |= 1 << bit
      values.push(field === 'parts' ? Object.entries(value.parts).map(([key, child]) => [partNames.indexOf(key), encode(child)]) : value[field])
    })
    const node = [mask, ...values], key = JSON.stringify(node)
    if (!nodeIndex.has(key)) { nodeIndex.set(key, nodes.length); nodes.push(node) }
    return nodeIndex.get(key)
  }
  const encodeRow = row => ({ ...row, components: Object.fromEntries(Object.entries(row.components).map(([name, value]) => [name, encode(value)])) })
  const project = row => { const { components, missing, ...rest } = row; return rest }
  const all = [...industries, ...concepts]
  const globals = [legacy('global', 0, date), legacy('a-share', 1, date), ...styleIds.map((id, i) => legacy(id, i + 2, date))]
  const settings = config.sectorScoring
  return { ...observation(date), schemaVersion: 'market-dashboard-v3', scoringVersion: 'market-score-v0.1',
    sectorScoringVersion: versions.scoringVersion, sectorUniverseVersion: versions.universeVersion,
    global: globals[0], aShare: globals[1], styles: globals.slice(2), industries: industries.map(project),
    concepts: { selectionVersion: 'concept-selection-v0.1', scoringVersion: versions.scoringVersion,
      selectionScoringVersion: 'concept-score-v0.1', selectedAt: at(date), core: concepts.slice(0, 25).map(project),
      dynamic: concepts.slice(25, 35).map(row => ({ ...project(row), selectionScore: 80, selectedOn: date, retainedTradingDays: 1 })) },
    dataStatus: { completeness: Math.round([...globals, ...all].reduce((sum, row) => sum + row.completeness, 0) / 118), stale: false, missing: [] },
    sectorRotation: { sectorScoringVersion: versions.scoringVersion, sectorUniverseVersion: versions.universeVersion,
      ...observation(date), officialClose: true, industries: industries.map(encodeRow), concepts: concepts.map(encodeRow),
      componentEncoding: 'node-mask-v1', componentFields, componentPartNames: partNames, componentNodes: nodes, missingReasons: [],
      auditDefinitions: { weights: settings.weights, componentWeights: settings.componentWeights, gates: settings.gates, heat: settings.heat },
      releaseEligible: false, safeCodes: [] } }
}
function makeV2(date, day) {
  const global = legacy('global', day, date), aShare = legacy('a-share', day + 1, date)
  return { ...observation(date), schemaVersion: 'market-dashboard-v2', scoringVersion: 'market-score-v0.1', global, aShare,
    styles: styleIds.map((id, i) => legacy(id, i + day, date)), industries: industryIds.map((id, i) => legacy(id, i + day, date)),
    concepts: { selectionVersion: 'concept-selection-v0.1', scoringVersion: 'concept-score-v0.1', selectedAt: at(date),
      core: conceptIds.slice(0, 25).map((id, i) => legacy(id, i + day, date)),
      dynamic: conceptIds.slice(25, 35).map((id, i) => ({ ...legacy(id, i + day, date), selectionScore: 80, selectedOn: date, retainedTradingDays: 1 })) },
    dataStatus: { completeness: 100, stale: false, missing: [] } }
}
// Lazy construction keeps ordinary builds free of fixture work; each response is serialized afresh.
let cache
function fixtures() {
  if (!cache) {
    cache = acceptanceDates.map((date, day) => {
      const v3 = makeV3(date, day)
      return { v3, v2: makeV2(date, day), rows: decodeSectorRows(v3) }
    })
    // Leaderboard objects are shared by the encoded, projected and decoded rows.
    // Derive counts from the supplied dates instead of inventing unavailable closes.
    const points = cache.map(item => new Map(item.rows.map(row => [row.id, row])))
    cache.forEach((item, day) => item.rows.forEach(row => {
      for (const axis of ['strength', 'opportunity']) {
        const ranks = points.slice(Math.max(0, day - 14), day + 1).map(point => point.get(row.id).ranks[axis])
        const inTopTen = rank => rank !== null && rank <= 10
        let streak = 0
        for (const rank of ranks.slice().reverse()) { if (!inTopTen(rank)) break; streak++ }
        const previous = day ? points[day - 1].get(row.id).ranks[axis] : null
        Object.assign(row.leaderboard[axis], { topTenStreak: streak, topTenCount15d: ranks.filter(inTopTen).length,
          rankChange: previous === null || row.ranks[axis] === null ? null : previous - row.ranks[axis] })
      }
    }))
  }
  return cache
}
export function dashboardFixture(schemaVersion, window) {
  const key = schemaVersion === 'market-dashboard-v3' ? 'v3' : 'v2'
  if (!window) return fixtures().at(-1)[key]
  const count = { '1d': 1, '5d': 5, '20d': 15, '90d': 15 }[window]
  return { window, snapshots: fixtures().slice(-count).map(item => compactSnapshot({ payload_json: JSON.stringify(item[key]), observed_at: item[key].observedAt })) }
}
function publicRow(row) { return pick(row, publicKeys) }
export function rotationFixture(endpoint, query) {
  const { universe, view, axis, id, days } = query
  const current = fixtures().at(-1), rows = current.rows.filter(row => row.universe === universe)
  if (endpoint === 'latest') {
    const previous = new Map(fixtures().at(-2).rows.map(row => [row.id, row]))
    const sectors = rows.map(row => ({ ...publicRow(row), change1d: Object.fromEntries(axes.map(axis => [axis,
      row[axis] === null || previous.get(row.id)[axis] === null ? null : row[axis] - previous.get(row.id)[axis]])) }))
      .filter(row => view === 'potential' ? row.opportunity !== null && row.opportunity >= 70 && row.strength < 70 && row.risk < 70 && row.heatState !== 'crowded'
        : view === 'main' ? row.strength >= 70 && row.risk < 70 : row.risk >= 70 || row.change1d.risk >= 10 || row.heatState === 'crowded')
      .sort((a, b) => {
        const order = view === 'potential' ? ['opportunity'] : view === 'main' ? ['strength', 'opportunity'] : ['risk']
        for (const key of order) { const delta = (b[key] ?? -1) - (a[key] ?? -1); if (delta) return delta }
        return a.id.localeCompare(b.id)
      })
    return { ...observation(acceptanceDates.at(-1)), ...versions, universe, view, sectors }
  }
  const supplied = fixtures().slice(-days)
  if (endpoint === 'history') return { ...versions, universe, axis, days, dates: supplied.map(item => item.v3.marketDate),
    rows: rows.map(row => ({ id: row.id, name: row.name, values: supplied.map(item => {
      const point = item.rows.find(candidate => candidate.id === row.id)
      return { marketDate: item.v3.marketDate, score: point[axis], rank: point.ranks[axis] }
    }) })) }
  return { ...versions, universe, id, days, history: supplied.map(item => {
    const row = item.rows.find(row => row.id === id)
    return { ...publicRow(row), ...observation(item.v3.marketDate), ...versions, officialClose: true,
      components: row.components, missing: row.missing,
      contributors: [{ axis: 'strength', component: 'priceTrend', value: row.strength, weight: 30, impact: row.strength * .3 }],
      // Wind is the required schema enum, not a claim about this synthetic fixture's origin.
      provenance: { source: 'Wind', ...observation(item.v3.marketDate), officialClose: true,
        sectorScoringVersion: versions.scoringVersion, sectorUniverseVersion: versions.universeVersion } }
  }) }
}
