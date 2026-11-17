import {h,ref,watch} from 'vue'
import {formatHistoryValue} from '../../src/features/sector-rotation-v4/model.mjs'
const axes=[['strength','强度'],['opportunity','机会'],['risk','风险']]
const labels={priceTrend:'价格趋势',breadth:'上涨广度',participation:'成交参与度',persistence:'强势持续性',position:'历史位置',breadthImprovement:'广度改善',momentumImprovement:'动量改善',participationWarming:'参与度回暖',relativeTurn:'相对市场转折',downsideDiffusion:'下跌扩散',trendDeterioration:'趋势恶化',divergence:'指数与成分背离',crowding:'拥挤程度',concentration:'集中程度'}
const partLabels={return1d:'当日涨幅',return5d:'近5日涨幅',return20d:'近20日涨幅',advancingShare:'上涨股票占比',medianReturn:'成分收益中位数',strongStockShare:'强势股占比',turnoverPercentile:'成交额历史分位',turnoverMarketShare:'全市场成交额占比',volumeExpansionShare:'放量股票占比',meanPercentile:'历史强度分位',topDecileStreak:'前10%连续天数',position60d:'60日历史位置',position250d:'250日历史位置',delta5d:'近5日改善',improvingDays:'连续改善天数',shortAcceleration:'短期加速度',mediumAcceleration:'中期加速度',current:'当前水平',relativeTurn5d:'5日相对转折',relativeTurn20d:'20日相对转折',slope5d:'短期强度斜率',indexBreadth:'指数与广度背离',indexMedian:'指数与成分中位数背离',activity:'活跃程度',acceleration:'活跃度加速',top5TurnoverShare:'前五大成交占比',top1ContributionShare:'单股绝对收益集中度'}
const finite=Number.isFinite
const number=(v,d=0)=>finite(v)?v.toFixed(d):'暂缺'
const percent=v=>finite(v)?formatHistoryValue(v,'return1d'):'暂缺'
const share=v=>finite(v)?(v*100).toFixed(1)+'%':'暂缺'
const position=v=>finite(v)?v.toFixed(1)+'%分位':'暂缺'
const change=v=>finite(v)?(v>0?'+':'')+v:'暂缺'
const tone=v=>finite(v)?v>0?'preview-gain':v<0?'preview-loss':'':''
const time=v=>v?new Date(v).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间':'可得时间未确认'
function missingLabels(codes){return [...new Set(codes.map(code=>partLabels[code.split('.').reverse().find(k=>partLabels[k])]??labels[code.split('.')[0]]??'其他评分输入'))]}
function grid(items){return h('dl',{class:'preview-detail-metrics'},items.map(([label,value])=>h('div',[h('dt',label),h('dd',value)])))}
function constituents(data,expanded,toggle,loading){
 const rows=data?.rows??[]
 return h('section',{class:'preview-constituents'},[
  h('div',{class:'preview-section-heading'},[h('h3','成分股涨幅榜'),data?.total>10?h('button',{type:'button',class:'market-button','aria-expanded':expanded,onClick:toggle},expanded?'收起为前10名':'展开全部 '+data.total+' 只'):null]),
  loading?h('p',{class:'preview-meta',role:'status'},'正在读取所选日期的完整成分股…'):null,
  !rows.length?h('p',{class:'preview-meta'},'该日期暂无成分股行情。'):h('div',[
   h('p',{class:'preview-meta'},'按当日涨幅降序 · 有效行情 '+data.validCount+' / '+data.total+' · 成分日期 '+data.membershipDate+(data.approximateMembership?'（当前成分回填）':'')+(data.priceBasis==='forward_adjusted'?' · 历史收益按前复权价格计算，价格列为前复权收盘价':' · 最新价')+(data.observedAt?' · 行情 '+time(data.observedAt):'')),
   h('div',{class:'preview-table-scroll'},h('table',{class:'preview-table'},[
    h('thead',h('tr',['排名','股票 / 代码','涨幅','价格（元）','成交额'].map(text=>h('th',text)))),
    h('tbody',(expanded?rows:rows.slice(0,10)).map(row=>h('tr',{key:row.code},[
     h('td',row.rank??'—'),h('th',{scope:'row'},[h('span',row.name??'名称暂缺'),h('small',{class:'preview-stock-code'},row.code)]),
     h('td',{class:tone(row.return1d)},finite(row.return1d)?percent(row.return1d):'无有效行情'),h('td',number(row.lastPrice,2)),h('td',finite(row.turnover)?(row.turnover/1e8).toFixed(2)+'亿元':'暂缺')
    ])))
   ])),h('p',{class:'preview-meta'},'停牌或行情缺失的成分股不补零、不参与涨幅排名，展开全部可查看。股票名称采用当前代码表。')
  ])
 ])
}
function breakdown(point,weights){return axes.map(([axis,label])=>h('section',[
 h('h4',label+'分拆解'),
 h('table',{class:'preview-table'},[h('thead',h('tr',['分项','名义权重','分项分','覆盖率'].map(t=>h('th',t)))),h('tbody',Object.entries(weights?.[axis]??{}).map(([key,weight])=>{const c=point.components?.[key];return h('tr',[h('th',{scope:'row'},labels[key]??key),h('td',weight+'%'),h('td',number(c?.value,1)),h('td',share(c?.coverage))])}))]),
 h('details',{class:'preview-notes'},[h('summary','查看子项'),...Object.keys(weights?.[axis]??{}).map(key=>{const c=point.components?.[key];return h('div',[h('strong',labels[key]??key),h('ul',Object.entries(c?.parts??{}).map(([name,part])=>h('li',(partLabels[name]??'其他子项')+'：'+number(part?.value,1)+'分 · 覆盖 '+share(part?.coverage))))])})])
]))}
export default {
 props:['detail','selectedDate','constituentsLoading'],emits:['close','selectDate','loadConstituents'],
 setup(props,{emit}){
  const expanded=ref(false)
  watch([()=>props.selectedDate,()=>props.detail.id,()=>props.detail.batchId],()=>expanded.value=false)
  return()=>{
  const history=props.detail.history,point=history.find(r=>r.marketDate===props.selectedDate)??history.at(-1)
  if(!point)return null
  const m=point.metrics??{},missing=missingLabels(point.missing??[]),universe=point.universe==='concept'?'概念':'行业'
  const historyRows=[...history].reverse().map(r=>h('tr',{class:r.marketDate===point.marketDate?'preview-selected-date':''},[
   h('th',h('button',{type:'button',class:'preview-name',onClick:()=>emit('selectDate',r.marketDate)},r.marketDate)),
   h('td',{class:tone(r.metrics?.return1d)},percent(r.metrics?.return1d)),...axes.map(([key])=>h('td',r[key]??'—'))
  ]))
  return h('div',{class:'preview-backdrop',onClick:e=>{if(e.target===e.currentTarget)emit('close')}},h('section',{class:'preview-detail',role:'dialog','aria-modal':'true','aria-label':'板块详情'},[
   h('header',{class:'preview-section-heading'},[h('div',[h('h2',point.name),h('p',{class:'preview-meta'},point.id+' · '+universe+' · 来源：同花顺 Hithink')]),h('button',{type:'button',class:'market-button',onClick:()=>emit('close')},'关闭')]),
   h('label',{class:'preview-date-selector'},['观察日期 ',h('select',{'aria-label':'观察日期',value:point.marketDate,onChange:e=>emit('selectDate',e.target.value)},[...history].reverse().map(r=>h('option',{value:r.marketDate},r.marketDate+(r.historicalReconstruction?' · 重建':r.officialClose?' · 收盘':' · 盘中'))))]),
   h('p',{class:'preview-meta'},'采集：'+time(point.observedAt)+' · '+(point.historicalReconstruction?'历史重建，非当时已知信息':point.officialClose?'正式收盘快照':'真实盘中快照')),
   constituents(props.detail.constituentsByDate?.[point.marketDate],expanded.value,()=>{
    const data=props.detail.constituentsByDate?.[point.marketDate]
    if(!expanded.value&&data&&data.rows.length<data.total)emit('loadConstituents',point.marketDate)
    expanded.value=!expanded.value
   },props.constituentsLoading),
   h('div',{class:'preview-detail-scores'},axes.map(([key,label])=>h('section',[h('h3',label),h('strong',point[key]??'—'),h('p','排名 '+(point.ranks?.[key]??'—')+' / '+(point.universeSize??'—')),h('p','较前日 '+change(point.change1d?.[key])+' · 完整度 '+number(point.axisCompleteness?.[key],1)+'%')]))),
   h('section',[h('h3','价格与趋势'),grid([['当日涨幅',percent(m.return1d)],['近5日涨幅',percent(m.return5d)],['近20日涨幅',percent(m.return20d)],['当日涨幅排名',(point.returnRank??'—')+' / '+(point.universeSize??'—')],['5日相对沪深300',finite(m.relativeStrength5d)?change(Number(m.relativeStrength5d.toFixed(2)))+'个百分点':'暂缺'],['20日相对沪深300',finite(m.relativeStrength20d)?change(Number(m.relativeStrength20d.toFixed(2)))+'个百分点':'暂缺'],['60日价格位置',position(m.position60d)],['250日价格位置',position(m.position250d)],['此前连续前10%',finite(m.topDecileStreak)?m.topDecileStreak+'个交易日':'暂缺']]),h('p',{class:'preview-meta'},'价格位置是历史价格分位，不等于估值高低；相对收益为板块收益减基准收益。')]),
   h('section',[h('h3','成分表现与参与度'),grid([['上涨股票占比',share(m.advancingShare)],['下跌股票占比',share(m.decliningShare)],['成分涨幅中位数',finite(m.medianReturn)?percent(m.medianReturn*100):'暂缺'],['强势股占比',share(m.strongStockShare)],['当前累计成交额',finite(m.turnover)?(m.turnover/1e8).toFixed(2)+'亿元':'暂缺'],['成交额历史分位',position(m.turnoverPercentile)],['前5大成交占比',share(m.top5TurnoverShare)],['单股收益集中度',share(m.top1ContributionShare)],['此前15日前10%次数',finite(m.topDecileCount15d)?m.topDecileCount15d+'次':'暂缺']]),h('p',{class:'preview-meta'},'单股收益集中度采用等权绝对收益占比代理。盘中成交额是当前累计值，未预测全天成交额。')]),
   h('section',[h('h3','数据质量与缺失'),grid([['总体完整度',number(point.completeness)+'%'],['有效历史样本',number(point.validCloses)+'个交易日'],['样本状态',point.coldStart?'冷启动／历史不足':'正常'],['改善证据',number(point.improvementEvidence)+'类'],['成分关系',point.membershipMode==='current_members_backfill'?'当前成分回填历史':'当天成分快照'],['活跃状态',({cold:'冷',neutral:'中性',warming:'升温',active:'活跃',crowded:'拥挤'})[point.heatState]??'暂未判定']]),
    h('p',{class:'preview-meta'},'完整度表示输入覆盖，不是预测成功率。历史重建即使使用当天成分，也不等于当时已可获得。'),
    missing.length?h('p',{class:'preview-missing'},'缺失说明：'+missing.join('、')+'。缺失不补零，按现有规则降低完整度或使相关分项不可用。'):h('p',{class:'preview-meta'},'当前记录没有报告缺失项。')]),
   h('details',{class:'preview-notes'},[h('summary','评分拆解 · 查看分项和覆盖率'),h('p','分项分为归一化后的 0–100 分，不是原始涨幅。名义权重来自当前评分配置；缺失会影响有效权重，机会分另有改善证据门槛，不能把名义权重简单相乘当作最终贡献。'),...breakdown(point,props.detail.scoringWeights)]),
   h('details',{class:'preview-notes'},[h('summary','历史对比 · '+history.length+'个交易日'),h('div',{class:'preview-table-scroll'},h('table',{class:'preview-table'},[h('thead',h('tr',['日期','涨幅','强度','机会','风险'].map(t=>h('th',t)))),h('tbody',historyRows)]))]),
   h('details',{class:'preview-notes'},[h('summary','技术字段（排查用）'),h('pre',JSON.stringify(point,null,2))])
  ]))
 }}
}
