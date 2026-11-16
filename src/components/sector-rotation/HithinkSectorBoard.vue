<template>
 <section v-if="model" class="sector-rotation ths-board" aria-labelledby="ths-board-title">
  <div class="market-section-heading"><div><h3 id="ths-board-title">板块轮动 <span>行业90 / 全概念</span></h3><p>{{ model.sourceLabel }} · {{ model.marketDate }} {{ model.session==='close'?'收盘':'盘中' }}</p></div><a class="market-button" href="/sectors/hithink">全部行业与概念 →</a></div>
  <p class="sector-rotation__meta" :class="{'market-notice':model.stale}">{{ model.freshnessLabel }} · {{ timeLabel(model.observedAt) }} 北京时间</p><p class="market-notice">{{ model.warning }} 评分仅供研究，高强度不等于低风险。</p><p v-if="error" class="market-notice" role="status">{{ error }}</p>
  <h4 class="ths-heading">行业 · 90个一级行业 · 每榜最多10项</h4>
  <div class="ths-lists"><section v-for="view in VIEWS" :key="view.key"><h4>{{ view.label }} <span>{{ model.industry[view.key].length }}/10</span></h4><p class="sector-rotation__meta">{{ basis[view.key] }}</p><HithinkSectorRow v-for="row in model.industry[view.key]" :key="row.id" :row="row" :data-industry-row="row.id" @select="select"/><p v-if="!model.industry[view.key].length" class="market-empty">暂无符合条件的行业</p></section></div>
  <div class="market-section-heading ths-heading"><h4>概念观察</h4><div class="sector-rotation__tabs" role="group" aria-label="概念选择"><button type="button" :aria-pressed="conceptTab==='core'" @click="conceptTab='core'">核心25 · {{ model.concept.core.length }}/25</button><button type="button" :aria-pressed="conceptTab==='dynamic'" @click="conceptTab='dynamic'">动态10 · {{ model.concept.dynamic.length }}/10</button></div></div>
  <p class="sector-rotation__meta">固定核心与动态候选单独观察 · 完整概念目录见全部行业与概念</p><div class="ths-concepts"><HithinkSectorRow v-for="row in model.concept[conceptTab]" :key="row.id" :row="row" @select="select"/></div><p v-if="!model.concept[conceptTab].length" class="market-empty">暂无有效概念数据，缺失不补值</p>
  <div class="sector-rotation__tabs" role="group" aria-label="历史板块分类"><button v-for="u in universes" :key="u.key" type="button" :aria-pressed="historyUniverse===u.key" @click="historyUniverse=u.key">{{ u.label }}历史</button></div>
  <HithinkSectorHistory :universe="historyUniverse" :refresh-key="model.batchId" @select="selection=$event"/><p class="sector-rotation__meta">{{ model.schemaVersion }} · {{ model.sectorScoringVersion }} · {{ model.sectorUniverseVersion }} · {{ model.featureVersion }} · {{ model.membershipVersion }}</p>
  <HithinkSectorDetail :selection="selection" @close="selection=null"/>
 </section>
</template>
<script setup lang="ts">
import {computed,ref} from 'vue'
import {deriveBoard,VIEWS} from '@/features/sector-rotation-v4/model.mjs'
import type {Latest,SectorRow,Universe,View} from '@/features/sector-rotation-v4/types'
import HithinkSectorRow from './HithinkSectorRow.vue'
import HithinkSectorHistory from './HithinkSectorHistory.vue'
import HithinkSectorDetail from './HithinkSectorDetail.vue'
const props=defineProps<{latest:Latest;now?:Date;error?:string}>()
const model=computed(()=>{try{return deriveBoard(props.latest,props.now)}catch{return null}})
const conceptTab=ref<'core'|'dynamic'>('core'),historyUniverse=ref<Universe>('industry')
const selection=ref<{id:string;name:string;universe:Universe;marketDate?:string}|null>(null)
const universes=[{key:'industry',label:'行业'},{key:'concept',label:'概念'}] as const
const basis:Record<View,string>={potential:'机会≥70 · 强度<70 · 风险<70 · 非拥挤 · 完整度≥70%',main:'强度≥70 · 风险<70 · 完整度≥70%',risk:'风险≥70，或较前收盘升≥10分，或拥挤'}
function select(row:SectorRow){selection.value={id:row.id,name:row.name,universe:row.universe}}
const timeLabel=(value:string)=>new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})
</script>
<style scoped>
.ths-lists{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.ths-lists>section{min-width:0}.ths-lists h4,.ths-heading{color:#d2e7ef;font-size:14px;margin:16px 0 10px}.ths-lists h4 span{font-size:11px;color:#92a9b8}.ths-lists article{margin:8px 0}.ths-concepts{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.ths-board a{white-space:normal;min-height:44px;display:flex;align-items:center}.ths-board .market-notice{margin:10px 0}@media(max-width:700px){.ths-lists,.ths-concepts{grid-template-columns:1fr}.market-section-heading{flex-wrap:wrap}}
</style>
