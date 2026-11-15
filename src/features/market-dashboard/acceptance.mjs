import { validSectorIdentity } from '../../../functions/_lib/market-dashboard.js'

export function isSectorAcceptanceMode(env = import.meta.env) {
  return env?.MODE === 'sector-acceptance' && env?.VITE_SECTOR_ROTATION_ACCEPTANCE === 'true'
}
export const acceptanceMetadata = Object.freeze({ environment: 'acceptance', dataKind: 'synthetic', generatedAt: '2026-11-15T00:00:00Z' })
const origin = 'https://sector-acceptance.invalid'
const response = (body, status = 200) => Response.json(body, { status, headers: { 'Cache-Control': 'no-store' } })
const invalid = () => response({ error: 'INVALID_QUERY' }, 400)
const exactQuery = (params, keys, optional = []) => keys.every(key => params.getAll(key).length === 1)
  && [...params.keys()].every(key => [...keys, ...optional].includes(key) && params.getAll(key).length === 1)
const daysValue = (value, maximum) => /^(?:[1-9]|[1-5][0-9]|60)$/.test(value) && Number(value) <= maximum

// An in-memory fetch-compatible transport. There is deliberately no network fallback.
export async function acceptanceFetch(input, init = {}) {
  const signal = init.signal ?? (input instanceof Request ? input.signal : undefined)
  if (signal?.aborted) throw new DOMException('Acceptance request aborted', 'AbortError')
  try {
    const url = new URL(input instanceof Request ? input.url : input, origin)
    const method = init.method ?? (input instanceof Request ? input.method : 'GET')
    if (method !== 'GET') return response({ error: 'METHOD_NOT_ALLOWED' }, 405)
    if (url.origin !== origin || url.hash || url.username || url.password) return invalid()
    const params = url.searchParams
    const market = /^\/api\/market-dashboard\/(latest|history)$/.exec(url.pathname)
    if (market) {
      const history = market[1] === 'history'
      if (!exactQuery(params, history ? ['window'] : [], ['schemaVersion'])) return invalid()
      const schema = params.get('schemaVersion') ?? 'market-dashboard-v2', window = params.get('window')
      if (!['market-dashboard-v2', 'market-dashboard-v3'].includes(schema) || history && !['1d', '5d', '20d', '90d'].includes(window)) return invalid()
      const { dashboardFixture } = await import('./acceptance-fixtures.mjs')
      return response(dashboardFixture(schema, history ? window : undefined))
    }
    const rotation = /^\/api\/sector-rotation\/(latest|history|detail)$/.exec(url.pathname)
    if (!rotation) return response({ error: 'NOT_FOUND' }, 404)
    const endpoint = rotation[1], keys = endpoint === 'latest' ? ['universe', 'view'] : endpoint === 'history' ? ['universe', 'axis', 'days'] : ['universe', 'id', 'days']
    if (!exactQuery(params, keys)) return invalid()
    const query = Object.fromEntries(params)
    if (!['industry', 'concept'].includes(query.universe)) return invalid()
    if (endpoint === 'latest' && !['potential', 'main', 'risk'].includes(query.view)) return invalid()
    if (endpoint === 'history' && (!['strength', 'opportunity'].includes(query.axis) || !daysValue(query.days, 15))) return invalid()
    if (endpoint === 'detail' && (!validSectorIdentity(query.universe, query.id) || !daysValue(query.days, 60))) return invalid()
    if (query.days) query.days = Number(query.days)
    const { rotationFixture } = await import('./acceptance-fixtures.mjs')
    return response(rotationFixture(endpoint, query))
  } catch {
    return response({ error: 'ACCEPTANCE_DATA_UNAVAILABLE' }, 503)
  }
}
