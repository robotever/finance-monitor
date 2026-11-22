import {validDate} from '../../src/features/cross-market-risk/parsers.mjs'
const ids=['ashare','large','small','value','growth','dividend','tech']
const sources=['MX','Hithink','CSI','Eastmoney']
const keys=(x,allowed)=>x&&typeof x==='object'&&!Array.isArray(x)&&Object.keys(x).every(k=>allowed.includes(k))&&allowed.every(k=>k in x)
const check=x=>{if(!x)throw Error('INVALID_RADAR_INPUTS')}
const count=x=>Number.isSafeInteger(x)&&x>=0
const number=x=>typeof x==='number'&&Number.isFinite(x)&&Math.abs(x)<=1e16
export function validateInputs(p,now=Date.now()){
 check(keys(p,['schemaVersion','observedAt','marketDate','objects']))
 check(p.schemaVersion==='radar-inputs-v1'&&typeof p.observedAt==='string'&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(p.observedAt)&&Number.isFinite(Date.parse(p.observedAt))&&Date.parse(p.observedAt)<=now+300000)
 p.observedAt=new Date(p.observedAt).toISOString()
 check(validDate(p.marketDate)&&p.marketDate<=new Date(now+8*3600000).toISOString().slice(0,10)&&p.marketDate<=new Date(Date.parse(p.observedAt)+8*3600000).toISOString().slice(0,10))
 check(keys(p.objects,ids))
 for(const id of ids){
  const o=p.objects[id];check(keys(o,['id','scope','sources','membershipAsOf','history'])&&o.id===id&&typeof o.scope==='string'&&o.scope.length>0&&o.scope.length<200)
  check(Array.isArray(o.sources)&&o.sources.every(s=>sources.includes(s))&&new Set(o.sources).size===o.sources.length)
  check(o.membershipAsOf===null||validDate(o.membershipAsOf)&&o.membershipAsOf<=new Date(now+8*3600000).toISOString().slice(0,10))
  check(Array.isArray(o.history)&&o.history.length<=320)
  let date=''
  for(const r of o.history){
   check(keys(r,['date','up','down','flat','turnover','mainNetFlow','fundMatched','fundExpected','membershipMode']))
   check(validDate(r.date)&&r.date>date&&r.date<=p.marketDate);date=r.date
   check(['provider-aggregate','current-members'].includes(r.membershipMode))
   const counts=[r.up,r.down,r.flat];check(counts.every(v=>v===null)||counts.every(count)&&counts.reduce((a,b)=>a+b,0)>0)
   check(r.turnover===null||number(r.turnover)&&r.turnover>0)
   check(r.mainNetFlow===null||number(r.mainNetFlow))
   check(r.fundMatched===null||count(r.fundMatched));check(r.fundExpected===null||count(r.fundExpected)&&r.fundExpected>0)
   if(r.membershipMode==='current-members')check(o.membershipAsOf!==null)
   if(r.mainNetFlow!==null){
    check(r.turnover!==null&&Math.abs(r.mainNetFlow)<=r.turnover*1.05)
    if(id!=='ashare'||r.membershipMode==='current-members')check(r.fundMatched!==null&&r.fundMatched===r.fundExpected)
   }
   if(r.fundMatched!==null&&r.fundExpected!==null){check(r.fundMatched<=r.fundExpected);if(r.membershipMode==='current-members'&&counts.every(count))check(counts.reduce((a,b)=>a+b,0)<=r.fundExpected)}
  }
 }
 check(new TextEncoder().encode(JSON.stringify(p)).length<=500000)
 return p
}
export const INPUTS_QUERY='SELECT payload_json FROM radar_input_batches ORDER BY market_date DESC, julianday(observed_at) DESC, observed_at DESC LIMIT 1'
export async function readInputs(db,now=Date.now()){
 if(!db)return null
 try{const row=await db.prepare(INPUTS_QUERY).first();return row?validateInputs(JSON.parse(row.payload_json),now):null}catch{return null}
}
