<template>
 <div v-if="selection" class="sector-rotation-detail" @click.self="$emit('close')" @keydown.esc="$emit('close')">
  <section ref="panel" class="sector-rotation-detail__panel" role="dialog" aria-modal="true" aria-labelledby="ths-detail-title" tabindex="-1" @keydown.tab="trapFocus">
   <header class="market-section-heading"><h3 id="ths-detail-title">{{ selection.name }} · 同花顺板块详情</h3><button class="market-button" type="button" @click="$emit('close')">关闭</button></header>
   <p v-if="loading" role="status">详情加载中…</p><p v-if="error" class="market-notice" role="status">{{ error }}</p>
   <template v-if="detail"><p class="sector-rotation__meta">Hithink · {{ detail.sectorScoringVersion }} · {{ detail.sectorUniverseVersion }}</p><p v-if="detail.approximateHistory" class="market-notice">当前成分回填，存在幸存者偏差。历史评分尚未完成验证。</p>
    <p v-if="selection.marketDate" class="market-notice">选中历史日期 {{ selection.marketDate }}；下方同时列示近60日快照，盘中与正式收盘单独标记。</p>
    <article v-for="point in observations" :key="point.observedAt" :class="{'ths-selected':point.marketDate===selection.marketDate}"><h4>{{ point.marketDate }} {{ point.observedAt.slice(11,16) }} UTC · {{ point.officialClose?'正式收盘':'盘中' }}</h4><HithinkSectorRow :row="point" />
      <details v-if="point.components"><summary>评分依据与覆盖率</summary><ul><li v-for="(component,name) in point.components" :key="name">{{ componentLabel(String(name)) }}：{{ component.value ?? '—' }} · 覆盖 {{ Math.round(component.coverage*100) }}%<span v-if="component.missing.length"> · 缺失 {{ component.missing.join('、') }}</span></li></ul></details>
    </article>
   </template>
  </section>
 </div>
</template>
<script setup lang="ts">
import {computed,nextTick,onUnmounted,ref,shallowRef,watch} from 'vue'
import {loadHithinkDetail} from '@/features/sector-rotation-v4/api.mjs'
import type {Detail,Universe} from '@/features/sector-rotation-v4/types'
import HithinkSectorRow from './HithinkSectorRow.vue'
const props=defineProps<{selection:{id:string;name:string;universe:Universe;marketDate?:string}|null}>()
defineEmits<{close:[]}>()
const detail=shallowRef<Detail|null>(null),error=ref(''),loading=ref(false),panel=ref<HTMLElement|null>(null)
const observations=computed(()=>detail.value?[...detail.value.history].reverse():[])
let controller:AbortController|undefined,previousFocus:HTMLElement|null=null
watch(()=>props.selection,async(selection)=>{controller?.abort();detail.value=null;error.value='';if(!selection){previousFocus?.focus();return}previousFocus=document.activeElement as HTMLElement;await nextTick();panel.value?.focus();const request=new AbortController();controller=request;loading.value=true;const result=await loadHithinkDetail({...selection,signal:request.signal});if(request.signal.aborted)return;loading.value=false;detail.value=result.data;error.value=result.error?.message??''})
function trapFocus(e:KeyboardEvent){const items=panel.value?.querySelectorAll<HTMLElement>('button,summary,a[href],[tabindex="0"]');if(!items?.length)return;const first=items[0]!,last=items[items.length-1]!;if(e.shiftKey&&(document.activeElement===first||document.activeElement===panel.value)){e.preventDefault();last.focus()}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}}
const labels:Record<string,string>={strength:'强度',opportunity:'机会',risk:'风险',priceTrend:'价格趋势',participation:'参与度',activity:'活跃度',persistence:'持续性',position:'位置',breadth:'广度',downsideDiffusion:'下跌扩散',crowding:'拥挤度',trendDeterioration:'趋势恶化',momentumImprovement:'动量改善',breadthImprovement:'广度改善'}
const componentLabel=(name:string)=>labels[name]??name
onUnmounted(()=>{controller?.abort();previousFocus?.focus()})
</script>
<style scoped>
.sector-rotation-detail{position:fixed;inset:0;z-index:100;background:#020a13c9;display:flex;justify-content:flex-end}.sector-rotation-detail__panel{width:min(720px,100%);max-height:100%;overflow:auto;background:#0b1925;color:#d5e4ef;padding:20px}.sector-rotation-detail__panel article{padding:12px 0;border-bottom:1px solid #304657}.sector-rotation-detail__panel h4{font-size:13px}.sector-rotation-detail__panel details{padding:10px;color:#a9bdcb;font-size:12px}.ths-selected{outline:2px solid #63b9c5;outline-offset:-2px}
</style>
