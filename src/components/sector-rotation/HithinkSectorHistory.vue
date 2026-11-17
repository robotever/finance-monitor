<template>
 <section class="sector-rotation__history-heading" :aria-busy="loading">
  <div class="market-section-heading"><h4>历史轮动 <span>最近日期在左 · 当日盘中＋历史收盘 · 前10名</span></h4><div class="sector-rotation__tabs" role="group" aria-label="历史评分维度"><button v-for="a in axes" :key="a.key" type="button" :aria-pressed="axis===a.key" @click="axis=a.key">{{ a.label }}</button></div></div>
  <p v-if="error" class="market-notice" role="status">{{ error }}</p>
  <p v-if="history?.approximateHistory" class="market-notice">当前成分回填历史 · 存在幸存者偏差</p>
  <div v-if="history" class="sector-rotation__matrix-scroll" tabindex="0" aria-label="横向滚动历史轮动矩阵"><table class="sector-rotation__matrix"><thead><tr><th scope="col">名次</th><th v-for="d in history.dates" :key="d" scope="col">{{ d }}{{ d===history.liveDate?' · 盘中':'' }}</th></tr></thead><tbody><tr v-for="rank in matrix" :key="rank.rank"><th scope="row">{{ rank.rank }}</th><td v-for="(cell,i) in rank.cells" :key="i"><button v-if="cell" type="button" :aria-label="`${cell.name} ${cell.marketDate} 第${rank.rank}名，打开详情`" @click="$emit('select',{id:cell.id,name:cell.name,universe,marketDate:cell.marketDate})"><span>{{ cell.name }}</span><strong>{{ cell.score ?? '—' }}分</strong></button><span v-else>—</span></td></tr></tbody></table></div>
  <p v-else class="market-empty">{{ loading ? '历史加载中…' : '暂无可比的正式收盘历史' }}</p>
  <p class="sector-rotation__meta">{{ history?.dates.length ?? 0 }}/15 个交易日 · 当日随有效采集更新，缺失不补值</p>
 </section>
</template>
<script setup lang="ts">
import {computed,onUnmounted,ref,shallowRef,watch} from 'vue'
import {loadHithinkHistory} from '@/features/sector-rotation-v4/api.mjs'
import {buildHistoryMatrix} from '@/features/sector-rotation-v4/model.mjs'
import type {Universe,Axis,History} from '@/features/sector-rotation-v4/types'
const props=defineProps<{universe:Universe;refreshKey?:string}>()
defineEmits<{select:[selection:{id:string;name:string;universe:Universe;marketDate:string}]}>()
const axes=[{key:'strength',label:'强度'},{key:'opportunity',label:'机会'},{key:'risk',label:'风险'}] as const
const axis=ref<Axis>('strength'),history=shallowRef<History|null>(null),loading=ref(false),error=ref('')
const matrix=computed(()=>history.value?buildHistoryMatrix(history.value):[])
let controller:AbortController|undefined
watch(()=>[props.universe,props.refreshKey,axis.value],async()=>{controller?.abort();const request=new AbortController();controller=request;loading.value=true;history.value=null;error.value='';const r=await loadHithinkHistory({universe:props.universe,axis:axis.value,signal:request.signal});if(request.signal.aborted)return;loading.value=false;history.value=r.data;error.value=r.error?.message??''},{immediate:true})
onUnmounted(()=>controller?.abort())
</script>
