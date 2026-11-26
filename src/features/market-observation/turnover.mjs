import {validDate} from '../cross-market-risk/parsers.mjs'
const fail=()=>{throw Error('INVALID_TURNOVER_STRUCTURE')}
const check=x=>{if(!x)fail()}
const shape=(x,keys)=>check(x&&typeof x==='object'&&!Array.isArray(x)&&keys.length===Object.keys(x).length&&keys.every(k=>Object.hasOwn(x,k)))
const txt=(s,n=1000)=>typeof s==='string'&&s.length<=n
const money=x=>x===null||typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<1e16
const signed=x=>typeof x==='number'&&Number.isFinite(x)&&Math.abs(x)<1e16
const approx=(a,b)=>Math.abs(a-b)<=Math.max(0.01,Math.abs(b)*1e-9)
const ids=['all','sh','sz','chinext','star']
function instant(x,now){check(txt(x,50)&&/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})$/.test(x)&&validDate(x.slice(0,10))&&Number.isFinite(Date.parse(x))&&Date.parse(x)<=now+300000);return new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(x))}
function hierarchy(v){if(v.all!==null&&v.sh!==null&&v.sz!==null)check(v.all+1>=v.sh+v.sz);if(v.chinext!==null&&v.sz!==null)check(v.chinext<=v.sz+1);if(v.star!==null&&v.sh!==null)check(v.star<=v.sh+1)}
export function validateTurnover(p,now=Date.now()){
 shape(p,['version','date','previousDate','asOf','comparisonTime','rows','history','sources','notes']);check(p.version==='turnover-structure-v1'&&validDate(p.date)&&validDate(p.previousDate)&&p.previousDate<p.date);const latest=instant(p.asOf,now);check(latest.slice(0,10)>=p.date)
 check(p.comparisonTime===null||typeof p.comparisonTime==='string'&&/^(?:09:(?:3\d|[45]\d)|10:[0-5]\d|11:(?:[0-2]\d|30)|13:[0-5]\d|14:[0-5]\d|15:00)$/.test(p.comparisonTime))
 check(Array.isArray(p.rows)&&p.rows.length===5&&p.rows.every((r,i)=>r.id===ids[i]));const values={}
 for(const r of p.rows){shape(r,['id','name','comparisonMode','currentCny','currentAsOf','previousSameTimeCny','changeCny','changePct','comparisonAsOf','reason']);check(['same-minute','daily-close','unavailable'].includes(r.comparisonMode)&&txt(r.name,80)&&money(r.currentCny)&&money(r.previousSameTimeCny)&&(r.reason===null||txt(r.reason,500)));const current=instant(r.currentAsOf,now);check(current.slice(0,10)===p.date);values[r.id]=r.currentCny
  if(r.previousSameTimeCny===null){check(r.comparisonMode==='unavailable'&&r.changeCny===null&&r.changePct===null&&r.comparisonAsOf===null&&txt(r.reason,500)&&r.reason.length>0)}
  else{check(r.currentCny!==null&&r.comparisonMode!=='unavailable'&&r.comparisonAsOf!==null);if(r.comparisonMode==='daily-close')check(current.slice(11,16)>='15:30'&&r.comparisonAsOf===p.previousDate);else{check(p.comparisonTime!==null);const prev=instant(r.comparisonAsOf,now);check(prev.slice(0,10)===p.previousDate&&prev.slice(11,16)===p.comparisonTime&&current.slice(11,16)===p.comparisonTime)}check(signed(r.changeCny)&&approx(r.changeCny,r.currentCny-r.previousSameTimeCny));if(r.previousSameTimeCny>0)check(signed(r.changePct)&&approx(r.changePct,(r.currentCny/r.previousSameTimeCny-1)*100));else check(r.changePct===null)}
 }
 hierarchy(values)
 const h=p.history;shape(h,['startDate','endDate','asOf','points']);check(validDate(h.startDate)&&validDate(h.endDate)&&h.startDate<=h.endDate&&h.endDate<=p.previousDate);instant(h.asOf,now);check(Array.isArray(h.points)&&h.points.length>0&&h.points.length<=370)
 let before='';for(const r of h.points){shape(r,['date',...ids]);check(validDate(r.date)&&r.date>before&&r.date>=h.startDate&&r.date<=h.endDate&&ids.every(id=>money(r[id])));before=r.date;hierarchy(r)}
 check(Array.isArray(p.sources)&&p.sources.length>0&&p.sources.length<=100)
 for(const s of p.sources){shape(s,['id','url','asOf']);check(txt(s.id,150)&&txt(s.url,2000));const u=new URL(s.url);check(u.protocol==='https:'&&!u.username&&!u.password&&!u.port&&!u.hash&&((u.hostname==='web.ifzq.gtimg.cn'&&u.pathname==='/appstock/app/day/query')||(u.hostname==='push2his.eastmoney.com'&&u.pathname==='/api/qt/stock/trends2/get')||(u.hostname==='mkapi2.dfcfs.com'&&u.pathname==='/finskillshub/api/claw/query')||(u.hostname==='fuyao.aicubes.cn'&&(u.pathname==='/'||u.pathname.startsWith('/api/')))));for(const k of u.searchParams.keys())check(!/key|token|secret|signature/i.test(k));instant(s.asOf,now)}
 check(Array.isArray(p.notes)&&p.notes.length<=30&&p.notes.every(n=>txt(n,1200)));return p
}
