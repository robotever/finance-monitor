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

function rotationPayload({ collection = '2026-11-13T15:00:00+08:00', industrySource = collection,
  conceptSource = collection } = {}) {
  return JSON.parse(execFileSync('python3', ['-B', '-c', `
import json, sys
from pathlib import Path
from tools.market_dashboard import job
from tools.market_dashboard.tests.test_job import rotation_batches
config = json.loads(Path('config/market-dashboard.json').read_text())
config.setdefault('sources', {})['now'] = sys.argv[1]
batches = rotation_batches(config)
for row in batches['industries'].rows: row['_timestamp'] = sys.argv[2]
for row in batches['concepts'].rows: row['_timestamp'] = sys.argv[3]
block = job.build_rotation_block(batches, [], config)
inputs = job.derive_inputs(batches, job.datetime.fromisoformat(config['sources']['now']), config)
print(json.dumps(job.build_rotation_payload(inputs, [], block, config), ensure_ascii=False, allow_nan=False,
                 separators=(',', ':')))
`, collection, industrySource, conceptSource], { cwd: new URL('..', import.meta.url), encoding: 'utf8' }))
}

function rotationAuditFixture(mature) {
  return JSON.parse(execFileSync('python3', ['-B', '-c', `
import json, sys
from datetime import date, timedelta
from pathlib import Path
from tools.market_dashboard import job
from tools.market_dashboard.tests.test_job import rotation_batches
config = json.loads(Path('config/market-dashboard.json').read_text())
config.setdefault('sources', {})['now'] = '2026-11-13T15:00:00+08:00'
batches = rotation_batches(config)
current = job._rotation_inputs(batches, config)
prior = []
if sys.argv[1] == 'mature':
    for offset in range(60):
        day = str(date(2026, 9, 1) + timedelta(days=offset))
        for index, item in enumerate(current):
            prior.append({'id': item['id'], 'universe': item['universe'], 'marketDate': day, 'session': 'close',
                'sectorScoringVersion': config['sectorScoringVersion'],
                'sectorUniverseVersion': config['sectorUniverseVersion'], '_rawScores': {'strength': 40 + offset/10},
                'metrics': {'relativeStrength20d': offset + index/1000, 'flowRatio1d': index/10 + offset/100,
                    'breadth': 40 + offset/10, 'activityPercentile': 30 + offset/2,
                    'strengthPercentile': 50 + offset/4, 'strengthRank': index % 10 + 1}})
rows = job._score_rotation_rows(current, prior, config)
expected = {row['id']: {'components': row['components'], 'missing': row['missing']} for row in rows}
block = job.build_rotation_block(batches, prior, config)
inputs = job.derive_inputs(batches, job.datetime.fromisoformat(config['sources']['now']), config)
payload = job.build_rotation_payload(inputs, [], block, config)
print(json.dumps({'payload': payload, 'expected': expected}, ensure_ascii=False, allow_nan=False, separators=(',', ':')))
`, mature ? 'mature' : 'cold'], { cwd: new URL('..', import.meta.url), encoding: 'utf8' }))
}

const clone = value => structuredClone(value)
function setComponentValue(payload, row, name, value, coverage) {
  const original = payload.sectorRotation.componentNodes[row.components[name]]
  const node = structuredClone(original), mask = node[0]
  assert.ok(mask & 1, `${name} must carry a value field`)
  node[1] = value
  if (coverage !== undefined) node[2] = coverage / 100
  row.components[name] = payload.sectorRotation.componentNodes.push(node) - 1
}
function visibleSector(payload, id) {
  return [...payload.industries, ...payload.concepts.core, ...payload.concepts.dynamic].find(row => row.id === id)
}
function configureOpportunity(payload, id, raw, { evidence = 3, validCloses = 60, coverage = 100,
  publicScore = Math.floor(raw + .5), rank = 1 } = {}) {
  const row = [...payload.sectorRotation.industries, ...payload.sectorRotation.concepts].find(item => item.id === id)
  const improvementWeights = [25, 20, 20], lowWeight = improvementWeights.slice(evidence).reduce((sum, value) => sum + value, 0)
  const highWeight = 100 - lowWeight, high = (raw * 100 - 59 * lowWeight) / highWeight
  setComponentValue(payload, row, 'position', high, coverage)
  setComponentValue(payload, row, 'activityWarming', high, coverage)
  for (const [index, name] of ['fundsImprovement','breadthImprovement','momentumImprovement'].entries()) {
    setComponentValue(payload, row, name, index < evidence ? high : 59, coverage)
  }
  Object.assign(row, { opportunity: publicScore, validCloses, improvementEvidence: evidence, coldStart: validCloses < 60 })
  row.axisCompleteness.opportunity = coverage
  row.ranks.opportunity = rank
  const projected = visibleSector(payload, id)
  for (const key of ['opportunity','validCloses','improvementEvidence','coldStart','axisCompleteness','ranks']) {
    projected[key] = structuredClone(row[key])
  }
  return row
}
function restampUniverse(payload, universe, observedAt) {
  const rows = universe === 'industry' ? payload.sectorRotation.industries : payload.sectorRotation.concepts
  for (const row of rows) row.observedAt = observedAt
  for (const row of [...payload.industries, ...payload.concepts.core, ...payload.concepts.dynamic]) {
    if (row.universe === universe) row.observedAt = observedAt
  }
}

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
    p => { p.sectorRotation.componentPartNames[0] = 'rawResponse' },
    p => { p.sectorRotation.componentPartNames[0] = '__proto__' },
    p => { const row = p.sectorRotation.industries[0]; row.components.providerPayload = row.components.priceTrend; delete row.components.priceTrend },
    p => { const row = p.sectorRotation.industries[0]; p.sectorRotation.componentNodes[row.components.priceTrend] = [0] },
    p => { p.sectorRotation.missingReasons[0] = '/Users/private/provider.json' },
  ]
  for (const mutate of invalid) {
    const candidate = clone(original); mutate(candidate)
    assert.throws(() => validatePayload(candidate), /INVALID_PAYLOAD/)
  }
})

test('node-mask audit round-trips exact cold and mature producer trees for both universes', async t => {
  const { decodeSectorRows, publicSectorRow } = await import('../functions/_lib/market-dashboard.js')
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  for (const mature of [false, true]) {
    const fixture = rotationAuditFixture(mature), rows = decodeSectorRows(fixture.payload)
    assert.equal(rows.length, 110)
    for (const row of rows) {
      assert.deepEqual({ components: row.components, missing: row.missing }, fixture.expected[row.id])
    }
    const db = database(t)
    assert.equal((await onRequestPost(publishContext(fixture.payload, db))).status, 201)
    for (const stored of db.execute('SELECT * FROM sector_rotation_snapshots').results) {
      const row = publicSectorRow(stored, true)
      assert.deepEqual({ components: row.components, missing: row.missing }, fixture.expected[row.id])
    }
  }
})

test('real v3 builder accepts fresh lagged and differing source times while preserving provenance', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const detail = await rotationHandler('detail'), db = database(t)
  const candidate = rotationPayload({ collection: '2026-11-13T15:05:00+08:00',
    industrySource: '2026-11-13T15:00:00+08:00', conceptSource: '2026-11-13T15:01:00+08:00' })
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  const audit = await (await detail(rotationContext('detail', db, '?universe=industry&id=882100.WI'))).json()
  assert.equal(audit.history[0].observedAt, '2026-11-13T07:05:00.000000Z')
  assert.equal(audit.history[0].provenance.observedAt, '2026-11-13T15:00:00+08:00')
  const concept = await (await detail(rotationContext('detail', db, '?universe=concept&id=884201.WI'))).json()
  assert.equal(concept.history[0].provenance.observedAt, '2026-11-13T15:01:00+08:00')
})

test('v3 rejects stale, future, wrong-date and pre-close source observations before storage', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  for (const observedAt of ['2026-11-13T14:34:59+08:00', '2026-11-13T15:05:01+08:00',
    '2026-11-12T15:00:00+08:00', '2026-11-13T14:59:59+08:00']) {
    const db = database(t), candidate = rotationPayload({ collection: '2026-11-13T15:05:00+08:00' })
    restampUniverse(candidate, 'industry', observedAt)
    assert.equal((await onRequestPost(publishContext(candidate, db))).status, 400)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM market_dashboard_snapshots').results[0].count, 0)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 0)
  }
})

test('source validation respects microseconds and the official close catch-up window', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const original = rotationPayload({ collection: '2026-11-13T15:05:00+08:00' })
  for (const mutation of ['microsecondFuture', 'afterCloseWindow']) {
    const candidate = clone(original), db = database(t)
    if (mutation === 'microsecondFuture') restampUniverse(candidate, 'industry', '2026-11-13T15:05:00.000001+08:00')
    else candidate.observedAt = candidate.sectorRotation.observedAt = '2026-11-13T15:30:00.000001+08:00'
    assert.equal((await onRequestPost(publishContext(candidate, db))).status, 400, mutation)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 0)
  }
})

test('opportunity persistence keeps confirmed raw precision and caps only insufficient evidence', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const db = database(t), candidate = rotationPayload()
  configureOpportunity(candidate, '882100.WI', 69.1, { rank: 2 })
  configureOpportunity(candidate, '882101.WI', 69.2, { rank: 1 })
  configureOpportunity(candidate, '882102.WI', 80, { evidence: 1, publicScore: 69, rank: 3 })
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  const rows = db.execute("SELECT sector_id, opportunity_rank_key FROM sector_rotation_snapshots WHERE sector_id IN ('882100.WI','882101.WI','882102.WI') ORDER BY sector_id").results
  assert.deepEqual(rows, [
    { sector_id: '882100.WI', opportunity_rank_key: 69.1 },
    { sector_id: '882101.WI', opportunity_rank_key: 69.2 },
    { sector_id: '882102.WI', opportunity_rank_key: 69 },
  ])
  db.execute("UPDATE sector_rotation_snapshots SET strength=80, strength_rank_key=80, risk=10, risk_rank_key=10, completeness=90 WHERE sector_id IN ('882100.WI','882101.WI','882102.WI')")
  const latest = await rotationHandler('latest')
  const main = await (await latest(rotationContext('latest', db, '?universe=industry&view=main'))).json()
  assert.deepEqual(main.sectors.filter(row => ['882100.WI','882101.WI','882102.WI'].includes(row.id)).map(row => row.id),
    ['882101.WI','882100.WI','882102.WI'])
  assert.deepEqual(db.execute("SELECT sector_id FROM sector_rotation_snapshots WHERE opportunity IS NOT NULL ORDER BY opportunity_rank").results.map(row => row.sector_id),
    ['882101.WI','882100.WI','882102.WI'])
})

test('opportunity half-point reconstruction agrees with Python and rejects inconsistent public scores', async t => {
  const { validatePayload, sectorRankKey } = await import('../functions/_lib/market-dashboard.js')
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const values = [72.66666666666667, 4.666666666666667, 74.33333333333333,
    66.33333333333333, 40.333333333333336]
  const cases = [
    { values, raw: 51.5, score: 52 },
    { values: values.map(value => value + 1), raw: 52.5, score: 53 },
    { values: values.map(value => value - 1), raw: 50.5, score: 51 },
    { values: [42, 34.666666666666664, 64, 79.33333333333333, 56.666666666666664], raw: 53.5, score: 54 },
    { values: values.map((value, index) => value - (index === 4 ? .00001 : 0)), score: 51 },
    { values: values.map((value, index) => value + (index === 4 ? .00001 : 0)), score: 52 },
  ]
  const producer = JSON.parse(execFileSync('python3', ['-B', '-c', `
import json, sys
from pathlib import Path
from tools.market_dashboard.scoring import score_normalized_components
weights = json.loads(Path('config/market-dashboard.json').read_text())['sectorScoring']['weights']['opportunity']
results = []
for values in json.load(sys.stdin):
    components = {name: {'value': value, 'coverage': 1} for name, value in zip(weights, values)}
    scored = score_normalized_components(components, weights)
    results.append({'raw': scored.raw, 'score': scored.score, 'completeness': scored.completeness})
print(json.dumps(results, allow_nan=False))
`], { cwd: new URL('..', import.meta.url), input: JSON.stringify(cases.map(item => item.values)), encoding: 'utf8' }))
  const original = rotationPayload()
  for (const [index, fixture] of cases.entries()) {
    const expected = producer[index], candidate = clone(original), db = database(t)
    assert.equal(expected.score, fixture.score)
    assert.equal(expected.completeness, 100)
    if (fixture.raw !== undefined) assert.equal(expected.raw, fixture.raw)
    const row = configureOpportunity(candidate, '882100.WI', expected.raw,
      { evidence: 2, publicScore: expected.score })
    for (const [offset, name] of Object.keys(candidate.sectorRotation.auditDefinitions.weights.opportunity).entries()) {
      setComponentValue(candidate, row, name, fixture.values[offset], 100)
    }
    for (const wrongScore of [expected.score - 1, expected.score + 1]) {
      const invalid = clone(candidate)
      invalid.sectorRotation.industries[0].opportunity = visibleSector(invalid, row.id).opportunity = wrongScore
      assert.throws(() => validatePayload(invalid), /INVALID_PAYLOAD/)
      assert.equal((await onRequestPost(publishContext(invalid, db))).status, 400)
      assert.equal(db.execute('SELECT COUNT(*) AS count FROM market_dashboard_snapshots').results[0].count, 0)
      assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 0)
    }
    const decoded = validatePayload(candidate).sectors.find(item => item.id === row.id)
    assert.equal(sectorRankKey(decoded, 'opportunity', candidate.sectorRotation.auditDefinitions), expected.raw)
    assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
    assert.deepEqual(db.execute('SELECT opportunity, opportunity_rank_key FROM sector_rotation_snapshots WHERE sector_id=?',
      [row.id]).results, [{ opportunity: expected.score, opportunity_rank_key: expected.raw }])
  }
})

test('opportunity evidence gates reject fabricated availability and accept exact boundaries', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const cases = [
    { validCloses: 19, coverage: 100, evidence: 2 },
    { validCloses: 20, coverage: 69.999, evidence: 2 },
    { validCloses: 20, coverage: 70, evidence: 1 },
  ]
  for (const settings of cases) {
    const db = database(t), candidate = rotationPayload()
    configureOpportunity(candidate, '882100.WI', 80, settings)
    assert.equal((await onRequestPost(publishContext(candidate, db))).status, 400)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM market_dashboard_snapshots').results[0].count, 0)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 0)
  }
  const db = database(t), boundary = rotationPayload()
  configureOpportunity(boundary, '882100.WI', 80, { validCloses: 20, coverage: 70, evidence: 2 })
  assert.equal((await onRequestPost(publishContext(boundary, db))).status, 201)
})

test('opportunity gates use decoded coverage and evidence and cannot be weakened in audit definitions', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const original = rotationPayload()
  for (const mutation of ['coverage', 'evidence', 'gates']) {
    const candidate = clone(original), db = database(t)
    const row = configureOpportunity(candidate, '882100.WI', 80, { evidence: 2, coverage: 70 })
    if (mutation === 'coverage') setComponentValue(candidate, row, 'position',
      candidate.sectorRotation.componentNodes[row.components.position][1], 0)
    if (mutation === 'evidence') {
      setComponentValue(candidate, row, 'fundsImprovement', 59, 70)
    }
    if (mutation === 'gates') {
      row.validCloses = visibleSector(candidate, row.id).validCloses = 0
      candidate.sectorRotation.auditDefinitions.gates.minimumCloses = 0
    }
    assert.equal((await onRequestPost(publishContext(candidate, db))).status, 400, mutation)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM market_dashboard_snapshots').results[0].count, 0)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 0)
  }
})

test('restored audit names and required nested shapes fail before either table is written', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const original = rotationPayload()
  for (const mutation of ['rawResponse', '__proto__', 'root', 'empty', 'nested']) {
    const candidate = clone(original), db = database(t), block = candidate.sectorRotation
    const row = block.industries[0]
    if (['rawResponse', '__proto__'].includes(mutation)) block.componentPartNames[0] = mutation
    if (mutation === 'root') {
      row.components.providerPayload = row.components.priceTrend; delete row.components.priceTrend
    }
    if (mutation === 'empty') block.componentNodes[row.components.priceTrend] = [0]
    if (mutation === 'nested') {
      const node = clone(block.componentNodes[row.components.priceTrend])
      node.at(-1)[0][0] = block.componentPartNames.indexOf('flow1d')
      row.components.priceTrend = block.componentNodes.push(node) - 1
    }
    assert.equal((await onRequestPost(publishContext(candidate, db))).status, 400, mutation)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM market_dashboard_snapshots').results[0].count, 0)
    assert.equal(db.execute('SELECT COUNT(*) AS count FROM sector_rotation_snapshots').results[0].count, 0)
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
  assert.deepEqual(Object.keys(body.sectors[0]).sort(), ['change1d','coldStart','completeness','heatState','id','leaderboard','name','opportunity','ranks','risk','strength'])
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

test('rotation latest applies prior-close changes for risk membership and documented tie breaks', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const latest = await rotationHandler('latest'), db = database(t), candidate = rotationPayload({ collection: '2026-11-13T15:05:00+08:00' })
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  const columns = '(observed_at, market_date, session, universe, sector_id, sector_name, strength, strength_rank_key, opportunity, opportunity_rank_key, risk, risk_rank_key, heat_state, completeness, strength_rank, opportunity_rank, risk_rank, official_close, cold_start, valid_closes, improvement_evidence, scoring_version, universe_version, components_json, missing_json, contributors_json, leaderboard_json, provenance_json, created_at)'
  db.execute(`INSERT INTO sector_rotation_snapshots ${columns}
    SELECT '2026-11-12T07:00:00.000000Z', '2026-11-12', session, universe, sector_id, sector_name,
      strength, strength_rank_key, opportunity, opportunity_rank_key, risk, risk_rank_key, heat_state,
      completeness, strength_rank, opportunity_rank, risk_rank, official_close, cold_start, valid_closes,
      improvement_evidence, scoring_version, universe_version, components_json, missing_json,
      contributors_json, leaderboard_json, provenance_json, created_at
    FROM sector_rotation_snapshots WHERE universe='industry'`)
  db.execute("UPDATE sector_rotation_snapshots SET strength=65, strength_rank_key=65.1, opportunity=82, opportunity_rank_key=82.2, risk=30, risk_rank_key=30.1, heat_state='warming', completeness=90 WHERE market_date='2026-11-13' AND sector_id IN ('882100.WI','882103.WI')")
  db.execute("UPDATE sector_rotation_snapshots SET strength=50 WHERE market_date='2026-11-12' AND sector_id='882100.WI'")
  db.execute("UPDATE sector_rotation_snapshots SET strength=60 WHERE market_date='2026-11-12' AND sector_id='882103.WI'")
  db.execute("UPDATE sector_rotation_snapshots SET risk=60, risk_rank_key=60.2, completeness=90, heat_state='neutral' WHERE market_date='2026-11-13' AND sector_id IN ('882104.WI','882105.WI')")
  db.execute("UPDATE sector_rotation_snapshots SET risk=45 WHERE market_date='2026-11-12' AND sector_id='882104.WI'")
  db.execute("UPDATE sector_rotation_snapshots SET risk=51 WHERE market_date='2026-11-12' AND sector_id='882105.WI'")
  const potential = await (await latest(rotationContext('latest', db, '?universe=industry&view=potential'))).json()
  assert.deepEqual(potential.sectors.slice(0, 2).map(row => row.id), ['882100.WI', '882103.WI'])
  assert.deepEqual(potential.sectors.slice(0, 2).map(row => row.change1d.strength), [15, 5])
  const risk = await (await latest(rotationContext('latest', db, '?universe=industry&view=risk'))).json()
  assert.ok(risk.sectors.some(row => row.id === '882104.WI'))
  assert.ok(!risk.sectors.some(row => row.id === '882105.WI'))
  assert.deepEqual(risk.sectors.filter(row => ['882104.WI','882105.WI'].includes(row.id)).map(row => row.change1d.risk), [15])
  // Equal risk scores sort by the prior-close increase before stable IDs.
  db.execute("UPDATE sector_rotation_snapshots SET risk=80, risk_rank_key=80.2 WHERE market_date='2026-11-13' AND sector_id IN ('882104.WI','882105.WI')")
  db.execute("UPDATE sector_rotation_snapshots SET risk=30 WHERE market_date='2026-11-12' AND sector_id='882105.WI'")
  const tiedRisk = await (await latest(rotationContext('latest', db, '?universe=industry&view=risk'))).json()
  assert.deepEqual(tiedRisk.sectors.filter(row => ['882104.WI','882105.WI'].includes(row.id)).map(row => row.id),
    ['882105.WI','882104.WI'])
  const sourceRows = db.execute("SELECT * FROM sector_rotation_snapshots WHERE market_date='2026-11-13' AND universe='industry'").results
  const priorRows = new Map(db.execute("SELECT * FROM sector_rotation_snapshots WHERE market_date='2026-11-12' AND universe='industry'").results.map(row => [row.sector_id,row]))
  const scorerRows = sourceRows.map(row => ({ id: row.sector_id, universe: row.universe,
    strength: row.strength, opportunity: row.opportunity, risk: row.risk, heatState: row.heat_state,
    completeness: row.completeness, _rawScores: Object.fromEntries(['strength','opportunity','risk'].map(axis => [axis,row[`${axis}_rank_key`]])),
    change1d: Object.fromEntries(['strength','opportunity','risk'].map(axis => [axis,
      row[axis] !== null && priorRows.get(row.sector_id)?.[axis] != null ? row[axis] - priorRows.get(row.sector_id)[axis] : null])) }))
  const expected = JSON.parse(execFileSync('python3', ['-B','-c', `
import json, sys
from pathlib import Path
from tools.market_dashboard.rotation import derive_current_views
config = json.loads(Path('config/market-dashboard.json').read_text())
print(json.dumps({name: [row['id'] for row in rows] for name, rows in derive_current_views(json.load(sys.stdin), config).items()}))
`], { input: JSON.stringify(scorerRows), encoding: 'utf8' }))
  // A same-day close must never become the one-day baseline.
  const sameDay = sourceRows.map(row => ({ ...row, observed_at: '2026-11-13T07:01:00.000000Z', strength: 0, risk: 0 }))
  await db.batch(sameDay.map(row => db.prepare(`INSERT INTO sector_rotation_snapshots
    (${Object.keys(row).join(',')}) VALUES (${Object.keys(row).map(() => '?').join(',')})`).bind(...Object.values(row))))
  for (const [view, name] of [['potential','potentialRotation'],['main','confirmedMainline'],['risk','risingRisk']]) {
    const body = await (await latest(rotationContext('latest', db, `?universe=industry&view=${view}`))).json()
    assert.deepEqual(body.sectors.map(row => row.id), expected[name])
  }
})

test('rotation latest leaves change missing without a prior trading close', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const latest = await rotationHandler('latest'), db = database(t), candidate = rotationPayload()
  assert.equal((await onRequestPost(publishContext(candidate, db))).status, 201)
  db.execute("UPDATE sector_rotation_snapshots SET risk=60, risk_rank_key=60.2, completeness=90, heat_state='neutral' WHERE sector_id='882104.WI'")
  const body = await (await latest(rotationContext('latest', db, '?universe=industry&view=risk'))).json()
  assert.ok(!body.sectors.some(row => row.id === '882104.WI'))
  db.execute("UPDATE sector_rotation_snapshots SET risk=70, risk_rank_key=70 WHERE sector_id='882104.WI'")
  const eligible = await (await latest(rotationContext('latest', db, '?universe=industry&view=risk'))).json()
  assert.equal(eligible.sectors.find(row => row.id === '882104.WI').change1d.risk, null)
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

test('history selects one coherent latest official close per market date regardless of backfill order', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const history = await rotationHandler('history')
  const base = rotationPayload({ collection: '2026-11-13T15:05:00+08:00' })
  for (const reverse of [false, true]) {
    const db = database(t)
    assert.equal((await onRequestPost(publishContext(base, db))).status, 201)
    const rows = db.execute("SELECT * FROM sector_rotation_snapshots WHERE universe='industry'").results
    db.execute("DELETE FROM sector_rotation_snapshots WHERE universe='industry'")
    const snapshots = [
      rows.map(row => ({ ...row, observed_at: '2026-11-13T07:00:00.000000Z', strength: 40 })),
      rows.map(row => ({ ...row, observed_at: '2026-11-13T07:05:00.000000Z', strength: 80 })),
    ]
    if (reverse) snapshots.reverse()
    await db.batch(snapshots.flat().map(row => db.prepare(`INSERT INTO sector_rotation_snapshots
      (${Object.keys(row).join(',')}) VALUES (${Object.keys(row).map(() => '?').join(',')})`).bind(...Object.values(row))))
    const response = await history(rotationContext('history', db, '?universe=industry&axis=strength'))
    assert.equal(response.status, 200)
    const matrix = await response.json()
    assert.equal(matrix.rows.length, 35)
    assert.ok(matrix.rows.every(row => row.values.length === 1 && row.values[0].score === 80))
  }
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

test('schema-selected browser reads preserve v2 fallback and isolate histories across newer snapshots', async t => {
  const { onRequestPost } = await import('../functions/api/market-dashboard/publish.js')
  const { onRequestGet: latest } = await import('../functions/api/market-dashboard/latest.js')
  const { onRequestGet: history } = await import('../functions/api/market-dashboard/history.js')
  const { loadMarketDashboard, loadMarketHistory } = await import('../src/features/market-dashboard/api.mjs')
  const db = database(t), v3 = rotationPayload()
  const v2 = JSON.parse(execFileSync('python3', ['-B', '-c', `
import json
from tools.market_dashboard.job import run_job
print(json.dumps(run_job({'fixture': True, 'dry_run': True}).payload))
`], { encoding: 'utf8' }))
  assert.equal((await onRequestPost(publishContext(v2, db))).status, 201)
  assert.equal((await onRequestPost(publishContext(v3, db))).status, 201)
  const fetcher = url => {
    const request = new Request(new URL(url, 'https://example.test'))
    return (new URL(request.url).pathname.endsWith('/latest') ? latest : history)({ request, env: { MARKET_DB: db } })
  }
  assert.equal((await (await latest({ env: { MARKET_DB: db } })).json()).schemaVersion, 'market-dashboard-v3')
  // Explicit and default browser v2 reads must survive a newer shadow v3 snapshot.
  for (const options of [{}, { schemaVersion: 'market-dashboard-v2' }]) {
    assert.deepEqual((await loadMarketDashboard(fetcher, options)).data, v2)
    const result = await loadMarketHistory('5d', fetcher, options)
    assert.equal(result.error, null)
    assert.deepEqual(result.data.snapshots.map(row => row.observedAt), ['2026-11-13T02:15:00.000000Z'])
    assert.ok(result.data.snapshots.every(row => !Object.hasOwn(row.industries[0], 'opportunity')))
  }
  // Move v2 ahead of v3: explicit v3 must still use its own latest and anchor.
  const newerV2 = structuredClone(v2)
  newerV2.observedAt = '2026-11-14T07:00:00Z'
  newerV2.marketDate = '2026-11-14'
  assert.equal((await onRequestPost(publishContext(newerV2, db))).status, 201)
  const v3Options = { schemaVersion: 'market-dashboard-v3' }
  assert.deepEqual((await loadMarketDashboard(fetcher, v3Options)).data, v3)
  const v3History = await loadMarketHistory('5d', fetcher, v3Options)
  assert.equal(v3History.error, null)
  assert.deepEqual(v3History.data.snapshots.map(row => [row.observedAt, row.schemaVersion]),
    [['2026-11-13T07:00:00.000000Z', 'market-dashboard-v3']])
  const v2History = await loadMarketHistory('5d', fetcher)
  assert.equal(v2History.error, null)
  assert.deepEqual(v2History.data.snapshots.map(row => row.observedAt),
    ['2026-11-13T02:15:00.000000Z', '2026-11-14T07:00:00.000000Z'])
  assert.deepEqual((await loadMarketDashboard(fetcher)).data, newerV2)
  assert.deepEqual(await (await latest({ env: { MARKET_DB: db } })).json(), newerV2)
})
