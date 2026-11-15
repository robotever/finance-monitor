import { errorResponse, jsonResponse, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION } from '../../_lib/market-dashboard.js'

function query(request) {
  const params = new URL(request.url).searchParams
  if ([...params.keys()].some(key => !['universe', 'axis', 'days'].includes(key)) ||
      params.getAll('universe').length !== 1 || params.getAll('axis').length !== 1 || params.getAll('days').length > 1) return null
  const universe = params.get('universe'), axis = params.get('axis'), text = params.get('days') ?? '15'
  if (!['industry', 'concept'].includes(universe) || !['strength', 'opportunity'].includes(axis) || !/^\d+$/.test(text)) return null
  const days = Number(text)
  return days >= 1 && days <= 15 ? { universe, axis, days } : null
}

export async function onRequestGet({ request, env }) {
  const selected = query(request)
  if (!selected) return errorResponse('INVALID_QUERY', 400)
  try {
    const datesResult = await env.MARKET_DB.prepare(`
      SELECT DISTINCT market_date FROM sector_rotation_snapshots
      WHERE universe = ? AND scoring_version = ? AND universe_version = ? AND official_close = 1
      ORDER BY market_date DESC LIMIT ?
    `).bind(selected.universe, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION, selected.days).all()
    const dates = datesResult.results.map(row => row.market_date).reverse()
    if (!dates.length) return errorResponse('NO_SNAPSHOT', 404)
    const placeholders = dates.map(() => '?').join(',')
    // The last collected official snapshot is canonical for the entire date;
    // choose once per universe/version, then read every sector from that snapshot.
    const result = await env.MARKET_DB.prepare(`
      WITH chosen AS (
        SELECT market_date, MAX(observed_at) AS observed_at FROM sector_rotation_snapshots
        WHERE universe = ? AND scoring_version = ? AND universe_version = ? AND official_close = 1
          AND market_date IN (${placeholders})
        GROUP BY market_date
      )
      SELECT rows.market_date, rows.sector_id, rows.sector_name, rows.${selected.axis} AS score,
        rows.${selected.axis}_rank AS rank
      FROM sector_rotation_snapshots AS rows
      JOIN chosen ON chosen.market_date = rows.market_date AND chosen.observed_at = rows.observed_at
      WHERE rows.universe = ? AND rows.scoring_version = ? AND rows.universe_version = ? AND rows.official_close = 1
      ORDER BY rows.sector_id ASC, rows.market_date ASC
    `).bind(selected.universe, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION, ...dates,
      selected.universe, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION).all()
    const grouped = new Map()
    for (const row of result.results) {
      if (!grouped.has(row.sector_id)) grouped.set(row.sector_id, { id: row.sector_id, name: row.sector_name, points: new Map() })
      grouped.get(row.sector_id).points.set(row.market_date, { marketDate: row.market_date, score: row.score, rank: row.rank })
    }
    const rows = [...grouped.values()].sort((left, right) => left.id.localeCompare(right.id)).map(row => ({
      id: row.id, name: row.name, values: dates.map(date => row.points.get(date) ?? { marketDate: date, score: null, rank: null }),
    }))
    return jsonResponse({ universe: selected.universe, axis: selected.axis, days: selected.days, dates,
      scoringVersion: SECTOR_SCORING_VERSION, universeVersion: SECTOR_UNIVERSE_VERSION, rows },
    200, 'public, max-age=300, s-maxage=600')
  } catch { return errorResponse('STORAGE_UNAVAILABLE', 503) }
}
