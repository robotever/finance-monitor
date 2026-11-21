import {freshNews} from './model.mjs'
export const NEWS_POLICY_VERSION='finance-v1'
export const CATEGORY_LABELS={company:'公司动态',industry:'行业动态',market:'盘中异动',macro:'宏观政策'}
const ORDINARY=/国防部|军方|军队|海军|革命卫队|触雷|导弹|炮击|空袭|交火|无人机|伤亡|袭击|签证|外交部|大使|总统|总理|地震|交通事故/
const FINANCIAL_LINK=/油轮|原油|天然气|能源|油价|运价|航运|关税|制裁|利率|汇率|股价|贸易|进出口|半导体|芯片|投资|数据中心|人工智能|经济|央行|财政|金融|GDP/i
const MOVEMENT=/涨停|跌停|领涨|领跌|放量|缩量|换手率|成交额|成交量|资金净流入|净买入|净卖出|(?:涨|跌)(?:幅|超|逾|近|破|至)|(?:指数|期货|股价|金价|银价|油价|汇率|人民币|黄金|原油|铜价).{0,24}(?:升|降|报|突破|失守|上行|下行|上涨|下跌)/
const COMPANY=/公司|股份|集团|控股|财报|业绩|净利润|营收|回购|增持|减持|收购|并购|重组|分红|派息|IPO|上市|融资|定增|募资|重大合同|中标|交付|股东|董事会|招股|港交所|上交所|深交所|英伟达|腾讯|阿里巴巴|比亚迪|苹果|特斯拉|宁德时代|华为|小米|OPPO/i
const MACRO=/央行|美联储|欧洲央行|人民银行|加息|降息|利率|国债|债券|汇率|人民币|美元指数|通胀|CPI|PPI|PMI|GDP|就业|非农|财政|税收|监管|关税|贸易|进出口|外资|货币政策|信贷|社融|经济增长|制裁/i
const INDUSTRY=/产业|行业|半导体|芯片|存储|算力|数据中心|人工智能|机器人|新能源|锂电|电池|光伏|储能|低空|航空|汽车|消费|医药|医疗|创新药|房地产|地产|矿业|有色|钢铁|煤炭|石油|天然气|原油|油轮|航运|港口|运价|电价|电网|产能|产量|销量|供需|涨价|降价|出货|订单|ETF/
export function classifyFinancialNews(item){
 const text=String(item.title??'')
 if(item.source==='market_monitor')return item.category==='market'&&/^market-monitor:(shanghai|chinext|hstech):/.test(item.id??'')&&/^【行情快照】/.test(text)?'market':null
 if(ORDINARY.test(text)&&!FINANCIAL_LINK.test(text))return null
 if(MOVEMENT.test(text))return 'market'
 if(COMPANY.test(text)||item.relatedStockCount>0)return 'company'
 if(MACRO.test(text))return 'macro'
 if(INDUSTRY.test(text))return 'industry'
 return null
}
export function financeNewsPolicy(items){
 return items.flatMap(item=>{const category=classifyFinancialNews(item);return category?[{...item,category,categoryLabel:CATEGORY_LABELS[category],contextOnly:ORDINARY.test(item.title)&&!MACRO.test(item.title)&&!COMPANY.test(item.title)}]:[]})
}
const WATCH={shanghai:{name:'上证指数',threshold:1},chinext:{name:'创业板指',threshold:1},hstech:{name:'恒生科技',threshold:2}}
export function marketObservation(id,quote,origin,now=Date.now()){
 const config=WATCH[id],stamp=Date.parse(quote?.observedAt),change=quote?.changePercent
 if(!config||quote?.status!=='intraday'||typeof quote.price!=='number'||!Number.isFinite(quote.price)||quote.price<=0||typeof change!=='number'||!Number.isFinite(change)||!Number.isFinite(stamp)||stamp>now||now-stamp>180000||Math.abs(change)<config.threshold)return null
 const day=quote.observedAt.slice(0,10),bucket=Math.floor(Math.abs(change)/config.threshold),direction=change>0?'up':'down',event=`${id}:${day}:${direction}:${bucket}`
 const url=new URL('/',origin);url.searchParams.set('watch',id);url.searchParams.set('observation',event)
 return {id:'market-monitor:'+event,title:`【行情快照】${config.name}报${quote.price.toFixed(2)}，日内${change>0?'上涨':'下跌'}${Math.abs(change).toFixed(2)}%（达到${config.threshold}%观察线）`,url:url.toString(),source:'market_monitor',sourceName:'系统监测',publishedAt:stamp,important:false,category:'market',categoryLabel:CATEGORY_LABELS.market}
}

export function selectFinancialNews(items,now=Date.now()){
 let contextCount=0
 return freshNews(financeNewsPolicy(items),now,{accept:item=>!item.contextOnly||++contextCount<=2})
}
export function mergeFinancialNews(incoming,previous,now=Date.now()){
 return selectFinancialNews([...incoming,...previous.filter(item=>item.source!=='market_monitor')],now)
}
export function mediaUnavailable(sources){
 return !sources.some(s=>s.id!=='market_monitor'&&s.status!=='failed')
}
