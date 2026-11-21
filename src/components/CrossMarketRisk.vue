<template>
 <section class="cross-risk" aria-label="跨市场风险监控" :aria-busy="loading">
  <header class="cross-risk__overview">
   <div><p v-if="dashboard" class="cross-risk__summary">{{dashboard.summary}}</p><p v-else>{{loading?'正在核验跨市场数据…':'暂未取得有效风险数据'}}</p><div v-if="dashboard" class="cross-risk__coverage"><span>{{dashboard.assessable}}/{{dashboard.total}}项可评估</span><span v-if="dashboard.stressCount" class="risk-tone-stress">{{dashboard.stressCount}}项压力</span><span v-if="dashboard.watchCount" class="risk-tone-watch">{{dashboard.watchCount}}项升温</span><span v-if="dashboard.unknownCount">{{dashboard.unknownCount}}项待核验</span><span v-if="dashboard.sourceErrors">{{dashboard.sourceErrors}}个数据源未更新</span></div></div>
   <button type="button" class="quiet-button" :disabled="loading" @click="refresh">{{loading?'核验中':'刷新'}}</button>
  </header>
  <p v-if="error" role="status" class="cross-risk__error">{{error}}</p>
  <div v-if="dashboard?.confirmations.length" class="cross-risk__links"><p v-for="text in dashboard.confirmations" :key="text">{{text}}</p></div>
  <div v-if="dashboard" class="cross-risk__grid">
   <article v-for="card in dashboard.cards" :key="card.id" class="risk-card" :class="`risk-card--${card.state}`">
    <header><h3>{{card.title}}<small>{{card.id==='conditions'?'4周变化':card.id==='equities'?'共同5日':'5期变化'}}</small></h3><span class="risk-state" :class="`risk-tone-${card.state}`">{{card.label}}<template v-if="card.partial&&card.state!=='unknown'"> · 部分缺失</template></span></header>
    <p class="risk-card__reason">{{card.reason}}</p>
    <div class="risk-metrics">
     <div v-for="metric in card.metrics" :key="metric.id" class="risk-metric" :class="{'risk-metric--old':metric.stale||metric.failed}">
      <span class="risk-metric__label">{{metric.label}}<small>{{metric.frequency}}<template v-if="metric.date"> · {{metric.date}}</template><template v-if="metric.stale&&metric.value!==null"> · 滞后</template><template v-else-if="metric.failed&&metric.value!==null"> · 上次数据</template></small></span>
      <strong>{{formatValue(metric)}}</strong><span class="risk-metric__change" :title="changeTitle(metric,card)">{{formatChange(metric,card)}}</span>
     </div>
    </div>
    <div v-if="card.trend.length>1" class="risk-trend"><svg viewBox="0 0 260 36" preserveAspectRatio="none" role="img" :aria-label="`${card.trendLabel}最近${card.trend.length}期，${card.trend[0]?.date}至${card.trend.at(-1)?.date}`"><path :d="sparkline(card.trend)" fill="none" stroke="currentColor" stroke-width="1.5" vector-effect="non-scaling-stroke"/></svg><span>{{card.trendLabel}} · {{card.trend.length}}期<template v-if="card.coverage"> · {{card.coverage}}</template></span></div>
    <p v-else-if="card.coverage" class="risk-card__coverage">{{card.coverage}}</p>
   </article>
  </div>
  <div v-else-if="loading" class="cross-risk__loading">连接官方发布与行情序列…</div>
  <details class="cross-risk__method"><summary>数据与方法<time v-if="dashboard">核验 {{formatTime(dashboard.checkedAt)}} 北京</time></summary>
   <p>日频与周频按各自发布日期核验；日频超过5个自然日、周频超过14日不评估当前状态。曲线及融资基差严格按同日配对，股市联动按5个共同交易日计算。变动列：汇率/股市为5期收益率，利率为5期bp变化，VIX为5期点数变化，NFCI为4周变化。</p>
   <p>状态是可调整的观察规则，不是风险概率；六类信号相互关联，不相加成总分。数值分位仅在至少60个有效观测时展示，不等同预测准确率。</p>
   <ul><li v-for="card in dashboard?.cards" :key="card.id"><strong>{{card.title}}</strong>：{{card.impact}} {{ruleText(card.id)}}</li></ul>
   <div v-if="dashboard" class="cross-risk__sources"><div v-for="source in dashboard.sources" :key="source.id"><span>{{source.name}}</span><span>{{source.status==='ok'?'已核验':source.cached?'本次失败 · 保留上次观测':'暂不可用'}}</span><time>{{source.observedAt??'—'}}</time></div></div>
   <div v-if="dashboard" class="cross-risk__percentiles"><span v-for="metric in percentileMetrics" :key="metric.id">{{metric.label}} · 近{{metric.sampleCount}}期分位 {{metric.percentile}}%</span></div>
   <p class="cross-risk__source-links"><a href="https://www.cboe.com/tradable_products/vix/" target="_blank" rel="noopener noreferrer">Cboe</a><a href="https://home.treasury.gov/treasury-daily-interest-rate-xml-feed" target="_blank" rel="noopener noreferrer">美国财政部</a><a href="https://www.chicagofed.org/research/data/nfci/about" target="_blank" rel="noopener noreferrer">芝加哥联储</a><a href="https://www.newyorkfed.org/markets/reference-rates" target="_blank" rel="noopener noreferrer">纽约联储</a><a href="https://www.bis.org/publications/broad-dollar-exchange-rate-eme-risk-factor" target="_blank" rel="noopener noreferrer">BIS研究</a></p>
  </details>
 </section>
</template>
<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,shallowRef} from 'vue'
import {RISK_VERSION,RULES,type Metric,type Point,type RiskCard,type RiskModel} from '@/features/cross-market-risk/model.mjs'
const dashboard=shallowRef<RiskModel|null>(null),loading=ref(false),error=ref('')
let controller:AbortController|undefined,timer:ReturnType<typeof setInterval>|undefined,alive=true
const percentileMetrics=computed(()=>dashboard.value?.cards.flatMap(c=>c.metrics).filter(m=>m.percentile!==null&&!m.stale&&!m.failed)??[])
async function refresh(){
 if(loading.value)return;loading.value=true;controller=new AbortController()
 try{
  const response=await fetch('/api/cross-market/risk',{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(32000)]),cache:'no-store'})
  if(!response.ok)throw Error('RISK_UNAVAILABLE')
  const data=await response.json() as RiskModel
  if(data.version!==RISK_VERSION||!Number.isFinite(data.checkedAt)||!Array.isArray(data.cards)||data.cards.length!==6||!Array.isArray(data.confirmations))throw Error('INVALID_RISK_DATA')
  if(alive){dashboard.value=data;error.value=''}
 }catch{
  if(alive){error.value='本次核验未完成，暂不判断当前风险。';if(dashboard.value)dashboard.value={...dashboard.value,state:'unknown',summary:'本次核验失败，以下为上次取得的观测。',assessable:0,watchCount:0,stressCount:0,unknownCount:6,confirmations:[],cards:dashboard.value.cards.map(c=>({...c,state:'unknown',label:'未更新',reason:'等待数据核验。',metrics:c.metrics.map(m=>({...m,failed:true}))}))}}
 }finally{if(alive)loading.value=false}
}
function formatValue(metric:Metric){if(metric.value===null)return '—';const decimals=metric.unit==='bp'?1:['cnh'].includes(metric.id)?4:['nfci','credit'].includes(metric.id)?3:2;return metric.value.toLocaleString('zh-CN',{minimumFractionDigits:decimals,maximumFractionDigits:decimals})+metric.unit}
function changeValue(metric:Metric,card:RiskCard){if(metric.stale||metric.failed)return null;if(['fx','equities'].includes(card.id))return metric.return5;if(metric.frequency==='周频')return metric.changeWindow??null;return metric.unit==='%'&&metric.change5!==null?metric.change5*100:metric.change5}
function formatChange(metric:Metric,card:RiskCard){const n=changeValue(metric,card);if(n===null)return '—';const unit=['fx','equities'].includes(card.id)?'%':['%','bp'].includes(metric.unit)?'bp':metric.unit==='点'?'点':'';const decimals=metric.frequency==='周频'?3:unit==='bp'?1:2,rounded=Number(n.toFixed(decimals));return (rounded>0?'+':'')+rounded.toFixed(decimals)+unit}
function changeTitle(metric:Metric,card:RiskCard){return (card.id==='equities'?'5个共同交易日':metric.windowLabel??'5期')+'变化'}
function formatTime(ms:number){return new Date(ms).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'})}
function sparkline(points:Point[]){const values=points.map(p=>p.value),low=Math.min(...values),high=Math.max(...values),range=high-low||1;return points.map((p,i)=>`${i?'L':'M'}${(i/Math.max(1,points.length-1)*256+2).toFixed(1)},${(32-(p.value-low)/range*28).toFixed(1)}`).join(' ')}
function ruleText(id:string){const r=RULES;return ({volatility:`关注/压力：VIX ${r.vix!.join('/')}点，或5期上升${r.vixChange!.join('/')}点。`,rates:`关注/压力：10年名义或实际利率5期上升${r.yield5bp!.join('/')}bp。`,conditions:`关注/压力：NFCI达到${r.nfci!.join('/')}，或4周上升${r.nfci4w!.join('/')}。`,fx:`5期关注/压力：美元上升${r.dollar5!.join('/')}%、美元/人民币上升${r.cnh5!.join('/')}%、美元/日元下降${r.yen5!.join('/')}%。`,funding:`${r.fundingBp![0]}bp关注，${r.fundingBp![1]}bp且连续3期才记压力。`,equities:`至少两个市场在共同窗口下跌${r.equityFall5!.join('/')}%记关注/压力。`} as Record<string,string>)[id]??''}
function visible(){if(!document.hidden)void refresh()}
onMounted(()=>{void refresh();timer=setInterval(visible,300000);document.addEventListener('visibilitychange',visible)})
onUnmounted(()=>{alive=false;controller?.abort();clearInterval(timer);document.removeEventListener('visibilitychange',visible)})
</script>
<style scoped>
.cross-risk{padding:0 14px 14px;color:#bad0df}.cross-risk__overview{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:2px 0 12px}.cross-risk__summary{font-size:12px;line-height:1.65;color:#d6e6f0;margin:0}.cross-risk__coverage{display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:6px;font-size:10px;color:#809db3}.cross-risk__overview button{white-space:nowrap}.cross-risk__links{padding:8px 10px;background:#112b3b;border-radius:5px;margin-bottom:10px;font-size:10px;line-height:1.7;color:#9fc7da}.cross-risk__links p{margin:0}.cross-risk__grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr));gap:9px}.risk-card{min-width:0;border:1px solid #223a4e;background:#0c1b2b;border-radius:7px;padding:11px}.risk-card header{display:flex;align-items:center;justify-content:space-between;gap:6px}.risk-card h3{font-size:12px;font-weight:600;color:#c7dfeb;margin:0}.risk-card h3 small{display:block;font-size:8px;font-weight:400;color:#6f91a8;margin-top:3px}.risk-state{font-size:10px;white-space:nowrap}.risk-tone-normal{color:#79bdcf}.risk-tone-watch{color:#dcc07c}.risk-tone-stress{color:#ec9692}.risk-tone-unknown{color:#8198aa}.risk-card--stress{border-color:#694147}.risk-card--watch{border-color:#635638}.risk-card__reason{font-size:10px;line-height:1.6;color:#89a8be;margin:7px 0;min-height:32px}.risk-metric{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:6px;align-items:center;border-top:1px solid #1e3445;padding:6px 0;font-size:10px}.risk-metric__label{color:#aac7d9;min-width:0}.risk-metric__label small{display:block;font-size:8px;color:#6f91a8;line-height:1.7;white-space:nowrap}.risk-metric strong{font-size:11px;color:#d6e6ef;font-weight:500;font-family:ui-monospace,monospace;white-space:nowrap}.risk-metric__change{font:9px ui-monospace,monospace;color:#86b7ca;white-space:nowrap;min-width:42px;text-align:right}.risk-metric--old strong,.risk-metric--old .risk-metric__change{color:#647d90}.risk-trend{margin-top:6px;color:#5eafc7}.risk-trend svg{width:100%;height:36px;display:block}.risk-trend span,.risk-card__coverage{font-size:8px;color:#7296ac}.cross-risk__method{border-top:1px solid #253d50;margin-top:11px;padding-top:9px;font-size:10px;color:#87a8bd}.cross-risk__method summary{display:flex;justify-content:space-between;gap:10px;cursor:pointer}.cross-risk__method time{font-size:9px;color:#66889f}.cross-risk__method p,.cross-risk__method li{font-size:10px;line-height:1.8;margin:7px 0}.cross-risk__method ul{padding-left:16px}.cross-risk__sources>div{display:flex;gap:8px;flex-wrap:wrap;justify-content:space-between;border-bottom:1px solid #21384a;padding:5px 0}.cross-risk__percentiles{display:flex;gap:5px 12px;flex-wrap:wrap;margin-top:8px;font-size:9px}.cross-risk__source-links{display:flex;flex-wrap:wrap;gap:12px}.cross-risk__source-links a{color:#8cbdce}.cross-risk__error{color:#e5bd84;font-size:11px;margin:0 0 10px}.cross-risk__loading{padding:22px 0;text-align:center;font-size:12px;color:#819eb1}@media(min-width:1500px){.cross-risk__grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:600px){.cross-risk{padding:0 10px 10px}.cross-risk__grid{grid-template-columns:1fr}.risk-card__reason{min-height:0}.risk-metric{font-size:11px}.risk-metric__label small{font-size:9px}.risk-metric strong{font-size:12px}}
</style>
