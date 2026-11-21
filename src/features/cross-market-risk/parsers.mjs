export function numeric(raw){
 if(typeof raw!=='number'&&typeof raw!=='string')return null
 if(typeof raw==='string'&&(!raw.trim()||raw.trim()==='.'))return null
 const n=Number(raw);return Number.isFinite(n)?n:null
}
export function validDate(date){
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date??''))return false
 const n=Date.parse(date+'T00:00:00Z');return Number.isFinite(n)&&new Date(n).toISOString().slice(0,10)===date
}
function point(date,raw,positive=false){const value=numeric(raw);return validDate(date)&&value!==null&&(!positive||value>0)?{date,value}:null}
function csvRows(text,maxRows=400){
 const lines=String(text).trim().replace(/^\uFEFF/,'').split(/\r?\n/)
 const split=line=>line.split(',').map(s=>s.trim().replace(/^"|"$/g,''))
 return {header:split(lines[0]??''),rows:lines.slice(1).slice(-maxRows).map(split)}
}
const isoDate=raw=>{if(/^\d{4}-\d{2}-\d{2}$/.test(raw??''))return raw;const m=/^(\d{2})\/(\d{2})\/(\d{4})$/.exec(raw??'');return m?`${m[3]}-${m[1]}-${m[2]}`:''}
export function parseVix(text){const {header,rows}=csvRows(text),col=header.indexOf('CLOSE');if(col<0)throw Error('INVALID_VIX');return rows.flatMap(r=>point(isoDate(r[0]),r[col],true)??[])}
export function parseNfci(text){
 const {header,rows}=csvRows(text,160),out={nfci:[],credit:[]}
 for(const [key,name] of [['nfci','NFCI'],['credit','Credit']]){const col=header.indexOf(name);if(col<0)throw Error('INVALID_NFCI');out[key]=rows.flatMap(r=>point(isoDate(r[0]),r[col])??[])}
 return out
}
export function parseTreasury(text,fields){
 const out=Object.fromEntries(Object.keys(fields).map(k=>[k,[]]))
 for(const match of String(text).matchAll(/<m:properties\b[^>]*>([\s\S]*?)<\/m:properties>/g)){
  const row=match[1],date=row.match(/<d:NEW_DATE\b[^>]*>([^<]+)<\/d:NEW_DATE>/)?.[1]?.slice(0,10)
  for(const [role,field] of Object.entries(fields)){
   if(!/^[A-Z0-9_]+$/.test(field))throw Error('INVALID_FIELD')
   const raw=row.match(new RegExp(`<d:${field}\\b[^>]*>([^<]*)<\\/d:${field}>`))?.[1]
   const value=point(date,raw);if(value)out[role].push(value)
  }
 }
 return out
}
export function parseNyFed(data,type){
 if(!Array.isArray(data?.refRates))throw Error('INVALID_REFERENCE_RATES')
 return data.refRates.filter(r=>r.type===type).flatMap(r=>point(r.effectiveDate,r.percentRate)??[])
}
export function parseFx(text){
 const data=String(text).match(/var\s+_data=\("([^"\n]*)"\);?\s*$/)?.[1]
 if(!data)throw Error('INVALID_FX')
 return data.split('|').slice(-300).flatMap(row=>{const r=row.split(',');return point(r[0],r[4],true)??[]})
}
export function parseEquity(data,code){
 const row=data?.data?.[code],rows=row?.day??row?.qfqday??row?.fqday
 if(data?.code!==0||!Array.isArray(rows))throw Error('INVALID_EQUITY')
 return rows.flatMap(r=>point(r[0],r[2],true)??[])
}
