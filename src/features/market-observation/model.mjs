import {validDate} from '../cross-market-risk/parsers.mjs'
export const MARKET_OBSERVATION_VERSION='market-observation-v1'
export const OBSERVATION_METRICS={breadth:['upShare','upCount','downCount','medianChange'],trend:['ma20Share','ma60Share','high20Share','low20Share','high60Share','low60Share'],turnover:['turnoverCny','top10pctShare','dailyVolumeRatio20','dailyVolumePercentile'],relay:['upCount','downCount','sealRate','yesterdayReturn','promotionRate']}
const check=x=>{if(!x)throw Error('INVALID_MARKET_OBSERVATION')}
const finite=x=>typeof x==='number'&&Number.isFinite(x)&&Math.abs(x)<1e16
const count=x=>Number.isSafeInteger(x)&&x>=0&&x<=100000
const text=(x,max=500)=>typeof x==='string'&&x.length<=max
function shape(x,required,optional=[]){check(x&&typeof x==='object'&&!Array.isArray(x)&&required.every(k=>Object.hasOwn(x,k))&&Object.keys(x).every(k=>required.includes(k)||optional.includes(k)))}
function date(x){check(validDate(x));return x}
function instant(x){check(text(x,50)&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(x)&&validDate(x.slice(0,10))&&Number.isFinite(Date.parse(x)));return Date.parse(x)}
function asOf(x,observed){if(validDate(x)){check(x<=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date(observed)));return x;}check(instant(x)<=observed+300000);return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date(x))}
const approx=(a,b)=>Math.abs(a-b)<1e-6
export function validateMarketObservation(p,now=Date.now()){
 shape(p,['schemaVersion','observedAt','marketDate','previousMarketDate','snapshotAt','scope','groups','details','sources','notes'],['cached'])
 check(p.schemaVersion===MARKET_OBSERVATION_VERSION);const observed=instant(p.observedAt);check(observed<=now+300000)
 date(p.marketDate);date(p.previousMarketDate);check(p.previousMarketDate<p.marketDate&&asOf(p.snapshotAt,observed)===p.marketDate&&p.marketDate<=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date(observed)))
 const s=p.scope;shape(s,['name','expected','received','active','excluded','historyMatched','historyExpected','historyAsOf']);check(text(s.name,150)&&[s.expected,s.received,s.active,s.excluded,s.historyMatched,s.historyExpected].every(count)&&s.expected>0&&s.expected===s.received&&s.active+s.excluded===s.received&&s.historyMatched<=s.historyExpected&&s.historyExpected<=s.received);date(s.historyAsOf);check(s.historyAsOf<=p.marketDate)
 check(Array.isArray(p.groups)&&p.groups.length===4&&new Set(p.groups.map(g=>g.id)).size===4)
 const vals={}
 for(const g of p.groups){shape(g,['id','title','asOf','metrics']);check(Object.hasOwn(OBSERVATION_METRICS,g.id)&&text(g.title,80));asOf(g.asOf,observed);const expected=OBSERVATION_METRICS[g.id];check(Array.isArray(g.metrics)&&g.metrics.length===expected.length&&new Set(g.metrics.map(m=>m.id)).size===expected.length)
  vals[g.id]={}
  for(const m of g.metrics){shape(m,['id','label','value','unit','date','mode','sample','reason']);check(expected.includes(m.id)&&text(m.label,100)&&['intraday','daily','previous-close'].includes(m.mode)&&(m.sample===null||count(m.sample)&&m.sample<=s.received)&&(m.reason===null||text(m.reason,300)));const day=asOf(m.date,observed);check(day<=p.marketDate)
   const unit=['upCount','downCount'].includes(m.id)?'家':m.id==='turnoverCny'?'亿元':m.id==='dailyVolumeRatio20'?'倍':'%';check(m.unit===unit&&(m.value===null||finite(m.value)))
   if(m.value!==null){check(m.sample===null||m.sample>0);if(unit==='家')check(count(m.value)&&m.value<=s.received);else if(!['medianChange','yesterdayReturn'].includes(m.id))check(m.value>=0&&(unit!=='%'||m.value<=100))}
   if(g.id==='trend'){check(m.mode==='daily'&&day===s.historyAsOf)}
   if(['dailyVolumeRatio20','dailyVolumePercentile'].includes(m.id))check(m.mode==='daily'&&day===s.historyAsOf)
   vals[g.id][m.id]=m.value
  }
 }
 shape(p.details,['distribution','relay','dragonTiger','abnormal']);const d=p.details
 check(Array.isArray(d.distribution)&&d.distribution.length<=20&&d.distribution.every(r=>{shape(r,['label','count']);return text(r.label,40)&&count(r.count)})&&d.distribution.reduce((a,r)=>a+r.count,0)===s.active)
 if(s.active&&vals.breadth.upShare!==null&&vals.breadth.upCount!==null)check(approx(vals.breadth.upShare,vals.breadth.upCount/s.active*100))
 if(vals.breadth.upCount!==null&&vals.breadth.downCount!==null)check(vals.breadth.upCount+vals.breadth.downCount<=s.active)
 const r=d.relay;shape(r,['date','asOf','status','sourceSealRate','upCount','downCount','openCount','touchedCount','ladder','yesterdayLimitUp'],['downAsOf','upPoolAsOf']);check(r.date===p.marketDate&&['ok','failed'].includes(r.status));asOf(r.asOf,observed)
 for(const key of ['downAsOf','upPoolAsOf'])if(r[key]!==undefined)asOf(r[key],observed)
 for(const key of ['upCount','downCount','openCount','touchedCount'])check(r[key]===null||count(r[key])&&r[key]<=s.received)
 check(r.sourceSealRate===null||finite(r.sourceSealRate)&&r.sourceSealRate>=0&&r.sourceSealRate<=1)
 if(r.sourceSealRate!==null&&vals.relay.sealRate!==null)check(approx(r.sourceSealRate*100,vals.relay.sealRate))
 if(r.upCount!==null&&r.openCount!==null&&r.touchedCount!==null)check(r.upCount+r.openCount===r.touchedCount)
 check(Array.isArray(r.ladder)&&r.ladder.length<=100&&new Set(r.ladder.map(x=>x.boards)).size===r.ladder.length)
 for(const row of r.ladder){shape(row,['boards','count']);check(Number.isSafeInteger(row.boards)&&row.boards>=2&&row.boards<100&&count(row.count))}
 const y=r.yesterdayLimitUp;shape(y,['date','expected','matched','meanReturn','promotionRate'],['poolAsOf']);check(y.date===p.previousMarketDate&&count(y.expected)&&count(y.matched)&&y.matched<=y.expected&&(y.meanReturn===null||finite(y.meanReturn))&&(y.promotionRate===null||finite(y.promotionRate)&&y.promotionRate>=0&&y.promotionRate<=100));if(y.poolAsOf!==undefined)asOf(y.poolAsOf,observed)
 const dt=d.dragonTiger;shape(dt,['date','asOf','status','rows','note']);check(dt.date===p.previousMarketDate&&['ok','failed'].includes(dt.status)&&(dt.note===null||text(dt.note,600)));asOf(dt.asOf,observed);check(Array.isArray(dt.rows)&&dt.rows.length<=2000)
 for(const row of dt.rows){shape(row,['code','name','netCny','buyCny','sellCny'],['rangeDays']);check((row.code===null||/^\d{6}\.(SH|SZ|BJ)$/.test(row.code))&&(row.name===null||text(row.name,100))&&[row.netCny,row.buyCny,row.sellCny].every(v=>v===null||finite(v))&&(row.rangeDays===undefined||row.rangeDays===null||count(row.rangeDays)))}
 const ab=d.abnormal;shape(ab,['asOf','status','rows'],['note']);check(['ok','failed'].includes(ab.status)&&(ab.note===undefined||ab.note===null||text(ab.note,600)));asOf(ab.asOf,observed);check(Array.isArray(ab.rows)&&ab.rows.length<=2000)
 for(const row of ab.rows){shape(row,['code','name','startDate','endDate','label']);check((row.code===null||text(row.code,30))&&(row.name===null||text(row.name,100))&&text(row.label,150));date(row.startDate);if(row.endDate!==null){date(row.endDate);check(row.endDate>=row.startDate)}}
 check(Array.isArray(p.sources)&&p.sources.length>0&&p.sources.length<=200)
 for(const source of p.sources){shape(source,['id','url','asOf']);check(text(source.id,150));const u=new URL(source.url);check(u.protocol==='https:'&&u.hostname==='fuyao.aicubes.cn'&&!u.port&&!u.username&&!u.password&&!u.hash&&(u.pathname==='/'||u.pathname.startsWith('/api/')||u.pathname.startsWith('/docs/')));for(const key of u.searchParams.keys())check(!/key|token|secret|signature/i.test(key));asOf(source.asOf,observed)}
 check(Array.isArray(p.notes)&&p.notes.length<=30&&p.notes.every(n=>text(n,1200))&&(p.cached===undefined||typeof p.cached==='boolean'))
 check(new TextEncoder().encode(JSON.stringify(p)).length<1000000);return p
}
