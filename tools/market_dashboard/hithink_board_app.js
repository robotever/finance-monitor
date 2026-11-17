import {h,ref,onMounted,onUnmounted} from 'vue'
import PreviewDetail from './hithink_preview_detail.js'
import './hithink_preview_compact.css'
import {buildHistoryMatrix,formatHistoryValue} from '../../src/features/sector-rotation-v4/model.mjs'
import {createSnapshotReader} from './hithink_snapshot_reader.mjs'

export function createSectorBoard({snapshot=false}={}){return {setup(){
 const latest=ref(null),catalog=ref(null),detail=ref(null),error=ref(''),search=ref(''),page=ref(1),universe=ref('concept'),tab=ref('core'),history=ref(null),axis=ref('return1d'),selectedDate=ref(null)
 const views=[['potential','潜在轮动'],['main','主线确认'],['risk','风险升温']]
 const request=snapshot?createSnapshotReader():async(url)=>{const r=await fetch('/__local-reconstruction/'+url);const p=await r.json();if(!r.ok)throw Error(p.error);return p}
 async function load(){try{error.value='';catalog.value=await request('catalog?'+new URLSearchParams({universe:universe.value,page:String(page.value),pageSize:'50',q:search.value}));history.value=await request('history?'+new URLSearchParams({universe:universe.value,axis:axis.value,days:'15'}))}catch(e){error.value=String(e)}}
 async function select(row,date=null){selectedDate.value=date;try{detail.value=await request('detail?'+new URLSearchParams({universe:row.universe,id:row.id,days:'60'}))}catch(e){error.value=String(e)}}
 const button=(label,fn,props={})=>h('button',{type:'button',class:'market-button',onClick:fn,...props},label)
 const percent=r=>formatHistoryValue(r.metrics?.return1d??null,'return1d')
 const tone=v=>Number.isFinite(v)?v>0?'preview-gain':v<0?'preview-loss':'':''
 function table(rows,label){return h('div',{class:'preview-table-scroll',tabindex:0,'aria-label':label},[
  h('table',{class:'preview-table'},[h('thead',h('tr',['板块','涨幅','强度','机会','风险'].map(t=>h('th',{scope:'col'},t)))),h('tbody',rows.map(r=>h('tr',{key:r.id},[
   h('th',{scope:'row'},h('button',{type:'button',class:'preview-name',onClick:()=>select(r),title:r.id+' · 完整度'+r.completeness+'%'},r.name)),
   h('td',{class:tone(r.metrics?.return1d)},percent(r)),...['strength','opportunity','risk'].map(a=>h('td',r[a]??'—'))
  ])))])])}
 let timer
 async function refresh(){try{
  latest.value=await request('latest');await load()
  const opened=detail.value
  if(opened&&opened.batchId!==latest.value.batchId){
   const updated=await request('detail?'+new URLSearchParams({universe:opened.universe,id:opened.id,days:'60'}))
   if(detail.value===opened)detail.value=updated
  }
 }catch(e){error.value=String(e)}}
 onMounted(()=>{refresh();if(!snapshot)timer=setInterval(refresh,30000);window.addEventListener('focus',refresh)})
 onUnmounted(()=>{clearInterval(timer);window.removeEventListener('focus',refresh)})
 return()=>h('main',{class:'market-dashboard fv-card sector-rotation preview-compact'},[
  h('header',{class:'preview-header'},[
   h('div',[h('h1',snapshot?'板块研究 · 在线验收版':'板块研究 · 本地实时看板'),h('p',{class:'preview-meta'},latest.value?'市场日期 '+latest.value.marketDate+' · 采集 '+new Date(latest.value.observedAt).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})+' 北京时间 · '+(latest.value.historicalReconstruction?'历史重建':latest.value.officialClose?'收盘快照':'盘中快照'):'读取中…')]),
   button('刷新',refresh)
  ]),
  h('nav',{class:'preview-links','aria-label':'页面快速导航'},[snapshot?h('a',{href:'/'},'← 市场雷达与新闻'):null,h('a',{href:'#preview-overview'},'行业三榜'),h('a',{href:'#preview-concepts'},'概念观察'),h('a',{href:'#reconstruction-history'},'历史轮动'),h('a',{href:'#preview-catalog'},'全部目录')]),
  snapshot?h('p',{class:'market-notice'},'当前为发布时的数据快照，尚未接通线上自动更新，请以显示的采集时间为准。'):null,
  h('details',{class:'preview-notes'},[h('summary',snapshot?'数据说明 · 发布快照 / 历史含重建':'数据说明 · 15分钟采集 / 历史含重建 / 仅本机'),h('p',(snapshot?'本版数据固定在发布时点。':'盘中每15分钟采集，页面每30秒检查本地更新。')+'历史含事后重建及当前成分回填，存在幸存者偏差。缺失不补零，评分未完成预测有效性验证。'+(snapshot?'':'仅本机，未公开发布。')),latest.value?h('p',latest.value.sectorScoringVersion+' / '+latest.value.sectorUniverseVersion):null]),
  error.value?h('p',{class:'market-notice',role:'status'},error.value):null,
  h('section',{id:'preview-overview'},[h('h2','行业三榜'),h('div',{class:'preview-leaderboards'},views.map(([key,label])=>h('section',{class:'preview-panel'},[
   h('h3',label+' · '+(latest.value?.industry[key].length??0)+'项'),
   latest.value?.industry[key].length?table(latest.value.industry[key],label):h('p',{class:'preview-empty'},'暂无符合条件行业')
  ])))]),
  h('details',{id:'preview-concepts',class:'preview-fold'},[
   h('summary','概念观察 · 核心 '+(latest.value?.concept.core.length??0)+' / 动态 '+(latest.value?.concept.dynamic.length??0)+' · 点击展开'),
   h('div',{class:'sector-rotation__tabs'},[button('核心25',()=>tab.value='core',{'aria-pressed':tab.value==='core'}),button('动态10',()=>tab.value='dynamic',{'aria-pressed':tab.value==='dynamic'})]),
   table(latest.value?.concept[tab.value]??[],'概念观察')
  ]),
  h('section',{id:'reconstruction-history'},[
   h('div',{class:'preview-section-heading'},[h('h2','历史轮动'),h('span','最近日期在左 · 点击板块看详情')]),
   h('div',{class:'preview-history-controls'},[
    h('label',['分类 ',h('select',{value:universe.value,onChange:e=>{universe.value=e.target.value;page.value=1;load()}},[h('option',{value:'concept'},'概念'),h('option',{value:'industry'},'行业')])]),
    h('div',{class:'sector-rotation__tabs sector-rotation__history-tabs',role:'group','aria-label':'轮动排序维度'},[['return1d','涨幅'],['strength','强度'],['opportunity','机会'],['risk','风险']].map(([key,label])=>button(label,()=>{axis.value=key;load()},{'aria-pressed':(history.value?.axis??axis.value)===key})))
   ]),
   history.value?h('div',{class:'sector-rotation__matrix-scroll',tabindex:0,'aria-label':'15个交易日轮动矩阵'},[h('table',{class:'sector-rotation__matrix','data-history-columns':history.value.dates.length},[
    h('thead',h('tr',[h('th',{scope:'col'},'排名'),...history.value.dates.map(d=>h('th',{scope:'col','data-history-date':d},d+(d===history.value.liveDate?' · 盘中':'')))])),
    h('tbody',buildHistoryMatrix(history.value).map(rank=>h('tr',[h('th',{scope:'row'},rank.rank),...rank.cells.map(cell=>h('td',cell?h('button',{type:'button','aria-label':cell.name+' '+cell.marketDate+' 第'+rank.rank+'名，打开详情',onClick:()=>select({...cell,universe:universe.value},cell.marketDate)},[h('span',cell.name),h('strong',{class:history.value.axis==='return1d'?tone(cell.score):''},formatHistoryValue(cell.score,history.value.axis))]):'—'))])))
   ])]):h('p',{class:'preview-empty'},'历史加载中…'),
   h('p',{class:'preview-meta'},(snapshot?'当日列为发布时点快照；':'当日列随有效采集更新；')+'前日变化相对前一交易日，历史重建不代表当时已知信息。')
  ]),
  h('details',{id:'preview-catalog',class:'preview-fold'},[
   h('summary','全部行业与概念 · 480项 · 搜索、分页与详细评分'),
   h('form',{onSubmit:e=>{e.preventDefault();page.value=1;load()},class:'preview-catalog-controls'},[
    h('label',['分类 ',h('select',{value:universe.value,onChange:e=>{universe.value=e.target.value;page.value=1;load()}},[h('option',{value:'concept'},'概念'),h('option',{value:'industry'},'行业')])]),
    h('label',['名称或代码 ',h('input',{type:'search',placeholder:'搜索完整目录',value:search.value,onInput:e=>search.value=e.target.value})]),h('button',{type:'submit',class:'market-button'},'搜索')
   ]),
   h('p',{class:'preview-meta'},'共 '+(catalog.value?.total??0)+'项 · 第'+page.value+'页 / 每页50项'),
   table(catalog.value?.sectors??[],'完整目录'),
   h('nav',{class:'sector-rotation__tabs','aria-label':'板块分页'},[button('上一页',()=>{page.value--;load()},{disabled:page.value<=1}),button('下一页',()=>{page.value++;load()},{disabled:page.value*50>=(catalog.value?.total??0)})])
  ]),
  detail.value?h(PreviewDetail,{detail:detail.value,selectedDate:selectedDate.value,onClose:()=>detail.value=null,onSelectDate:date=>selectedDate.value=date}):null
 ])
}}}
