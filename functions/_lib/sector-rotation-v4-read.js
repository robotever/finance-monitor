import { V4_VERSIONS } from './sector-rotation-v4.js'
import { jsonResponse, errorResponse } from './market-dashboard.js'

const axes = ['strength', 'opportunity', 'risk']
const finite = v => typeof v === 'number' && Number.isFinite(v)
const versionColumns = ['schema_version', 'scoring_version', 'universe_version', 'feature_version', 'membership_version']
// Every public read joins the manifest and pins the complete version tuple.
const active = `m.status='active' AND ${versionColumns.map(k => `m.${k}=?`).join(' AND ')}`
const versionValues = Object.values(V4_VERSIONS)
const joined = 'sector_rotation_v04_sectors s JOIN sector_rotation_v04_manifests m ON m.batch_id=s.batch_id'
const chronological = 'm.observed_at DESC, m.batch_id DESC'

export function parseV4Query(request, kind) {
  const p = new URL(request.url).searchParams
  const allowed = { latest: [], catalog: ['universe','page','pageSize','q','view','role'], history: ['universe','axis','days'], detail: ['universe','id','days'] }[kind]
  if ([...p.keys()].some(k => !allowed.includes(k) || p.getAll(k).length !== 1)) return null
  if (kind === 'latest') return {}
  const universe = p.get('universe')
  if (!['industry','concept'].includes(universe)) return null
  const number = (key, fallback, max) => { const text = p.get(key) ?? String(fallback); return /^[1-9]\d*$/.test(text) && Number.isSafeInteger(+text) && +text <= max ? +text : null }
  if (kind === 'catalog') {
    const page = number('page', 1, 10000), pageSize = number('pageSize', 50, 100)
    const q = p.get('q') ?? '', view = p.get('view') ?? 'all', role = p.get('role') ?? 'all'
    if (!page || !pageSize || q.length > 100 || /[\u0000-\u001f]/.test(q) || !['all','potential','main','risk'].includes(view) || !['all','core','dynamic','candidate'].includes(role) || universe === 'industry' && role !== 'all') return null
    return { universe, page, pageSize, q, view, role }
  }
  const days = number('days', kind === 'history' ? 15 : 60, kind === 'history' ? 15 : 60)
  if (!days) return null
  if (kind === 'history') return [...axes,'return1d'].includes(p.get('axis')) ? { universe, axis: p.get('axis'), days } : null
  const id = p.get('id')
  return (universe === 'industry' ? /^881\d{3}\.TI$/ : /^88[56]\d{3}\.TI$/).test(id ?? '') ? { universe, id, days } : null
}

async function latestManifest(db) {
  return db.prepare(`SELECT m.* FROM ${joined} WHERE ${active} ORDER BY ${chronological} LIMIT 1`).bind(...versionValues).first()
}
async function batchRows(db, batchId, universe) {
  const result = await db.prepare(`SELECT s.* FROM ${joined} WHERE ${active} AND m.batch_id=? ${universe ? 'AND s.universe=?' : ''} ORDER BY s.sector_id`).bind(...versionValues, batchId, ...(universe ? [universe] : [])).all()
  return result.results
}
async function baseline(db, marketDate, universe) {
  const prior = await db.prepare(`SELECT m.* FROM ${joined} WHERE ${active} AND m.official_close=1 AND m.market_date<? ${universe ? 'AND s.universe=?' : ''} ORDER BY m.market_date DESC, ${chronological} LIMIT 1`).bind(...versionValues, marketDate, ...(universe ? [universe] : [])).first()
  return new Map((prior ? await batchRows(db, prior.batch_id, universe) : []).map(r => [r.universe + ':' + r.sector_id, r]))
}
const safeText = v => typeof v === 'string' && v.length <= 200 && !/[\u0000-\u001f]|\/Users\/|\/home\/|Bearer |authorization|api[_-]?key|token|password/i.test(v)
const publicKey = k => /^[a-zA-Z][a-zA-Z0-9]*$/.test(k) && !/private|secret|credential|token|password|authorization|apiKey|filePath|localPath|^(raw|constituents|stockIds)$/i.test(k)
function component(v, depth = 0) {
  if (!v || typeof v !== 'object' || depth > 4) return undefined
  const out = { value: finite(v.value) ? v.value : null, coverage: finite(v.coverage) ? v.coverage : 0, missing: Array.isArray(v.missing) ? v.missing.filter(safeText) : [] }
  for (const k of ['usedWeight','totalWeight','effectiveWeight']) if (finite(v[k])) out[k] = v[k]
  if (v.parts && typeof v.parts === 'object') out.parts = Object.fromEntries(Object.entries(v.parts).filter(([k]) => publicKey(k)).map(([k,x]) => [k,component(x,depth+1)]).filter(([,x]) => x))
  return out
}
function project(row, prior) {
  const raw = JSON.parse(row.row_json)
  const result = { id: row.sector_id, name: safeText(row.sector_name) ? row.sector_name : row.sector_id, universe: row.universe }
  for (const a of axes) result[a] = finite(row[a]) ? row[a] : null
  result.completeness = row.completeness
  result.ranks = Object.fromEntries(axes.map(a => [a,row[a+'_rank']]))
  result.change1d = Object.fromEntries(axes.map(a => [a, prior && finite(row[a]) && finite(prior[a]) ? row[a] - prior[a] : null]))
  for (const k of ['heatState','coldStart','validCloses','improvementEvidence','membershipMode','conceptRole']) result[k] = raw[k]
  result.missing = Array.isArray(raw.missing) ? raw.missing.filter(safeText) : []
  result.approximateHistory = raw.membershipMode === 'current_members_backfill'
  for (const k of ['metrics','axisCompleteness']) if (raw[k]) result[k] = Object.fromEntries(Object.entries(raw[k]).filter(([key,v]) => publicKey(key) && (v === null || finite(v) || typeof v === 'boolean')))
  if (raw.components) result.components = Object.fromEntries(Object.entries(raw.components).map(([k,v]) => [k,component(v)]).filter(([k,v]) => publicKey(k) && v))
  return result
}
function metadata(m, rows) {
  const membershipModes = [...new Set(rows.map(r => JSON.parse(r.row_json).membershipMode))].sort()
  return { ...V4_VERSIONS, sourceMode: 'hithink', batchId: m.batch_id, observedAt: m.observed_at, marketDate: m.market_date, session: m.session, officialClose: !!m.official_close, membershipModes, approximateHistory: membershipModes.includes('current_members_backfill') }
}
function applies(r, view) {
  if (view === 'all') return true
  if (view === 'potential') return r.completeness >= 70 && finite(r.opportunity) && r.opportunity >= 70 && finite(r.strength) && r.strength < 70 && finite(r.risk) && r.risk < 70 && r.heatState !== 'crowded'
  if (view === 'main') return r.completeness >= 70 && finite(r.strength) && r.strength >= 70 && finite(r.risk) && r.risk < 70
  return finite(r.risk) && r.risk >= 70 || finite(r.change1d.risk) && r.change1d.risk >= 10 || r.heatState === 'crowded'
}
function compare(view) {
  const order = view === 'potential' ? ['opportunity','strengthChange'] : view === 'main' ? ['strength','opportunity'] : ['risk','riskChange']
  return (a,b) => {
    for (const key of order) {
      const value = item => key.endsWith('Change') ? item.public.change1d[key.slice(0,-6)] : item.raw.rankKeys?.[key] ?? item.public[key]
      const x = value(a), y = value(b)
      if (x !== y) { if (!finite(x)) return 1; if (!finite(y)) return -1; return y-x }
    }
    return a.public.id.localeCompare(b.public.id)
  }
}
const entries = (rows, prior) => rows.map(r => ({ public: project(r,prior.get(r.universe+':'+r.sector_id)), raw: JSON.parse(r.row_json) }))
const lists = rows => Object.fromEntries(['potential','main','risk'].map(view => [view, rows.filter(r => applies(r.public,view)).sort(compare(view)).slice(0,10).map(r => r.public)]))

// Local inspection uses the identical rules after adding reconstructed deltas.
export function selectProjectedV4Lists(rows) {
  const items=applyConceptRoles(rows.map(r=>({public:{...r},raw:r})))
  return {industry:lists(items.filter(r=>r.public.universe==='industry')),
    concept:{...lists(items.filter(r=>r.public.universe==='concept')),
      core:items.filter(r=>r.public.conceptRole==='core').map(r=>r.public),
      dynamic:items.filter(r=>r.public.conceptRole==='dynamic').sort(compare('potential')).map(r=>r.public)}}
}

function applyConceptRoles(items) {
  const concepts = items.filter(r => r.public.universe === 'concept')
  const selected = new Set(concepts.filter(({public:r}) => r.conceptRole !== 'core' && r.completeness >= 70 && axes.every(a => finite(r[a])) && r.risk < 70 && r.heatState !== 'crowded').sort(compare('potential')).slice(0,10).map(r => r.public.id))
  for (const item of concepts) if (item.public.conceptRole !== 'core') item.public.conceptRole = selected.has(item.public.id) ? 'dynamic' : 'candidate'
  return items
}
async function readLatest(db, m) {
  const rows = await batchRows(db,m.batch_id), prior = await baseline(db,m.market_date)
  const items = applyConceptRoles(entries(rows,prior)), concepts = items.filter(r => r.public.universe === 'concept')
  return { ...metadata(m,rows), industry: lists(items.filter(r => r.public.universe === 'industry')), concept: {
    ...lists(concepts), core: concepts.filter(r => r.public.conceptRole === 'core').slice(0,25).map(r => r.public),
    dynamic: concepts.filter(r => r.public.conceptRole === 'dynamic').sort(compare('potential')).map(r => r.public),
  } }
}
async function readCatalog(db,m,q) {
  const rows = await batchRows(db,m.batch_id,q.universe), prior = await baseline(db,m.market_date,q.universe)
  const needle = q.q.toLocaleLowerCase()
  const filtered = applyConceptRoles(entries(rows,prior)).filter(({public:r}) => applies(r,q.view) && (q.role === 'all' || r.conceptRole === q.role) && (!needle || r.id.toLowerCase().includes(needle) || r.name.toLocaleLowerCase().includes(needle)))
  if (q.view !== 'all') filtered.sort(compare(q.view))
  return { ...metadata(m,rows), ...q, total: filtered.length, sectors: filtered.slice((q.page-1)*q.pageSize,q.page*q.pageSize).map(r => r.public) }
}
async function readHistory(db,m,q) {
  const value=q.axis==='return1d'?"CASE WHEN json_type(s.row_json,'$.metrics.return1d') IN ('integer','real') THEN json_extract(s.row_json,'$.metrics.return1d') END":`s.${q.axis}`
  const rank=q.axis==='return1d'?`CASE WHEN (${value}) IS NOT NULL THEN ROW_NUMBER() OVER (PARTITION BY m.market_date ORDER BY (${value}) DESC,s.sector_id) END`:`s.${q.axis}_rank`
  const result = await db.prepare(`WITH chosen AS (SELECT m.batch_id,m.market_date,ROW_NUMBER() OVER (PARTITION BY m.market_date ORDER BY ${chronological}) AS ordinal FROM sector_rotation_v04_manifests m WHERE ${active} AND (m.official_close=1 OR m.market_date=?) AND m.observed_at<=?), days AS (SELECT batch_id,market_date FROM chosen WHERE ordinal=1 ORDER BY market_date DESC LIMIT ?) SELECT s.sector_id,s.sector_name,${value} AS axis_value,${rank} AS axis_rank,json_object('membershipMode',json_extract(s.row_json,'$.membershipMode')) AS row_json,m.market_date FROM ${joined} JOIN days d ON d.batch_id=m.batch_id WHERE ${active} AND s.universe=? ORDER BY s.sector_id,m.market_date`).bind(...versionValues,m.market_date,m.observed_at,q.days,...versionValues,q.universe).all()
  if (!result.results.length) return null
  const dates = [...new Set(result.results.map(r => r.market_date))].sort().reverse(), grouped = new Map()
  for (const r of result.results) { if (!grouped.has(r.sector_id)) grouped.set(r.sector_id,{id:r.sector_id,name:r.sector_name,values:new Map()}); grouped.get(r.sector_id).values.set(r.market_date,{marketDate:r.market_date,score:r.axis_value,rank:r.axis_rank}) }
  return { ...metadata(m,result.results), ...q, dates, liveDate:m.official_close?null:m.market_date, rows: [...grouped.values()].map(r => ({id:r.id,name:safeText(r.name)?r.name:r.id,values:dates.map(d => r.values.get(d) ?? {marketDate:d,score:null,rank:null})})) }
}
async function readDetail(db,m,q) {
  // A corrected publication may reuse an observation timestamp. Choose the same
  // whole-batch winner as latest before sector filtering and the date window.
  const result = await db.prepare(`
    WITH canonical AS (
      SELECT m.*, ROW_NUMBER() OVER (PARTITION BY m.observed_at ORDER BY ${chronological}) AS ordinal
      FROM sector_rotation_v04_manifests m WHERE ${active} AND m.observed_at<=?
    ), dates AS (
      SELECT DISTINCT m.market_date FROM sector_rotation_v04_sectors s
      JOIN canonical m ON m.batch_id=s.batch_id
      WHERE m.ordinal=1 AND s.universe=? AND s.sector_id=?
      ORDER BY m.market_date DESC LIMIT ?
    )
    SELECT s.*,m.observed_at,m.market_date,m.session,m.official_close
    FROM sector_rotation_v04_sectors s JOIN canonical m ON m.batch_id=s.batch_id
    JOIN dates d ON d.market_date=m.market_date
    WHERE m.ordinal=1 AND s.universe=? AND s.sector_id=?
    ORDER BY m.observed_at
  `).bind(...versionValues,m.observed_at,q.universe,q.id,q.days,q.universe,q.id).all()
  if (!result.results.length) return null
  const closes = await db.prepare(`WITH ranked AS (SELECT m.batch_id,m.market_date,ROW_NUMBER() OVER (PARTITION BY m.market_date ORDER BY ${chronological}) AS ordinal FROM sector_rotation_v04_manifests m WHERE ${active} AND m.official_close=1 AND m.market_date<?) SELECT m.market_date,s.strength,s.opportunity,s.risk FROM ranked m LEFT JOIN sector_rotation_v04_sectors s ON s.batch_id=m.batch_id AND s.universe=? AND s.sector_id=? WHERE m.ordinal=1 ORDER BY m.market_date DESC`).bind(...versionValues,m.market_date,q.universe,q.id).all()
  const priorFor = date => closes.results.find(r => r.market_date < date)
  // The current observation uses the same derived dynamic membership as catalog/latest.
  // Historical observations retain their published role evidence.
  let currentRoles = new Map()
  if (q.universe === 'concept') {
    const current = await batchRows(db,m.batch_id,q.universe), prior = await baseline(db,m.market_date,q.universe)
    currentRoles = new Map(applyConceptRoles(entries(current,prior)).map(r => [r.public.id,r.public.conceptRole]))
  }
  return { ...metadata(m,result.results), ...q, history: result.results.map(r => {
    const item = project(r,priorFor(r.market_date))
    if (r.batch_id === m.batch_id && currentRoles.has(item.id)) item.conceptRole = currentRoles.get(item.id)
    return {...item,observedAt:r.observed_at,marketDate:r.market_date,session:r.session,officialClose:!!r.official_close}
  }) }

}
export async function v4Read(context,kind) {
  const query = parseV4Query(context.request,kind)
  if (!query) return errorResponse('INVALID_QUERY',400)
  try {
    const db = context.env.MARKET_DB, manifest = await latestManifest(db)
    if (!manifest) return errorResponse('NO_SNAPSHOT',404)
    const payload = await ({latest:readLatest,catalog:readCatalog,history:readHistory,detail:readDetail}[kind])(db,manifest,query)
    return payload ? jsonResponse(payload,200,'public, max-age=30, s-maxage=60') : errorResponse('NO_SNAPSHOT',404)
  } catch { return errorResponse('STORAGE_UNAVAILABLE',503) }
}
