import test from 'node:test'
import assert from 'node:assert/strict'
import {createSSRApp,h} from 'vue'
import {renderToString} from 'vue/server-renderer'
import Detail from '../tools/market_dashboard/hithink_preview_detail.js'
test('detail renders readable evidence with correct percentage units and distinct missing values',async()=>{
 const point={id:'885001.TI',name:'测试概念',universe:'concept',marketDate:'2026-11-17',observedAt:'2026-11-17T03:00:00.000Z',availableAt:null,historicalReconstruction:false,officialClose:false,
  strength:55,opportunity:62,risk:22,ranks:{strength:18,opportunity:5,risk:380},change1d:{strength:2,opportunity:3,risk:-4},axisCompleteness:{strength:88,opportunity:96.4,risk:91},completeness:92,validCloses:250,coldStart:false,improvementEvidence:2,universeSize:390,returnRank:1,membershipMode:'point_in_time_snapshot',missing:['participation.turnoverMarketShare.missingInput'],
  metrics:{return1d:2.55,return5d:-3,return20d:null,advancingShare:.5,medianReturn:.01,position60d:12.5,turnover:250000000},components:{priceTrend:{value:70,coverage:.8,missing:[]}}}
 const detail={history:[point],scoringWeights:{strength:{priceTrend:30}}}
 const html=await renderToString(createSSRApp({render:()=>h(Detail,{detail,selectedDate:point.marketDate})}))
 for(const text of ['价格与趋势','成分表现与参与度','数据质量与缺失','评分拆解','历史对比','+2.55%','-3.00%','50.0%','+1.00%','12.5%分位','2.50亿元','88.0%','价格趋势','30%','70.0','80.0%','全市场成交额占比','技术字段'])assert.ok(html.includes(text),text)
 assert.ok(html.includes('暂缺'));assert.ok(!html.includes('undefined'));assert.ok(!html.includes('NaN'))
})
