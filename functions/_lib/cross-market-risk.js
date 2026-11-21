import {upstreamText} from './upstream.js'
import {parseVix,parseTreasury,parseNfci,parseNyFed,parseFx,parseEquity} from '../../src/features/cross-market-risk/parsers.mjs'
import {buildRiskModel,normalizeSeries,RISK_VERSION} from '../../src/features/cross-market-risk/model.mjs'
const treasury='https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml'
const equity=code=>'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+code+',day,,,100,qfq'
const forex=code=>'https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_data=/NewForexService.getDayKLine?symbol='+code
export const RISK_SOURCES=[
 {id:'vix',name:'Cboe',roles:['vix'],url:'https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv',parse:text=>({vix:parseVix(text)})},
 {id:'treasury',name:'美国财政部',roles:['us2y','us10y'],treasuryType:'daily_treasury_yield_curve',parse:text=>parseTreasury(text,{us2y:'BC_2YEAR',us10y:'BC_10YEAR'})},
 {id:'real',name:'美国财政部实际利率',roles:['real10y'],treasuryType:'daily_treasury_real_yield_curve',parse:text=>parseTreasury(text,{real10y:'TC_10YEAR'})},
 {id:'nfci',name:'芝加哥联储',roles:['nfci','credit'],url:'https://api.data.chicagofed.org/NFCI/nfci-data-series-csv.csv',parse:parseNfci},
 ...['sofr','effr'].map(id=>({id,name:'纽约联储 '+id.toUpperCase(),roles:[id],url:`https://markets.newyorkfed.org/api/rates/${id==='sofr'?'secured':'unsecured'}/${id}/last/90.json`,parse:text=>({[id]:parseNyFed(JSON.parse(text),id.toUpperCase())})})),
 ...[['dollar','DINIW'],['cnh','USDCNH'],['jpy','USDJPY']].map(([id,code])=>({id,name:'新浪财经 '+code,roles:[id],url:forex(code),parse:text=>({[id]:parseFx(text)})})),
 ...[['shanghai','sh000001'],['hstech','hkHSTECH'],['nasdaq','us.IXIC']].map(([id,code])=>({id,name:'腾讯财经 '+code,roles:[id],url:equity(code),parse:text=>({[id]:parseEquity(JSON.parse(text),code)})})),
]
export async function fetchRiskSource(id,{fetcher=fetch,now=Date.now()}={}){
 const source=RISK_SOURCES.find(s=>s.id===id);if(!source)throw Error('INVALID_RISK_SOURCE')
 const headers={'User-Agent':'Mozilla/5.0 (FinanceMonitor)','Referer':id==='vix'?'https://www.cboe.com/':source.url?.includes('sina')?'https://finance.sina.com.cn/':undefined}
 if(!headers.Referer)delete headers.Referer
 const read=url=>upstreamText(url,{fetcher,headers,maxBytes:1500000})
 let result
 if(source.treasuryType){
  const date=new Date(now),year=date.getUTCFullYear(),years=date.getUTCMonth()<2?[year-1,year]:[year]
  const pieces=await Promise.all(years.map(y=>read(`${treasury}?data=${source.treasuryType}&field_tdr_date_value=${y}`)))
  result=source.parse(pieces.join('\n'))
 }else result=source.parse(await read(source.url))
 const data=Object.fromEntries(source.roles.map(role=>[role,normalizeSeries(result[role],now)]))
 if(!Object.values(data).some(rows=>rows.length))throw Error('NO_VALID_RISK_DATA')
 return data
}
export async function loadRiskSource(id,{cache,origin='https://newsmonitor.pages.dev',fetcher=fetch,now=Date.now(),waitUntil}={}){
 const source=RISK_SOURCES.find(s=>s.id===id);if(!source)throw Error('INVALID_RISK_SOURCE')
 const key=new Request(new URL(`/api/cross-market/source-cache/${RISK_VERSION}/${id}`,origin))
 let old=null
 try{const r=await cache?.match(key);old=r?await r.json():null}catch{}
 if(old&&(!Number.isFinite(old.lastSuccessAt)||old.lastSuccessAt>now||!old.data||!Object.values(old.data).every(Array.isArray)))old=null
 if(old&&now-old.lastSuccessAt<300000)return {...old,id,name:source.name,status:'ok',cached:true}
 try{
  const data=await fetchRiskSource(id,{fetcher,now}),lastSuccessAt=Date.now()
  const result={id,name:source.name,status:'ok',data,lastSuccessAt}
  if(cache){const write=cache.put(key,Response.json(result,{headers:{'Cache-Control':'public,max-age=604800'}})).catch(()=>{});if(waitUntil)waitUntil(write);else await write}
  return result
 }catch{
  return {id,name:source.name,status:'failed',data:old?.data??{},lastSuccessAt:old?.lastSuccessAt??null,safeErrorCode:'SOURCE_UNAVAILABLE',cached:Boolean(old)}
 }
}
export async function buildCrossMarketRisk({loadSource,now}={}){
 const results=new Array(RISK_SOURCES.length);let next=0
 async function worker(){while(next<RISK_SOURCES.length){const i=next++,source=RISK_SOURCES[i];try{results[i]=await loadSource(source.id)}catch{results[i]={id:source.id,name:source.name,status:'failed',data:{},lastSuccessAt:null,safeErrorCode:'SOURCE_UNAVAILABLE'}}}}
 await Promise.all(Array.from({length:4},worker))
 const series=Object.assign({},...results.map(r=>r.data)),failed=results.filter(r=>r.status==='failed').flatMap(r=>RISK_SOURCES.find(s=>s.id===r.id).roles)
 const checkedAt=now??Date.now(),model=buildRiskModel(series,failed,checkedAt)
 return {...model,sources:results.map(({data,...status})=>({...status,observedAt:Object.values(data??{}).flatMap(rows=>rows.map(p=>p.date)).sort().at(-1)??null})),sourceErrors:results.filter(r=>r.status==='failed').length}
}
