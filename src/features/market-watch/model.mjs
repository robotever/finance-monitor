export const INSTRUMENTS=[
 {id:'shanghai',name:'上证指数',code:'sh000001',provider:'tencent',unit:'点',description:'上证综合指数 · 人民币'},
 {id:'chinext',name:'创业板指',code:'sz399006',provider:'tencent',unit:'点',description:'创业板价格指数 · 人民币'},
 {id:'hstech',name:'恒生科技',code:'hkHSTECH',provider:'tencent',session:'hongkong',description:'恒生科技指数 · 港元 · 行情可能延迟'},
 {id:'nasdaq',name:'纳斯达克',code:'us.IXIC',provider:'tencent',session:'daily',description:'纳斯达克综合指数 · 60交易日日线 · 行情可能延迟'},
 {id:'gold',name:'黄金',symbol:'OANDA:XAUUSD',provider:'tradingview',description:'OANDA 黄金现货 / 美元 · 美元/盎司'},
 {id:'oil',name:'原油',symbol:'TVC:USOIL',provider:'tradingview',description:'WTI 原油 CFD · 美元/桶'},
 {id:'dollar',name:'美元指数',provider:'sina',session:'daily',description:'美元指数 DINIW · 60交易日日线 · 行情可能延迟'},
 {id:'cnh',name:'离岸人民币',symbol:'FX_IDC:USDCNH',provider:'tradingview',description:'美元 / 离岸人民币 · 人民币/美元'},
]
export function widgetConfig(id){
 const i=INSTRUMENTS.find(i=>i.id===id);if(!i?.symbol)throw Error('UNSUPPORTED_INSTRUMENT')
 return {autosize:true,symbol:i.symbol,interval:'15',timezone:'Asia/Shanghai',theme:'dark',style:'2',locale:'zh_CN',allow_symbol_change:false,hide_side_toolbar:true,hide_top_toolbar:false,save_image:false,calendar:false,hide_volume:true,backgroundColor:'#0b1626',gridColor:'rgba(110,145,180,0.08)',support_host:'https://www.tradingview.com'}
}
export function parseMinute(data,code,now=Date.now()){
 const row=data?.data?.[code],day=row?.data?.date,quote=row?.qt?.[code]
 if(data.code!==0||!/^\d{8}$/.test(day??'')||!Array.isArray(quote))throw Error('INVALID_QUOTE')
 const points=(row.data.data??[]).map(s=>{const [time,price]=String(s).split(' ');return {time,price:Number(price)}}).filter(p=>/^\d{4}$/.test(p.time)&&Number.isFinite(p.price)&&p.price>0)
 const price=Number(quote[3]),previousClose=Number(quote[4]),stamp=String(quote[30]??'').replace(/[^0-9]/g,'')
 if(!points.length||!(price>0)||!(previousClose>0)||!/^\d{14}$/.test(stamp??''))throw Error('INVALID_QUOTE')
 const marketDate=day.slice(0,4)+'-'+day.slice(4,6)+'-'+day.slice(6,8),observedAt=stamp.slice(0,4)+'-'+stamp.slice(4,6)+'-'+stamp.slice(6,8)+'T'+stamp.slice(8,10)+':'+stamp.slice(10,12)+':'+stamp.slice(12,14)+'+08:00'
 const ms=Date.parse(observedAt);if(!Number.isFinite(ms)||ms>now+60000)throw Error('INVALID_QUOTE_TIME')
 const hongkong=code.startsWith('hk')
 const china=new Date(now+8*3600000),minute=china.getUTCHours()*60+china.getUTCMinutes(),weekday=china.getUTCDay(),open=weekday>0&&weekday<6&&((minute>=570&&minute<=(hongkong?720:690))||(minute>=780&&minute<=(hongkong?960:900)))
 return {price,previousClose,changePercent:Math.round((price/previousClose-1)*10000)/100,marketDate,observedAt,points,status:open?(now-ms>180000?'delayed':'intraday'):'closed',provider:'腾讯财经',fetchedAt:now}
}
export function chartX(time,session='china'){const minutes=Number(time.slice(0,2))*60+Number(time.slice(2)),hk=session==='hongkong',morning=hk?150:120,total=hk?330:240;return 10+Math.max(0,Math.min(total,minutes<=570+morning?minutes-570:morning+minutes-780))/total*920}
export function chartGeometry(points,previousClose,session='china'){
 if(!points.length)return null
 const values=points.map(p=>p.price).filter(Number.isFinite);if(!values.length)return null
 const low=Math.min(...values,previousClose),high=Math.max(...values,previousClose),pad=Math.max((high-low)*.15,high*.0005),min=low-pad,max=high+pad
 const y=value=>220-(value-min)/(max-min)*200
 const x=(p,i)=>session==='daily'?10+i/Math.max(1,points.length-1)*920:chartX(p.time,session)
 return {min,max,baseline:y(previousClose),lastX:x(points.at(-1),points.length-1),path:points.map((p,i)=>`${i?'L':'M'}${x(p,i).toFixed(2)},${y(p.price).toFixed(2)}`).join(' ')}
}

const weekendClosed=now=>{const d=new Date(now);return d.getUTCDay()===6||d.getUTCDay()===0&&d.getUTCHours()<20}
export function parseDaily(data,code,now=Date.now()){
 const row=data?.data?.[code],quote=row?.qt?.[code],days=row?.day
 if(data.code!==0||!Array.isArray(days)||!Array.isArray(quote)||!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(quote[30]??''))throw Error('INVALID_QUOTE')
 const points=days.map(d=>({time:d[0],price:Number(d[2])})).filter(p=>/^\d{4}-\d{2}-\d{2}$/.test(p.time)&&p.price>0&&Number.isFinite(p.price))
 const price=Number(quote[3]),previousClose=Number(quote[4]);if(points.length<2||!(price>0)||!(previousClose>0))throw Error('INVALID_QUOTE')
 const stamp=quote[30],date=new Date(stamp.slice(0,10)+'T12:00:00Z'),zone=new Intl.DateTimeFormat('en-US',{timeZone:'America/New_York',timeZoneName:'shortOffset'}).formatToParts(date).find(p=>p.type==='timeZoneName').value,offset=zone==='GMT-4'?'-04:00':'-05:00',observedAt=stamp.replace(' ','T')+offset
 if(Date.parse(observedAt)>now+60000)throw Error('INVALID_QUOTE_TIME')
 return {price,previousClose,changePercent:Math.round((price/previousClose-1)*10000)/100,marketDate:points.at(-1).time,observedAt,points,status:weekendClosed(now)?'closed':'delayed',provider:'腾讯财经 · 纳指日线 / 报价可能延迟',fetchedAt:now}
}

export function parseDollar(quoteText,historyText,now=Date.now()){
 const fields=quoteText.match(/hq_str_DINIW="([^"\n]*)"/)?.[1].split(',')
 const packed=historyText.match(/var\s+_data=\("([^"\n]*)"\);?\s*$/)?.[1]
 if(!fields||!packed)throw Error('INVALID_QUOTE')
 const points=packed.split('|').slice(-60).map(row=>{const cols=row.split(',');return {time:cols[0],price:Number(cols[4])}}).filter(p=>/^\d{4}-\d{2}-\d{2}$/.test(p.time)&&Number.isFinite(p.price)&&p.price>0).slice(-60)
 const price=Number(fields[1]),previousClose=Number(fields[3]),observedAt=fields[10]+'T'+fields[0]+'+08:00'
 if(points.length<2||!(price>0)||!(previousClose>0)||!Number.isFinite(Date.parse(observedAt))||Date.parse(observedAt)>now+60000)throw Error('INVALID_QUOTE')
 return {price,previousClose,changePercent:Math.round((price/previousClose-1)*10000)/100,marketDate:points.at(-1).time,observedAt,points,status:weekendClosed(now)?'closed':'delayed',provider:'新浪财经 · DINIW 日线 / 报价可能延迟',fetchedAt:now}
}

export function visibleChartPoints(points,zoom=1){return points.slice(-Math.max(2,Math.ceil(points.length/Math.max(1,zoom))))}
