import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import { createServer } from 'vite'
import { createSSRApp, createRenderer, h, markRaw, nextTick, reactive, ssrContextKey } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { deriveSectorRotationView } from '../src/features/market-dashboard/model.mjs'
let server
before(async () => { server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false, watch: null }, appType: 'custom' }) })
after(async () => { await server?.close() })
async function render(name, props) {
  assert.ok(existsSync(new URL(`../src/components/${name}.vue`, import.meta.url)), `${name} must exist`)
  const module = await server.ssrLoadModule(`/src/components/${name}.vue`)
  return renderToString(createSSRApp({ render: () => h(module.default, props) }))
}
const versions = { scoringVersion: 'sector-score-v0.2', universeVersion: 'sector-universe-v0.1' }
const row = (id, fields = {}) => ({ id, name: `超长中文板块名称用于验证手机布局${id}`, strength: 60, opportunity: 80, risk: 30, heatState: 'warming', completeness: 80, coldStart: true,
  ranks: { strength: 12, opportunity: 2, risk: 20 }, leaderboard: Object.fromEntries(['strength','opportunity'].map(axis => [axis, { axis, topTenStreak: 2, topTenCount15d: 4, rankChange: 3 }])), change1d: { strength: 3, opportunity: null, risk: 0 }, ...fields })
const latest = (view = 'potential', universe = 'concept') => ({ ...versions, universe, view, observedAt: '2026-11-13T07:00:00Z', marketDate: '2026-11-13', session: 'close', sectors: [row('884100.WI', view === 'main' ? { strength: 80 } : view === 'risk' ? { risk: 80, opportunity: null, heatState: 'crowded' } : {}), row('884101.WI')] })
const history = { ...versions, universe: 'concept', axis: 'strength', days: 15, dates: ['2026-11-13'], rows: [{ id: '884100.WI', name: '历史板块', values: [{ marketDate: '2026-11-13', score: 85, rank: 1 }] }] }
test('board defaults to concept potential with three independent scores and authoritative row order', async () => {
  const html = await render('SectorRotationBoard', { latest: latest(), history })
  for (const text of ['板块轮动','行业','概念','潜在轮动','主线确认','风险升温','强度','机会','风险','升温','冷启动','正式收盘','近15日4次','暂无涨跌数据','历史不足15日']) assert.ok(html.includes(text), text)
  assert.ok(html.indexOf('884100.WI') < html.indexOf('884101.WI'))
  assert.ok(!/综合分|composite|热度分/.test(html))
  assert.match(html, /机会榜（正式收盘）连续2日/)
  assert.match(html, /排名上升3/)
})
test('all views and universe selections are accessible, and incomplete lists never look complete', async () => {
  for (const view of ['potential','main','risk']) {
    const html = await render('SectorRotationBoard', { latest: latest(view, 'industry'), initialView: view, initialUniverse: 'industry' })
    assert.match(html, /role="tablist" aria-label="板块分类"/)
    assert.match(html, /id="rotation-universe-industry"[^>]*aria-selected="true"[^>]*aria-controls="rotation-panel"/)
    assert.match(html, /id="rotation-panel" role="tabpanel" aria-labelledby="rotation-universe-industry"/)
    assert.match(html, new RegExp(`id="rotation-view-${view}"[^>]*aria-selected="true"`))
    assert.match(html, /<button[^>]*data-sector=/)
    if (view === 'risk') { assert.match(html, /拥挤/); assert.match(html, /机会<\/span><strong>—/); }
  }
  const html = await render('SectorRotationBoard', { latest: latest(), initialView: 'main' })
  assert.match(html, /正在等待主线确认数据/)
  const empty = await render('SectorRotationBoard', { latest: { ...latest(), sectors: [] } })
  assert.match(empty, /暂无符合条件的板块/)
})
test('matrix has named table, date headers, focusable cells, top ten only and unavailable returns', async () => {
  const html = await render('SectorRotationBoard', { latest: latest(), history })
  assert.match(html, /<table[^>]*aria-label="强度榜近15个正式收盘日"/)
  assert.match(html, /<th scope="col">2026-11-13/)
  assert.match(html, /<button[^>]*aria-label="历史板块，2026-11-13，第1名/)
  assert.equal((html.match(/<th scope="row">/g) ?? []).length, 10)
  assert.match(html, /涨跌 —/)
  assert.match(html, /aria-label="历史评分维度"/)
})
test('detail dialog shows only actual available closes, audit, null scores and close control', async () => {
  const detail = { ...versions, universe: 'concept', id: '884100.WI', days: 60, history: [{ ...row('884100.WI', { opportunity: null }), ...versions, observedAt: '2026-11-13T07:00:00Z', marketDate: '2026-11-13', session: 'close', officialClose: true,
    components: { position: { value: null, coverage: 0, missing: ['position250d'] } }, missing: ['position250d'], contributors: [{ axis: 'strength', component: 'priceTrend', value: 65, weight: 30, impact: 19.5 }], provenance: { source: 'Wind', observedAt: '2026-11-13T07:00:00Z' } }] }
  const item = deriveSectorRotationView(latest(), history, { detail }).detail
  const html = await render('SectorRotationDetail', { detail: item, name: '历史板块', open: true })
  for (const text of ['历史板块','实际可得 1 个正式收盘日','强度','机会','风险','排名','贡献因素','标准化组件','position250d','Wind','sector-score-v0.2','sector-universe-v0.1']) assert.ok(html.includes(text), text)
  assert.match(html, /<dialog[^>]*aria-labelledby="rotation-detail-title"/)
  assert.match(html, /<h3 id="rotation-detail-title"/)
  assert.match(html, /<button[^>]*aria-label="关闭板块详情"/)
  assert.equal((html.match(/data-detail-close=/g) ?? []).length, 1)
  const error = await render('SectorRotationDetail', { open: true, error: '详情暂不可用' })
  assert.match(error, /详情暂不可用/)
})
test('shadow integration is off by default and responsive hooks constrain page overflow', () => {
  const source = readFileSync(new URL('../src/components/MarketResearchDashboard.vue', import.meta.url), 'utf8')
  assert.match(source, /VITE_SECTOR_ROTATION_RELEASE === 'true'/)
  assert.match(source, /MODE === 'rotation-shadow'/)
  assert.match(source, /MODE === 'production-rotation'/)
  assert.match(source, /releaseEligible/)
  const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
  for (const hook of ['.sector-rotation','.sector-rotation__matrix-scroll','.sector-rotation-detail','390px','1440px']) assert.ok(css.includes(hook), hook)
})

test('selected historical cell detail discloses the selected close scores, ranks and axis-specific counts', async () => {
  const snapshot = { ...row('884100.WI'), observedAt: '2026-11-13T07:00:00Z', marketDate: '2026-11-13', officialClose: true }
  const html = await render('SectorRotationDetail', { open: true, selectedCell: { id: snapshot.id, name: '历史板块', marketDate: snapshot.marketDate, score: 80, rank: 2 }, selectedAxis: 'opportunity', observations: [snapshot], name: '历史板块' })
  for (const text of ['当日三项评分','强度 60','机会 80','风险 30','机会榜近15日4次','分数变化 —','第2名']) assert.ok(html.includes(text), text)
})

test('default dashboard does not mount any v3 board or detail UI', async () => {
  const html = await render('MarketResearchDashboard', {})
  assert.ok(!html.includes('sector-rotation-detail'))
  assert.ok(!html.includes('id="rotation-title"'))
})

async function mountDashboard(module) {
  let state
  const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode() {}, nextSibling() {} })
  const app = renderer.createApp({ setup() { state = module.default.setup({}, { expose() {}, emit() {} }); return () => null } })
  app.provide(ssrContextKey, {})
  app.mount({})
  for (let i = 0; i < 100 && state.loading.value; i++) await new Promise(resolve => setTimeout(resolve, 10))
  return { app, state }
}

test('production rotation build exposes real observation beta while retaining release ineligibility', async () => {
  const production = await createServer({ mode: 'production-rotation', server: { middlewareMode: true, hmr: false, ws: false, watch: null }, appType: 'custom' })
  const previousFetch = globalThis.fetch
  try {
    const module = await production.ssrLoadModule('/src/components/MarketResearchDashboard.vue')
    const html = await renderToString(createSSRApp({ render: () => h(module.default) }))
    assert.match(html, /data-environment="sector-observation"/)
    assert.match(html, /真实数据观察期 · 评分方法尚未完成历史验证 · 不构成交易信号/)
    const { acceptanceFetch } = await import('../src/features/market-dashboard/acceptance.mjs')
    let networkCalls = 0
    globalThis.fetch = async (...args) => { networkCalls++; return acceptanceFetch(...args) }
    const { app, state } = await mountDashboard(module)
    try {
      assert.equal(state.loading.value, false)
      assert.equal(state.v3Active.value, true)
      assert.equal(state.v3Latest.value.sectorRotation.releaseEligible, false)
      assert.ok(networkCalls > 0, 'production observation uses API transport rather than fixture fallback')
    } finally { app.unmount() }
  } finally {
    globalThis.fetch = previousFetch
    await production.close()
  }
})

test('production rotation build falls back to v2 when the v3 response is malformed', async () => {
  const production = await createServer({ mode: 'production-rotation', server: { middlewareMode: true, hmr: false, ws: false, watch: null }, appType: 'custom' })
  const previousFetch = globalThis.fetch
  try {
    const module = await production.ssrLoadModule('/src/components/MarketResearchDashboard.vue')
    const { acceptanceFetch } = await import('../src/features/market-dashboard/acceptance.mjs')
    globalThis.fetch = async (input, init) => String(input).includes('schemaVersion=market-dashboard-v3')
      ? new Response('{"schemaVersion":"broken"}', { status: 200, headers: { 'content-type': 'application/json' } })
      : acceptanceFetch(input, init)
    const { app, state } = await mountDashboard(module)
    try {
      assert.equal(state.loading.value, false)
      assert.equal(state.v3Active.value, false)
      assert.ok(state.dashboard.value, 'validated v2 fallback remains visible')
    } finally { app.unmount() }
  } finally {
    globalThis.fetch = previousFetch
    await production.close()
  }
})

test('acceptance build keeps a persistent synthetic banner even before fixtures load', async () => {
  const previous = process.env.VITE_SECTOR_ROTATION_ACCEPTANCE
  process.env.VITE_SECTOR_ROTATION_ACCEPTANCE = 'true'
  const acceptanceServer = await createServer({ mode: 'sector-acceptance', server: { middlewareMode: true, hmr: false, ws: false, watch: null }, appType: 'custom' })
  try {
    const module = await acceptanceServer.ssrLoadModule('/src/components/MarketResearchDashboard.vue')
    const html = await renderToString(createSSRApp({ render: () => h(module.default) }))
    assert.match(html, /data-environment="sector-acceptance"/)
    assert.match(html, /临时验收环境 · 全部为测试数据 · 不代表真实市场信号/)
    assert.match(html, /role="note"/)
    const transformed = await acceptanceServer.transformIndexHtml('/', readFileSync(new URL('../index.html', import.meta.url), 'utf8'))
    assert.match(transformed, /name="robots" content="noindex,nofollow"/)
    assert.match(transformed, /<title>板块轮动临时验收 · 测试数据<\/title>/)
    assert.match(transformed, /name="description" content=".*测试数据/)
    const previousFetch = globalThis.fetch
    let networkCalls = 0
    globalThis.fetch = async () => { networkCalls++; throw new Error('market network forbidden during acceptance') }
    let state
    const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode() {}, nextSibling() {} })
    const app = renderer.createApp({ setup() { state = module.default.setup({}, { expose() {}, emit() {} }); return () => null } })
    app.provide(ssrContextKey, {})
    try {
      app.mount({})
      // Exercise actual onMounted -> refresh, and all subsequent dashboard interactions.
      for (let i = 0; i < 100 && state.loading.value; i++) await new Promise(resolve => setTimeout(resolve, 10))
      assert.equal(state.loading.value, false)
      assert.equal(state.v3Active.value, true)
      assert.equal(state.v3Latest.value.sectorRotation.releaseEligible, false)
      assert.equal(state.rotationError.value, '')
      assert.equal(state.latestError.value, null)
      assert.equal(state.historyError.value, null)
      const lastHistory = state.history.value.snapshots.at(-1)
      assert.equal(Date.parse(lastHistory.observedAt), Date.parse(state.dashboard.value.observedAt))
      for (const family of ['global', 'aShare']) for (const axis of ['strength', 'heat', 'risk']) {
        assert.equal(lastHistory[family][axis], state.dashboard.value[family][axis], `mounted acceptance cards and history agree: ${family}/${axis}`)
      }
      for (const universe of ['industry', 'concept']) for (const view of ['potential', 'main', 'risk']) for (const axis of ['strength', 'opportunity']) {
        await state.changeRotation({ universe, view, axis })
        assert.equal(state.rotationError.value, '')
        assert.ok(state.rotationLatest.value.sectors.length)
        await state.openSector({ universe, id: state.rotationLatest.value.sectors[0].id, name: '测试板块' })
        assert.equal(state.detailError.value, '')
        assert.equal(state.detailPayload.value.history.length, 15)
      }
      await state.refresh()
      assert.equal(state.v3Active.value, true)
      assert.equal(networkCalls, 0, 'real mounted dashboard and interaction loaders must never reach the network')
    } finally {
      app.unmount()
      globalThis.fetch = previousFetch
    }
  } finally {
    await acceptanceServer.close()
    if (previous === undefined) delete process.env.VITE_SECTOR_ROTATION_ACCEPTANCE
    else process.env.VITE_SECTOR_ROTATION_ACCEPTANCE = previous
  }
})

test('acceptance detail keeps its own synthetic warning inside the modal across loading, errors and audit content', async () => {
  const warning = '临时验收环境 · 全部为测试数据 · 不代表真实市场信号'
  const detail = { ...versions, id: '884100.WI', universe: 'concept', axisLabels: { strength: '强度', opportunity: '机会', risk: '风险' },
    series: [], audit: { components: {}, missing: [], contributors: [], provenance: { source: 'Wind', observedAt: '2026-11-13T07:00:00Z' } } }
  for (const state of [{ loading: true }, { error: '详情暂不可用' }, { detail }]) {
    const html = await render('SectorRotationDetail', { open: true, acceptanceEnvironment: true, ...state })
    assert.match(html, /<dialog[^>]*aria-describedby="rotation-detail-acceptance-warning"/)
    assert.match(html, /id="rotation-detail-acceptance-warning"[^>]*data-environment="sector-acceptance"[^>]*role="note"/)
    assert.ok(html.includes(warning))
    assert.ok(html.indexOf(warning) < html.indexOf('sector-rotation-detail__header'), 'warning starts inside the dialog above its scrollable content')
  }
  const ordinary = await render('SectorRotationDetail', { open: true, detail })
  assert.ok(!ordinary.includes(warning), 'ordinary details do not inherit the acceptance environment')
  assert.ok(ordinary.includes('Wind'), 'provenance is retained without changing its validator enum')
})

test('ordinary and shadow HTML retain default metadata even with the acceptance flag', async () => {
  const previous = process.env.VITE_SECTOR_ROTATION_ACCEPTANCE
  process.env.VITE_SECTOR_ROTATION_ACCEPTANCE = 'true'
  try {
    for (const mode of ['production', 'rotation-shadow']) {
      const ordinary = await createServer({ mode, server: { middlewareMode: true, hmr: false, ws: false, watch: null }, appType: 'custom' })
      try {
        const html = await ordinary.transformIndexHtml('/', readFileSync(new URL('../index.html', import.meta.url), 'utf8'))
        assert.match(html, /<title>Finance Monitor · 全市场研究终端<\/title>/)
        assert.ok(!html.includes('noindex'))
        const module = await ordinary.ssrLoadModule('/src/components/MarketResearchDashboard.vue')
        const rendered = await renderToString(createSSRApp({ render: () => h(module.default) }))
        assert.ok(!rendered.includes('data-environment="sector-acceptance"'))
        assert.ok(!rendered.includes('临时验收环境'))
      } finally { await ordinary.close() }
    }
  } finally {
    if (previous === undefined) delete process.env.VITE_SECTOR_ROTATION_ACCEPTANCE
    else process.env.VITE_SECTOR_ROTATION_ACCEPTANCE = previous
  }
})

test('historical selection shows its own derived audit while retaining the full score trajectory', async () => {
  const detail = { ...versions, id: '884100.WI', universe: 'concept', axisLabels: { strength:'强度',opportunity:'机会',risk:'风险' }, series: [{ observedAt:'2026-11-12T07:00:00Z',marketDate:'2026-11-12',officialClose:true,strength:60,opportunity:80,risk:30,ranks:{strength:12,opportunity:2,risk:20},heatStateLabel:'升温' },{ observedAt:'2026-11-13T07:00:00Z',marketDate:'2026-11-13',officialClose:true,strength:65,opportunity:85,risk:30,ranks:{strength:10,opportunity:1,risk:20},heatStateLabel:'升温' }], audit:{ components:{},missing:['latestOnlyMissing'],contributors:[],provenance:{source:'Wind',observedAt:'2026-11-13T07:00:00Z'} } }
  const selected = { ...row('884100.WI'),marketDate:'2026-11-12',officialClose:true,components:{},missing:['selectedCloseMissing'],contributors:[],provenance:{source:'Wind',observedAt:'2026-11-12T07:00:00Z'} }
  const html = await render('SectorRotationDetail',{ open:true,detail,selectedCell:{id:selected.id,marketDate:'2026-11-12',score:80,rank:2},observations:[selected] })
  assert.match(html,/selectedCloseMissing/)
  assert.ok(!html.includes('latestOnlyMissing'))
  assert.equal((html.match(/data-detail-close=/g) ?? []).length,2)
})

test('multiple close publications on one day count once and historical inspection uses the latest close', async () => {
  const points=[{ observedAt:'2026-11-13T07:00:00Z',marketDate:'2026-11-13',officialClose:true,strength:60,opportunity:80,risk:30,ranks:{strength:12,opportunity:2,risk:20},heatStateLabel:'升温' },{ observedAt:'2026-11-13T07:05:00Z',marketDate:'2026-11-13',officialClose:true,strength:65,opportunity:85,risk:30,ranks:{strength:10,opportunity:1,risk:20},heatStateLabel:'升温' }]
  const detail={ ...versions,id:'884100.WI',universe:'concept',axisLabels:{strength:'强度',opportunity:'机会',risk:'风险'},series:points,audit:null }
  const observations=points.map((point,index)=>({...row('884100.WI'),...point,components:{},missing:[index?'latestClose':'olderClose'],contributors:[],provenance:{source:'Wind',observedAt:point.observedAt,marketDate:point.marketDate,officialClose:true}}))
  const html=await render('SectorRotationDetail',{open:true,detail,observations,selectedCell:{id:'884100.WI',marketDate:'2026-11-13',score:85,rank:1}})
  assert.equal((html.match(/data-detail-close=/g) ?? []).length,1)
  assert.match(html,/实际可得 1 个正式收盘日/)
  assert.match(html,/latestClose/);assert.ok(!html.includes('olderClose'))
})

test('board identifies replacement row and historical-cell triggers across refreshes', async () => {
  const html = await render('SectorRotationBoard', { latest: latest(), history })
  assert.ok(html.includes('data-rotation-focus="[&quot;concept&quot;,&quot;current&quot;,&quot;potential&quot;,&quot;884100.WI&quot;]"'))
  assert.ok(html.includes('data-rotation-focus="[&quot;concept&quot;,&quot;history&quot;,&quot;strength&quot;,&quot;2026-11-13&quot;,&quot;884100.WI&quot;]"'))
})

// Run the real SFC setup/watchers with a minimal renderer. Focus doubles model the
// browser rule that focusing a detached node has no effect; browser QA covers DOM events.
test('dialog restores connected, replacement and missing board triggers without losing modal wrapping', async () => {
  const module = await server.ssrLoadModule('/src/components/SectorRotationDetail.vue')
  const previousDocument = globalThis.document
  const document = globalThis.document = { activeElement: null }
  try {
    for (const surface of ['current', 'history']) for (const refresh of ['ordinary', 'replacement', 'missing']) {
      const key = JSON.stringify(['concept', surface, surface === 'current' ? 'potential' : 'strength', '884100.WI'])
      let replacements = []
      const board = { isConnected: true, querySelectorAll: () => replacements, querySelector: () => fallback }
      const control = (identity = null) => markRaw({
        isConnected: true, dataset: { rotationFocus: identity },
        getAttribute: name => name === 'data-rotation-focus' ? identity : null,
        closest: selector => selector === '.sector-rotation' ? board : null,
        getClientRects: () => [1],
        focus() { if (this.isConnected) document.activeElement = this },
      })
      const trigger = control(key), replacement = control(key), unrelated = control('other-sector'), fallback = control()
      const close = control(), last = control()
      const props = reactive({ open: false })
      let state
      const renderer = createRenderer({ createComment: () => ({}), insert() {}, remove() {}, parentNode() {}, nextSibling() {} })
      const app = renderer.createApp({ setup() { state = module.default.setup(props, { expose() {}, emit() {} }); return () => null } })
      app.provide(ssrContextKey, {})
      app.mount({})
      await nextTick()
      state.dialog.value = { open: false, showModal() { this.open = true }, close() { this.open = false }, querySelectorAll: () => [close, last] }
      state.closeButton.value = close
      trigger.focus()
      props.open = true
      await nextTick(); await nextTick()
      assert.equal(document.activeElement, close, 'modal starts at its close button')
      let prevented = false
      state.trapFocus({ key: 'Tab', shiftKey: true, preventDefault() { prevented = true } })
      assert.ok(prevented); assert.equal(document.activeElement, last)
      state.trapFocus({ key: 'Tab', shiftKey: false, preventDefault() {} })
      assert.equal(document.activeElement, close)
      if (refresh !== 'ordinary') {
        trigger.isConnected = false
        replacements = refresh === 'replacement' ? [unrelated, replacement] : [unrelated]
      }
      props.open = false
      await nextTick(); await nextTick()
      assert.equal(document.activeElement, refresh === 'ordinary' ? trigger : refresh === 'replacement' ? replacement : fallback, `${surface}: ${refresh}`)
      app.unmount()
    }
  } finally { if (previousDocument === undefined) delete globalThis.document; else globalThis.document = previousDocument }
})
