import {mkdir,readFile,writeFile,rename} from 'node:fs/promises'
import {join} from 'node:path'
import {INSTRUMENTS,parseMinute,parseDaily,parseDollar} from '../../src/features/market-watch/model.mjs'

const forexHistory=symbol=>'https://vip.stock.finance.sina.com.cn/forex/api/jsonp.php/var%20_data=/NewForexService.getDayKLine?symbol='+symbol
// Sina product metadata: https://finance.sina.com.cn/futures/quotes/XAU.shtml
// and https://finance.sina.com.cn/futures/quotes/CL.shtml (both identify CFD).
const localMetadata={
 gold:{symbol:'XAU',description:'伦敦金（现货黄金）CFD · 美元/盎司 · 涨跌按昨结算 · 60交易日日线',name:'伦敦金',unit:'美元/盎司'},
 oil:{symbol:'CL',description:'纽约原油 CFD（期货参考报价）· 美元/桶 · 涨跌按昨结算 · 60交易日日线',name:'纽约原油',unit:'美元/桶'},
 cnh:{symbol:'fx_susdcnh',description:'美元 / 离岸人民币 · 人民币/美元 · 60交易日日线',unit:'人民币/美元'},
}
function validate(value,now){
 if(!value||!(value.price>0)||!(value.previousClose>0)||!Number.isFinite(value.changePercent)||!Number.isFinite(Date.parse(value.observedAt))||Date.parse(value.observedAt)>now+60000||!Array.isArray(value.points)||!value.points.length||value.points.some(p=>!Number.isFinite(p.price)||p.price<=0||!/^\d{4}(?:-\d{2}-\d{2})?$/.test(p.time)))throw Error('INVALID_QUOTE')
 return value
}
function parseSina(id,quoteText,historyText,now){
 const meta=localMetadata[id],code=id==='cnh'?meta.symbol:'hf_'+meta.symbol
 const fields=quoteText.match(new RegExp('hq_str_'+code+'="([^"\\n]*)"'))?.[1].split(',')
 if(!fields)throw Error('INVALID_QUOTE')
 let points,price,previousClose,observedAt
 if(id==='cnh'){
  if(!fields[9]?.includes('离岸人民币')||[fields[8],fields[10],fields[11]].some(value=>!/^[-+]?\d+(?:\.\d+)?$/.test(value??'')))throw Error('INVALID_QUOTE_INSTRUMENT')
  const packed=historyText.match(/var\s+_data=\("([^"\n]*)"\);?\s*$/)?.[1]
  if(!packed)throw Error('INVALID_QUOTE_HISTORY')
  points=packed.split('|').filter(Boolean).slice(-60).map(row=>{const cols=row.split(',');return {time:cols[0],price:Number(cols[4])}})
  price=Number(fields[8]);previousClose=Number((price-Number(fields[11])).toFixed(6));observedAt=fields[17]+'T'+fields[0]+'+08:00'
  if(!Number.isFinite(Number(fields[11]))||Math.abs((price/previousClose-1)*100-Number(fields[10]))>.02)throw Error('INVALID_QUOTE_CHANGE')
 }else{
  if(!fields[13]?.includes(meta.name))throw Error('INVALID_QUOTE_INSTRUMENT')
  const packed=historyText.match(/var\s+_data=\((\[[\s\S]*\])\);?\s*$/)?.[1]
  if(!packed)throw Error('INVALID_QUOTE_HISTORY')
  points=JSON.parse(packed).slice(-60).map(row=>({time:row.date,price:Number(row.close)}))
  price=Number(fields[0]);previousClose=Number(fields[7]);observedAt=fields[12]+'T'+fields[6]+'+08:00'
 }
 if(points.length<2||points.some(p=>!/^\d{4}-\d{2}-\d{2}$/.test(p.time)))throw Error('INVALID_QUOTE_HISTORY')
 return validate({price,previousClose,changePercent:Math.round((price/previousClose-1)*10000)/100,observedAt,marketDate:points.at(-1).time,points,status:'delayed',provider:'新浪财经 / 报价可能延迟',fetchedAt:now,description:meta.description,unit:meta.unit,session:'daily'},now)
}

/** Local-only public quotes. fetcher is injected by the local server for direct networking. */
export function createLocalMarketQuotes({stateRoot,fetcher=fetch,now=Date.now,offline=false}={}){
 if(!stateRoot)throw Error('STATE_ROOT_REQUIRED')
 const clock=()=>typeof now==='function'?now():now
 async function text(url,sina=false){
  const response=await fetcher(url,{headers:{'User-Agent':'Mozilla/5.0 (FinanceMonitor Local)','Referer':sina?'https://finance.sina.com.cn/':'https://gu.qq.com/'},signal:AbortSignal.timeout(12000)})
  if(!response.ok)throw Error('QUOTE_UPSTREAM_'+response.status)
  const bytes=await response.arrayBuffer();if(bytes.byteLength>5000000)throw Error('QUOTE_TOO_LARGE')
  return new TextDecoder(sina&&url.includes('hq.sinajs')&&!/charset=utf-8/i.test(response.headers.get('content-type')??'')?'gb18030':'utf-8').decode(bytes)
 }
 return async function quote(id){
  const instrument=INSTRUMENTS.find(i=>i.id===id)
  if(!instrument)throw Error('INVALID_INSTRUMENT')
  const path=join(stateRoot,'market-quotes',id+'.json'),stamp=clock()
  try{
   if(offline)throw Error('OFFLINE')
   let value
   if(localMetadata[id]){
    const symbol=localMetadata[id].symbol,code=id==='cnh'?symbol:'hf_'+symbol
    const [current,history]=await Promise.all([text('https://hq.sinajs.cn/list='+code,true),text(id==='cnh'?forexHistory(symbol):'https://stock2.finance.sina.com.cn/futures/api/jsonp.php/var%20_data=/GlobalFuturesService.getGlobalFuturesDailyKLine?symbol='+symbol,true)])
    value=parseSina(id,current,history,stamp)
   }else if(id==='dollar'){
    const [current,history]=await Promise.all([text('https://hq.sinajs.cn/list=DINIW',true),text(forexHistory('DINIW'),true)])
    value={...parseDollar(current,history,stamp),session:'daily',description:'美元指数 DINIW · 60交易日日线',unit:'点'}
   }else{
    const daily=instrument.session==='daily',endpoint=daily?'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param='+instrument.code+',day,,,60,qfq':'https://web.ifzq.gtimg.cn/appstock/app/minute/query?code='+instrument.code
    value={...(daily?parseDaily:parseMinute)(JSON.parse(await text(endpoint)),instrument.code,stamp),session:instrument.session??'china',description:instrument.description,unit:'点'}
   }
   validate(value,stamp)
   await mkdir(join(stateRoot,'market-quotes'),{recursive:true})
   const temp=path+'.'+process.pid+'.'+Math.random().toString(36).slice(2)+'.tmp'
   await writeFile(temp,JSON.stringify(value),{mode:0o600});await rename(temp,path)
   return value
  }catch{
   try{const cached=validate(JSON.parse(await readFile(path,'utf-8')),stamp);return {...cached,status:'cached',provider:cached.provider+' · 最近数据（本地缓存）'}}catch{throw Error('QUOTE_UNAVAILABLE: '+instrument.name+'；未取得可验证的本地行情')}
  }
 }
}
