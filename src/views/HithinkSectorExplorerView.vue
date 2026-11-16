<template>
 <main class="ths-explorer market-dashboard fv-card sector-rotation">
  <header class="market-section-heading"><div><h1>同花顺板块全目录</h1><p>90个一级行业 · 全部合格概念 · 三项评分独立观察</p></div><a class="market-button" href="/">返回市场研究</a></header>
  <p v-if="!enabled" class="market-notice">同花顺板块预览尚未启用。首页继续使用现有板块数据。</p>
  <template v-else>
   <form class="ths-controls" @submit.prevent="searchCatalog"><label>板块分类<select v-model="universe"><option value="industry">行业</option><option value="concept">概念</option></select></label><label>名称或代码<input v-model="search" maxlength="100" placeholder="搜索完整目录" type="search"></label><label>观察视图<select v-model="view"><option value="all">全部板块</option><option v-for="v in VIEWS" :key="v.key" :value="v.key">{{ v.label }}</option></select></label><label v-if="universe==='concept'">概念分组<select v-model="role"><option value="all">全部概念</option><option value="core">核心25</option><option value="dynamic">动态10</option><option value="candidate">其他候选</option></select></label><button class="market-button" type="submit">搜索</button></form>
   <p v-if="error" class="market-notice" role="status">{{ error }}<button class="market-button" type="button" @click="load">重试</button></p>
   <div aria-live="polite"><p v-if="loading">正在读取完整目录…</p><p v-else-if="catalog" class="sector-rotation__meta">共 {{ catalog.total }} 项 · 第 {{ page }}/{{ pages }} 页 · 同花顺 Hithink · {{ catalog.marketDate }} · {{ catalog.session==='close'?'正式收盘':'盘中' }} · {{ freshness }}</p></div>
   <p v-if="catalog?.approximateHistory" class="market-notice">历史使用当前成分回填，存在幸存者偏差，非严格时点历史。评分仅供研究。</p>
   <div class="ths-results" :aria-busy="loading"><HithinkSectorRow v-for="row in catalog?.sectors ?? []" :key="row.id" :row="row" @select="select"/></div><p v-if="catalog && !catalog.sectors.length && !loading" class="market-empty">没有匹配的板块，请调整名称、代码或筛选条件。</p>
   <nav v-if="catalog" class="ths-pagination" aria-label="板块分页"><button class="market-button" type="button" :disabled="loading||page<=1" @click="go(page-1)">上一页</button><span>{{ page }} / {{ pages }}</span><button class="market-button" type="button" :disabled="loading||page>=pages" @click="go(page+1)">下一页</button><label>每页<select v-model.number="pageSize"><option :value="25">25</option><option :value="50">50</option><option :value="100">100</option></select></label></nav>
   <HithinkSectorHistory :universe="universe" :refresh-key="catalog?.batchId" @select="selection=$event"/>
   <p v-if="catalog" class="sector-rotation__meta">{{ catalog.schemaVersion }} · {{ catalog.sectorScoringVersion }} · {{ catalog.sectorUniverseVersion }} · {{ catalog.featureVersion }} · {{ catalog.membershipVersion }}</p>
   <HithinkSectorDetail :selection="selection" @close="selection=null"/>
  </template>
 </main>
</template>
<script setup lang="ts">
import {computed,onMounted,onUnmounted,ref,shallowRef,watch} from 'vue'
import {loadHithinkCatalog} from '@/features/sector-rotation-v4/api.mjs'
import {VIEWS} from '@/features/sector-rotation-v4/model.mjs'
import type {Catalog,Universe,SectorRow,View} from '@/features/sector-rotation-v4/types'
import HithinkSectorRow from '@/components/sector-rotation/HithinkSectorRow.vue'
import HithinkSectorHistory from '@/components/sector-rotation/HithinkSectorHistory.vue'
import HithinkSectorDetail from '@/components/sector-rotation/HithinkSectorDetail.vue'
const props=withDefaults(defineProps<{enabled?:boolean}>(),{enabled:import.meta.env.VITE_HITHINK_SECTOR_V4==='true' && import.meta.env.MODE!=='sector-acceptance'})
const universe=ref<Universe>('concept'),view=ref<View|'all'>('all'),role=ref('all'),search=ref(''),page=ref(1),pageSize=ref(50),loading=ref(false),error=ref('')
const catalog=shallowRef<Catalog|null>(null),selection=ref<{id:string;name:string;universe:Universe;marketDate?:string}|null>(null)
const pages=computed(()=>Math.max(1,Math.ceil((catalog.value?.total??0)/pageSize.value)))
const freshness=computed(()=>{const c=catalog.value;if(!c)return '';return Date.now()-Date.parse(c.observedAt)>(c.officialClose?72*3600000:30*60000)?'已过期 · 最后有效快照':'最近有效快照'})
let controller:AbortController|undefined
async function load(){if(!props.enabled)return;controller?.abort();const request=new AbortController();controller=request;loading.value=true;error.value='';catalog.value=null;const r=await loadHithinkCatalog({universe:universe.value,page:page.value,pageSize:pageSize.value,q:search.value.trim(),view:view.value,role:role.value,signal:request.signal});if(request.signal.aborted)return;loading.value=false;catalog.value=r.data;error.value=r.error?.message??''}
function searchCatalog(){page.value=1;return load()}
function go(p:number){page.value=p;load()}
function select(row:SectorRow){selection.value={id:row.id,name:row.name,universe:row.universe}}
watch(()=>[universe.value,view.value,role.value,pageSize.value],()=>{if(universe.value==='industry')role.value='all';selection.value=null;searchCatalog()})
onMounted(load);onUnmounted(()=>controller?.abort())
</script>
<style scoped>
.ths-explorer{max-width:1440px;margin:24px auto;padding:24px}.ths-explorer h1{font-size:20px;color:#dce9f0}.ths-explorer .market-section-heading p{margin-top:10px}.ths-controls{display:flex;flex-wrap:wrap;gap:12px;align-items:end;margin:16px 0}.ths-controls label,.ths-pagination label{display:flex;flex-direction:column;gap:6px;color:#a9bdcb;font-size:12px}.ths-controls input,.ths-controls select,.ths-pagination select{background:#0c2434;color:#dce9f0;border:1px solid #2b536c;min-height:44px;padding:8px;max-width:100%;font:inherit}.ths-controls button{min-height:44px}.ths-results{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.ths-pagination{display:flex;flex-wrap:wrap;align-items:center;gap:14px;margin:16px 0;color:#a9bdcb}.ths-pagination button{min-height:44px}@media(max-width:700px){.ths-explorer{padding:14px;margin:10px}.ths-results{grid-template-columns:1fr}.ths-controls{display:grid;grid-template-columns:1fr}.ths-controls input,.ths-controls select{width:100%}.market-section-heading{flex-wrap:wrap}}
</style>
