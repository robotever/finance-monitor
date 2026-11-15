import { errorResponse, jsonResponse, publicSectorRow, SECTOR_SCORING_VERSION,
  SECTOR_UNIVERSE_VERSION, validSectorIdentity } from '../../_lib/market-dashboard.js'

function query(request) {
  const params = new URL(request.url).searchParams
  if ([...params.keys()].some(key => !['universe', 'id', 'days'].includes(key)) ||
      params.getAll('universe').length !== 1 || params.getAll('id').length !== 1 || params.getAll('days').length > 1) return null
  const universe = params.get('universe'), id = params.get('id'), text = params.get('days') ?? '60'
  if (!validSectorIdentity(universe, id) || !/^\d+$/.test(text)) return null
  const days = Number(text)
  return days >= 1 && days <= 60 ? { universe, id, days } : null
}

export async function onRequestGet({ request, env }) {
  const selected = query(request)
  if (!selected) return errorResponse('INVALID_QUERY', 400)
  try {
    const datesResult = await env.MARKET_DB.prepare(`
      SELECT DISTINCT market_date FROM sector_rotation_snapshots
      WHERE universe = ? AND sector_id = ? AND scoring_version = ? AND universe_version = ?
      ORDER BY market_date DESC LIMIT ?
    `).bind(selected.universe, selected.id, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION, selected.days).all()
    const dates = datesResult.results.map(row => row.market_date)
    if (!dates.length) return errorResponse('NO_SNAPSHOT', 404)
    const placeholders = dates.map(() => '?').join(',')
    const result = await env.MARKET_DB.prepare(`
      SELECT * FROM sector_rotation_snapshots
      WHERE universe = ? AND sector_id = ? AND scoring_version = ? AND universe_version = ?
        AND market_date IN (${placeholders})
      ORDER BY observed_at ASC
    `).bind(selected.universe, selected.id, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION, ...dates).all()
    const history = result.results.map(row => publicSectorRow(row, true))
    return jsonResponse({ universe: selected.universe, id: selected.id, days: selected.days,
      scoringVersion: SECTOR_SCORING_VERSION, universeVersion: SECTOR_UNIVERSE_VERSION, history },
    200, 'public, max-age=300, s-maxage=600')
  } catch { return errorResponse('STORAGE_UNAVAILABLE', 503) }
}
