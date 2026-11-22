<template>
 <section id="market-research-radar" class="market-radar terminal-panel" aria-labelledby="market-radar-title" :aria-busy="loading">
  <header class="terminal-panel__header"><h2 id="market-radar-title">市场研究雷达</h2><span class="market-radar__date" v-if="data">日线 · {{data.commonDate??`A股 ${data.ashare.date??'—'} / 全球 ${data.global.date??'—'}`}}</span></header>
  <div v-if="data" class="market-radar__body">
   <p v-if="error||data.issues.length" class="market-radar__notice" role="status">{{error||issueText}} <button class="quiet-button" @click="refresh" :disabled="loading">重试</button></p>
   <div class="market-radar__primary"><RadarScoreCard :item="data.global" :show-date="!data.commonDate"/><RadarScoreCard :item="data.ashare" :show-date="!data.commonDate"/></div>
   <section class="market-radar__styles" aria-labelledby="radar-style-title"><h3 id="radar-style-title">风格对比</h3><div><RadarScoreCard v-for="item in data.styles" :key="item.id" :item="item" compact :show-date="!data.commonDate"/></div></section>
   <details class="market-radar__method"><summary>日线口径与计算方法</summary><p>A股及风格强度保留原趋势因子60%，加入真实上涨广度25%、主力净流入/成交额15%；风险保留原回撤、波动、下跌60%，加入下跌广度20%、净流出压力20%。缺少必要输入时该轴留空，不转移权重。热度继续看所选指数供应商口径的成交量分位与量比，不能代称净流入；资金占比用相同成份加总成交额，不与指数较广的成交额口径混用。全球口径保持独立。</p><p>资金、广度来自已校验的MX聚合或同花顺/中证成份加MX个股汇总。历史为同一公式逐期回算，不拼旧版快照。资金历史尚未补齐的风格只显示有依据的日期，不用价格分数冒充历史。1日/5日变化对应1/5个完整观测间隔，全球按共同观测日对齐。均线、分位仅用各历史时点以前的数据。日线排除未收盘柱，不能替代盘中行情。</p><p>价值风格采用沪深300价值（000919），替代旧中证800价值（H30356）；同版历史已重算，不跨指数拼分数。风格代理篮子不同，不能当作纯因子归因；红利为价格指数而非含股息全收益。</p><div class="market-radar__sources"><div v-for="source in data.sources" :key="source.id"><span>{{source.name}}</span><span>{{source.status==='ok'?'已取得':'未更新'}}</span><time>{{source.observedAt??'—'}}</time></div></div><p>主力资金是供应商按交易分类统计的资金流，不等同真实账户净申赎。个股资金源值可能已按万/亿舍入。规则、映射范围和权重可调整，尚未通过收益预测验证。原始因子与权重在各卡“依据”中查看。</p><button class="quiet-button" :disabled="loading" @click="refresh">{{loading?'获取中':'重新获取数据'}}</button></details>
  </div>
  <div v-else class="market-radar__empty" role="status">{{loading?'正在计算日线研究数据…':'研究数据暂未更新'}}<button v-if="!loading" class="quiet-button" @click="refresh">重试</button></div>
 </section>
</template>
<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,shallowRef} from 'vue'
import RadarScoreCard from './RadarScoreCard.vue'
import {RADAR_VERSION,type Radar,type RadarObject} from '@/features/market-radar/model.mjs'
const data=shallowRef<Radar|null>(null),loading=ref(false),error=ref('')
let controller:AbortController|undefined,timer:ReturnType<typeof setInterval>|undefined,alive=true
const issueText=computed(()=>{const d=data.value;if(!d)return '';if(d.sourceErrors)return `${d.sourceErrors}个数据通道未更新，相关指标暂不显示`;if(d.issues.length>2)return '部分研究指标暂未更新';return d.issues.map(x=>`${x.name}${x.status==='stale'?`数据停留在${x.date}`:x.status==='calendar'?'交易日历待更新':x.status==='insufficient'?'历史不足':'部分指标未更新'}`).join('；')})
function validObject(x:RadarObject){return x&&typeof x.id==='string'&&['strength','heat','risk'].every(k=>{const n=x[k as keyof RadarObject];return n===null||typeof n==='number'&&Number.isFinite(n)&&n>=0&&n<=100})&&Array.isArray(x.history)}
async function refresh(){
 if(loading.value)return;loading.value=true;controller=new AbortController()
 try{
  const response=await fetch('/api/market-radar',{signal:AbortSignal.any([controller.signal,AbortSignal.timeout(32000)]),cache:'no-store'});if(!response.ok)throw Error('UNAVAILABLE')
  const result=await response.json() as Radar
  if(result.version!==RADAR_VERSION||!validObject(result.global)||!validObject(result.ashare)||!Array.isArray(result.styles)||result.styles.length!==6||!result.styles.every(validObject)||!Array.isArray(result.issues))throw Error('INVALID_RADAR')
  if(alive){data.value=result;error.value=''}
 }catch{
  if(alive){error.value='本次研究数据未更新';if(data.value){const clear=(x:RadarObject):RadarObject=>({...x,status:'failed',strength:null,heat:null,risk:null,change1d:null,change5d:null,history:[]});data.value={...data.value,global:clear(data.value.global),ashare:clear(data.value.ashare),styles:data.value.styles.map(clear)}}}
 }finally{if(alive)loading.value=false}
}
function visible(){if(!document.hidden)void refresh()}
onMounted(()=>{void refresh();timer=setInterval(visible,300000);document.addEventListener('visibilitychange',visible)})
onUnmounted(()=>{alive=false;controller?.abort();clearInterval(timer);document.removeEventListener('visibilitychange',visible)})
</script>
<style scoped>
.market-radar__date{color:#7897ad;font-size:10px;text-align:right}.market-radar__body{padding:0 14px 12px}.market-radar__primary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.market-radar__styles{margin-top:13px}.market-radar__styles h3{font-size:12px;color:#bdd3e2;font-weight:500;margin:0 0 9px}.market-radar__styles>div{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:9px}.market-radar__method{border-top:1px solid #233c50;margin-top:10px;padding-top:8px;color:#85a5bb;font-size:10px}.market-radar__method summary{cursor:pointer}.market-radar__method p{font-size:10px;line-height:1.8;margin:8px 0}.market-radar__sources>div{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;padding:4px 0;border-bottom:1px solid #20374a;font-size:9px}.market-radar__notice{padding:6px 0 9px;color:#ddc293;font-size:10px;line-height:1.7}.market-radar__empty{padding:24px 14px;text-align:center;color:#7f9db1;font-size:12px}@media(max-width:1100px){.market-radar__styles>div{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.market-radar__primary{grid-template-columns:1fr}.market-radar__styles>div{grid-template-columns:repeat(2,minmax(0,1fr))}.market-radar__body{padding:0 10px 10px}.market-radar__date{font-size:9px;max-width:180px}}
</style>
