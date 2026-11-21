import test from 'node:test'
import assert from 'node:assert/strict'
import {INSTRUMENTS,parseMinute,parseDaily,parseDollar,chartGeometry,widgetConfig} from '../src/features/market-watch/model.mjs'
test('fixed watchlist has eight explicit instruments and closed symbol editing',()=>{
 assert.equal(INSTRUMENTS.length,8);assert.equal(new Set(INSTRUMENTS.map(i=>i.id)).size,8)
 const c=widgetConfig('gold');assert.equal(c.symbol,'OANDA:XAUUSD');assert.equal(c.allow_symbol_change,false)
 assert.throws(()=>widgetConfig('unknown'))
})
test('minute quotes retain original timestamp and prior close; no stale feed labeled live',()=>{
 const row={data:{date:'20261120',data:['0930 10 0','0931 11 0','0932 bad 0']},qt:{sh000001:['1','上证','000001','11','10',...Array(25).fill(''),'20261120093100']}}
 const v=parseMinute({code:0,data:{sh000001:row}},'sh000001',Date.parse('2026-11-21T04:00Z'))
 assert.equal(v.points.length,2);assert.equal(v.changePercent,10);assert.equal(v.marketDate,'2026-11-20');assert.equal(v.status,'closed')
 assert.throws(()=>parseMinute({data:{}},'sh000001'))
})
test('chart geometry handles flat prices and rejects nonfinite data without fabricated points',()=>{
 const g=chartGeometry([{time:'0930',price:10},{time:'0931',price:10}],10)
 assert.ok(g.path&&!g.path.includes('NaN'));assert.ok(g.max>g.min)
 assert.equal(chartGeometry([],10),null)
})
test('intraday geometry does not stretch morning prices to the close',()=>{
 const g=chartGeometry([{time:'0930',price:10},{time:'1030',price:11}],10)
 assert.equal(g.lastX,240)
})
test('Hong Kong source timestamps and longer session are honored',()=>{
 const row={data:{date:'20261120',data:['0930 10 0','1600 11 0']},qt:{hkHSTECH:['100','恒生科技','HSTECH','11','10',...Array(25).fill(''),'2026/11/20 16:08:54']}}
 const q=parseMinute({code:0,data:{hkHSTECH:row}},'hkHSTECH',Date.parse('2026-11-21T04:00Z'))
 assert.equal(q.observedAt,'2026-11-20T16:08:54+08:00');assert.equal(q.status,'closed')
 assert.equal(chartGeometry(q.points,q.previousClose,'hongkong').lastX,930)
})

test('Nasdaq daily chart preserves actual index and New York quote timezone',()=>{
 const qt=['200','纳斯达克','.IXIC','11','10',...Array(25).fill(''),'2026-11-20 17:15:59']
 const q=parseDaily({code:0,data:{'us.IXIC':{day:[['2026-11-19','10','10'],['2026-11-20','10','11']],qt:{'us.IXIC':qt}}}},'us.IXIC',Date.parse('2026-11-21T04:00Z'))
 assert.equal(q.observedAt,'2026-11-20T17:15:59-05:00');assert.equal(q.points[1].price,11);assert.equal(q.changePercent,10)
 assert.equal(chartGeometry(q.points,q.previousClose,'daily').lastX,930)
})

test('dollar index quote and daily history parse as data without executing upstream scripts',()=>{
 const quote='var hq_str_DINIW="05:59:00,103.8404,103.8404,103.9423,3813,103.9573,103.9618,103.5805,103.8404,美元指数,2026-11-21";'
 const history='/*<script>ignore</script>*/var _data=("2026-11-19,103.8,103.5,104,103.9423,|2026-11-20,103.9,103.5,104,103.8404");'
 const q=parseDollar(quote,history,Date.parse('2026-11-21T04:00Z'))
 assert.equal(q.price,103.8404);assert.equal(q.previousClose,103.9423);assert.equal(q.observedAt,'2026-11-21T05:59:00+08:00');assert.equal(q.points.at(-1).price,103.8404)
 assert.throws(()=>parseDollar('alert(1)',history));assert.throws(()=>parseDollar(quote,'not history'))
})
test('weekend quotes are clearly closed rather than only delayed',()=>{
 const qt=['200','纳斯达克','.IXIC','11','10',...Array(25).fill(''),'2026-11-20 17:15:59']
 const q=parseDaily({code:0,data:{'us.IXIC':{day:[['2026-11-19','10','10'],['2026-11-20','10','11']],qt:{'us.IXIC':qt}}}},'us.IXIC',Date.parse('2026-11-21T04:00Z'))
 assert.equal(q.status,'closed')
 const d=parseDollar('var hq_str_DINIW="05:59:00,103.8404,103.8404,103.9423,3813,103.9573,103.9618,103.5805,103.8404,美元指数,2026-11-21";','var _data=("2026-11-19,103.8,103.5,104,103.9423,|2026-11-20,103.9,103.5,104,103.8404");',Date.parse('2026-11-21T04:00Z'))
 assert.equal(d.status,'closed')
})

test('chart zoom keeps latest observations and supports resetting full range',async()=>{
 const {visibleChartPoints}=await import('../src/features/market-watch/model.mjs')
 const points=Array.from({length:40},(_,i)=>({time:String(i),price:i+1}))
 assert.deepEqual(visibleChartPoints(points,1),points)
 assert.deepEqual(visibleChartPoints(points,2),points.slice(-20))
 assert.deepEqual(visibleChartPoints(points,4),points.slice(-10))
 assert.deepEqual(visibleChartPoints(points.slice(0,2),4),points.slice(0,2))
})

test('seven approved instruments use exact TradingView symbols with supported default periods',()=>{
 const expected={shanghai:['SSE:000001','D'],chinext:['SZSE:399006','15'],hstech:['HSI:HSTECH','D'],gold:['OANDA:XAUUSD','15'],oil:['TVC:USOIL','15'],dollar:['INDEX:DXY','D'],cnh:['FX_IDC:USDCNH','15']}
 for(const [id,[symbol,interval]] of Object.entries(expected)){assert.equal(widgetConfig(id).symbol,symbol);assert.equal(widgetConfig(id).interval,interval);assert.equal(widgetConfig(id).hide_top_toolbar,false)}
 assert.throws(()=>widgetConfig('nasdaq'))
 assert.equal(INSTRUMENTS.find(i=>i.id==='shanghai').provider,'tencent')
})
