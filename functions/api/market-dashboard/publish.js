import { authorized, errorResponse, jsonResponse, readBoundedJson, ROTATION_SCHEMA_VERSION, validatePayload } from '../../_lib/market-dashboard.js'

function rankKey(row, axis, weights) {
  if (row[axis] === null) return null
  let total = 0, used = 0
  for (const [name, weight] of Object.entries(weights[axis])) {
    const value = row.components[name]?.value
    if (typeof value === 'number' && Number.isFinite(value)) { total += value * weight; used += weight }
  }
  let score = used ? total / used : row[axis]
  if (axis === 'opportunity' && row.opportunity <= 69) score = Math.min(score, 69)
  return score
}

function contributors(row, definitions) {
  const entries = []
  for (const axis of ['strength', 'opportunity', 'risk']) {
    for (const [name, weight] of Object.entries(definitions.weights[axis])) {
      const value = row.components[name]?.value
      if (typeof value === 'number') entries.push({ axis, component: name, value, weight, impact: value * weight / 100 })
    }
  }
  return entries.sort((left, right) => Math.abs(right.impact) - Math.abs(left.impact) ||
    left.axis.localeCompare(right.axis) || left.component.localeCompare(right.component)).slice(0, 5)
}

function sectorStatement(db, payload, observedAt, row, createdAt) {
  const definitions = payload.sectorRotation.auditDefinitions
  const provenance = { source: 'Wind', observedAt: row.observedAt, marketDate: payload.marketDate,
    session: payload.session, officialClose: row.officialClose, sectorScoringVersion: payload.sectorScoringVersion,
    sectorUniverseVersion: payload.sectorUniverseVersion }
  return db.prepare(`
    INSERT INTO sector_rotation_snapshots
      (observed_at, market_date, session, universe, sector_id, sector_name,
       strength, strength_rank_key, opportunity, opportunity_rank_key, risk, risk_rank_key,
       heat_state, completeness, strength_rank, opportunity_rank, risk_rank, official_close,
       cold_start, valid_closes, improvement_evidence, scoring_version, universe_version,
       components_json, missing_json, contributors_json, leaderboard_json, provenance_json, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(observed_at, universe, sector_id, scoring_version) DO NOTHING
  `).bind(observedAt, payload.marketDate, payload.session, row.universe, row.id, row.name,
    row.strength, rankKey(row, 'strength', definitions.weights), row.opportunity,
    rankKey(row, 'opportunity', definitions.weights), row.risk, rankKey(row, 'risk', definitions.weights),
    row.heatState, row.completeness, row.ranks.strength, row.ranks.opportunity, row.ranks.risk,
    row.officialClose ? 1 : 0, row.coldStart ? 1 : 0, row.validCloses, row.improvementEvidence,
    payload.sectorScoringVersion, payload.sectorUniverseVersion, JSON.stringify(row.components),
    JSON.stringify(row.missing), JSON.stringify(contributors(row, definitions)), JSON.stringify(row.leaderboard),
    JSON.stringify(provenance), createdAt)
}

export async function onRequestPost({ request, env }) {
  const token = env.MARKET_DASHBOARD_PUBLISH_TOKEN
  if (typeof token !== 'string' || token.length === 0) return errorResponse('SERVICE_UNAVAILABLE', 503)
  try {
    if (!await authorized(request, token)) return errorResponse('UNAUTHORIZED', 401)
  } catch { return errorResponse('SERVICE_UNAVAILABLE', 503) }
  let payload, observed
  try { payload = await readBoundedJson(request) }
  catch (error) {
    const code = error.message === 'PAYLOAD_TOO_LARGE' ? 'PAYLOAD_TOO_LARGE' : 'INVALID_JSON'
    return errorResponse(code, code === 'PAYLOAD_TOO_LARGE' ? 413 : 400)
  }
  try {
    observed = validatePayload(payload)
    const futureLimit = Date.now() + 5 * 60000
    const subMillisecond = Number(observed.utc.slice(-4, -1))
    if (observed.millis > futureLimit || observed.millis === futureLimit && subMillisecond > 0) {
      return errorResponse('INVALID_PAYLOAD', 400)
    }
  } catch { return errorResponse('INVALID_PAYLOAD', 400) }
  try {
    const createdAt = new Date().toISOString()
    const dashboardScoringVersion = payload.schemaVersion === ROTATION_SCHEMA_VERSION ? payload.sectorScoringVersion : payload.scoringVersion
    const dashboard = env.MARKET_DB.prepare(`
      INSERT INTO market_dashboard_snapshots
        (observed_at, market_date, session, schema_version, scoring_version, completeness, payload_json, created_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(observed_at, scoring_version) DO NOTHING
    `).bind(observed.utc, payload.marketDate, payload.session, payload.schemaVersion,
      dashboardScoringVersion, payload.dataStatus.completeness, JSON.stringify(payload), createdAt)
    if (payload.schemaVersion !== ROTATION_SCHEMA_VERSION) {
      const result = await dashboard.run()
      const duplicate = result.meta.changes === 0
      return jsonResponse({ ok: true, duplicate, observedAt: payload.observedAt }, duplicate ? 200 : 201)
    }
    if (typeof env.MARKET_DB.batch !== 'function') throw new Error('BATCH_REQUIRED')
    const sectors = observed.sectors.map(row => sectorStatement(env.MARKET_DB, payload, observed.utc, row, createdAt))
    const cutoff = new Date(observed.millis - 90 * 86400000).toISOString()
    const prune = env.MARKET_DB.prepare(`
      DELETE FROM sector_rotation_snapshots
      WHERE official_close = 0 AND scoring_version = ? AND universe_version = ? AND observed_at < ?
    `).bind(payload.sectorScoringVersion, payload.sectorUniverseVersion, cutoff)
    const results = await env.MARKET_DB.batch([dashboard, ...sectors, prune])
    const result = results[0]
    const duplicate = result.meta.changes === 0
    return jsonResponse({ ok: true, duplicate, observedAt: payload.observedAt }, duplicate ? 200 : 201)
  } catch { return errorResponse('STORAGE_UNAVAILABLE', 503) }
}
