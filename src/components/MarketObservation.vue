<template>
 <section id="market-observation" class="market-observation terminal-panel" aria-labelledby="market-observation-title" :aria-busy="loading">
  <ModuleHeader title="市场观测指标" title-id="market-observation-title" :time-text="data ? `快照 · ${timeText(data.snapshotAt)}` : undefined" :datetime="data?.snapshotAt" time-title="来源快照时间（北京时间）；刷新读取最新已发布数据" :loading="loading" @refresh="refresh"/>
  <div v-if="data" class="observation-body">
   <p v-if="error || data.cached" class="observation-status" role="status">{{error || '当前显示缓存快照，时间见标题栏'}}</p>
   <div class="observation-grid">
    <article v-for="group in data.groups" :key="group.id" class="observation-card" :data-observation-group="group.id" :aria-labelledby="`observation-${group.id}`">
     <header><h3 :id="`observation-${group.id}`">{{titles[group.id]}}</h3><time :datetime="group.asOf">{{timeText(group.asOf)}}</time></header>
     <dl class="observation-metrics">
      <div v-for="metric in group.metrics" :key="metric.id" class="observation-metric" :data-metric="metric.id">
       <dt>{{metric.label}}</dt>
       <dd :title="metricTitle(metric)"><strong>{{numberText(metric.value)}}</strong><span v-if="metric.value !== null" class="metric-unit">{{metric.unit}}</span><span v-else class="sr-only">{{missingReason(metric.reason)}}</span></dd>
       <span class="metric-date">{{modeText(metric.mode)}} · {{timeText(metric.date)}}</span>
      </div>
     </dl>
     <details v-if="group.id === 'breadth' && data.details.distribution.length" class="observation-card-detail" data-observation-detail="distribution">
      <summary>涨跌分布</summary>
      <div class="observation-distribution" role="img" aria-label="各涨跌区间股票家数">
       <div v-for="(bin, index) in data.details.distribution" :key="bin.label" :class="{'distribution-down': index < 3, 'distribution-up': index > 3}"><span>{{bin.count}}</span><i :style="{height: `${Math.max(2, bin.count / distributionMax * 48)}px`}"/><small>{{bin.label}}</small></div>
      </div>
     </details>
     <details v-if="group.id === 'relay'" class="observation-card-detail" data-observation-detail="relay">
      <summary>封板与昨日涨停明细</summary>
      <p>{{timeText(data.details.relay.date)}}：涨停 {{numberText(data.details.relay.upCount)}} 家，跌停 {{numberText(data.details.relay.downCount)}} 家，炸板 {{numberText(data.details.relay.openCount)}} 家，触板 {{numberText(data.details.relay.touchedCount)}} 家。</p>
      <p v-if="data.details.relay.ladder.length">连板梯队：{{data.details.relay.ladder.map(row => `${row.boards}板 ${row.count}家`).join(' · ')}}</p>
      <p>昨日涨停样本（{{timeText(data.details.relay.yesterdayLimitUp.date)}}）：{{data.details.relay.yesterdayLimitUp.matched}} / {{data.details.relay.yesterdayLimitUp.expected}} 家；今日平均涨幅 {{percentText(data.details.relay.yesterdayLimitUp.meanReturn)}}，晋级率 {{percentText(data.details.relay.yesterdayLimitUp.promotionRate)}}。</p>
     </details>
    </article>
   </div>
   <details class="observation-detail" data-observation-detail="events">
    <summary>龙虎榜与异动</summary>
    <section aria-labelledby="observation-dragon-title">
     <h3 id="observation-dragon-title">龙虎榜 <time :datetime="data.details.dragonTiger.date">{{timeText(data.details.dragonTiger.date)}}</time><span>前一交易日披露</span></h3>
     <p v-if="data.details.dragonTiger.note">{{data.details.dragonTiger.note}}</p>
     <div v-if="data.details.dragonTiger.rows.length" class="observation-table-wrap"><table data-observation-table="dragon-tiger"><caption class="sr-only">龙虎榜机构净额、榜单总买卖额，单位亿元，分别保留上榜周期</caption><thead><tr><th scope="col">证券</th><th scope="col">周期</th><th scope="col">机构净额（亿）</th><th scope="col">榜单总买入（亿）</th><th scope="col">榜单总卖出（亿）</th></tr></thead><tbody><tr v-for="(row, index) in dragonRows" :key="`${row.code}-${row.rangeDays}-${index}`"><th scope="row">{{row.name || '名称未提供'}} <small v-if="row.code">{{row.code}}</small></th><td>{{row.rangeDays == null ? '—' : `${row.rangeDays}日`}}</td><td>{{currencyText(row.netCny)}}</td><td>{{currencyText(row.buyCny)}}</td><td>{{currencyText(row.sellCny)}}</td></tr></tbody></table></div>
     <p v-else>{{data.details.dragonTiger.status === 'failed' ? '龙虎榜来源暂未更新。' : '该日暂无可展示记录。'}}</p>
     <button v-if="data.details.dragonTiger.rows.length > 20" class="quiet-button" :aria-expanded="dragonExpanded" @click="dragonExpanded = !dragonExpanded">{{dragonExpanded ? '收起' : `展开全部 ${data.details.dragonTiger.rows.length} 条`}}</button>
    </section>
    <section aria-labelledby="observation-abnormal-title">
     <h3 id="observation-abnormal-title">异动记录 <time :datetime="data.details.abnormal.asOf">{{timeText(data.details.abnormal.asOf)}}</time></h3>
     <p v-if="data.details.abnormal.note">{{data.details.abnormal.note}}</p>
     <div v-if="data.details.abnormal.rows.length" class="observation-table-wrap"><table data-observation-table="abnormal"><thead><tr><th scope="col">证券</th><th scope="col">观察区间</th><th scope="col">异动</th></tr></thead><tbody><tr v-for="(row, index) in abnormalRows" :key="`${row.code}-${row.startDate}-${index}`"><th scope="row">{{row.name || '市场异动'}} <small v-if="row.code">{{row.code}}</small></th><td>{{timeText(row.startDate)}}<template v-if="row.endDate && row.endDate !== row.startDate"> — {{timeText(row.endDate)}}</template></td><td>{{row.label}}</td></tr></tbody></table></div>
     <p v-else>{{data.details.abnormal.status === 'failed' ? '异动来源暂未更新。' : '当前暂无可展示记录。'}}</p>
     <button v-if="data.details.abnormal.rows.length > 20" class="quiet-button" :aria-expanded="abnormalExpanded" @click="abnormalExpanded = !abnormalExpanded">{{abnormalExpanded ? '收起' : `展开全部 ${data.details.abnormal.rows.length} 条`}}</button>
    </section>
   </details>
   <details class="observation-detail" data-observation-detail="methodology">
    <summary>统计口径与来源</summary>
    <p>范围：{{data.scope.name}}。应有 {{data.scope.expected}} 家，收到 {{data.scope.received}} 家，有效交易 {{data.scope.active}} 家，排除 {{data.scope.excluded}} 家。历史匹配 {{data.scope.historyMatched}} / {{data.scope.historyExpected}} 家，截至 {{timeText(data.scope.historyAsOf)}}。</p>
    <p>市场广度观察涨跌家数与分布；趋势覆盖使用已完成交易日的均线与新高新低；量能结构比较相同时间口径的成交额；封板与接力观察涨停封住情况及昨日涨停样本的今日表现。盘中、日线及前收盘分别标注，分母和可用样本见各指标提示。刷新读取已发布快照，不触发重新采集。</p>
    <p>交易日 {{timeText(data.marketDate)}}；前一交易日 {{timeText(data.previousMarketDate)}}。快照与日线日期可以不同，龙虎榜使用前一交易日披露数据。缺失值显示“—”，不按零计入。</p>
    <p v-for="note in data.notes" :key="note">{{note}}</p>
    <div class="observation-sources"><div v-for="(source, index) in sourceRows" :key="`${source.id}-${source.url}`" data-observation-source><a :href="source.url" target="_blank" rel="noopener noreferrer">{{sourceName(source.id, index)}}</a><time :datetime="source.asOf">{{timeText(source.asOf)}}</time></div></div>
    <ul v-if="missingMetrics.length" class="observation-missing"><li v-for="metric in missingMetrics" :key="metric.id">{{metric.label}}：{{missingReason(metric.reason)}}</li></ul>
   </details>
  </div>
  <p v-else class="observation-empty" role="status">{{loading ? '正在读取市场观测数据…' : (error || '市场观测数据尚未发布')}}<button v-if="!loading" class="quiet-button" @click="refresh">重试</button></p>
 </section>
</template>

<script setup lang="ts">
import {computed, onMounted, onUnmounted, ref, shallowRef} from 'vue'
import ModuleHeader from './ModuleHeader.vue'
import {validateMarketObservation} from '@/features/market-observation/model.mjs'

type Metric = {id:string;label:string;value:number|null;unit:string;date:string;mode:'intraday'|'daily'|'previous-close';sample:number|null;reason:string|null}
type Payload = {schemaVersion:string;observedAt:string;marketDate:string;previousMarketDate:string;snapshotAt:string;scope:{name:string;expected:number;received:number;active:number;excluded:number;historyMatched:number;historyExpected:number;historyAsOf:string};groups:{id:'breadth'|'trend'|'turnover'|'relay';title:string;asOf:string;metrics:Metric[]}[];details:{distribution:{label:string;count:number}[];relay:{date:string;sourceSealRate:number|null;upCount:number|null;downCount:number|null;openCount:number|null;touchedCount:number|null;ladder:{boards:number;count:number}[];yesterdayLimitUp:{date:string;expected:number;matched:number;meanReturn:number|null;promotionRate:number|null}};dragonTiger:{date:string;asOf:string;status:'ok'|'failed';rows:{code:string|null;name:string|null;netCny:number|null;buyCny:number|null;sellCny:number|null;rangeDays:number|null}[];note?:string|null};abnormal:{asOf:string;status:'ok'|'failed';rows:{code:string|null;name:string|null;startDate:string;endDate:string|null;label:string}[];note?:string|null}};sources:{id:string;url:string;asOf:string}[];notes:string[];cached?:boolean}
const data=shallowRef<Payload|null>(null), loading=ref(false), error=ref(''), dragonExpanded=ref(false), abnormalExpanded=ref(false)
const titles={breadth:'市场广度',trend:'趋势覆盖',turnover:'量能结构',relay:'封板与接力'}
const distributionMax=computed(()=>Math.max(1,...(data.value?.details.distribution.map(row=>row.count) ?? [])))
const dragonRows=computed(()=>data.value?.details.dragonTiger.rows.slice(0,dragonExpanded.value?undefined:20) ?? [])
const abnormalRows=computed(()=>data.value?.details.abnormal.rows.slice(0,abnormalExpanded.value?undefined:20) ?? [])
const sourceRows=computed(()=>{
 const rows=new Map<string,Payload['sources'][number]>()
 for(const source of data.value?.sources ?? []){
  const url=new URL(source.url)
  for(const parameter of ['limit','offset','page','page_size'])url.searchParams.delete(parameter)
  const key=`${source.id}|${url.href}`,existing=rows.get(key)
  if(!existing || new Date(source.asOf).getTime() > new Date(existing.asOf).getTime())rows.set(key,source)
 }
 return [...rows.values()]
})
const missingMetrics=computed(()=>data.value?.groups.flatMap(group=>group.metrics).filter(metric=>metric.value === null) ?? [])
let controller:AbortController|undefined, timer:ReturnType<typeof setInterval>|undefined, alive=true
function numberText(value:number|null,digits=1){return value === null ? '—' : value.toLocaleString('zh-CN',{maximumFractionDigits:digits})}
function currencyText(value:number|null){return value === null ? '—' : numberText(value / 1e8, 2)}
function percentText(value:number|null){return value === null ? '—' : `${numberText(value)}%`}
function timeText(value:string){
 if(/^\d{4}-\d{2}-\d{2}$/.test(value))return value.slice(5).replace('-', '/')
 const parsed=new Date(value)
 return Number.isFinite(parsed.getTime()) ? new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(parsed) : '—'
}
function modeText(mode:Metric['mode']){return {intraday:'盘中',daily:'日线', 'previous-close':'前收盘'}[mode]}
function missingReason(reason:string|null){
 const reasons:Record<string,string>={MISSING:'来源暂未提供',SOURCE_UNAVAILABLE:'来源暂未更新',INSUFFICIENT_HISTORY:'历史样本不足',INSUFFICIENT_COVERAGE:'有效样本不足',NO_SAMPLE:'暂无符合条件样本',NO_SNAPSHOT:'尚无行情快照',DATE_MISMATCH:'来源日期未对齐'}
 if(!reason)return '来源暂未提供'
 return reasons[reason] || (/[\u4e00-\u9fff]/.test(reason) ? reason : '当前可用数据不足，暂不计算')
}
function metricTitle(metric:Metric){return `${modeText(metric.mode)} · ${metric.date}${metric.sample === null ? '' : ` · 有效样本 ${metric.sample} 家`}${metric.value === null ? ` · ${missingReason(metric.reason)}` : ''}`}
function sourceName(id:string,index:number){
 const names:Record<string,string>={hithink:'同花顺行情','hithink-finance':'同花顺行情','hithink-daily':'同花顺日线',eastmoney:'东方财富','dragon-tiger':'龙虎榜',abnormal:'市场异动','prices/snapshot':'全A股行情快照','special-data/limit-up-statistics':'涨停与封板统计','special-data/limit-up-pool':'涨停样本','special-data/limit-down-pool':'跌停样本','special-data/dragon-tiger-list':'机构龙虎榜','special-data/abnormal-monitor-list':'市场异动监控','hithink-readonly-daily-history':'同花顺已完成日线'}
 return names[id] || `数据来源 ${index+1}`
}
async function refresh(){
 if(loading.value)return
 loading.value=true;controller=new AbortController()
 try{
  const response=await fetch('/api/market-observation',{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(32000)]),cache:'no-store'})
  if(!response.ok)throw new Error('UNAVAILABLE')
  const result=validateMarketObservation(await response.json()) as Payload
  if(alive){data.value=result;error.value=''}
 }catch{if(alive)error.value=data.value ? '刷新未成功，保留原快照及数据时间' : '市场观测数据暂未更新'}
 finally{if(alive)loading.value=false}
}
function visible(){if(!document.hidden)void refresh()}
onMounted(()=>{void refresh();timer=setInterval(visible,300000);document.addEventListener('visibilitychange',visible)})
onUnmounted(()=>{alive=false;controller?.abort();clearInterval(timer);document.removeEventListener('visibilitychange',visible)})
defineExpose({refresh})
</script>

<style scoped>
.observation-body{padding:0 14px 12px}.observation-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.observation-card{min-width:0;background:#101f30;border:1px solid #243b50;border-radius:7px;padding:11px 12px}.observation-card>header{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:10px}.observation-card h3{font-size:13px;font-weight:500;color:#c7deed;margin:0}.observation-card header time{font-size:10px;color:#7899b0;white-space:nowrap}.observation-metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px 10px;margin:0}.observation-metric{min-width:0}.observation-metric dt{font-size:11px;color:#92afc3;line-height:1.5}.observation-metric dd{margin:3px 0 1px;color:#e0ecf4;white-space:nowrap}.observation-metric strong{font-size:22px;line-height:1.2;font-weight:600;font-variant-numeric:tabular-nums}.metric-unit{font-size:10px;color:#8eacc1;margin-left:4px}.metric-date{display:block;font-size:9px;line-height:1.6;color:#7596af}.observation-status{font-size:10px;color:#cfb98d;padding:0 0 8px;margin:0}.observation-card-detail,.observation-detail{font-size:10px;color:#89a9bf;border-top:1px solid #233c50;margin-top:10px;padding-top:8px}.observation-card-detail summary,.observation-detail summary{cursor:pointer;width:fit-content;line-height:1.6}.observation-card-detail p,.observation-detail p{font-size:10px;line-height:1.8;margin:7px 0}.observation-detail h3{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:12px 0 6px;font-size:11px;font-weight:500;color:#bcd3e3}.observation-detail h3 time,.observation-detail h3 span{font-size:10px;color:#7899b0;font-weight:400}.observation-table-wrap{overflow-x:auto}.observation-detail table{width:100%;border-collapse:collapse;font-size:10px;font-variant-numeric:tabular-nums}.observation-detail th,.observation-detail td{text-align:right;border-bottom:1px solid #20364a;padding:6px 8px;white-space:nowrap}.observation-detail th:first-child,.observation-detail td:first-child{text-align:left;padding-left:0}.observation-detail th{font-weight:400;color:#a2bed0}.observation-detail small{font-size:9px;color:#708ea4;margin-left:4px}.observation-sources>div{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-bottom:1px solid #20364a}.observation-sources a{color:#9dc1dc;text-decoration:none}.observation-sources a:hover{text-decoration:underline}.observation-missing{padding-left:15px;line-height:1.8}.observation-empty{padding:24px 14px;text-align:center;color:#7f9db1;font-size:12px}.observation-empty button{margin-left:9px}.observation-distribution{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:4px;align-items:end;margin-top:10px;min-height:82px}.observation-distribution>div{display:flex;align-items:center;flex-direction:column;justify-content:end;gap:3px;color:#8ba4b5;font-size:9px;min-width:0}.observation-distribution i{display:block;width:70%;max-width:30px;background:#647f94;border-radius:2px 2px 0 0}.observation-distribution .distribution-down i{background:#397e74}.observation-distribution .distribution-up i{background:#ae666b}.observation-distribution small{font-size:8px;white-space:nowrap}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}@media(min-width:1600px){.observation-grid{grid-template-columns:repeat(4,minmax(0,1fr))}}@media(max-width:600px){.observation-body{padding:0 10px 10px}.observation-grid{gap:8px}.observation-card{padding:9px 8px}.observation-card>header{align-items:flex-start;flex-direction:column;gap:2px}.observation-card h3{font-size:12px}.observation-metrics{gap:10px 6px}.observation-metric dt{font-size:10px}.observation-metric strong{font-size:19px}.metric-date{font-size:8px}.observation-detail th,.observation-detail td{padding:6px 5px}.observation-distribution small{font-size:7px}}@media(max-width:420px){.observation-grid{grid-template-columns:1fr}.observation-card>header{flex-direction:row}.metric-date{font-size:9px}}
</style>
