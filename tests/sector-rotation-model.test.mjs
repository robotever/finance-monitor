import test from 'node:test'
import assert from 'node:assert/strict'
import * as model from '../src/features/market-dashboard/model.mjs'
const versions = { scoringVersion: 'sector-score-v0.2', universeVersion: 'sector-universe-v0.1' }
const board = (axis, streak, count) => ({ axis, topTenStreak: streak, topTenCount15d: count, rankChange: 2 })
const sector = (id, fields = {}) => ({ id, name: id, strength: 60, opportunity: 80, risk: 30, heatState: 'warming',
  completeness: 80, coldStart: true, ranks: { strength: 12, opportunity: 2, risk: 20 },
  leaderboard: { strength: board('strength', 2, 4), opportunity: board('opportunity', 5, 9) },
  change1d: { strength: 3, opportunity: null, risk: 0 }, ...fields })
const latest = (sectors, view = 'potential') => ({ ...versions, observedAt: '2026-11-13T02:15:00Z', marketDate: '2026-11-13',
  session: 'intraday', universe: 'industry', view, sectors })
const history = () => ({ ...versions, universe: 'industry', axis: 'strength', days: 15,
  dates: ['2026-11-11', '2026-11-12', '2026-11-13'], rows: [
    { id: '882100.WI', name: '行业甲', values: [{ marketDate: '2026-11-11', score: 80, rank: 1 },
      { marketDate: '2026-11-12', score: null, rank: null }, { marketDate: '2026-11-13', score: 70, rank: 2 }] },
    { id: '882101.WI', name: '行业乙', values: [{ marketDate: '2026-11-11', score: 70, rank: 2 },
      { marketDate: '2026-11-12', score: 90, rank: 1 }, { marketDate: '2026-11-13', score: 90, rank: 1 }] }] })
const derive = (...args) => {
  assert.equal(typeof model.deriveSectorRotationView, 'function', 'sector rotation view model must be exported')
  return model.deriveSectorRotationView(...args)
}
const now = new Date('2026-11-13T02:20:00Z')

test('rotation membership respects nullable opportunity, exact boundaries and independent risk triggers', () => {
  const rows = [sector('a'), sector('b', { strength: 70 }), sector('c', { opportunity: null }),
    sector('d', { completeness: 69 }), sector('e', { heatState: 'crowded' }),
    sector('f', { risk: 70 }), sector('g', { opportunity: null, change1d: { strength: null, opportunity: null, risk: 10 } })]
  const view = derive(latest(rows), null, { now })
  assert.deepEqual(view.potential.map(row => row.id), ['a'])
  assert.deepEqual(view.main.map(row => row.id), ['b'])
  assert.deepEqual(view.risk.map(row => row.id), ['f', 'g', 'e'])
  // Missing opportunity never becomes an inferred or substituted opportunity.
  assert.equal(view.potential.some(row => row.id === 'g'), false)
})

test('derived lists sort explicit axes with null last and stable ids while selected list retains server order', () => {
  const rows = [sector('c', { opportunity: 79 }), sector('b'), sector('a'),
    sector('m', { strength: 70, opportunity: null }), sector('n', { strength: 70, opportunity: 60 }),
    sector('r', { risk: 70 }), sector('q', { risk: 70, change1d: { strength: null, opportunity: null, risk: 10 } }),
    sector('x', { heatState: 'crowded', opportunity: null })]
  const view = derive(latest(rows), history(), { now })
  assert.deepEqual(view.potential.map(row => row.id), ['c', 'b', 'a'])
  assert.deepEqual(view.main.map(row => row.id), ['n', 'm'])
  assert.deepEqual(view.risk.map(row => row.id), ['q', 'r', 'x'])
  assert.equal(view.risk.at(-1).opportunity, null)
  for (const list of [view.potential, view.main, view.risk]) for (const row of list) {
    assert.equal(Object.hasOwn(row, 'compositeScore'), false)
    assert.equal(Object.hasOwn(row, 'heat'), false)
  }
})

test('three compact endpoint lists retain authoritative unrounded tie order', () => {
  const p = latest([sector('b'), sector('a')])
  const main = latest([sector('n', { strength: 70 }), sector('m', { strength: 70 })], 'main')
  const risk = latest([sector('r', { risk: 70 })], 'risk')
  const view = derive({ potential: p, main, risk }, null, { now })
  assert.deepEqual(view.potential.map(row => row.id), ['b', 'a'])
  assert.deepEqual(view.main.map(row => row.id), ['n', 'm'])
  assert.deepEqual(view.risk.map(row => row.id), ['r'])
})

test('axis specific official-close streaks remain separate from intraday view membership and cold evidence labels', () => {
  const view = derive(latest([sector('a'), sector('b', { completeness: 69, coldStart: false, heatState: null })]), history(), { now })
  const row = view.rows.find(row => row.id === 'a')
  assert.equal(row.leaderboardLabels.strength, '强度榜（正式收盘）连续2日 · 近15日4次')
  assert.equal(row.leaderboardLabels.opportunity, '机会榜（正式收盘）连续5日 · 近15日9次')
  assert.equal(row.coldStartLabel, '冷启动')
  assert.equal(row.heatStateLabel, '升温')
  assert.equal(row.evidenceLabel, '证据充分')
  assert.equal(view.rows.find(row => row.id === 'b').evidenceLabel, '证据不足')
  assert.equal(view.rows.find(row => row.id === 'b').heatStateLabel, '暂无数据')
  assert.equal(row.leaderboard.opportunity.topTenStreak, 5)
  assert.equal(view.sessionLabel, '盘中观察')
})

test('rank-by-date matrix keeps missing cells null and never carries prior scores or invents returns', () => {
  const view = derive(latest([]), history(), { now, topN: 2 })
  assert.deepEqual(view.matrix.dates, ['2026-11-11', '2026-11-12', '2026-11-13'])
  assert.equal(view.matrix.axisLabel, '强度榜')
  assert.equal(view.matrix.insufficientHistory, true)
  assert.deepEqual(view.matrix.rows[0].cells.map(cell => cell?.id ?? null), ['882100.WI', '882101.WI', '882101.WI'])
  assert.deepEqual(view.matrix.rows[1].cells.map(cell => cell?.id ?? null), ['882101.WI', null, '882100.WI'])
  assert.equal(view.matrix.rows[0].cells[0].change1d, null)
  assert.equal(view.matrix.rows[0].cells[0].dailyReturn, null)
})

test('matrix takes the last 15 supplied official dates and never fills missing trading dates', () => {
  const h = history(); h.dates = Array.from({ length: 17 }, (_, i) => `2026-10-${String(i + 1).padStart(2, '0')}`)
  h.rows = [{ id: 'a', name: '甲', values: h.dates.map(marketDate => ({ marketDate, score: 80, rank: 1 })) }]
  const matrix = derive(latest([]), h, { now }).matrix
  assert.equal(matrix.dates.length, 15); assert.equal(matrix.dates[0], '2026-10-03')
  assert.equal(matrix.rows.length, 10); assert.equal(matrix.insufficientHistory, false)
})

test('rotation freshness distinguishes stale transport, missing close and confirmed close', () => {
  const p = latest([]), evening = new Date('2026-11-13T12:00:00Z')
  assert.equal(derive(p, null, { now: new Date('2026-11-13T02:46:00Z') }).freshness.stale, true)
  assert.equal(derive(p, null, { now: evening }).freshness.label, '缺少收盘确认')
  const close = { ...p, observedAt: '2026-11-13T07:00:00Z', session: 'close' }
  assert.equal(derive(close, null, { now: evening }).freshness.stale, false)
  assert.equal(derive(close, null, { now: evening }).sessionLabel, '正式收盘')
  assert.equal(derive(close, null, { now: evening, stale: true }).freshness.stale, true)
})

test('detail presents only available observations and derived audits without modifying frozen API input', () => {
  const p = latest([sector('882100.WI')]), h = history()
  const detail = { ...versions, universe: 'industry', id: '882100.WI', days: 60, history: [
    { ...sector('882100.WI'), ...versions, observedAt: '2026-11-11T07:00:00Z', marketDate: '2026-11-11', session: 'close',
      officialClose: true, components: { priceTrend: { value: 60, coverage: 1, missing: [] } }, missing: ['position250d'],
      contributors: [], provenance: { source: 'Wind', observedAt: '2026-11-11T07:00:00Z' } }] }
  const before = structuredClone({ p, h, detail })
  const freeze = value => { if (value && typeof value === 'object') { Object.freeze(value); Object.values(value).forEach(freeze) } }
  freeze(p); freeze(h); freeze(detail)
  const view = derive(p, h, { now, detail })
  assert.equal(view.detail.series.length, 1)
  assert.equal(view.detail.series[0].opportunity, 80)
  assert.deepEqual(view.detail.audit.missing, ['position250d'])
  assert.equal(view.detail.axisLabels.opportunity, '机会')
  assert.deepEqual({ p, h, detail }, before)
  view.detail.audit.components.priceTrend.value = 0
  assert.equal(detail.history[0].components.priceTrend.value, 60)
})

test('rotation refuses cross-universe, cross-version and mixed observation bundles', () => {
  assert.equal(typeof model.deriveSectorRotationView, 'function')
  const primary = latest([sector('a')]), other = latest([sector('b')], 'main')
  for (const key of ['universe', 'scoringVersion', 'universeVersion', 'observedAt', 'marketDate', 'session']) {
    const mismatch = { ...other, [key]: 'incompatible' }
    assert.throws(() => derive({ potential: primary, main: mismatch }, null, { now }), /observation|version/)
  }
  assert.throws(() => derive(primary, { ...history(), universe: 'concept' }, { now }), /mismatch/)
  assert.throws(() => derive(primary, null, { now, detail: { universe: 'concept' } }), /mismatch/)
  assert.throws(() => derive({}, null, { now }), /required/)
})

test('view marks only supplied endpoint lists complete so partial requests cannot imply full coverage', () => {
  assert.deepEqual(derive(latest([sector('a')]), null, { now }).completeViews, ['potential'])
  const p = latest([]), main = latest([], 'main'), risk = latest([], 'risk')
  assert.deepEqual(derive({ potential: p, main, risk }, null, { now }).completeViews, ['potential', 'main', 'risk'])
})
