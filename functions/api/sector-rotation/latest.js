import { errorResponse, jsonResponse, publicSectorRow, SECTOR_SCORING_VERSION,
  SECTOR_UNIVERSE_VERSION } from '../../_lib/market-dashboard.js'

const VIEWS = ['potential', 'main', 'risk']
const UNIVERSES = ['industry', 'concept']

function query(request) {
  const params = new URL(request.url).searchParams
  if ([...params.keys()].some(key => !['universe', 'view'].includes(key)) ||
      params.getAll('universe').length !== 1 || params.getAll('view').length !== 1) return null
  const universe = params.get('universe'), view = params.get('view')
  return UNIVERSES.includes(universe) && VIEWS.includes(view) ? { universe, view } : null
}

const finite = value => typeof value === 'number' && Number.isFinite(value)
function applies(row, view) {
  if (view === 'potential') return row.completeness >= 70 && finite(row.opportunity) && row.opportunity >= 70 &&
    finite(row.strength) && row.strength < 70 && finite(row.risk) && row.risk < 70 && row.heatState !== 'crowded'
  if (view === 'main') return row.completeness >= 70 && finite(row.strength) && row.strength >= 70 &&
    finite(row.risk) && row.risk < 70
  return finite(row.risk) && row.risk >= 70 || row.heatState === 'crowded'
}

function compare(view) {
  const axes = view === 'potential' ? ['opportunity', 'strength'] : view === 'main' ? ['strength', 'opportunity'] : ['risk']
  return (left, right) => {
    for (const axis of axes) {
      const a = left.rankKeys[axis], b = right.rankKeys[axis]
      if (a === null && b !== null) return 1
      if (a !== null && b === null) return -1
      if (a !== b) return b - a
    }
    return left.sector.id.localeCompare(right.sector.id)
  }
}

export async function onRequestGet({ request, env }) {
  const selected = query(request)
  if (!selected) return errorResponse('INVALID_QUERY', 400)
  try {
    const latest = await env.MARKET_DB.prepare(`
      SELECT observed_at, market_date, session FROM sector_rotation_snapshots
      WHERE universe = ? AND scoring_version = ? AND universe_version = ?
      ORDER BY observed_at DESC LIMIT 1
    `).bind(selected.universe, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION).first()
    if (!latest) return errorResponse('NO_SNAPSHOT', 404)
    const rows = await env.MARKET_DB.prepare(`
      SELECT * FROM sector_rotation_snapshots
      WHERE universe = ? AND scoring_version = ? AND universe_version = ? AND observed_at = ?
      ORDER BY sector_id ASC
    `).bind(selected.universe, SECTOR_SCORING_VERSION, SECTOR_UNIVERSE_VERSION, latest.observed_at).all()
    const sectors = rows.results.map(row => ({ sector: publicSectorRow(row), rankKeys: {
      strength: row.strength_rank_key, opportunity: row.opportunity_rank_key, risk: row.risk_rank_key,
    }})).filter(row => applies(row.sector, selected.view)).sort(compare(selected.view)).map(row => row.sector)
    return jsonResponse({ observedAt: latest.observed_at, marketDate: latest.market_date, session: latest.session,
      universe: selected.universe, view: selected.view, scoringVersion: SECTOR_SCORING_VERSION,
      universeVersion: SECTOR_UNIVERSE_VERSION, sectors }, 200, 'public, max-age=30, s-maxage=60')
  } catch { return errorResponse('STORAGE_UNAVAILABLE', 503) }
}
