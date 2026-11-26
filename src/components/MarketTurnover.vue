<template>
 <div class="market-turnover" data-market-turnover>
  <p class="turnover-comparison">{{data.date}} <span>亿元 · 较 {{data.previousDate}}{{dailyClose ? ' 全天（收盘后）' : data.comparisonTime ? ` ${data.comparisonTime} 同时间` : ' 同时间（待核验）'}}</span></p>
  <table>
   <caption class="sr-only">{{dailyClose ? '五市场收盘后成交额与前一交易日全天变化' : '五市场当日累计成交额与前一交易日同时间变化'}}，金额单位亿元</caption>
   <thead><tr><th scope="col">市场</th><th scope="col">当日成交额</th><th scope="col">{{dailyClose ? '较昨日收盘' : '较昨日同时间'}}</th></tr></thead>
   <tbody><tr v-for="row in data.rows" :key="row.id" :data-turnover-market="row.id">
    <th scope="row">{{row.name}}</th>
    <td :title="`当日累计 · ${timeText(row.currentAsOf)}`"><strong>{{formatTurnover(row.currentCny)}}</strong><time :datetime="row.currentAsOf">{{shortTime(row.currentAsOf)}}</time></td>
    <td :class="direction(row.changeCny)" :title="comparisonTitle(row)"><strong>{{formatTurnover(row.changeCny,true)}}</strong><small>{{percent(row.changePct)}}</small></td>
   </tr></tbody>
  </table>
  <div class="turnover-chart">
   <div class="turnover-markets" role="group" aria-label="历史成交额市场"><button v-for="item in markets" :key="item.id" type="button" :aria-pressed="market === item.id" @click="market=item.id;hoverIndex=null">{{item.name}}</button></div>
   <div class="turnover-tools">
    <div role="group" aria-label="历史成交额时间范围"><button v-for="months in [1,3,6,12]" :key="months" type="button" :aria-pressed="activeMonths === months" @click="selectRange(months)">{{months === 12 ? '1年' : `${months}月`}}</button></div>
    <div role="group" aria-label="历史图缩放和平移"><button type="button" aria-label="向前平移历史图" :disabled="windowStart === 0" @click="pan(-1)">←</button><button type="button" aria-label="缩小历史图" :disabled="windowEnd-windowStart >= points.length" @click="zoom(1.5)">−</button><button type="button" aria-label="放大历史图" :disabled="windowEnd-windowStart <= 5" @click="zoom(.67)">＋</button><button type="button" aria-label="向后平移历史图" :disabled="windowEnd >= points.length" @click="pan(1)">→</button></div>
   </div>
   <p class="turnover-chart-label">日成交额（日线汇总） <span>亿元</span></p>
   <div v-if="geometry.coordinates.some(Boolean)" class="turnover-plot">
    <svg viewBox="0 0 640 230" tabindex="0" role="img" :aria-label="`${marketName}日成交额曲线；左右键选日期，加减键缩放，Home及End键选择首尾`" @pointermove="hover" @pointerdown="hover" @keydown="chartKey">
     <g v-for="tick in geometry.ticks" :key="tick.y"><line x1="90" :y1="tick.y" x2="624" :y2="tick.y" class="turnover-grid"/><text x="80" :y="tick.y+4" text-anchor="end">{{tick.value.toLocaleString('zh-CN',{maximumFractionDigits:0})}}</text></g>
     <path :d="geometry.path" class="turnover-line"/>
     <template v-for="(point,index) in geometry.coordinates" :key="index"><circle v-if="point && !geometry.coordinates[index-1] && !geometry.coordinates[index+1]" :cx="point.x" :cy="point.y" r="2.5" class="turnover-dot"/></template>
     <template v-if="selectedCoordinate"><line :x1="selectedCoordinate.x" y1="20" :x2="selectedCoordinate.x" y2="192" class="turnover-crosshair"/><circle :cx="selectedCoordinate.x" :cy="selectedCoordinate.y" r="4" class="turnover-dot"/></template>
     <text x="90" y="220">{{visible[0]?.date}}</text><text x="624" y="220" text-anchor="end">{{visible.at(-1)?.date}}</text>
    </svg>
    <p class="turnover-readout" aria-live="polite"><time>{{selectedPoint?.date}}</time><strong>{{selectedPoint?.value == null ? '—' : selectedPoint.value.toLocaleString('zh-CN',{maximumFractionDigits:2})}} 亿元</strong><span v-if="selectedPoint?.value == null">当日数据缺失</span></p>
   </div>
   <p v-else class="turnover-empty" role="status">所选市场区间暂无可核验的日成交额。</p>
   <p class="turnover-coverage">{{coverage}} · 日线汇总，缺失不补零<br>触摸 / 悬停或左右键查看；＋ / − 缩放，箭头平移</p>
  </div>
  <details class="turnover-method"><summary>量能口径与来源</summary>
   <p>全市场为沪深北 A 股（含 ST / CDR）；创业板是深市子集，科创板是沪市子集，五行不可相加。盘中变化只比较前一交易日同时间；15:30后改为两日全天实际成交额。未通过口径核验时留空。</p>
   <p>历史仅含实际取得的已完成日线；日线截至 {{data.history.endDate}}，取得时间 {{timeText(data.history.asOf)}}。</p>
   <p v-for="row in data.rows.filter(item=>item.reason)" :key="row.id">{{row.name}}：{{reasonText(row.reason)}}</p>
   <p v-for="note in data.notes" :key="note">{{note}}</p>
   <p v-for="(source,index) in data.sources" :key="`${source.id}-${index}`"><a :href="source.url" target="_blank" rel="noopener noreferrer">{{sourceLabel(source.id,index)}}</a> · {{timeText(source.asOf)}}</p>
  </details>
 </div>
</template>

<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import type {TurnoverPayload} from '@/features/market-observation/turnover.mjs'
import {turnoverSeries,rangeStart,chartGeometry,resizeWindow,moveWindow,formatTurnover} from '@/features/market-observation/turnover-chart.mjs'
import type {MarketId} from '@/features/market-observation/turnover-chart.mjs'
const props=defineProps<{data:TurnoverPayload}>()
const markets:{id:MarketId;name:string}[]=[{id:'all',name:'全市场'},{id:'sh',name:'沪市'},{id:'sz',name:'深市'},{id:'chinext',name:'创业板'},{id:'star',name:'科创板'}]
const market=ref<MarketId>('all'),activeMonths=ref<number|null>(12),windowStart=ref(0),windowEnd=ref(0),hoverIndex=ref<number|null>(null)
const dailyClose=computed(()=>props.data.rows.some(row=>row.comparisonMode==='daily-close'))
const points=computed(()=>turnoverSeries(props.data.history.points,market.value))
const marketName=computed(()=>markets.find(item=>item.id===market.value)?.name ?? '全市场')
const visible=computed(()=>points.value.slice(windowStart.value,windowEnd.value))
const geometry=computed(()=>chartGeometry(visible.value))
const selectedIndex=computed(()=>Math.min(Math.max(hoverIndex.value ?? visible.value.length-1,0),visible.value.length-1))
const selectedPoint=computed(()=>visible.value[selectedIndex.value])
const selectedCoordinate=computed(()=>geometry.value.coordinates[selectedIndex.value])
const coverage=computed(()=>points.value.length ? `历史覆盖 ${points.value[0]?.date} — ${points.value.at(-1)?.date}` : '历史覆盖待更新')
function selectRange(months:number){activeMonths.value=months;windowStart.value=rangeStart(points.value,months);windowEnd.value=points.value.length;hoverIndex.value=null}
watch(()=>props.data.history,()=>selectRange(activeMonths.value ?? 12),{immediate:true})
function zoom(factor:number){const next=resizeWindow(points.value.length,windowStart.value,windowEnd.value,factor);windowStart.value=next.start;windowEnd.value=next.end;activeMonths.value=null;hoverIndex.value=null}
function pan(direction:number){const next=moveWindow(points.value.length,windowStart.value,windowEnd.value,direction);windowStart.value=next.start;windowEnd.value=next.end;activeMonths.value=null;hoverIndex.value=null}
function hover(event:PointerEvent){const rect=(event.currentTarget as SVGElement).getBoundingClientRect();if(!rect.width)return;const fraction=((event.clientX-rect.left)*640/rect.width-90)/534;hoverIndex.value=Math.max(0,Math.min(visible.value.length-1,Math.round(fraction*(visible.value.length-1))))}
function chartKey(event:KeyboardEvent){
 if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key)){event.preventDefault();hoverIndex.value=event.key==='Home' ? 0 : event.key==='End' ? visible.value.length-1 : Math.max(0,Math.min(visible.value.length-1,selectedIndex.value+(event.key==='ArrowLeft'?-1:1)))}
 if(['+','=','-'].includes(event.key)){event.preventDefault();zoom(event.key==='-'?1.5:.67)}
}
function direction(value:number|null){return value === null || value===0 ? '' : value>0 ? 'turnover-positive':'turnover-negative'}
function percent(value:number|null){return value === null ? '—' : `${value>0?'+':''}${value.toFixed(2)}%`}
function shortTime(value:string){return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value))}
function timeText(value:string){return new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date(value))+' 北京时间'}
function comparisonTitle(row:TurnoverPayload['rows'][number]){if(row.comparisonMode==='daily-close')return `${props.data.previousDate} 全天成交额 ${formatTurnover(row.previousSameTimeCny)} 亿元；收盘后比较全天实际成交额`;return `${props.data.previousDate} ${props.data.comparisonTime ?? '时间未对齐'} · 前一交易日同时间 ${formatTurnover(row.previousSameTimeCny)} 亿元${row.comparisonAsOf ? ` · ${timeText(row.comparisonAsOf)}`:''}${row.reason ? ` · ${reasonText(row.reason)}`:''}`}
function reasonText(reason:string|null){return reason && /[\u4e00-\u9fff]/.test(reason) ? reason : '同时间数据缺失或统计范围尚未通过核验，暂不计算变化'}
function sourceLabel(id:string,index:number){if(id.includes('mx')||id.includes('eastmoney-market'))return '东方财富市场级日成交额';if(id.includes('hithink'))return id.includes('daily')||id.includes('history') ? '同花顺日线':'同花顺行情';if(id.includes('eastmoney'))return '东方财富市场分时';if(id.includes('tencent'))return '腾讯市场分时';return `数据来源 ${index+1}`}
</script>

<style scoped>
.market-turnover{min-width:0;font-variant-numeric:tabular-nums;color:#c6dbea}.turnover-comparison{display:flex;flex-wrap:wrap;justify-content:space-between;gap:3px;font-size:9px;color:#8facbf;margin:0 0 7px;line-height:1.6}.turnover-comparison span{color:#7899b0}table{table-layout:fixed;width:100%;border-collapse:collapse;font-size:11px}th,td{padding:6px 0;border-bottom:1px solid #243b4e;text-align:right}th:first-child{width:23%;text-align:left}thead th{font-size:9px;color:#87a8be;font-weight:400}tbody th{font-size:11px;font-weight:400;color:#b1cbdc}td strong{font-size:13px;font-weight:500;display:block}td time,td small{display:block;font-size:9px;line-height:1.7;color:#7899b0}td small{color:inherit}.turnover-positive{color:#eb9297}.turnover-negative{color:#71c6ac}.turnover-chart{min-width:0;margin-top:11px;padding-top:9px;border-top:1px solid #294355}.turnover-markets,.turnover-tools,.turnover-tools>div{display:flex;align-items:center;gap:4px}.turnover-markets{display:grid;grid-template-columns:repeat(5,minmax(0,1fr))}.turnover-tools{justify-content:space-between;margin-top:7px;flex-wrap:wrap;gap:6px}.market-turnover button{font:inherit;font-size:9px;white-space:nowrap;background:#132b3e;border:1px solid #2a485d;border-radius:4px;color:#92b4ca;padding:4px 5px;cursor:pointer}.market-turnover button[aria-pressed="true"]{background:#285b76;border-color:#65a9c3;color:#e1f8ff}.market-turnover button:hover{border-color:#71cbe3}.market-turnover button:disabled{opacity:.35;cursor:default}.market-turnover button:focus-visible,.market-turnover svg:focus-visible{outline:2px solid #71cbe3;outline-offset:2px}.turnover-chart-label{display:flex;justify-content:space-between;font-size:9px;color:#91afc3;margin:9px 0 0}.turnover-chart-label span{color:#7292aa}.turnover-plot svg{display:block;width:100%;height:auto;touch-action:pan-y}.turnover-plot svg text{font-size:16px;fill:#819fb4}.turnover-grid{stroke:#284252;stroke-dasharray:3 4;stroke-width:1}.turnover-line{fill:none;stroke:#70c8de;stroke-width:1.7;stroke-linejoin:round;vector-effect:non-scaling-stroke}.turnover-crosshair{stroke:#a1bbc9;stroke-dasharray:3 4}.turnover-dot{fill:#a1ecf7;stroke:#102031;stroke-width:1.5}.turnover-readout{display:flex;justify-content:center;align-items:center;gap:8px;flex-wrap:wrap;font-size:10px;min-height:16px;margin:0;color:#8daec4}.turnover-readout strong{color:#a0e5f4;font-weight:500}.turnover-readout span{font-size:9px}.turnover-coverage{font-size:9px;color:#7394ab;line-height:1.8;margin:6px 0 0;overflow-wrap:anywhere}.turnover-empty{font-size:10px;color:#84a4bc;line-height:1.8;text-align:center;padding:30px 8px}.turnover-method{margin-top:9px;padding-top:8px;border-top:1px solid #294152;color:#89a7bc;font-size:10px}.turnover-method summary{cursor:pointer}.turnover-method p{line-height:1.8;margin:7px 0;overflow-wrap:anywhere}.turnover-method a{color:#a2d2e4}.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
</style>
