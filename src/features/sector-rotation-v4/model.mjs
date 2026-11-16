export const VERSIONS = Object.freeze({schemaVersion:'market-dashboard-v4',sectorScoringVersion:'sector-score-v0.3',sectorUniverseVersion:'sector-universe-ths-v1',featureVersion:'sector-features-ths-v1',membershipVersion:'sector-membership-ths-v1'})
export const AXES = ['strength','opportunity','risk']
export const VIEWS = [{key:'potential',label:'潜在轮动'},{key:'main',label:'主线确认'},{key:'risk',label:'风险升温'}]
const modes = ['current_members_backfill','point_in_time_snapshot']
const record = v => v !== null && typeof v==='object' && !Array.isArray(v)
const int = (v,min,max) => Number.isInteger(v)&&v>=min&&v<=max
const score = v => v===null||int(v,0,100)
const check = v => { if(!v) throw Error('INVALID_SCHEMA') }
const identity = (id,u) => (u==='industry'?/^881\d{3}\.TI$/:/^88[56]\d{3}\.TI$/).test(id)
const date = v => typeof v==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(v)&&Number.isFinite(Date.parse(v))
const timestamp = v => typeof v==='string'&&Number.isFinite(Date.parse(v))
const text = v => typeof v==='string'&&v.length>0&&v.length<=200
export function validateMetadata(p) {
 check(record(p)&&Object.entries(VERSIONS).every(([k,v])=>p[k]===v)&&p.sourceMode==='hithink'&&text(p.batchId))
 check(timestamp(p.observedAt)&&date(p.marketDate)&&new Date(Date.parse(p.observedAt)+8*3600000).toISOString().slice(0,10)===p.marketDate)
 check(['close','intraday'].includes(p.session)&&p.officialClose===(p.session==='close')&&typeof p.approximateHistory==='boolean')
 check(Array.isArray(p.membershipModes)&&p.membershipModes.every(m=>modes.includes(m)))
 return p
}
function validateRow(r,u) {
 check(record(r)&&r.universe===u&&identity(r.id,u)&&text(r.name)&&AXES.every(a=>score(r[a]))&&int(r.completeness,0,100))
 check(record(r.ranks)&&AXES.every(a=>r.ranks[a]===null||int(r.ranks[a],1,u==='industry'?90:10000)))
 check(record(r.change1d)&&AXES.every(a=>r.change1d[a]===null||int(r.change1d[a],-100,100)))
 check([null,'cold','neutral','warming','active','crowded'].includes(r.heatState)&&typeof r.coldStart==='boolean'&&int(r.validCloses,0,100000)&&int(r.improvementEvidence,0,4))
 check(modes.includes(r.membershipMode)&&[null,'core','dynamic','candidate'].includes(r.conceptRole)&&typeof r.approximateHistory==='boolean'&&Array.isArray(r.missing)&&r.missing.every(text))
 return r
}
function validateRows(rows,u,max) {check(Array.isArray(rows)&&rows.length<=max&&new Set(rows.map(r=>r.id)).size===rows.length);rows.forEach(r=>validateRow(r,u))}
export function validateLatest(p) {
 validateMetadata(p)
 for(const u of ['industry','concept']) {check(record(p[u]));for(const v of VIEWS)validateRows(p[u][v.key],u,10)}
 validateRows(p.concept.core,'concept',25);validateRows(p.concept.dynamic,'concept',10)
 check(p.concept.core.every(r=>r.conceptRole==='core')&&!p.concept.dynamic.some(r=>p.concept.core.some(c=>c.id===r.id)))
 return p
}
export function selectSectorAdapter(enabled,p) {if(!enabled||!p)return 'v3';try{validateLatest(p);return 'v4'}catch{return 'v3'}}
export function deriveBoard(p,now=new Date()) {
 validateLatest(p)
 const age = now.getTime()-Date.parse(p.observedAt)
 const stale = age>(p.officialClose?3*24*3600000:30*60000)
 return {...p,sourceLabel:'同花顺 Hithink · 仅板块数据',stale,freshnessLabel:stale?'已过期 · 保留最后有效快照':p.officialClose?'正式收盘快照':'盘中快照 · 15分钟更新',warning:p.approximateHistory?'历史使用当前成分回填，存在幸存者偏差，非严格时点历史。':'历史使用当时成分快照。'}
}
export function buildHistoryMatrix(p) {
 return Array.from({length:10},(_,i)=>({rank:i+1,cells:p.dates.map(d=>{const r=p.rows.find(r=>r.values.some(v=>v.marketDate===d&&v.rank===i+1));if(!r)return null;return {...r,...r.values.find(v=>v.marketDate===d),values:undefined}})}))
}
export function catalogQuery(o={}) {
 const {universe,page=1,pageSize=50,q='',view='all',role='all'}=o
 if(!['industry','concept'].includes(universe)||!int(page,1,Number.MAX_SAFE_INTEGER)||!int(pageSize,1,100)||typeof q!=='string'||q.length>100||!['all',...VIEWS.map(v=>v.key)].includes(view)||!['all','core','dynamic','candidate'].includes(role)||universe==='industry'&&role!=='all')throw Error('INVALID_QUERY')
 const p=new URLSearchParams({universe,page:String(page),pageSize:String(pageSize)})
 if(q)p.set('q',q);if(view!=='all')p.set('view',view);if(role!=='all')p.set('role',role)
 return p
}
export function validateCatalog(p,o) {
 validateMetadata(p);check(p.universe===o.universe&&p.page===(o.page??1)&&p.pageSize===(o.pageSize??50)&&p.q===(o.q??'')&&p.view===(o.view??'all')&&p.role===(o.role??'all')&&int(p.total,0,10000));validateRows(p.sectors,p.universe,p.pageSize);return p
}
export function validateHistory(p,o) {
 validateMetadata(p);check(p.universe===o.universe&&p.axis===o.axis&&p.days===(o.days??15)&&Array.isArray(p.dates)&&p.dates.length<=p.days&&p.dates.every((d,i)=>date(d)&&(!i||d>p.dates[i-1]))&&Array.isArray(p.rows))
 check(new Set(p.rows.map(r=>r.id)).size===p.rows.length)
 for(const r of p.rows) {check(identity(r.id,p.universe)&&text(r.name)&&r.values.length===p.dates.length);r.values.forEach((v,i)=>check(v.marketDate===p.dates[i]&&score(v.score)&&(v.rank===null||int(v.rank,1,p.universe==='industry'?90:10000))))}
 return p
}
export function validateDetail(p,o) {
 validateMetadata(p);check(p.universe===o.universe&&p.id===o.id&&p.days===(o.days??60)&&Array.isArray(p.history)&&p.history.length>0)
 p.history.forEach((r,i)=>{validateRow(r,p.universe);check(r.id===p.id&&timestamp(r.observedAt)&&date(r.marketDate)&&r.officialClose===(r.session==='close')&&(!i||r.observedAt>p.history[i-1].observedAt))});return p
}
