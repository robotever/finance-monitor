import {numeric,validDate} from '../cross-market-risk/parsers.mjs'
import {expectedCompletedSession} from './calendar.mjs'
import {normalizeSeries} from '../cross-market-risk/model.mjs'
export const RADAR_VERSION='market-radar-v2'
export const INDEXES=[
 {id:'sp500',name:'标普500',code:'us.INX',kind:'global',market:'us'},
 {id:'ashare',name:'A股市场',indexName:'中证全指',code:'sh000985',kind:'market',market:'china'},
 {id:'large',name:'大盘',indexName:'沪深300',code:'sh000300',kind:'style',market:'china'},
 {id:'small',name:'小盘',indexName:'中证1000',code:'sh000852',kind:'style',market:'china'},
 {id:'value',name:'价值',indexName:'沪深300价值',code:'sh000919',kind:'style',market:'china'},
 {id:'growth',name:'成长',indexName:'创业板指',code:'sz399006',kind:'style',market:'china'},
 {id:'dividend',name:'红利',indexName:'中证红利',code:'sh000922',kind:'style',market:'china'},
 {id:'tech',name:'科技',indexName:'科创50',code:'sh000688',kind:'style',market:'china'},
]
const finite=n=>typeof n==='number'&&Number.isFinite(n)
const clamp=n=>Math.max(0,Math.min(100,n))
const scale=(n,a,b)=>finite(n)?clamp((n-a)/(b-a)*100):null
const mean=a=>a.reduce((n,v)=>n+v,0)/a.length
function orderedBars(rows){
 const byDate=new Map()
 for(const r of Array.isArray(rows)?rows:[]){const close=numeric(r.close),volume=numeric(r.volume);if(validDate(r.date)&&close!==null&&close>0)byDate.set(r.date,{date:r.date,close,volume:volume!==null&&volume>0?volume:null})}
 return [...byDate.values()].sort((a,b)=>a.date.localeCompare(b.date))
}
export function parseRadarBars(data,code){
 const row=data?.data?.[code],rows=row?.day??row?.qfqday
 if(data?.code!==0||!Array.isArray(rows))throw Error('INVALID_RADAR_INDEX')
 return orderedBars(rows.map(r=>({date:r[0],close:r[2],volume:r[5]})))
}
function marketClock(now,market){
 const zone=market==='us'?'America/New_York':'Asia/Shanghai'
 const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:zone,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(now)).map(p=>[p.type,p.value]))
 return {date:`${parts.year}-${parts.month}-${parts.day}`,minute:Number(parts.hour)*60+Number(parts.minute)}
}
export function completedBars(rows,market='china',now=Date.now()){
 const clock=marketClock(now,market),cutoff=market==='us'?17*60+15:15*60+15
 return (rows??[]).filter(r=>validDate(r.date)&&(r.date<clock.date||r.date===clock.date&&clock.minute>=cutoff))
}
function percentile(values,current){return (values.filter(x=>x<current).length+values.filter(x=>x===current).length*.5)/values.length*100}
function factor(key,label,value,unit,score,weight){return {key,label,value,unit,score,weight}}
function weighted(factors){return factors.every(f=>finite(f.score))?factors.reduce((n,f)=>n+f.score*f.weight/100,0):null}
function priceFeatures(rows){
 const last=rows.at(-1),r5=(last.close/rows.at(-6).close-1)*100,r20=(last.close/rows.at(-21).close-1)*100
 const d20=(last.close/mean(rows.slice(-20).map(r=>r.close))-1)*100,d60=(last.close/mean(rows.slice(-60).map(r=>r.close))-1)*100
 const returns=rows.slice(-21).slice(1).map((r,i)=>(r.close/rows.slice(-21)[i].close-1)),avg=mean(returns)
 const vol=Math.sqrt(returns.reduce((n,r)=>n+(r-avg)**2,0)/(returns.length-1))*Math.sqrt(252)*100
 const drawdown=(last.close/Math.max(...rows.slice(-20).map(r=>r.close))-1)*100
 const strength=[factor('return5','5期收益',r5,'%',scale(r5,-5,5),25),factor('return20','20期收益',r20,'%',scale(r20,-10,10),35),factor('ma20','偏离20期均线',d20,'%',scale(d20,-5,5),25),factor('ma60','偏离60期均线',d60,'%',scale(d60,-10,10),15)]
 const risk=[factor('drawdown20','20期回撤',drawdown,'%',scale(-drawdown,0,10),40),factor('volatility20','20期年化波动',vol,'%',scale(vol,10,45),30),factor('downside5','5期下跌',Math.min(0,r5),'%',scale(Math.max(0,-r5),0,6),30)]
 const volume=rows.slice(-60).map(r=>r.volume),prior=rows.slice(-21,-1).map(r=>r.volume),ratio=finite(last.volume)&&prior.every(finite)?last.volume/mean(prior):null
 const vrank=volume.every(finite)?percentile(volume,last.volume):null
 const ratioScore=finite(ratio)?ratio<=1?scale(ratio,.5,1)*.5:50+scale(ratio,1,2)*.5:null
 const heat=[factor('volumeRank','本指数60期成交量分位',vrank,'%',vrank,50),factor('volumeRatio','相对前20期均量',ratio,'倍',ratioScore,50)]
 return {r5,r20,volumeRatio:ratio,factors:{strength,heat,risk}}
}
function inputFeatures(row){
 const counts=row&&[row.up,row.down,row.flat],validCounts=counts&&counts.every(n=>Number.isSafeInteger(n)&&n>=0)&&counts.reduce((a,b)=>a+b,0)>0
 const total=validCounts?counts.reduce((a,b)=>a+b,0):null,up=validCounts?row.up/total*100:null,down=validCounts?row.down/total*100:null
 const covered=row&&(row.membershipMode==='provider-aggregate'||Number.isSafeInteger(row.fundExpected)&&row.fundExpected>0&&row.fundMatched===row.fundExpected)
 const ratio=covered&&finite(row.mainNetFlow)&&finite(row.turnover)&&row.turnover>0&&Math.abs(row.mainNetFlow)<=row.turnover*1.05?row.mainNetFlow/row.turnover*100:null
 return {up,down,ratio,total}
}
export function indexScoreSeries(input,benchmark,limit=Infinity,evidence){
 const rows=orderedBars(input),baseRows=benchmark?orderedBars(benchmark):null,base=baseRows?new Map(baseRows.map(r=>[r.date,r.close])):null,basePositions=baseRows?new Map(baseRows.map((r,i)=>[r.date,i])):null,inputs=new Map((evidence?.history??[]).map(r=>[r.date,r])),out=[]
 for(let i=Math.max(59,rows.length-limit);i<rows.length;i++){
  const window=rows.slice(i-59,i+1),f=priceFeatures(window)
  if(base){
   const relative=period=>{const pos=basePositions.get(rows[i].date),end=base.get(rows[i].date),start=base.get(rows[i-period].date);return baseRows[pos-period]?.date===rows[i-period].date&&finite(end)&&finite(start)?((rows[i].close/rows[i-period].close-1)-(end/start-1))*100:null}
   const r5=relative(5),r20=relative(20)
   f.factors.strength=f.factors.strength.map(x=>({...x,weight:x.weight*.6})).concat([factor('relative5','相对全指5期表现',r5,'个百分点',scale(r5,-4,4),24),factor('relative20','相对全指20期表现',r20,'个百分点',scale(r20,-8,8),16)])
  }
  const row=inputs.get(rows[i].date),real=inputFeatures(row)
  if(evidence){
   f.factors.strength=f.factors.strength.map(x=>({...x,weight:x.weight*.6})).concat([
    factor('advancingShare','上涨占有效交易样本',real.up,'%',real.up,25),
    factor('fundDirection','主力净流入/成交额',real.ratio,'%',scale(real.ratio,-10,10),15)])
   f.factors.risk=f.factors.risk.map(x=>({...x,weight:x.weight*.6})).concat([
    factor('decliningShare','下跌占有效交易样本',real.down,'%',real.down,20),
    factor('fundWithdrawal','主力净流出压力',real.ratio===null?null:Math.max(0,-real.ratio),'%',real.ratio===null?null:scale(Math.max(0,-real.ratio),0,10),20)])
  }
  const inputEvidence=evidence?{date:rows[i].date,up:row?.up??null,down:row?.down??null,flat:row?.flat??null,total:real.total,mainNetFlow:real.ratio===null?null:row.mainNetFlow,turnover:row?.turnover??null,fundRatio:real.ratio,fundMatched:row?.fundMatched??null,fundExpected:row?.fundExpected??null,membershipMode:row?.membershipMode??null,membershipAsOf:evidence.membershipAsOf??null,sources:evidence.sources??[],scope:evidence.scope??''}:null
  const exact=Object.fromEntries(Object.entries(f.factors).map(([axis,factors])=>[axis,weighted(factors)]))
  out.push({date:rows[i].date,...Object.fromEntries(Object.entries(exact).map(([k,v])=>[k,v===null?null:Math.round(v)])),inputEvidence,price:rows[i].close,return5:f.r5,volumeRatio:f.volumeRatio,factors:f.factors})
 }
 return out
}
export function globalScoreSeries(raw,limit=Infinity){
 const ids=['sp500','vix','us10y','real10y','dollar'],series=Object.fromEntries(ids.map(id=>[id,normalizeSeries(raw[id],Date.parse('9999-12-31T23:59:59Z')).filter(p=>!['sp500','vix','dollar'].includes(id)||p.value>0)]))
 if(ids.some(id=>!series[id].length))return []
 const maps=Object.fromEntries(ids.map(id=>[id,new Map(series[id].map(p=>[p.date,p.value]))]))
 const dates=series.sp500.map(p=>p.date).filter(date=>ids.every(id=>maps[id].has(date)))
 const rows=dates.map(date=>({date,...Object.fromEntries(ids.map(id=>[id,maps[id].get(date)]))})),out=[]
 for(let i=Math.max(59,rows.length-limit);i<rows.length;i++){
  const window=rows.slice(i-59,i+1),last=window.at(-1),base5=window.at(-6),f=priceFeatures(window.map(r=>({date:r.date,close:r.sp500,volume:null})))
  const vixScore=scale(last.vix,12,40),realChange=(last.real10y-base5.real10y)*100,nominalChange=(last.us10y-base5.us10y)*100,dollarChange=(last.dollar/base5.dollar-1)*100
  const strength=f.factors.strength.map(x=>({...x,weight:x.weight*.5})).concat([factor('vixLevel','VIX风险偏好',last.vix,'点',100-vixScore,25),factor('realChange','5期实际利率变化',realChange,'bp',100-scale(realChange,-30,30),15),factor('dollarChange','5期美元变化',dollarChange,'%',100-scale(dollarChange,-2,2),10)])
  const heat=[factor('vixRank','VIX60期分位',percentile(window.map(r=>r.vix),last.vix),'%',percentile(window.map(r=>r.vix),last.vix),60),factor('stockMove','标普5期变动幅度',Math.abs(f.r5),'%',scale(Math.abs(f.r5),0,6),25),factor('yieldMove','10年利率5期变动幅度',Math.abs(nominalChange),'bp',scale(Math.abs(nominalChange),0,40),15)]
  const risk=f.factors.risk.map(x=>({...x,weight:x.weight*.35})).concat([factor('vixPressure','VIX波动压力',last.vix,'点',vixScore,45),factor('realLevel','实际利率水平',last.real10y,'%',scale(last.real10y,-1,3),10),factor('dollarPressure','5期美元上行',Math.max(0,dollarChange),'%',scale(Math.max(0,dollarChange),0,3),10)])
  const factors={strength,heat,risk};out.push({date:last.date,...Object.fromEntries(Object.entries(factors).map(([k,v])=>[k,weighted(v)===null?null:Math.round(weighted(v))])),factors})
 }
 return out
}
function objectView(def,history,status,now){
 const market=def.id==='global'?'global':def.market??'china'
 const expected=expectedCompletedSession(market,marketClock(now,market==='global'?'us':market))
 const latest=history.at(-1),stale=latest&&expected&&latest.date<expected
 const state=status==='failed'?'failed':!latest?'insufficient':!expected?'calendar':stale?'stale':'ok',valid=state==='ok' 
 const change=period=>{const past=history.at(-1-period);return valid&&past?Object.fromEntries(['strength','heat','risk'].map(axis=>[axis,finite(latest[axis])&&finite(past[axis])?latest[axis]-past[axis]:null])):null}
 return {...def,scoreVersion:def.id==='global'?'global-score-v1':'radar-score-v2',inputEvidence:latest?.inputEvidence??null,status:state,date:latest?.date??null,...Object.fromEntries(['strength','heat','risk'].map(axis=>[axis,valid?latest[axis]:null])),change1d:change(1),change5d:change(5),history:valid?history.slice(-20).map(({date,strength,heat,risk})=>({date,strength,heat,risk})):[],factors:latest?.factors??{},return5:latest?.return5??null,volumeRatio:latest?.volumeRatio??null}
}
export function deriveRadar(indexData={},globalInput={},now=Date.now(),realInputs){
 const usable=Object.fromEntries(INDEXES.map(def=>[def.id,completedBars(orderedBars(indexData[def.id]?.bars),def.market,now)]))
 const benchmark=usable.ashare,ashare=objectView(INDEXES.find(x=>x.id==='ashare'),indexScoreSeries(benchmark,undefined,25,realInputs?.objects?.ashare??{history:[]}),indexData.ashare?.status??'failed',now)
 const styles=INDEXES.filter(x=>x.kind==='style').map(def=>{
  const history=indexScoreSeries(usable[def.id],indexData.ashare?.status==='ok'?benchmark:[],25,realInputs?.objects?.[def.id]??{history:[]})
  return objectView(def,history,indexData[def.id]?.status??'failed',now)
 })
 const rawGlobal={...Object.fromEntries(Object.entries(globalInput.series??{}).map(([id,points])=>[id,completedBars(normalizeSeries(points,now),'us',now)])),sp500:usable.sp500.map(r=>({date:r.date,value:r.close}))}
 const global=objectView({id:'global',name:'全球环境',indexName:'标普500 / VIX / 美债 / 美元'},globalScoreSeries(rawGlobal,25),indexData.sp500?.status==='ok'&&!globalInput.failed?'ok':'failed',now)
 const objects=[global,ashare,...styles],dates=[...new Set(objects.filter(x=>x.status==='ok').map(x=>x.date))]
 return {version:RADAR_VERSION,checkedAt:now,frequency:'daily',global,ashare,styles,asOf:ashare.date,commonDate:dates.length===1?dates[0]:null,issues:objects.filter(x=>x.status!=='ok'||['strength','heat','risk'].some(k=>x[k]===null)).map(x=>({id:x.id,name:x.name,status:x.status==='ok'?'partial':x.status,date:x.date})),reconstructedHistory:true}
}
