<template>
 <section class="market-watch terminal-panel" aria-labelledby="watch-title">
  <header class="terminal-panel__header"><div><p class="eyebrow">GLOBAL MARKET WATCH</p><h2 id="watch-title">全球联动 <span>固定观察 · 8项</span></h2></div><span class="market-watch__hint">价格与走势</span></header>
  <div class="market-watch__tabs" role="tablist" aria-label="固定关注品种"><button v-for="instrument in INSTRUMENTS" :id="`watch-tab-${instrument.id}`" :key="instrument.id" type="button" role="tab" :aria-selected="selected===instrument.id" aria-controls="watch-chart" :tabindex="selected===instrument.id?0:-1" :class="{active:selected===instrument.id}" @click="selected=instrument.id" @keydown="tabKey($event,instrument.id)">{{instrument.name}}</button></div>
  <div id="watch-chart" role="tabpanel" :aria-labelledby="`watch-tab-${selected}`" class="market-watch__body">
   <div class="market-watch__quote"><div><h3>{{active.name}}</h3><p>{{active.description}}</p></div><div v-if="quote&&active.provider!=='tradingview'" class="market-watch__price" :class="quote.changePercent>=0?'is-up':'is-down'"><strong>{{quote.price.toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}}</strong><span>{{quote.changePercent>0?'+':''}}{{quote.changePercent.toFixed(2)}}%</span></div><a v-else-if="active.symbol" :href="`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(active.symbol)}`" target="_blank" rel="noopener noreferrer" class="market-watch__external">查看来源 ↗</a></div>
   <template v-if="active.provider!=='tradingview'">
    <div v-if="quote&&geometry" class="price-chart" @pointermove="pointerMove" @pointerleave="hoverIndex=null">
     <div class="price-chart__labels"><span>{{geometry.max.toFixed(2)}}</span><span>{{geometry.min.toFixed(2)}}</span></div>
     <svg viewBox="0 0 960 240" role="img" :aria-label="`${active.name}${quote.marketDate}${active.session==='daily'?'日线':'分时'}走势图，当前${quote.price}，涨跌${quote.changePercent}%`" preserveAspectRatio="none"><defs><linearGradient id="watch-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#4ec9e7" stop-opacity=".24"/><stop offset="100%" stop-color="#4ec9e7" stop-opacity="0"/></linearGradient></defs><line v-for="y in [20,70,120,170,220]" :key="y" x1="10" x2="930" :y1="y" :y2="y" stroke="#23334b" stroke-width=".7"/><line x1="10" x2="930" :y1="geometry.baseline" :y2="geometry.baseline" stroke="#72849b" stroke-dasharray="5 5"/><path :d="geometry.path+` L${geometry.lastX},240 L10,240 Z`" fill="url(#watch-fill)"/><path :d="geometry.path" fill="none" stroke="#60d5ee" stroke-width="2" vector-effect="non-scaling-stroke"/><line v-if="hoverIndex!==null" :x1="hoverX" :x2="hoverX" y1="10" y2="230" stroke="#9bbace" stroke-dasharray="3 3"/></svg>
     <div v-if="hoverPoint" class="price-chart__tooltip">{{active.session==='daily'?hoverPoint.time:hoverPoint.time.slice(0,2)+':'+hoverPoint.time.slice(2)}} · {{hoverPoint.price.toFixed(2)}}</div>
     <div class="price-chart__times"><span>{{active.session==='daily'?quote.points[0]?.time:'09:30'}}</span><span>{{active.session==='daily'?'60个交易日':active.session==='hongkong'?'12:00 / 13:00':'11:30 / 13:00'}}</span><span>{{active.session==='daily'?quote.points.at(-1)?.time:active.session==='hongkong'?'16:00':'15:00'}}</span></div>
    </div>
    <div v-else class="chart-placeholder" role="status"><h3>{{loading?'正在读取指数行情…':'行情暂不可用'}}</h3><p v-if="error">{{error}}</p><button v-if="!loading" class="terminal-button" @click="loadQuote">重试行情</button></div>
    <footer class="market-watch__footer"><span v-if="quote">{{quote.provider}} · 行情 {{formatTime(quote.observedAt)}} · {{quote.status==='closed'?'休市 / 最近行情':quote.status==='delayed'?'行情可能延迟':'盘中行情'}}</span><span v-else>{{active.provider==='sina'?'新浪财经':'腾讯财经'}} · 60秒检查</span><span v-if="error" role="status">{{error}}</span><span v-else>北京时间 · 60秒检查</span></footer>
   </template>
   <template v-else><div ref="widgetHost" class="tradingview-host" :aria-label="`${active.name}官方行情图表`"/><p v-if="widgetError" class="market-watch__widget-error" role="status">图表连接暂未完成；可点击“查看来源”核实行情，或<button class="quiet-button" @click="renderWidget">重试图表</button>。</p><footer class="market-watch__footer"><span>TradingView · {{active.symbol}} · 价格 / 涨跌幅见图表</span><span>行情可能延迟 · 时间及休市状态以供应商图表为准</span></footer><a class="tradingview-credit" href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer">Charts by TradingView</a></template>
  </div>
 </section>
</template>
<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from 'vue'
import {INSTRUMENTS,chartGeometry,chartX,widgetConfig,type MarketQuote} from '@/features/market-watch/model.mjs'
const requested=new URLSearchParams(window.location.search).get('watch')
const selected=ref(INSTRUMENTS.some(i=>i.id===requested)?requested!:'shanghai'),active=computed(()=>INSTRUMENTS.find(i=>i.id===selected.value)!),quote=ref<MarketQuote|null>(null),loading=ref(false),error=ref(''),widgetError=ref(false),widgetHost=ref<HTMLElement|null>(null),hoverIndex=ref<number|null>(null)
const geometry=computed(()=>quote.value?chartGeometry(quote.value.points,quote.value.previousClose,active.value.session):null)
const hoverPoint=computed(()=>hoverIndex.value===null?null:quote.value?.points[hoverIndex.value]),hoverX=computed(()=>hoverIndex.value===null?10:active.value.session==='daily'?10+hoverIndex.value/Math.max(1,quote.value!.points.length-1)*920:chartX(quote.value!.points[hoverIndex.value]!.time,active.value.session))
let interval:ReturnType<typeof setInterval>,controller:AbortController|undefined,widgetTimer:ReturnType<typeof setTimeout>|undefined,observer:MutationObserver|undefined
function pointerMove(e:PointerEvent){if(!quote.value)return;const rect=(e.currentTarget as HTMLElement).getBoundingClientRect();const target=(e.clientX-rect.left)/(rect.width-46)*960;if(active.value.session==='daily'){hoverIndex.value=Math.max(0,Math.min(quote.value.points.length-1,Math.round((target-10)/920*(quote.value.points.length-1))));return}hoverIndex.value=quote.value.points.reduce((best,p,i)=>Math.abs(chartX(p.time,active.value.session)-target)<Math.abs(chartX(quote.value!.points[best]!.time,active.value.session)-target)?i:best,0)}
function formatTime(value:string){return new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
async function loadQuote(){
 if(active.value.provider==='tradingview')return
 controller?.abort();const local=new AbortController();controller=local;loading.value=true
 const id=selected.value
 try{const response=await fetch(`/api/market-watch/quote?instrument=${id}`,{signal:AbortSignal.any([local.signal,AbortSignal.timeout(12000)])});if(!response.ok)throw Error('行情暂不可用');const value=await response.json() as MarketQuote;if(!Array.isArray(value.points)||!Number.isFinite(value.price))throw Error('行情格式异常');if(selected.value===id){quote.value=value;error.value=''}}catch{if(!local.signal.aborted&&selected.value===id)error.value='刷新失败；已有行情仅供核对，请注意时间'}finally{if(selected.value===id)loading.value=false}
}
async function renderWidget(){
 clearTimeout(widgetTimer);observer?.disconnect();widgetError.value=false;await nextTick();if(!widgetHost.value||active.value.provider!=='tradingview')return
 const host=widgetHost.value;host.replaceChildren();const inner=document.createElement('div');inner.className='tradingview-widget-container__widget';inner.style.height='100%';host.append(inner)
 const script=document.createElement('script');script.src='https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';script.async=true;script.type='text/javascript';script.text=JSON.stringify(widgetConfig(selected.value));script.onerror=()=>{widgetError.value=true};host.append(script)
 observer=new MutationObserver(()=>{if(host.querySelector('iframe')){clearTimeout(widgetTimer);observer?.disconnect()}});observer.observe(host,{childList:true,subtree:true});widgetTimer=setTimeout(()=>{if(!host.querySelector('iframe'))widgetError.value=true},20000)
}
function tabKey(e:KeyboardEvent,id:string){if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const n=INSTRUMENTS.findIndex(i=>i.id===id),index=e.key==='Home'?0:e.key==='End'?7:(n+(e.key==='ArrowRight'?1:7))%8;selected.value=INSTRUMENTS[index]!.id;void nextTick(()=>document.getElementById('watch-tab-'+selected.value)?.focus())}
watch(selected,async()=>{controller?.abort();clearTimeout(widgetTimer);observer?.disconnect();quote.value=null;hoverIndex.value=null;error.value='';if(active.value.provider!=='tradingview')await loadQuote();else await renderWidget()})
onMounted(()=>{if(active.value.provider==='tradingview')void renderWidget();else void loadQuote();interval=setInterval(()=>{if(!document.hidden)void loadQuote()},60000)})
onUnmounted(()=>{clearInterval(interval);clearTimeout(widgetTimer);controller?.abort();observer?.disconnect()})
</script>
