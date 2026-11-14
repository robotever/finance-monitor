import { errorResponse, jsonResponse, ROTATION_SCHEMA_VERSION, SCHEMA_VERSION, SCORING_VERSION,
  SECTOR_SCORING_VERSION, requestedMarketSchema, storedPayload } from '../../_lib/market-dashboard.js'

export async function onRequestGet({ request, env }) {
  const schemaVersion = requestedMarketSchema(request)
  if (schemaVersion === null) return errorResponse('INVALID_QUERY', 400)
  try {
    const row = await env.MARKET_DB.prepare(`
      SELECT payload_json FROM market_dashboard_snapshots
      WHERE ((schema_version = ? AND scoring_version = ?) OR (schema_version = ? AND scoring_version = ?))
        AND (? IS NULL OR schema_version = ?)
      ORDER BY observed_at DESC, CASE WHEN schema_version = ? THEN 0 ELSE 1 END LIMIT 1
    `).bind(ROTATION_SCHEMA_VERSION, SECTOR_SCORING_VERSION, SCHEMA_VERSION, SCORING_VERSION,
      schemaVersion ?? null, schemaVersion ?? null, ROTATION_SCHEMA_VERSION).first()
    if (!row) return errorResponse('NO_SNAPSHOT', 404)
    return jsonResponse(storedPayload(row), 200, 'public, max-age=30, s-maxage=60')
  } catch { return errorResponse('STORAGE_UNAVAILABLE', 503) }
}
