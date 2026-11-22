import {validDate} from '../cross-market-risk/parsers.mjs'
export const ETF_VERSION='etf-observation-v1'
export const CORE_ETFS=Object.freeze([
 {code:'510300.SH',name:'华泰柏瑞',exchange:'SSE'},
 {code:'510310.SH',name:'易方达',exchange:'SSE'},
 {code:'510330.SH',name:'华夏',exchange:'SSE'},
 {code:'159919.SZ',name:'嘉实',exchange:'SZSE'},
])
const positive=x=>typeof x==='number'&&Number.isFinite(x)&&x>0&&x<1e16
const maybe=x=>x===null||positive(x)
const ensure=x=>{if(!x)throw Error('INVALID_ETF_OBSERVATION')}
function shape(value,required,optional=[]){ensure(value&&typeof value==='object'&&!Array.isArray(value)&&required.every(k=>Object.hasOwn(value,k))&&Object.keys(value).every(k=>required.includes(k)||optional.includes(k)))}
function ordered(rows,max=2000){let prior='';ensure(Array.isArray(rows)&&rows.length<=max);for(const r of rows){ensure(validDate(r.date)&&r.date>prior);prior=r.date}}
export function validateEtfBundle(b,now=Date.now()){
 shape(b,['schemaVersion','capBasis','generatedAt','sessions','funds','marketCaps','indexCloses','sources'],['notes','cached'])
 ensure(b?.schemaVersion===ETF_VERSION&&typeof b.generatedAt==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(b.generatedAt)&&Number.isFinite(Date.parse(b.generatedAt))&&Date.parse(b.generatedAt)<=now+300000)
 ensure(b.capBasis==='circulating-a-share')
 ensure(Array.isArray(b.sessions)&&b.sessions.length>0&&b.sessions.length<=2000)
 ordered(b.sessions.map(date=>({date})));const latest=b.sessions.at(-1),today=new Date(now+8*3600000).toISOString().slice(0,10);ensure(latest<=today)
 ensure(Array.isArray(b.funds)&&b.funds.length===4)
 for(const [i,f] of b.funds.entries()){
  shape(f,['code','name','exchange','points']);ensure(typeof f.name==='string'&&f.name.length<50)
  ensure(f.code===CORE_ETFS[i].code&&f.exchange===CORE_ETFS[i].exchange);ordered(f.points)
  for(const p of f.points){shape(p,['date','shares','nav','splitFactor']);ensure(p.date<=latest&&maybe(p.shares)&&maybe(p.nav)&&(!positive(p.shares)||Number.isSafeInteger(p.shares))&&(p.splitFactor===null||positive(p.splitFactor)&&p.splitFactor<=100))}
 }
 ordered(b.indexCloses);for(const p of b.indexCloses){shape(p,['date','value']);ensure(p.date<=latest&&positive(p.value))}
 ordered(b.marketCaps);for(const c of b.marketCaps){shape(c,['date','value']);ensure(c.date<=latest&&positive(c.value))}
 ensure(Array.isArray(b.sources)&&b.sources.length>0&&b.sources.length<=12&&b.sources.every(s=>typeof s.id==='string'&&typeof s.url==='string'&&s.url.startsWith('https://')))
 for(const source of b.sources){shape(source,['id','url'],['note']);ensure(['SSE','SZSE','Hithink','MX','Tencent'].includes(source.id));const u=new URL(source.url);ensure(!u.username&&!u.password&&!u.search&&!u.hash&&source.url.length<300)}
 ensure(b.notes===undefined||Array.isArray(b.notes)&&b.notes.length<=10&&b.notes.every(n=>typeof n==='string'&&n.length<600))
 ensure(b.cached===undefined||typeof b.cached==='boolean')
 ensure(new TextEncoder().encode(JSON.stringify(b)).length<1500000)
 return b
}
function tenThousand(value){const s=String(value??'').replaceAll(',','').trim();if(!/^\d+(?:\.\d{1,4})?$/.test(s))throw Error('INVALID_SHARE_UNIT');const [a,b='']=s.split('.');const n=Number(a)*10000+Number(b.padEnd(4,'0'));if(!Number.isSafeInteger(n)||n<=0)throw Error('INVALID_SHARE_VALUE');return n}
function unique(rows){const m=new Map();for(const r of rows){ensure(validDate(r.date));if(m.has(r.date)&&m.get(r.date).shares!==r.shares)throw Error('CONFLICTING_SHARES');m.set(r.date,r)}return [...m.values()].sort((a,b)=>a.date.localeCompare(b.date))}
export function parseSseShares(raw,code){ensure(CORE_ETFS.some(f=>f.code===code&&f.exchange==='SSE')&&Array.isArray(raw?.result));return unique(raw.result.map(r=>{ensure(r.SEC_CODE===code.slice(0,6));return {date:r.STAT_DATE,shares:tenThousand(r.TOT_VOL)}}))}
export function parseSzseShares(raw,code){ensure(code==='159919.SZ'&&Array.isArray(raw));const tab=raw.find(t=>Array.isArray(t.data));ensure(tab);return unique(tab.data.map(r=>{ensure(String(r.zqdm??r.fund_code??'').trim()===code.slice(0,6));return {date:r.size_date,shares:tenThousand(r.current_size)}}))}
function netFlow(previous,current,previousIndex,index){
 if(!positive(previous?.shares)||!positive(current?.shares)||!positive(current?.nav)||!positive(previous?.nav)||!positive(previousIndex)||!positive(index))return null
 const factor=current.splitFactor??1
 // An unverified NAV discontinuity may be a split/distribution/source mismatch.
 // Compare with same-date CSI300 return, not asset conservation (subscriptions can coincide).
 const relative=(current.nav*factor/previous.nav)/(index/previousIndex)-1
 if(Math.abs(relative)>.005)return null
 return (current.shares-previous.shares*factor)*current.nav
}
export function deriveEtfObservation(input){
 const b=validateEtfBundle(input),maps=b.funds.map(f=>new Map(f.points.map(p=>[p.date,p]))),caps=new Map(b.marketCaps.map(p=>[p.date,p.value])),closes=new Map(b.indexCloses.map(p=>[p.date,p.value]))
 const flows=maps.map(m=>b.sessions.map((d,i)=>i>0?netFlow(m.get(b.sessions[i-1]),m.get(d),closes.get(b.sessions[i-1]),closes.get(d)):null))
 const series=b.sessions.map((date,i)=>{
  const points=maps.map(m=>m.get(date)),fundCount=points.filter(p=>positive(p?.shares)&&positive(p?.nav)).length
  const assetsCny=fundCount===4?points.reduce((sum,p)=>sum+p.shares*p.nav,0):null,capCny=caps.get(date)??null,fs=flows.map(r=>r[i])
  return {date,assetsCny,capCny,ratioPct:assetsCny!==null&&capCny!==null?assetsCny/capCny*100:null,estimatedFlowCny:fs.every(Number.isFinite)?fs.reduce((a,v)=>a+v,0):null,fundCount}
 })
 const date=[...b.sessions].reverse().find(d=>maps.every(m=>positive(m.get(d)?.shares)))??null,index=b.sessions.indexOf(date)
 const sumFlow=(row,n)=>index>=n&&row.slice(index-n+1,index+1).every(Number.isFinite)?row.slice(index-n+1,index+1).reduce((a,v)=>a+v,0):null
 const funds=b.funds.map((f,i)=>{const p=maps[i].get(date),change=n=>{const before=maps[i].get(b.sessions[index-n]);return positive(p?.shares)&&positive(before?.shares)?p.shares-before.shares:null};return {...CORE_ETFS[i],date,shares:p?.shares??null,change1d:change(1),change5d:change(5),change20d:change(20),nav:p?.nav??null,assetsCny:positive(p?.shares)&&positive(p?.nav)?p.shares*p.nav:null,flow1d:sumFlow(flows[i],1),flow5d:sumFlow(flows[i],5),flow20d:sumFlow(flows[i],20)}})
 const point=series.find(p=>p.date===date),totals=n=>{const xs=funds.map(f=>f['flow'+n+'d']);return xs.every(Number.isFinite)?xs.reduce((a,v)=>a+v,0):null}
 return {date,generatedAt:b.generatedAt,funds,series,ratioPct:point?.ratioPct??null,assetsCny:point?.assetsCny??null,flow1d:totals(1),flow5d:totals(5),flow20d:totals(20),cached:b.cached===true,notes:b.notes??[],scope:'核心4只沪深300ETF；非全市场ETF、非国家队持仓'}
}
