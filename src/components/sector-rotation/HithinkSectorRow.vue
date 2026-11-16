<template>
  <article class="sector-rotation__row ths-row">
    <header><button type="button" class="sector-rotation__name" @click="$emit('select', row)">{{ row.name }}</button><span class="market-badge">{{ heatLabels[row.heatState ?? ''] ?? '状态缺失' }}</span></header>
    <p class="sector-rotation__meta">{{ row.id }} · 当日涨跌 {{ row.metrics?.return1d == null ? '—' : `${row.metrics.return1d}%` }}</p>
    <div class="sector-rotation__scores"><div v-for="axis in axes" :key="axis.key"><span>{{ axis.label }}</span><strong>{{ row[axis.key] ?? '—' }}</strong></div></div>
    <p class="sector-rotation__meta">完整度 {{ row.completeness }}% · {{ row.coldStart ? '冷启动' : `${row.validCloses}个有效收盘日` }}</p>
    <p class="sector-rotation__meta">较前收盘：<span v-for="axis in axes" :key="axis.key">{{ axis.label }} {{ change(row.change1d[axis.key]) }} </span></p>
    <p v-if="row.missing.length" class="market-notice">缺失：{{ row.missing.join('、') }}</p>
  </article>
</template>
<script setup lang="ts">
import type {SectorRow} from '@/features/sector-rotation-v4/types'
defineProps<{row:SectorRow}>()
defineEmits<{select:[row:SectorRow]}>()
const axes=[{key:'strength',label:'强度'},{key:'opportunity',label:'机会'},{key:'risk',label:'风险'}] as const
const heatLabels:Record<string,string>={cold:'冷',neutral:'中性',warming:'升温',active:'活跃',crowded:'拥挤'}
const change=(v:number|null)=>v===null?'—':v>0?`+${v}`:String(v)
</script>
<style scoped>
.ths-row{padding:10px}.ths-row .sector-rotation__scores{gap:4px;margin:8px 0}.ths-row .sector-rotation__scores div{padding:6px;flex-wrap:wrap}.ths-row .sector-rotation__scores strong{font-size:17px}
</style>
