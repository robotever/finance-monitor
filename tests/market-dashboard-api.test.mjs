import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { execFileSync } from 'node:child_process'

// Actual Task 3 derived fixture; only transport is replaced by offline Response objects.
const fixture = JSON.parse(execFileSync('python3', ['-c', `
import json
from tools.market_dashboard.job import run_job
print(json.dumps(run_job({'fixture': True, 'dry_run': True}).payload))
`], { encoding: 'utf8', env: { ...process.env, PYTHONDONTWRITEBYTECODE: '1' } }))
const payload = () => structuredClone(fixture)
async function api() {
  const path = new URL('../src/features/market-dashboard/api.mjs', import.meta.url)
  assert.ok(existsSync(path), 'market dashboard loader must exist')
  return import(path)
}
const response = body => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
function history() {
  const compact = object => Object.fromEntries(['id', 'strength', 'heat', 'risk', 'completeness'].map(key => [key, object[key]]))
  return { window: '5d', snapshots: [{ observedAt: fixture.observedAt, marketDate: fixture.marketDate,
    session: fixture.session, scoringVersion: fixture.scoringVersion, global: compact(fixture.global),
    aShare: compact(fixture.aShare), styles: fixture.styles.map(compact), industries: fixture.industries.map(compact),
    concepts: { selectionVersion: fixture.concepts.selectionVersion,
      scoringVersion: fixture.concepts.scoringVersion, selectedAt: fixture.concepts.selectedAt,
      core: fixture.concepts.core.map(compact), dynamic: fixture.concepts.dynamic.map(compact) } }] }
}

test('latest loads real Task 3 nullable 78-object payload without changing its metadata', async () => {
  const { loadMarketDashboard } = await api()
  const result = await loadMarketDashboard(async (url, init) => {
    assert.equal(url, '/api/market-dashboard/latest?schemaVersion=market-dashboard-v2')
    assert.ok(init.signal instanceof AbortSignal)
    return response(payload())
  })
  assert.equal(result.error, null)
  assert.deepEqual(result.data, fixture)
  assert.equal(result.data.global.heat, null)
  assert.equal(result.data.styles.length + result.data.industries.length
    + result.data.concepts.core.length + result.data.concepts.dynamic.length + 2, 78)
})

test('404 NO_SNAPSHOT is distinct from generic HTTP errors and redacts server text', async () => {
  const { loadMarketDashboard } = await api()
  const empty = await loadMarketDashboard(async () => new Response('{"error":"NO_SNAPSHOT"}', { status: 404 }))
  assert.equal(empty.data, null)
  assert.equal(empty.error.code, 'NO_SNAPSHOT')
  const unavailable = await loadMarketDashboard(async () => new Response('private upstream detail', { status: 503 }))
  assert.equal(unavailable.error.code, 'HTTP_ERROR')
  assert.equal(unavailable.error.status, 503)
  assert.doesNotMatch(JSON.stringify(unavailable), /private upstream/)
  const other404 = await loadMarketDashboard(async () => new Response('{"error":"OTHER"}', { status: 404 }))
  assert.equal(other404.error.code, 'HTTP_ERROR')
})

test('invalid JSON, empty success and malformed latest schema remain distinct safe failures', async () => {
  const { loadMarketDashboard } = await api()
  assert.equal((await loadMarketDashboard(async () => new Response('{broken'))).error.code, 'INVALID_JSON')
  assert.equal((await loadMarketDashboard(async () => response(null))).error.code, 'INVALID_SCHEMA')
  const mutations = [
    p => { p.industries.pop() }, p => { p.styles[0].id = p.styles[1].id },
    p => { p.schemaVersion = 'market-dashboard-v1' },
    p => { p.concepts.core.pop() }, p => { p.concepts.dynamic.pop() },
    p => { p.concepts.dynamic[0].id = p.concepts.core[0].id },
    p => { p.concepts.selectionVersion = 'unknown' }, p => { p.concepts.scoringVersion = 'unknown' },
    p => { p.concepts.selectedAt = 'invalid' }, p => { p.concepts.core[0].selectionScore = 50 },
    p => { p.concepts.dynamic[0].selectionScore = 101 },
    p => { p.concepts.dynamic[0].selectedOn = '2026-02-30' },
    p => { p.concepts.dynamic[0].retainedTradingDays = 0 },
    p => { p.aShare.selectionScore = 50 },
    p => { p.global.strength = '59' }, p => { p.aShare.risk = 101 },
    p => { p.aShare.completeness = null }, p => { p.global.sourceTimestamps = [] },
    p => { p.sourceMode.global.gold = 'unknown' }, p => { p.sourceMode.concepts = 'mx' },
    p => { p.sourceMode.conceptDiscovery = 'wind' }, p => { p.dataStatus.stale = 'false' },
    p => { p.global.change5d = { strength: 1 } }, p => { p.observedAt = '2026-02-30T10:15:00+08:00' },
    p => { p.scoringVersion = 'next-version' }, p => { p.aShare.stage = '扩张' },
  ]
  for (const mutate of mutations) {
    const candidate = payload(); mutate(candidate)
    assert.equal((await loadMarketDashboard(async () => response(candidate))).error.code, 'INVALID_SCHEMA')
  }
})

test('timeout aborts transport and also bounds a hung response body', async () => {
  const { loadMarketDashboard } = await api()
  let signal
  const stalledFetch = await loadMarketDashboard(async (_url, init) => {
    signal = init.signal
    return new Promise(() => {})
  }, { timeoutMs: 5 })
  assert.equal(stalledFetch.error.code, 'TIMEOUT')
  assert.equal(signal.aborted, true)
  const stalledBody = await loadMarketDashboard(async () => ({ ok: true, status: 200, json: () => new Promise(() => {}) }), { timeoutMs: 5 })
  assert.equal(stalledBody.error.code, 'TIMEOUT')
})

test('caller cancellation is propagated and remains distinct from timeout and network failure', async () => {
  const { loadMarketDashboard } = await api()
  const controller = new AbortController()
  const pending = loadMarketDashboard(async () => new Promise(() => {}), { signal: controller.signal, timeoutMs: 100 })
  controller.abort()
  assert.equal((await pending).error.code, 'ABORTED')
  assert.equal((await loadMarketDashboard(async () => { throw new Error('private provider exception') })).error.code, 'NETWORK_ERROR')
  const alreadyAborted = await loadMarketDashboard(async () => { throw new Error('should not fetch') }, { signal: controller.signal })
  assert.equal(alreadyAborted.error.code, 'ABORTED')
})

test('history validates requested window and compact snapshots including nullable score axes', async () => {
  const { loadMarketHistory } = await api()
  const result = await loadMarketHistory('5d', async url => {
    assert.equal(url, '/api/market-dashboard/history?window=5d&schemaVersion=market-dashboard-v2')
    return response(history())
  })
  assert.deepEqual(result.data, history())
  assert.equal(result.error, null)
  assert.equal((await loadMarketHistory('all', async () => { throw new Error('must not fetch') })).error.code, 'INVALID_WINDOW')
  for (const body of [{ window: '1d', snapshots: [] }, { window: '5d', snapshots: [] },
    { window: '5d', snapshots: [{ observedAt: 'invalid' }] }]) {
    assert.equal((await loadMarketHistory('5d', async () => response(body))).error.code, 'INVALID_SCHEMA')
  }
  const bad = history(); bad.snapshots[0].industries[0].risk = 101
  assert.equal((await loadMarketHistory('5d', async () => response(bad))).error.code, 'INVALID_SCHEMA')
})

test('partial history failure composes with latest success without discarding valid latest', async () => {
  const { loadMarketDashboard, loadMarketHistory } = await api()
  const fetcher = async url => new URL(url, 'https://example.test').pathname.endsWith('/latest') ? response(payload()) : new Response('unavailable', { status: 503 })
  const [latest, past] = await Promise.all([loadMarketDashboard(fetcher), loadMarketHistory('5d', fetcher)])
  assert.equal(latest.data.aShare.strength, 75)
  assert.equal(latest.error, null)
  assert.equal(past.data, null)
  assert.equal(past.error.code, 'HTTP_ERROR')
})

// Use the actual local producer: browser validation must accept its lossless v3 audit.
let v3Fixture
async function v3Payload() {
  if (!v3Fixture) {
    const { execFileSync } = await import('node:child_process')
    v3Fixture = JSON.parse(execFileSync('python3', ['-B', '-c', `
import json
from pathlib import Path
from tools.market_dashboard import job
from tools.market_dashboard.tests.test_job import rotation_batches
config = json.loads(Path('config/market-dashboard.json').read_text())
config.setdefault('sources', {})['now'] = '2026-11-13T15:00:00+08:00'
batches = rotation_batches(config)
block = job.build_rotation_block(batches, [], config)
inputs = job.derive_inputs(batches, job.datetime.fromisoformat(config['sources']['now']), config)
print(json.dumps(job.build_rotation_payload(inputs, [], block, config), allow_nan=False))
`], { cwd: new URL('..', import.meta.url), encoding: 'utf8' }))
  }
  return structuredClone(v3Fixture)
}
const versions = { scoringVersion: 'sector-score-v0.2', universeVersion: 'sector-universe-v0.1' }
const board = axis => ({ axis, topTenStreak: 2, topTenCount15d: 3, rankChange: 1 })
const sector = (id = '882100.WI') => ({ id, name: '板块', strength: 65, opportunity: 80, risk: 30,
  heatState: 'warming', completeness: 80, coldStart: true, ranks: { strength: 12, opportunity: 2, risk: 20 },
  leaderboard: { strength: board('strength'), opportunity: board('opportunity') },
  change1d: { strength: 3, opportunity: null, risk: 0 } })
const rotationLatest = () => ({ ...versions, observedAt: '2026-11-13T07:00:00Z', marketDate: '2026-11-13',
  session: 'close', universe: 'industry', view: 'potential', sectors: [sector()] })
const rotationHistory = () => ({ ...versions, universe: 'industry', axis: 'strength', days: 15,
  dates: ['2026-11-13'], rows: [{ id: '882100.WI', name: '板块', values: [{ marketDate: '2026-11-13', score: 65, rank: 12 }] }] })
function detailComponents() {
  const leaf = () => ({ value: 65, coverage: 1, missing: [] })
  const branches = {
    priceTrend: ['return1d','return5d','return20d'], funding: ['flow1d','flow5d','flow20d'],
    activity: ['turnover','marketShare','concentration','acceleration'], persistence: ['meanPercentile','topTenStreak'],
    position: ['position60d','position250d'], fundsImprovement: ['historical20d','delta5d'], breadthImprovement: ['delta5d','improvingDays'],
    momentumImprovement: ['shortAcceleration','mediumAcceleration'], activityWarming: ['current','delta5d'],
    downsideDiffusion: ['current','delta5d'], fundsWithdrawal: ['funding','delta5d'],
    trendDeterioration: ['return5d','return20d','slope5d'],
  }
  const component = key => branches[key] ? { ...leaf(), usedWeight: 100, totalWeight: 100, effectiveWeight: 100,
    parts: Object.fromEntries(branches[key].map(part => [part, component(key === 'activityWarming' && part === 'current' ? 'activity' : part)])) } : leaf()
  return Object.fromEntries([...Object.keys(branches), 'breadth','concentration','activityMean5d','divergence','crowding'].map(key => [key, component(key)]))
}
const rotationDetail = () => {
  const row = sector(); delete row.change1d
  return { ...versions, universe: 'industry', id: row.id, days: 60, history: [{ ...row, ...versions,
    observedAt: '2026-11-13T07:00:00Z', marketDate: '2026-11-13', session: 'close', officialClose: true,
    components: detailComponents(), missing: ['position250d'],
    contributors: [{ axis: 'strength', component: 'priceTrend', value: 65, weight: 30, impact: 19.5 }],
    provenance: { source: 'Wind', observedAt: '2026-11-13T07:00:00Z', marketDate: '2026-11-13',
      session: 'close', officialClose: true, sectorScoringVersion: versions.scoringVersion, sectorUniverseVersion: versions.universeVersion } }] }
}

test('explicit v3 loading validates split axes and exact 35/75 identities while v2 stays fallback only', async () => {
  const { loadMarketDashboard } = await api()
  const valid = await v3Payload()
  const options = { schemaVersion: 'market-dashboard-v3' }
  assert.deepEqual((await loadMarketDashboard(async () => response(valid), options)).data, valid)
  assert.equal((await loadMarketDashboard(async () => response(payload()), options)).error.code, 'INVALID_SCHEMA')
  assert.equal((await loadMarketDashboard(async () => response(valid))).error.code, 'INVALID_SCHEMA')
  for (const mutate of [p => { delete p.global.heat }, p => { p.aShare.opportunity = 80 },
    p => { p.styles[0].heatState = 'active' }, p => { p.industries[0].heat = 50 },
    p => { delete p.industries[0].opportunity }, p => { delete p.industries[0].heatState },
    p => { p.sectorRotation.industries[0].id = '882117.WI' },
    p => { p.sectorRotation.concepts[74].id = '8849999.WI' },
    p => { p.sectorUniverseVersion = 'future' }, p => { p.sectorRotation.industries[0].ranks.risk = 36 },
    p => { p.sectorRotation.componentNodes[0] = [255] }, p => { p.sectorRotation.componentPartNames[0] = 'rawResponse' }]) {
    const candidate = structuredClone(valid); mutate(candidate)
    assert.equal((await loadMarketDashboard(async () => response(candidate), options)).error?.code, 'INVALID_SCHEMA')
  }
})

test('v3 compact market history rejects mixed schemas, wrong axes and incompatible versions', async () => {
  const { loadMarketHistory } = await api()
  const { compactSnapshot } = await import('../functions/_lib/market-dashboard.js')
  const snapshot = compactSnapshot({ payload_json: JSON.stringify(await v3Payload()) })
  const body = { window: '5d', snapshots: [snapshot] }, options = { schemaVersion: 'market-dashboard-v3' }
  assert.deepEqual((await loadMarketHistory('5d', async () => response(body), options)).data, body)
  for (const mutate of [p => { p.snapshots.push(history().snapshots[0]) },
    p => { p.snapshots[0].industries[0].heat = 70 }, p => { delete p.snapshots[0].global.heat },
    p => { p.snapshots[0].sectorScoringVersion = 'old' }, p => { p.snapshots[0].concepts.core[0].id = '8849999.WI' }]) {
    const bad = structuredClone(body); mutate(bad)
    assert.equal((await loadMarketHistory('5d', async () => response(bad), options)).error?.code, 'INVALID_SCHEMA')
  }
})

test('rotation loaders bind query enums, identities and response echoes before exposing data', async () => {
  const { loadSectorRotationLatest, loadSectorRotationHistory, loadSectorRotationDetail } = await api()
  assert.equal(typeof loadSectorRotationLatest, 'function')
  const calls = [
    [loadSectorRotationLatest, { universe: 'industry', view: 'potential' }, rotationLatest, '/api/sector-rotation/latest?universe=industry&view=potential'],
    [loadSectorRotationHistory, { universe: 'industry', axis: 'strength' }, rotationHistory, '/api/sector-rotation/history?universe=industry&axis=strength&days=15'],
    [loadSectorRotationDetail, { universe: 'industry', id: '882100.WI' }, rotationDetail, '/api/sector-rotation/detail?universe=industry&id=882100.WI&days=60'],
  ]
  for (const [loader, options, fixture, url] of calls) {
    assert.deepEqual((await loader({ ...options, fetcher: async actual => { assert.equal(actual, url); return response(fixture()) } })).data, fixture())
    const bad = fixture(); bad.universe = 'concept'
    assert.equal((await loader({ ...options, fetcher: async () => response(bad) })).error.code, 'INVALID_SCHEMA')
    assert.equal((await loader({ ...options, universe: 'style', fetcher: async () => assert.fail('invalid query must not fetch') })).error.code, 'INVALID_QUERY')
  }
  for (const options of [{ universe: 'industry', view: 'heat' }, { universe: 'concept', axis: 'risk', days: 15 },
    { universe: 'industry', id: '882117.WI' }, { universe: 'industry', id: '882100.WI', days: 61 }]) {
    const loader = 'view' in options ? loadSectorRotationLatest : 'axis' in options ? loadSectorRotationHistory : loadSectorRotationDetail
    assert.equal((await loader({ ...options, fetcher: async () => assert.fail('invalid query must not fetch') })).error.code, 'INVALID_QUERY')
  }
})

test('rotation loaders fail closed on malformed ranks, audit, dates, identities and raw fields', async () => {
  const { loadSectorRotationLatest, loadSectorRotationHistory, loadSectorRotationDetail } = await api()
  assert.equal(typeof loadSectorRotationDetail, 'function')
  const groups = [
    [loadSectorRotationLatest, { universe: 'industry', view: 'potential' }, rotationLatest, [
      p => { p.sectors[0].heat = 90 }, p => { delete p.sectors[0].opportunity }, p => { p.sectors[0].ranks.strength = 36 },
      p => { p.sectors.push(structuredClone(p.sectors[0])) }, p => { p.sectors[0].heatState = 'hot' },
      p => { p.sectors[0].leaderboard.strength.axis = 'opportunity' }, p => { p.sectors[0].leaderboard.strength.topTenCount15d = 16 },
      p => { p.sectors[0].id = '882117.WI' }, p => { p.scoringVersion = 'old' }, p => { p.marketDate = '2026-11-12' }]],
    [loadSectorRotationHistory, { universe: 'industry', axis: 'strength' }, rotationHistory, [
      p => { p.rows[0].values[0].marketDate = '2026-11-12' }, p => { p.dates.push('2026-11-13') },
      p => { p.rows[0].values[0].rank = 0 }, p => { p.rows[0].values[0].score = 101 }, p => { p.days = 14 }]],
    [loadSectorRotationDetail, { universe: 'industry', id: '882100.WI' }, rotationDetail, [
      p => { p.history[0].id = '882101.WI' }, p => { p.history[0].components.priceTrend.rawResponse = {} },
      p => { p.history[0].components.priceTrend.coverage = 2 }, p => { p.history[0].provenance.token = 'secret' },
      p => { p.history[0].missing = ['/Users/private'] }, p => { p.history[0].contributors[0].impact = 'bad' },
      p => { p.history[0].officialClose = false }, p => { p.history[0].provenance.observedAt = '2026-11-13T07:00:01Z' }]],
  ]
  for (const [loader, options, fixture, mutations] of groups) for (const mutate of mutations) {
    const bad = fixture(); mutate(bad)
    assert.equal((await loader({ ...options, fetcher: async () => response(bad) })).error?.code, 'INVALID_SCHEMA')
  }
})

test('rotation transport failures retain safe timeout, network and independent latest success', async () => {
  const { loadSectorRotationLatest, loadSectorRotationHistory } = await api()
  assert.equal(typeof loadSectorRotationLatest, 'function')
  const options = { universe: 'industry', view: 'potential' }
  assert.equal((await loadSectorRotationLatest({ ...options, fetcher: async () => new Promise(() => {}), timeoutMs: 5 })).error.code, 'TIMEOUT')
  assert.equal((await loadSectorRotationLatest({ ...options, fetcher: async () => { throw Error('private') } })).error.code, 'NETWORK_ERROR')
  const [latest, past] = await Promise.all([
    loadSectorRotationLatest({ ...options, fetcher: async () => response(rotationLatest()) }),
    loadSectorRotationHistory({ universe: 'industry', axis: 'strength', fetcher: async () => new Response('private', { status: 503 }) }),
  ])
  assert.equal(latest.error, null); assert.equal(past.error.code, 'HTTP_ERROR')
})

test('damaged v3 nested containers are schema failures rather than transport failures', async () => {
  const { loadMarketHistory } = await api()
  const { compactSnapshot } = await import('../functions/_lib/market-dashboard.js')
  const snapshot = compactSnapshot({ payload_json: JSON.stringify(await v3Payload()) })
  for (const mutate of [p => { p.snapshots[0].styles[0] = null }, p => { p.snapshots[0].concepts.core[0] = null },
    p => { p.snapshots[0] = null }]) {
    const body = { window: '5d', snapshots: [structuredClone(snapshot)] }; mutate(body)
    assert.equal((await loadMarketHistory('5d', async () => response(body), { schemaVersion: 'market-dashboard-v3' })).error.code, 'INVALID_SCHEMA')
  }
})

test('detail rejects microsecond-future evidence and impossible history rank collisions', async () => {
  const { loadSectorRotationDetail, loadSectorRotationHistory } = await api()
  const detail = rotationDetail(); detail.history[0].provenance.observedAt = '2026-11-13T07:00:00.000001Z'
  assert.equal((await loadSectorRotationDetail({ universe: 'industry', id: '882100.WI', fetcher: async () => response(detail) })).error?.code, 'INVALID_SCHEMA')
  const h = rotationHistory(); h.rows.push({ id: '882101.WI', name: '另一板块', values: structuredClone(h.rows[0].values) })
  assert.equal((await loadSectorRotationHistory({ universe: 'industry', axis: 'strength', fetcher: async () => response(h) })).error?.code, 'INVALID_SCHEMA')
})

test('decoded producer audit details for all 110 identities survive browser validation losslessly', async () => {
  const { loadSectorRotationDetail } = await api()
  const { decodeSectorRows } = await import('../functions/_lib/market-dashboard.js')
  const payload = await v3Payload(), rows = decodeSectorRows(payload)
  for (const row of rows) {
    const compact = sector(row.id); delete compact.change1d
    const body = { ...versions, universe: row.universe, id: row.id, days: 60, history: [{ ...compact,
      name: row.name, strength: row.strength, opportunity: row.opportunity, risk: row.risk, heatState: row.heatState,
      completeness: row.completeness, coldStart: row.coldStart, ranks: row.ranks, leaderboard: row.leaderboard, ...versions,
      observedAt: payload.observedAt, marketDate: payload.marketDate, session: payload.session, officialClose: true,
      components: row.components, missing: row.missing, contributors: [], provenance: { source: 'Wind', observedAt: row.observedAt,
        marketDate: payload.marketDate, session: payload.session, officialClose: true,
        sectorScoringVersion: versions.scoringVersion, sectorUniverseVersion: versions.universeVersion } }] }
    const result = await loadSectorRotationDetail({ universe: row.universe, id: row.id, fetcher: async () => response(body) })
    assert.deepEqual(result.data, body, row.id)
  }
})

test('detail requires every versioned audit root and required nested weights and parts', async () => {
  const { loadSectorRotationDetail } = await api()
  for (const mutate of [p => { delete p.history[0].components.position },
    p => { delete p.history[0].components.priceTrend.parts }, p => { delete p.history[0].components.activity.usedWeight }]) {
    const body = rotationDetail(); mutate(body)
    assert.equal((await loadSectorRotationDetail({ universe: 'industry', id: '882100.WI', fetcher: async () => response(body) })).error?.code, 'INVALID_SCHEMA')
  }
})

test('market loaders explicitly request their validated schema and reject invalid selectors before transport', async () => {
  const { loadMarketDashboard, loadMarketHistory } = await api()
  const { compactSnapshot } = await import('../functions/_lib/market-dashboard.js')
  const v3 = await v3Payload()
  for (const schemaVersion of ['market-dashboard-v2', 'market-dashboard-v3']) {
    const latest = schemaVersion === 'market-dashboard-v2' ? payload() : v3
    const past = schemaVersion === 'market-dashboard-v2' ? history()
      : { window: '5d', snapshots: [compactSnapshot({ payload_json: JSON.stringify(v3) })] }
    const fetcher = async url => {
      const parsed = new URL(url, 'https://example.test')
      assert.deepEqual(parsed.searchParams.getAll('schemaVersion'), [schemaVersion])
      return response(parsed.pathname.endsWith('/latest') ? latest : past)
    }
    assert.equal((await loadMarketDashboard(fetcher, { schemaVersion })).error, null)
    assert.equal((await loadMarketHistory('5d', fetcher, { schemaVersion })).error, null)
  }
  for (const schemaVersion of ['', 'v3', 'market-dashboard-v4', null, 3]) {
    const fetcher = () => { assert.fail('invalid selectors must not fetch') }
    assert.equal((await loadMarketDashboard(fetcher, { schemaVersion })).error?.code, 'INVALID_QUERY')
    assert.equal((await loadMarketHistory('5d', fetcher, { schemaVersion })).error?.code, 'INVALID_QUERY')
  }
})

test('detail orders sub-millisecond observations strictly after normalizing UTC offsets', async () => {
  const { loadSectorRotationDetail } = await api()
  const options = { universe: 'industry', id: '882100.WI' }
  const early = rotationDetail().history[0], late = structuredClone(early)
  early.observedAt = '2026-11-13T15:00:00.000001+08:00'
  late.observedAt = '2026-11-13T07:00:00.000002Z'
  for (const [rows, accepted] of [[[early, late], true], [[late, early], false], [[early, early], false]]) {
    const body = { ...rotationDetail(), history: rows }
    const result = await loadSectorRotationDetail({ ...options, fetcher: async () => response(body) })
    assert.equal(result.error?.code ?? null, accepted ? null : 'INVALID_SCHEMA')
    if (accepted) assert.deepEqual(result.data.history.map(row => row.observedAt), [early.observedAt, late.observedAt])
  }
})

test('v3 compact history preserves nondecreasing sub-millisecond chronology', async () => {
  const { loadMarketHistory } = await api()
  const { compactSnapshot } = await import('../functions/_lib/market-dashboard.js')
  const early = compactSnapshot({ payload_json: JSON.stringify(await v3Payload()) }), late = structuredClone(early)
  early.observedAt = '2026-11-13T15:00:00.000001+08:00'
  late.observedAt = '2026-11-13T07:00:00.000002Z'
  for (const [snapshots, accepted] of [[[early, late], true], [[late, early], false], [[early, early], true]]) {
    const body = { window: '5d', snapshots }
    const result = await loadMarketHistory('5d', async () => response(body), { schemaVersion: 'market-dashboard-v3' })
    assert.equal(result.error?.code ?? null, accepted ? null : 'INVALID_SCHEMA')
  }
})
