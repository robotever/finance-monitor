import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { createServer } from 'vite'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { deriveMarketDashboardView } from '../src/features/market-dashboard/model.mjs'

let server
before(async () => { server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false, watch: null }, appType: 'custom' }) })
after(async () => { await server?.close() })
async function render(name, props) {
  assert.ok(existsSync(new URL(`../src/components/${name}.vue`, import.meta.url)), `${name} must exist`)
  const module = await server.ssrLoadModule(`/src/components/${name}.vue`)
  return renderToString(createSSRApp({ render: () => h(module.default, props) }))
}
const observed = '2026-11-13T02:15:00Z'
const object = (id, fields = {}) => ({ id, name: id, strength: 63, heat: 78, risk: 24,
  completeness: 80, missing: [], contributors: [], sourceTimestamps: [{ source: 'Wind', timestamp: observed }],
  change1d: null, change5d: null, ...fields })
function view(fields = {}) {
  return deriveMarketDashboardView({ schemaVersion: 'market-dashboard-v2', scoringVersion: 'market-score-v0.1',
    observedAt: observed, marketDate: '2026-11-13', session: 'intraday', global: object('global'), aShare: object('a-share'),
    styles: [], industries: [], concepts: { selectionVersion: 'concept-selection-v0.1',
      scoringVersion: 'concept-score-v0.1', selectedAt: observed, core: [], dynamic: [] },
    dataStatus: { completeness: 80, stale: false, missing: [] }, ...fields }, new Date(observed))
}
test('score card preserves null, missing evidence and stale/comparison disclosures', async () => {
  const item = view({ global: object('global', { strength: null, completeness: 49, missing: ['成交广度'],
    contributors: [{ label: '已提供因素', impact: -3, evidence: '已提供证据' }], comparisonFallback: 'close',
    change5d: { strength: null, heat: 0, risk: -2 } }), dataStatus: { completeness: 49, stale: true, missing: [] } }).global
  const html = await render('MarketScoreCard', { item, title: '全局环境', observedAt: observed })
  for (const text of ['—', '证据不足', '数据滞后', '成交广度', '已提供因素', '已提供证据', '收盘回退', '暂无可比快照']) assert.ok(html.includes(text), text)
  assert.match(html, /class="market-badge is-stale">数据滞后<\/span>/)
  assert.match(html, /class="market-badge is-missing">完整度 49%/)
  assert.ok(!html.includes('扩张'))
  assert.match(html, /<details/)
  assert.match(html, /datetime="2026-11-13T02:15:00Z"/)
})
test('score card renders loading and honest unavailable state without scores', async () => {
  assert.match(await render('MarketScoreCard', { loading: true, title: '全局环境' }), /加载/)
  const html = await render('MarketScoreCard', { title: '全局环境', error: '暂无有效快照' })
  assert.match(html, /暂无有效快照/)
  assert.ok(!html.includes('market-score__number'))
})
test('style grid uses six fixed design identities regardless of server array order', async () => {
  const ids = ['000300.SH', '000852.SH', 'H30356.CSI', '399006.SZ', '000922.CSI', '000688.SH']
  const items = view({ styles: ids.toReversed().map(id => object(id)) }).styles
  const html = await render('MarketStyleGrid', { items, observedAt: observed })
  const positions = ['大盘', '小盘', '价值', '成长', '红利', '科技'].map(label => html.indexOf(label))
  assert.ok(positions.every((position, i) => position >= 0 && (i === 0 || position > positions[i - 1])))
  assert.match(html, /5日/)
  assert.equal((html.match(/data-score-object=/g) ?? []).length, 6)
})
test('industry panorama renders all 35 accessible expansions and four truthful rankings', async () => {
  const dashboard = view({ industries: Array.from({ length: 35 }, (_, i) => object(`industry-${i}`, { name: `行业${i}`, change5d: null })), dataStatus: { completeness: 80, stale: true, missing: [] } })
  const html = await render('IndustryHeatmap', { items: dashboard.industries, rankings: dashboard.rankings, observedAt: observed })
  assert.equal((html.match(/data-industry=/g) ?? []).length, 35)
  for (const text of ['强度前五', '低位改善前五', '过热拥挤前五', '风险恶化前五', '暂无可比快照', '当前风险分排序', '不额外判断低位']) assert.ok(html.includes(text), text)
  assert.match(html.replace(/<!--[\s\S]*?-->/g, ''), /market-industry__quality">80%<span class="market-badge is-stale">数据滞后/)
  assert.match(html, /<select/)
  assert.equal((html.match(/<summary><span class="market-industry__name"/g) ?? []).length, 35)
})

test('concept radar defaults to dynamic ten, switches to core 25 and scopes summaries and rankings', async () => {
  const core = Array.from({ length: 25 }, (_, i) => object(`884${2000 + i}.WI`, { name: `核心概念${i}` }))
  const dynamic = Array.from({ length: 10 }, (_, i) => object(`884${2100 + i}.WI`, {
    name: `动态热点${i}`, selectionScore: 90 - i, selectedOn: '2026-11-13', retainedTradingDays: i + 1,
    ...(i === 0 ? { completeness: 60, observedAt: '2026-11-13T00:00:00Z' } : {}),
  }))
  const dashboard = view({ concepts: { selectionVersion: 'concept-selection-v0.1',
    scoringVersion: 'concept-score-v0.1', selectedAt: observed, core, dynamic } })
  const props = { core: dashboard.coreConcepts, dynamic: dashboard.dynamicConcepts,
    rankings: dashboard.conceptRankings, selectedAt: dashboard.concepts.selectedAt, observedAt: observed }
  const dynamicHtml = await render('ConceptRadar', props)
  assert.equal((dynamicHtml.match(/data-concept=/g) ?? []).length, 10)
  assert.ok(dynamicHtml.includes('动态热点0'))
  assert.ok(!dynamicHtml.includes('核心概念0'))
  for (const text of ['动态热点 10', '核心概念 25', '强度前五', '改善前五', '热度前五', '风险前五',
    'Wind 结构化行情统一评分', '妙想仅用于候选发现', '名单更新', '今日新入选', '证据不足', '数据滞后']) assert.ok(dynamicHtml.includes(text), text)
  assert.match(dynamicHtml, /role="tab" aria-selected="true" aria-controls="concept-panel"/)
  const coreHtml = await render('ConceptRadar', { ...props, initialTab: 'core' })
  assert.equal((coreHtml.match(/data-concept=/g) ?? []).length, 25)
  assert.ok(coreHtml.includes('核心概念0'))
  assert.ok(!coreHtml.includes('动态热点0'))

  const dashboardSource = readFileSync(new URL('../src/components/MarketResearchDashboard.vue', import.meta.url), 'utf8')
  assert.ok(dashboardSource.indexOf('<ConceptRadar') > dashboardSource.indexOf('<IndustryHeatmap'))
})

test('sector cards use opportunity and heat state while global cards retain legacy heat', async () => {
  const { deriveSectorRotationView } = await import('../src/features/market-dashboard/model.mjs')
  const sector = deriveSectorRotationView({ scoringVersion: 'sector-score-v0.2', universeVersion: 'sector-universe-v0.1', universe: 'industry', view: 'potential', observedAt: observed, marketDate: '2026-11-13', session: 'intraday', sectors: [{ id: '882100.WI', name: '测试行业', strength: 60, opportunity: null, risk: 30, heatState: 'warming', completeness: 60, coldStart: true, ranks: { strength: 1, opportunity: null, risk: 2 }, leaderboard: Object.fromEntries(['strength','opportunity'].map(axis => [axis, { axis, topTenStreak: 0, topTenCount15d: 0, rankChange: null }])) }] }).rows[0]
  for (const name of ['IndustryHeatmap','ConceptRadar']) {
    const html = await render(name, { rotationItems: [sector], observedAt: observed })
    for (const label of ['强度','机会','风险','升温','证据不足','冷启动']) assert.ok(html.includes(label), `${name}: ${label}`)
    assert.ok(!html.includes('热度分'))
  }
  const html = await render('MarketScoreCard', { sector, title: '测试行业' })
  assert.match(html, /机会/); assert.match(html, /升温/); assert.ok(!html.includes('热度'))
  const legacy = await render('MarketScoreCard', { item: view().global, title: '全局' })
  assert.match(legacy, /热度/); assert.ok(!legacy.includes('机会'))
})

test('v3 sector cards retain compact expansions, named sections and separate core/dynamic concept tabs', async () => {
  const { deriveSectorRotationView } = await import('../src/features/market-dashboard/model.mjs')
  const make = id => ({ id, name: id, strength: 60, opportunity: 80, risk: 30, heatState: 'warming', completeness: 80, coldStart: true, ranks: { strength: 1, opportunity: 2, risk: 3 }, leaderboard: Object.fromEntries(['strength','opportunity'].map(axis => [axis, { axis, topTenStreak: 2, topTenCount15d: 4, rankChange: 1 }])) })
  const rows = deriveSectorRotationView({ scoringVersion: 'sector-score-v0.2', universeVersion: 'sector-universe-v0.1', universe: 'concept', view: 'potential', observedAt: observed, marketDate: '2026-11-13', session: 'intraday', sectors: Array.from({ length: 35 }, (_, i) => make(`884${100 + i}.WI`)) }).rows
  const props = { rotationItems: rows, rotationCore: rows.slice(0,25), rotationDynamic: rows.slice(25), observedAt: observed }
  const dynamic = await render('ConceptRadar', props)
  assert.equal((dynamic.match(/data-concept=/g) ?? []).length,10)
  assert.match(dynamic, /id="market-concept-title"/)
  assert.match(dynamic, /动态热点 10/); assert.match(dynamic, /核心概念 25/)
  const core = await render('ConceptRadar', { ...props, initialTab:'core' })
  assert.equal((core.match(/data-concept=/g) ?? []).length,25)
  assert.match(core, /查看板块详情/)
  const industries = await render('IndustryHeatmap', { rotationItems: rows, observedAt: observed })
  assert.equal((industries.match(/data-industry=/g) ?? []).length,35)
  assert.match(industries, /id="market-industry-title"/)
  assert.match(industries, /<summary>/)
})
