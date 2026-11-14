import test from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync, mkdtempSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { execFileSync } from 'node:child_process'

const migrations = [
  new URL('../migrations/0001_market_dashboard.sql', import.meta.url),
  new URL('../migrations/0002_sector_rotation.sql', import.meta.url),
]

function database(t) {
  const directory = mkdtempSync(join(tmpdir(), 'rotation-d1-'))
  t.after(() => rmSync(directory, { recursive: true, force: true }))
  const file = join(directory, 'db.sqlite')
  const execute = (sql, params = [], script = false) => JSON.parse(execFileSync('python3', ['-c', `
import json, sqlite3, sys
request = json.load(sys.stdin)
with sqlite3.connect(sys.argv[1]) as connection:
    connection.row_factory = sqlite3.Row
    if request['script']:
        connection.executescript(request['sql'])
        result = {'results': [], 'meta': {'changes': connection.total_changes}}
    else:
        cursor = connection.execute(request['sql'], request['params'])
        result = {'results': [dict(row) for row in cursor.fetchall()], 'meta': {'changes': max(cursor.rowcount, 0)}}
print(json.dumps(result))
`, file], { input: JSON.stringify({ sql, params, script }), encoding: 'utf8' }))
  for (const migration of migrations) execute(readFileSync(migration, 'utf8'), [], true)
  const statement = (sql, params = []) => ({
    sql, params,
    bind: (...values) => statement(sql, values),
    run: async () => execute(sql, params),
    first: async () => execute(sql, params).results[0] ?? null,
    all: async () => execute(sql, params),
  })
  return {
    execute,
    prepare: sql => statement(sql),
    async batch(statements) {
      return JSON.parse(execFileSync('python3', ['-c', `
import json, sqlite3, sys
request = json.load(sys.stdin)
results = []
with sqlite3.connect(sys.argv[1]) as connection:
    connection.row_factory = sqlite3.Row
    for statement in request:
        cursor = connection.execute(statement['sql'], statement['params'])
        results.append({'results': [dict(row) for row in cursor.fetchall()], 'meta': {'changes': max(cursor.rowcount, 0)}})
print(json.dumps(results))
`, file], { input: JSON.stringify(statements.map(({ sql, params }) => ({ sql, params }))), encoding: 'utf8' }))
    },
  }
}

function rotationPayload() {
  return JSON.parse(execFileSync('python3', ['-B', '-c', `
import json
from pathlib import Path
from tools.market_dashboard import job
from tools.market_dashboard.tests.test_job import rotation_batches
config = json.loads(Path('config/market-dashboard.json').read_text())
config.setdefault('sources', {})['now'] = '2026-11-13T15:00:00+08:00'
batches = rotation_batches(config)
block = job.build_rotation_block(batches, [], config)
inputs = job.derive_inputs(batches, job.datetime.fromisoformat(config['sources']['now']), config)
print(json.dumps(job.build_rotation_payload(inputs, [], block, config), ensure_ascii=False, allow_nan=False,
                 separators=(',', ':')))
`], { cwd: new URL('..', import.meta.url), encoding: 'utf8' }))
}

const clone = value => structuredClone(value)

test('rotation migration enforces identity, audit and rank-query contracts', t => {
  assert.ok(existsSync(migrations[1]), 'sector rotation migration must exist')
  const db = database(t)
  const columns = db.execute('PRAGMA table_info(sector_rotation_snapshots)').results
  assert.deepEqual(columns.filter(row => row.pk).sort((a, b) => a.pk - b.pk).map(row => row.name),
    ['observed_at', 'universe', 'sector_id', 'scoring_version'])
  for (const name of ['components_json', 'missing_json', 'contributors_json', 'leaderboard_json', 'provenance_json']) {
    assert.equal(columns.find(row => row.name === name)?.notnull, 1, `${name} must be required`)
  }
  const valid = ['2026-11-13T07:00:00.000000Z', '2026-11-13', 'close', 'industry', '882100.WI',
    '石油石化', 60, 60.1, 70, 70.1, 20, 20.1, 'active', 80, 1, 2, 3, 1, 0, 0, 0,
    'sector-score-v0.2', 'sector-universe-v0.1', '{}', '[]', '[]', '{}', '{}', '2026-11-13T07:00:01Z']
  const placeholders = valid.map(() => '?').join(',')
  const insert = `INSERT INTO sector_rotation_snapshots VALUES (${placeholders})`
  db.execute(insert, valid)
  for (const [index, value] of [[3, 'style'], [12, 'hot'], [6, 101], [8, -1]]) {
    const row = [...valid]; row[0] = `2026-11-13T07:00:0${index}.000000Z`; row[index] = value
    assert.throws(() => db.execute(insert, row))
  }
  const indexes = new Map(db.execute('PRAGMA index_list(sector_rotation_snapshots)').results
    .map(index => [index.name, db.execute(`PRAGMA index_info('${index.name}')`).results.map(row => row.name)]))
  assert.deepEqual(indexes.get('idx_sector_rotation_latest'), ['universe', 'scoring_version', 'observed_at'])
  assert.deepEqual(indexes.get('idx_sector_rotation_market_date'), ['market_date', 'universe', 'scoring_version', 'official_close'])
  assert.deepEqual(indexes.get('idx_sector_rotation_strength_rank'), ['universe', 'scoring_version', 'observed_at', 'strength_rank'])
  assert.deepEqual(indexes.get('idx_sector_rotation_opportunity_rank'), ['universe', 'scoring_version', 'observed_at', 'opportunity_rank'])
  assert.deepEqual(indexes.get('idx_sector_rotation_risk_rank'), ['universe', 'scoring_version', 'observed_at', 'risk_rank'])
})

test('v3 validation decodes all 110 lossless audit rows and rejects identity, rank, enum and raw-data mutations', async () => {
  const { decodeSectorRows, validatePayload } = await import('../functions/_lib/market-dashboard.js')
  const original = rotationPayload()
  assert.doesNotThrow(() => validatePayload(original))
  const rows = decodeSectorRows(original)
  assert.equal(rows.length, 110)
  assert.deepEqual(rows.reduce((counts, row) => ({ ...counts, [row.universe]: (counts[row.universe] || 0) + 1 }), {}),
    { industry: 35, concept: 75 })
  assert.equal(rows[0].components.priceTrend.coverage, 0.2)
  assert.ok(Array.isArray(rows[0].components.priceTrend.missing))
  assert.ok(rows.every(row => row.missing.every(reason => typeof reason === 'string')))
  const invalid = [
    p => { p.schemaVersion = 'market-dashboard-v2' },
    p => { p.sectorScoringVersion = 'sector-score-unknown' },
    p => { p.sectorRotation.industries.pop() },
    p => { p.sectorRotation.concepts[1].id = p.sectorRotation.concepts[0].id },
    p => { p.sectorRotation.industries[0].heatState = 'hot' },
    p => { p.sectorRotation.industries[0].ranks.strength = 36 },
    p => { p.sectorRotation.industries[0].officialClose = false },
    p => { p.sectorRotation.componentNodes[0][0] = 999 },
    p => { p.sectorRotation.industries[0].components.priceTrend = 999999 },
    p => { p.sectorRotation.industries[0].rawResponse = { close: 1 } },
    p => { p.sectorRotation.industries[0].rows = [] },
    p => { p.sectorRotation.auditDefinitions.weights.strength.priceTrend = Number.NaN },
    p => { delete p.sectorRotation.auditDefinitions.weights.risk },
    p => { p.sectorRotation.observedAt = '2026-11-13T14:59:00+08:00' },
    p => { p.global.strength = 101 },
    p => { p.global.sourceTimestamps = [] },
    p => { p.dataStatus.completeness = 101 },
    p => { p.industries[0].opportunity = 99 },
    p => { p.concepts.dynamic[0].selectionScore = 101 },
    p => { p.concepts.dynamic[1] = structuredClone(p.concepts.dynamic[0]) },
    p => { p.sourceMode = { breadth: 'mx' } },
  ]
  for (const mutate of invalid) {
    const candidate = clone(original); mutate(candidate)
    assert.throws(() => validatePayload(candidate), /INVALID_PAYLOAD/)
  }
})

test('v3 accepts a reused concept roster selected before the current observation', async () => {
  const { validatePayload } = await import('../functions/_lib/market-dashboard.js')
  const candidate = rotationPayload()
  candidate.concepts.selectedAt = '2026-11-12T15:00:00+08:00'
  assert.doesNotThrow(() => validatePayload(candidate))
})

const TOKEN = 'synthetic-rotation-token'
const publishRequest = payload => new Request('https://example.test/api/market-dashboard/publish', {
  method: 'POST', headers: { Authorization: `Bearer ${TOKEN}` }, body: JSON.stringify(payload),
})
const publishContext = (payload, db) => ({ request: publishRequest(payload),
  env: { MARKET_DB: db, MARKET_DASHBOARD_PUBLISH_TOKEN: TOKEN } })

test('v3 publication commits the dashboard and exactly 110 decoded rows atomically and idempotently', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const db = database(t), candidate = rotationPayload()
  const first = await onRequestPost(publishContext(candidate, db))
  assert.equal(first.status, 201)
  assert.deepEqual(await first.json(), { ok: true, duplicate: false, observedAt: candidate.observedAt })
  assert.equal(db.execute("SELECT COUNT(*) AS count FROM market_dashboard_snapshots WHERE schema_version='market-dashboard-v3'").results[0].count, 1)
  assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 110)
  assert.deepEqual(db.execute('SELECT universe, COUNT(*) AS count FROM sector_rotation_snapshots GROUP BY universe ORDER BY universe').results,
    [{ universe: 'concept', count: 75 }, { universe: 'industry', count: 35 }])
  const stored = db.execute("SELECT * FROM sector_rotation_snapshots WHERE sector_id='882100.WI'").results[0]
  assert.equal(stored.strength, candidate.sectorRotation.industries[0].strength)
  assert.equal(typeof stored.strength_rank_key, 'number')
  assert.ok(JSON.parse(stored.components_json).priceTrend)
  assert.ok(!JSON.stringify(stored).includes('rawResponse'))
  const duplicate = await onRequestPost(publishContext(candidate, db))
  assert.equal(duplicate.status, 200)
  assert.deepEqual(await duplicate.json(), { ok: true, duplicate: true, observedAt: candidate.observedAt })
  assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 110)
})

test('a failed sector insert rolls back the v3 dashboard row and future v3 observations never reach storage', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const db = database(t), candidate = rotationPayload()
  db.execute("CREATE TRIGGER reject_rotation BEFORE INSERT ON sector_rotation_snapshots WHEN NEW.sector_id='882100.WI' BEGIN SELECT RAISE(ABORT, 'synthetic'); END", [], true)
  const failed = await onRequestPost(publishContext(candidate, db))
  assert.equal(failed.status, 503)
  assert.deepEqual(await failed.json(), { error: 'STORAGE_UNAVAILABLE' })
  assert.equal(db.execute('SELECT COUNT(*) AS count FROM market_dashboard_snapshots').results[0].count, 0)
  assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 0)
  const future = rotationPayload()
  future.observedAt = '2099-01-01T07:00:00Z'; future.marketDate = '2099-01-01'
  future.sectorRotation.observedAt = future.observedAt; future.sectorRotation.marketDate = future.marketDate
  for (const row of [...future.sectorRotation.industries, ...future.sectorRotation.concepts, ...future.industries,
    ...future.concepts.core, ...future.concepts.dynamic]) row.observedAt = future.observedAt
  const rejected = await onRequestPost(publishContext(future, db))
  assert.equal(rejected.status, 400)
  assert.deepEqual(await rejected.json(), { error: 'INVALID_PAYLOAD' })
  assert.equal(db.execute('SELECT COUNT(*) AS count FROM market_dashboard_snapshots').results[0].count, 0)
})

async function rotationHandler(name) {
  const module = await import(`../functions/api/sector-rotation/${name}.js`)
  return module.onRequestGet
}
const rotationContext = (name, db, query = '') => ({ request: new Request(`https://example.test/api/sector-rotation/${name}${query}`),
  env: { MARKET_DB: db } })

test('rotation latest validates enums, filters the requested view and returns deterministic compact v3 rows', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const latest = await rotationHandler('latest'), db = database(t), candidate = rotationPayload()
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  db.execute("UPDATE sector_rotation_snapshots SET strength=65, strength_rank_key=65.1, opportunity=82, opportunity_rank_key=82.2, risk=30, risk_rank_key=30.1, heat_state='warming', completeness=90 WHERE universe='industry' AND sector_id='882100.WI'")
  db.execute("UPDATE sector_rotation_snapshots SET strength=65, strength_rank_key=65.1, opportunity=82, opportunity_rank_key=82.3, risk=30, risk_rank_key=30.1, heat_state='warming', completeness=90 WHERE universe='industry' AND sector_id='882103.WI'")
  db.execute("UPDATE sector_rotation_snapshots SET strength=80, strength_rank_key=80.1, opportunity=60, opportunity_rank_key=60.2, risk=20, risk_rank_key=20.1, heat_state='active', completeness=90 WHERE universe='industry' AND sector_id='882101.WI'")
  db.execute("UPDATE sector_rotation_snapshots SET strength=70, strength_rank_key=70.1, opportunity=75, opportunity_rank_key=75.2, risk=90, risk_rank_key=90.1, heat_state='crowded', completeness=90 WHERE universe='industry' AND sector_id='882102.WI'")
  const potential = await latest(rotationContext('latest', db, '?universe=industry&view=potential'))
  assert.equal(potential.status, 200)
  const body = await potential.json()
  assert.deepEqual(body.sectors.map(row => row.id), ['882103.WI', '882100.WI'])
  assert.deepEqual(Object.keys(body.sectors[0]).sort(), ['coldStart','completeness','heatState','id','leaderboard','name','opportunity','ranks','risk','strength'])
  assert.ok(!JSON.stringify(body).includes('components'))
  assert.ok(!JSON.stringify(body).includes('provenance'))
  assert.equal((await (await latest(rotationContext('latest', db, '?universe=industry&view=main'))).json()).sectors[0].id, '882101.WI')
  assert.equal((await (await latest(rotationContext('latest', db, '?universe=industry&view=risk'))).json()).sectors[0].id, '882102.WI')
  for (const query of ['', '?universe=style&view=main', '?universe=industry&view=hot',
    '?universe=industry&universe=concept&view=main', '?universe=industry&view=main&extra=1']) {
    const response = await latest(rotationContext('latest', db, query))
    assert.equal(response.status, 400)
  }
})

test('rotation history is an official-close matrix and detail alone returns decoded audit with safe provenance', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const history = await rotationHandler('history'), detail = await rotationHandler('detail')
  const db = database(t), candidate = rotationPayload()
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  const historyResponse = await history(rotationContext('history', db, '?universe=industry&axis=strength'))
  assert.equal(historyResponse.status, 200)
  const matrix = await historyResponse.json()
  assert.equal(matrix.days, 15)
  assert.deepEqual(matrix.dates, ['2026-11-13'])
  assert.equal(matrix.rows.length, 35)
  assert.deepEqual(matrix.rows[0].values[0], { marketDate: '2026-11-13', score: 3, rank: 34 })
  assert.ok(!JSON.stringify(matrix).includes('components'))
  const detailResponse = await detail(rotationContext('detail', db, '?universe=industry&id=882100.WI'))
  assert.equal(detailResponse.status, 200)
  const audit = await detailResponse.json()
  assert.equal(audit.days, 60)
  assert.equal(audit.history.length, 1)
  assert.ok(audit.history[0].components.priceTrend)
  assert.ok(Array.isArray(audit.history[0].missing))
  assert.ok(Array.isArray(audit.history[0].contributors))
  assert.deepEqual(Object.keys(audit.history[0].provenance).sort(),
    ['marketDate','observedAt','officialClose','sectorScoringVersion','sectorUniverseVersion','session','source'])
  const serialized = JSON.stringify(audit)
  for (const forbidden of [TOKEN, 'rawResponse', 'rawRows', '/Users/', 'Authorization']) assert.ok(!serialized.includes(forbidden))
  for (const [name, query] of [['history', '?universe=concept&axis=heat'], ['history', '?universe=concept&axis=risk&days=16'],
    ['detail', '?universe=industry&id=fake.WI'], ['detail', '?universe=industry&id=882100.WI&days=61']]) {
    const response = await (name === 'history' ? history : detail)(rotationContext(name, db, query))
    assert.equal(response.status, 400)
  }
})

test('detail days bounds distinct market dates rather than an arbitrary row count', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const detail = await rotationHandler('detail'), db = database(t), candidate = rotationPayload()
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  const copy = `INSERT INTO sector_rotation_snapshots
    SELECT ?, ?, session, universe, sector_id, sector_name, strength, strength_rank_key, opportunity,
      opportunity_rank_key, risk, risk_rank_key, heat_state, completeness, strength_rank, opportunity_rank,
      risk_rank, official_close, cold_start, valid_closes, improvement_evidence, scoring_version,
      universe_version, components_json, missing_json, contributors_json, leaderboard_json, provenance_json, created_at
    FROM sector_rotation_snapshots WHERE sector_id='882100.WI' AND observed_at='2026-11-13T07:00:00.000000Z'`
  for (const [observed, date] of [['2026-11-12T07:00:00.000000Z','2026-11-12'],
    ['2026-11-11T07:00:00.000000Z','2026-11-11'], ['2026-11-10T07:00:00.000000Z','2026-11-10']]) db.execute(copy, [observed, date])
  const response = await detail(rotationContext('detail', db, '?universe=industry&id=882100.WI&days=1'))
  assert.equal(response.status, 200)
  const body = await response.json()
  assert.deepEqual([...new Set(body.history.map(row => row.marketDate))], ['2026-11-13'])
})

test('rotation read APIs redact semantically corrupt stored audit JSON', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const latest = await rotationHandler('latest'), detail = await rotationHandler('detail')
  const db = database(t), candidate = rotationPayload()
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  db.execute("UPDATE sector_rotation_snapshots SET leaderboard_json='[]' WHERE sector_id='882100.WI'")
  assert.equal((await latest(rotationContext('latest', db, '?universe=industry&view=potential'))).status, 503)
  db.execute("UPDATE sector_rotation_snapshots SET leaderboard_json='{}', components_json='[]' WHERE sector_id='882100.WI'")
  assert.equal((await detail(rotationContext('detail', db, '?universe=industry&id=882100.WI'))).status, 503)
})

test('market dashboard reads prefer v3 and keep its compact history free of audit internals', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const { onRequestGet: latest } = await import('../functions/api/market-dashboard/latest.js')
  const { onRequestGet: history } = await import('../functions/api/market-dashboard/history.js')
  const db = database(t), candidate = rotationPayload()
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  const latestResponse = await latest({ env: { MARKET_DB: db } })
  assert.equal(latestResponse.status, 200)
  assert.equal((await latestResponse.json()).schemaVersion, 'market-dashboard-v3')
  const historyResponse = await history({ request: new Request('https://example.test/api/market-dashboard/history?window=5d'), env: { MARKET_DB: db } })
  assert.equal(historyResponse.status, 200)
  const compact = await historyResponse.json()
  assert.equal(compact.snapshots[0].schemaVersion, 'market-dashboard-v3')
  assert.ok(Object.hasOwn(compact.snapshots[0].industries[0], 'opportunity'))
  assert.ok(!JSON.stringify(compact).includes('componentNodes'))
  assert.ok(!JSON.stringify(compact).includes('auditDefinitions'))
})

test('publication prunes only current-version intraday rows older than 90 days and never official or older-version audit', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const db = database(t), candidate = rotationPayload()
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  const source = "SELECT ?, '2026-01-01', ?, universe, sector_id, sector_name, strength, strength_rank_key, opportunity, opportunity_rank_key, risk, risk_rank_key, heat_state, completeness, strength_rank, opportunity_rank, risk_rank, ?, cold_start, valid_closes, improvement_evidence, ?, universe_version, components_json, missing_json, contributors_json, leaderboard_json, provenance_json, created_at FROM sector_rotation_snapshots WHERE sector_id='882100.WI' LIMIT 1"
  const columns = '(observed_at, market_date, session, universe, sector_id, sector_name, strength, strength_rank_key, opportunity, opportunity_rank_key, risk, risk_rank_key, heat_state, completeness, strength_rank, opportunity_rank, risk_rank, official_close, cold_start, valid_closes, improvement_evidence, scoring_version, universe_version, components_json, missing_json, contributors_json, leaderboard_json, provenance_json, created_at)'
  db.execute(`INSERT INTO sector_rotation_snapshots ${columns} ${source}`, ['2026-01-01T02:00:00.000000Z', 'intraday', 0, 'sector-score-v0.2'])
  db.execute(`INSERT INTO sector_rotation_snapshots ${columns} ${source}`, ['2026-01-01T07:00:00.000000Z', 'close', 1, 'sector-score-v0.2'])
  db.execute(`INSERT INTO sector_rotation_snapshots ${columns} ${source}`, ['2026-01-01T03:00:00.000000Z', 'intraday', 0, 'sector-score-v0.1'])
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 200)
  assert.deepEqual(db.execute("SELECT observed_at, official_close, scoring_version FROM sector_rotation_snapshots WHERE observed_at LIKE '2026-01-01%' ORDER BY observed_at").results, [
    { observed_at: '2026-01-01T03:00:00.000000Z', official_close: 0, scoring_version: 'sector-score-v0.1' },
    { observed_at: '2026-01-01T07:00:00.000000Z', official_close: 1, scoring_version: 'sector-score-v0.2' },
  ])
})
