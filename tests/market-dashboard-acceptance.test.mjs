import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync } from 'node:fs'
import { loadMarketDashboard, loadMarketHistory, loadSectorRotationLatest, loadSectorRotationHistory, loadSectorRotationDetail } from '../src/features/market-dashboard/api.mjs'
import { decodeSectorRows } from '../functions/_lib/market-dashboard.js'

async function adapter() {
  assert.ok(existsSync(new URL('../src/features/market-dashboard/acceptance.mjs', import.meta.url)), 'isolated acceptance adapter must exist')
  return import('../src/features/market-dashboard/acceptance.mjs')
}
test('acceptance requires both the exact build mode and explicit flag', async () => {
  const { isSectorAcceptanceMode, acceptanceMetadata } = await adapter()
  for (const MODE of ['production', 'development', 'rotation-shadow', '', 'sector-acceptance']) {
    for (const flag of [undefined, 'false', 'true', true]) {
      assert.equal(isSectorAcceptanceMode({ MODE, VITE_SECTOR_ROTATION_ACCEPTANCE: flag }), MODE === 'sector-acceptance' && flag === 'true')
    }
  }
  assert.equal(isSectorAcceptanceMode(), false)
  assert.equal(acceptanceMetadata.environment, 'acceptance')
  assert.equal(acceptanceMetadata.dataKind, 'synthetic')
  assert.ok(Number.isFinite(Date.parse(acceptanceMetadata.generatedAt)))
  assert.ok(Object.isFrozen(acceptanceMetadata))
})
test('all synthetic dashboard routes pass the unchanged strict v2/v3 validators', async t => {
  const { acceptanceFetch } = await adapter()
  let networkCalls = 0
  t.mock.method(globalThis, 'fetch', async () => { networkCalls++; throw new Error('network forbidden') })
  for (const schemaVersion of ['market-dashboard-v2', 'market-dashboard-v3']) {
    const result = await loadMarketDashboard(acceptanceFetch, { schemaVersion })
    assert.equal(result.error, null)
    assert.equal(result.data.industries.length, 35)
    if (schemaVersion.endsWith('v3')) {
      const rows = decodeSectorRows(result.data)
      assert.equal(rows.filter(row => row.universe === 'concept').length, 75)
      assert.equal(new Set(rows.map(row => row.id)).size, 110)
      assert.equal(result.data.sectorRotation.releaseEligible, false, 'acceptance must not pretend to satisfy the release gate')
    }
    for (const window of ['1d', '5d', '20d', '90d']) {
      const history = await loadMarketHistory(window, acceptanceFetch, { schemaVersion })
      assert.equal(history.error, null)
      assert.ok(history.data.snapshots.length > 0)
    }
  }
  assert.equal(networkCalls, 0)
})
test('both universes, every current view, both matrix axes and all identity details remain local', async t => {
  const { acceptanceFetch } = await adapter()
  let networkCalls = 0
  t.mock.method(globalThis, 'fetch', async () => { networkCalls++; throw new Error('network forbidden') })
  const payload = (await loadMarketDashboard(acceptanceFetch, { schemaVersion: 'market-dashboard-v3' })).data
  for (const universe of ['industry', 'concept']) {
    for (const view of ['potential', 'main', 'risk']) {
      const result = await loadSectorRotationLatest({ universe, view, fetcher: acceptanceFetch })
      assert.equal(result.error, null)
      assert.ok(result.data.sectors.length > 0, `${universe}/${view}`)
    }
    for (const axis of ['strength', 'opportunity']) {
      const history = await loadSectorRotationHistory({ universe, axis, fetcher: acceptanceFetch })
      assert.equal(history.error, null)
      assert.equal(history.data.dates.length, 15)
      assert.equal(new Set(history.data.dates).size, 15)
      assert.equal(history.data.dates[0], '2026-10-26')
      assert.equal(history.data.dates.at(-1), '2026-11-13')
      assert.equal(history.data.rows.length, universe === 'industry' ? 35 : 75)
    }
    for (const row of decodeSectorRows(payload).filter(row => row.universe === universe)) {
      const detail = await loadSectorRotationDetail({ universe, id: row.id, fetcher: acceptanceFetch })
      assert.equal(detail.error, null, row.id)
      assert.equal(detail.data.history.length, 15, '60-day requests disclose only the supplied 15 dates')
      assert.ok(detail.data.history[0].components.priceTrend.parts.return5d)
      assert.ok(detail.data.history[0].contributors.length)
    }
    assert.equal((await loadSectorRotationHistory({ universe, axis: 'strength', days: 3, fetcher: acceptanceFetch })).data.dates.length, 3)
  }
  assert.equal(networkCalls, 0)
})
test('malformed and unsupported requests fail locally and corrupted fixture responses cannot bypass validation', async t => {
  const { acceptanceFetch } = await adapter()
  let networkCalls = 0
  t.mock.method(globalThis, 'fetch', async () => { networkCalls++; throw new Error('network forbidden') })
  for (const path of ['/api/unknown', '/api/market-dashboard/latest?schemaVersion=v4', '/api/market-dashboard/history?window=2d',
    '/api/sector-rotation/latest?universe=concept&view=oops', '/api/sector-rotation/latest?universe=concept&view=main&view=risk',
    '/api/sector-rotation/history?universe=industry&axis=risk&days=15', '/api/sector-rotation/history?universe=industry&axis=strength&days=16',
    '/api/sector-rotation/detail?universe=concept&id=882100.WI&days=60', '/api/market-dashboard/latest?extra=1', 'https://example.com/api/market-dashboard/latest',
    '/api/sector-rotation/detail?universe=industry&id=882100.WI&days=0']) {
    const response = await acceptanceFetch(path)
    assert.ok(response.status >= 400, path)
    assert.ok((await response.json()).error)
  }
  assert.equal((await acceptanceFetch(new Request('https://sector-acceptance.invalid/api/market-dashboard/latest', { method: 'POST' }))).status, 405)
  assert.equal((await acceptanceFetch('/api/market-dashboard/latest', { method: 'POST' })).status, 405)
  assert.equal((await acceptanceFetch(new URL('https://sector-acceptance.invalid/api/market-dashboard/latest'))).status, 200)
  const corrupt = async (url, init) => {
    const body = await (await acceptanceFetch(url, init)).json()
    body.industries.pop()
    return Response.json(body)
  }
  assert.equal((await loadMarketDashboard(corrupt, { schemaVersion: 'market-dashboard-v3' })).error.code, 'INVALID_SCHEMA')
  const unavailable = await loadSectorRotationLatest({ universe: 'concept', view: 'potential', fetcher: async () => { throw new Error('fixture unavailable') } })
  assert.equal(unavailable.error.code, 'NETWORK_ERROR')
  assert.equal(networkCalls, 0)
})

test('synthetic leaderboard counts agree with the supplied matrix dates', async () => {
  const { acceptanceFetch } = await adapter()
  const history = (await loadSectorRotationHistory({ universe: 'industry', axis: 'strength', fetcher: acceptanceFetch })).data
  const row = history.rows.find(row => row.id === '882105.WI')
  assert.equal(row.values.filter(point => point.rank !== null && point.rank <= 10).length, 10)
  const detail = (await loadSectorRotationDetail({ universe: 'industry', id: row.id, fetcher: acceptanceFetch })).data
  assert.equal(detail.history.at(-1).leaderboard.strength.topTenCount15d, 10)
  assert.equal(detail.history.at(-1).leaderboard.strength.topTenStreak, 0)
})
