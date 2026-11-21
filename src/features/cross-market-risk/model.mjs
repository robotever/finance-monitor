import {numeric,validDate} from './parsers.mjs'
export const RISK_VERSION='cross-market-risk-v1'
export const RULES=Object.freeze({vix:[20,30],vixChange:[5,10],yield5bp:[20,40],nfci:[0,1],nfci4w:[.2,.4],dollar5:[1.5,3],cnh5:[1,2],yen5:[2,4],fundingBp:[10,25],equityFall5:[3,5]})
export const METRICS={
 vix:{label:'VIX',unit:'点',source:'Cboe',frequency:'日频'},
 us2y:{label:'美债2年',unit:'%',source:'美国财政部',frequency:'日频'},us10y:{label:'美债10年',unit:'%',source:'美国财政部',frequency:'日频'},real10y:{label:'10年实际利率',unit:'%',source:'美国财政部',frequency:'日频'},curve:{label:'10年−2年',unit:'bp',source:'同日派生',frequency:'日频'},
 nfci:{label:'NFCI',unit:'',source:'芝加哥联储',frequency:'周频'},credit:{label:'信用分项',unit:'',source:'芝加哥联储',frequency:'周频'},
 dollar:{label:'美元指数',unit:'点',source:'新浪财经',frequency:'日频'},cnh:{label:'美元/离岸人民币',unit:'',source:'新浪财经',frequency:'日频'},jpy:{label:'美元/日元',unit:'',source:'新浪财经',frequency:'日频'},
 funding:{label:'SOFR−EFFR',unit:'bp',source:'纽约联储 · 同日派生',frequency:'日频'},sofr:{label:'SOFR',unit:'%',source:'纽约联储',frequency:'日频'},effr:{label:'EFFR',unit:'%',source:'纽约联储',frequency:'日频'},
 shanghai:{label:'上证指数',unit:'点',source:'腾讯财经',frequency:'日频'},hstech:{label:'恒生科技',unit:'点',source:'腾讯财经',frequency:'日频'},nasdaq:{label:'纳指综合',unit:'点',source:'腾讯财经',frequency:'日频'},
}
export function normalizeSeries(points,now=Date.now()){
 const today=new Date(now).toISOString().slice(0,10),byDate=new Map()
 for(const p of Array.isArray(points)?points:[]){const value=numeric(p?.value);if(validDate(p?.date)&&p.date<=today&&value!==null)byDate.set(p.date,{date:p.date,value})}
 return [...byDate.values()].sort((a,b)=>a.date.localeCompare(b.date)).slice(-300)
}
export function alignSpread(a,b,scale=100){
 const right=new Map((b??[]).map(p=>[p.date,p.value]))
 return (a??[]).filter(p=>right.has(p.date)).map(p=>({date:p.date,value:Math.round((p.value-right.get(p.date))*scale*10000)/10000}))
}
export function metricSummary(points,definition,now=Date.now(),failed=false){
 const ordered=normalizeSeries(points,now),last=ordered.at(-1),weekly=definition.frequency==='周频'
 if(!last)return {...definition,value:null,date:null,stale:true,failed,change5:null,return5:null,percentile:null,history:[]}
 const base=ordered.at(-6),weeklyBase=ordered.at(-5),age=(now-Date.parse(last.date+'T00:00:00Z'))/86400000
 const history=ordered.slice(-60),sample=ordered.slice(-252),window=weekly?weeklyBase:base
 return {...definition,value:last.value,date:last.date,stale:age>(weekly?14:5),failed,
  change5:base?last.value-base.value:null,return5:base&&base.value>0?(last.value/base.value-1)*100:null,
  changeWindow:window?last.value-window.value:null,windowLabel:weekly?'4周':'5期',
  percentile:sample.length>=60?Math.round(sample.filter(p=>p.value<=last.value).length/sample.length*100):null,sampleCount:sample.length,history}
}
const finite=n=>typeof n==='number'&&Number.isFinite(n)
const usable=m=>m&&finite(m.value)&&!m.stale&&!m.failed
const level=(v,[watch,stress])=>!finite(v)?0:v>=stress?2:v>=watch?1:0
const stateFor=n=>['normal','watch','stress'][n]
export function buildRiskModel(raw={},failed=[],now=Date.now()){
 const bad=new Set(failed),series=Object.fromEntries(Object.keys(METRICS).map(id=>[id,normalizeSeries(raw[id],now)]))
 series.curve=alignSpread(series.us10y,series.us2y);series.funding=alignSpread(series.sofr,series.effr)
 if(bad.has('us10y')||bad.has('us2y'))bad.add('curve')
 if(bad.has('sofr')||bad.has('effr'))bad.add('funding')
 const m=Object.fromEntries(Object.entries(METRICS).map(([id,meta])=>[id,metricSummary(series[id],{id,...meta},now,bad.has(id))]))
 const has=id=>usable(m[id]),value=id=>has(id)?m[id].value:null,change=id=>has(id)?m[id].change5:null,ret=id=>has(id)?m[id].return5:null
 const cards=[]
 function card(id,title,keys,score,reason,impact,trendId,coverage){
  const metrics=keys.map(k=>m[k]),available=score!==null
  cards.push({id,title,state:available?stateFor(score):'unknown',label:available?['常态','升温','压力'][score]:metrics.some(x=>x.value!==null)?'待更新':'缺数据',metrics,reason:available?reason:'当前有效数据不足，暂不判断。',impact,trend:has(trendId)?m[trendId].history:[],trendLabel:METRICS[trendId]?.label,partial:metrics.some(x=>!usable(x)),coverage:coverage??null})
 }
 let volScore=has('vix')?Math.max(level(value('vix'),RULES.vix),level(change('vix'),RULES.vixChange)):null
 if(volScore===0&&!finite(change('vix')))volScore=null
 card('volatility','美股波动',['vix'],volScore,volScore===2?'期权隐含波动处于压力区。':volScore===1?'波动水平或近期升幅触及观察线。':'期权隐含波动未触及观察线。','主要反映美股未来30天波动预期，不表示涨跌方向。','vix')
 const rateSignals=['us10y','real10y'].filter(id=>has(id)&&finite(change(id))).map(id=>level(change(id)*100,RULES.yield5bp));let rateScore=rateSignals.length?Math.max(...rateSignals):null
 if(rateScore===0&&rateSignals.length<2)rateScore=null
 card('rates','利率冲击',['us10y','real10y','us2y','curve'],rateScore,rateScore>0?'长端名义或实际利率近期快速上行。':'未见长端利率快速上行。','利率上行可能压制长久期资产估值；倒挂本身不当作盘中危机。','us10y')
 let condScore=has('nfci')?Math.max(level(value('nfci'),RULES.nfci),level(m.nfci.changeWindow,RULES.nfci4w)):null
 if(condScore===0&&!finite(m.nfci.changeWindow))condScore=null
 card('conditions','信用与金融条件',['nfci','credit'],condScore,condScore>0?'美国金融条件偏紧或近4周明显收紧。':'美国综合金融条件仍偏宽松且未快速收紧。','周频确认信号；信用分项是指数，不是高收益债利差。','nfci')
 const fxSignals=[['dollar',1,RULES.dollar5],['cnh',1,RULES.cnh5],['jpy',-1,RULES.yen5]].filter(([id])=>finite(ret(id))).map(([id,direction,rule])=>level(ret(id)*direction,rule));let fxScore=fxSignals.length?Math.max(...fxSignals):null
 if(fxScore===0&&fxSignals.length<3)fxScore=null
 card('fx','汇率冲击',['dollar','cnh','jpy'],fxScore,fxScore>0?'美元、人民币或日元的5期变化触及观察线。':'覆盖汇率未出现达到观察线的快速变化。','强美元/人民币走弱关注融资与估值；日元升值仅提示套息条件变化。','dollar',`${fxSignals.length}/3汇率`)
 const lastBasis=series.funding.slice(-3),sustained=lastBasis.length===3&&lastBasis.every(p=>p.value>=RULES.fundingBp[1])
 const fundScore=has('funding')?value('funding')>=RULES.fundingBp[1]&&sustained?2:value('funding')>=RULES.fundingBp[0]?1:0:null
 card('funding','美元融资',['funding','sofr','effr'],fundScore,fundScore===2?'回购相对联邦基金利差连续3期偏高。':fundScore===1?'融资基差升温，连续性仍需核对。':'同日融资基差未触及观察线。','这是资金市场代理，月末/季末也可能抬升，不等于企业违约风险。','funding')
 const stockIds=['shanghai','hstech','nasdaq'].filter(has),common=stockIds.length>=2?series[stockIds[0]].map(p=>p.date).filter(date=>stockIds.every(id=>series[id].some(p=>p.date===date))):[]
 const stockReturns=stockIds.length>=2&&common.length>=6?stockIds.map(id=>{const data=new Map(series[id].map(p=>[p.date,p.value]));return {id,value:(data.get(common.at(-1))/data.get(common.at(-6))-1)*100}}):[]
 const commonFresh=common.length>0&&now-Date.parse(common.at(-1)+'T00:00:00Z')<=5*86400000
 let stockScore=commonFresh&&stockReturns.length>=2?stockReturns.filter(r=>r.value<=-RULES.equityFall5[1]).length>=2?2:stockReturns.filter(r=>r.value<=-RULES.equityFall5[0]).length>=2?1:0:null
 if(stockScore===0&&stockIds.length<3)stockScore=null
 card('equities','股市联动',['shanghai','hstech','nasdaq'],stockScore,stockScore>0?'至少两个市场在5个共同交易日窗口明显下跌。':'未见覆盖市场同步触及下跌观察线。','覆盖A股、港股科技和美股综合指数，不代表全球所有股市。','nasdaq',`${stockIds.length}/3市场`)
 const stockCard=cards.at(-1)
 if(stockReturns.length){
  stockCard.metrics=stockCard.metrics.map(metric=>stockIds.includes(metric.id)?{...metricSummary(series[metric.id].filter(p=>common.includes(p.date)),metric,now),windowLabel:'5个共同交易日'}:metric)
  stockCard.trend=stockCard.metrics.find(x=>x.id==='nasdaq'&&!x.stale&&!x.failed)?.history??[]
 }
 stockCard.partial=stockCard.metrics.some(metric=>!usable(metric))
 stockCard.alignedReturns=stockReturns;stockCard.alignedDate=common.at(-1)??null
 const assessable=cards.filter(c=>c.state!=='unknown').length,stress=cards.filter(c=>c.state==='stress'),watch=cards.filter(c=>c.state==='watch'),unknown=cards.filter(c=>c.state==='unknown')
 const state=stress.length?'stress':watch.length?'watch':assessable===cards.length?'normal':'unknown'
 const focused=[...stress,...watch].map(c=>c.title)
 const summary=focused.length?`压力线索集中在${focused.join('、')}。`:assessable===cards.length?'当前覆盖信号未触及观察线。':'有效信号不足，暂不形成整体判断。'
 const confirmations=[]
 if(volScore>0&&stockScore>0)confirmations.push(m.vix.date===stockCard.alignedDate?'波动走高与多市场回撤出现在同一观测日。':'波动与多市场回撤均有压力线索，观测日不同。')
 if(volScore>0&&condScore===0&&m.nfci.date<m.vix.date)confirmations.push(`金融条件周报截至${m.nfci.date}仍偏宽松；此后的波动冲击尚待后续周报确认。`)
 if(fundScore===2)confirmations.push('融资基差已连续3期超过压力线，需与其他市场核对。')
 return {version:RISK_VERSION,checkedAt:now,state,summary,confirmations:confirmations.slice(0,2),assessable,total:cards.length,watchCount:watch.length,stressCount:stress.length,unknownCount:unknown.length,cards}
}
