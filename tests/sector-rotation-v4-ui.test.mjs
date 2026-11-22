import test, { before, after } from 'node:test'
import assert from 'node:assert/strict'
import { createServer } from 'vite'
import { createSSRApp, h } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { validateLatest, selectSectorAdapter, deriveBoard, buildHistoryMatrix, catalogQuery, formatHistoryValue } from '../src/features/sector-rotation-v4/model.mjs'
import { loadHithinkLatest, loadHithinkCatalog } from '../src/features/sector-rotation-v4/api.mjs'
const versions = {schemaVersion:'market-dashboard-v4',sectorScoringVersion:'sector-score-v0.4',sectorUniverseVersion:'sector-universe-ths-v1',featureVersion:'sector-features-ths-v1',membershipVersion:'sector-membership-ths-v1'}
const row = (n, universe='industry') => ({ id:`${universe==='industry'?'881':'885'}${String(n).padStart(3,'0')}.TI`,name:`测试板块${n}`,universe,strength:80,opportunity:70,risk:20,completeness:80,ranks:{strength:n+1,opportunity:n+1,risk:n+1},heatState:'active',coldStart:false,validCloses:60,improvementEvidence:2,membershipMode:'current_members_backfill',conceptRole:universe==='concept'?'core':null,missing:[],approximateHistory:true,change1d:{strength:null,opportunity:null,risk:null} })
export const payload = () => ({...versions,batchId:'test',sourceMode:'hithink',observedAt:'2026-11-13T07:00:00.000Z',marketDate:'2026-11-13',session:'close',officialClose:true,membershipModes:['current_members_backfill'],approximateHistory:true,industry:Object.fromEntries(['potential','main','risk'].map(k=>[k,Array.from({length:10},(_,i)=>row(i))])),concept:{...Object.fromEntries(['potential','main','risk'].map(k=>[k,Array.from({length:10},(_,i)=>row(i,'concept'))])),core:Array.from({length:25},(_,i)=>row(i,'concept')),dynamic:Array.from({length:10},(_,i)=>({...row(i+25,'concept'),conceptRole:'dynamic'}))}})
test('isolated v4 contract rejects wrong source, versions, excess lists, duplicated identities and missing scores',()=>{
 const p=payload();assert.equal(validateLatest(p),p)
 for(const mutate of [p=>p.sourceMode='wind',p=>p.featureVersion='v3',p=>p.industry.main.push(row(11)),p=>p.concept.core.push(row(26,'concept')),p=>p.industry.main[1]=p.industry.main[0],p=>delete p.industry.main[0].risk]){const p=payload();mutate(p);assert.throws(()=>validateLatest(p),/INVALID_SCHEMA/)}
})
test('fallback is complete and never switches adapters without a valid snapshot',()=>{
 assert.equal(selectSectorAdapter(false,payload()),'v3');assert.equal(selectSectorAdapter(true,null),'v3');assert.equal(selectSectorAdapter(true,payload()),'v4')
 const p=payload();p.sectorScoringVersion='sector-score-v0.2';assert.equal(selectSectorAdapter(true,p),'v3')
})
test('model discloses approximation, stale observations and null scores without inventing zeroes',()=>{
 const p=payload();p.industry.main[0].strength=null;p.industry.main[0].missing=['breadth'];const m=deriveBoard(p,new Date('2026-11-16T09:00:00Z'));assert.equal(m.stale,true);assert.match(m.sourceLabel,/同花顺/);assert.match(m.warning,/当前成分/);assert.equal(m.industry.main[0].strength,null)
})
test('history matrix retains missing cells and exact rank rather than re-ranking',()=>{
 const m=buildHistoryMatrix({dates:['2026-11-12','2026-11-13'],rows:[{id:'881001.TI',name:'行业',values:[{marketDate:'2026-11-12',score:80,rank:2},{marketDate:'2026-11-13',score:null,rank:null}]}]});assert.equal(m[1].cells[0].score,80);assert.equal(m[0].cells[0],null);assert.equal(m[1].cells[1],null)
})
test('catalog query resets bounded pagination and preserves literal search',()=>{
 assert.equal(catalogQuery({universe:'concept',page:4,pageSize:100,q:'885389.TI'}).toString(),'universe=concept&page=4&pageSize=100&q=885389.TI');assert.throws(()=>catalogQuery({universe:'industry',page:0}),/INVALID_QUERY/)
})
test('API distinguishes NO_SNAPSHOT and rejects v3 data without fallback in the v4 adapter',async()=>{
 assert.equal((await loadHithinkLatest({fetcher:async()=>new Response(JSON.stringify({error:'NO_SNAPSHOT'}),{status:404})})).error.code,'NO_SNAPSHOT')
 assert.equal((await loadHithinkLatest({fetcher:async()=>Response.json({...payload(),sourceMode:'wind'})})).error.code,'INVALID_SCHEMA')
 let url;await loadHithinkCatalog({universe:'concept',page:4,pageSize:100,q:'885389.TI',fetcher:async u=>{url=u;return new Response('{}',{status:503})}});assert.match(url,/page=4&pageSize=100&q=885389.TI/)
})
let server
before(async()=>{server=await createServer({server:{middlewareMode:true,hmr:false,ws:false,watch:null},appType:'custom'})});after(async()=>server?.close())
test('history defaults to daily return and formats percentages separately from scores',async()=>{
 assert.equal(formatHistoryValue(2.55,'return1d'),'+2.55%');assert.equal(formatHistoryValue(-.5,'return1d'),'-0.50%');assert.equal(formatHistoryValue(null,'return1d'),'—');assert.equal(formatHistoryValue(56,'strength'),'56分')
 const {default:History}=await server.ssrLoadModule('/src/components/sector-rotation/HithinkSectorHistory.vue')
 const {createRenderer,ssrContextKey}=await import('vue');const previous=globalThis.fetch,requests=[];let state
 globalThis.fetch=async url=>{requests.push(String(url));return Response.json({},{status:503})}
 const renderer=createRenderer({createComment:()=>({}),insert(){},remove(){},parentNode(){},nextSibling(){}})
 const app=renderer.createApp({setup(){state=History.setup({universe:'concept'},{expose(){},emit(){}});return()=>null}});app.provide(ssrContextKey,{})
 try{app.mount({});assert.equal(state.axis.value,'return1d');assert.ok(requests[0].includes('axis=return1d'))}finally{app.unmount();globalThis.fetch=previous}
})
test('board renders all three industry lists, exact core/dynamic choices and provenance',async()=>{
 const {default:Board}=await server.ssrLoadModule('/src/components/sector-rotation/HithinkSectorBoard.vue');const html=await renderToString(createSSRApp({render:()=>h(Board,{latest:payload(),now:new Date('2026-11-16T09:00:00Z')})}));for(const text of ['行业90','潜在轮动','主线确认','风险升温','核心25','动态10','同花顺','sector-score-v0.4','当前成分','已过期','全部行业与概念'])assert.ok(html.includes(text),text);assert.equal((html.match(/data-industry-row=/g)||[]).length,30)
})
test('explorer resets page on search/filter and fetches literal full-universe page without fixture fallback',async()=>{
 const {default:Explorer}=await server.ssrLoadModule('/src/views/HithinkSectorExplorerView.vue')
 const {createRenderer,ssrContextKey,nextTick}=await import('vue');let state;const requests=[];const previous=globalThis.fetch
 globalThis.fetch=async url=>{requests.push(String(url));const q=new URL(String(url),'https://example.test').searchParams;return Response.json({...payload(),universe:q.get('universe'),page:Number(q.get('page')),pageSize:Number(q.get('pageSize')),q:q.get('q')??'',view:q.get('view')??'all',role:q.get('role')??'all',total:390,sectors:[]})}
 const renderer=createRenderer({createComment:()=>({}),insert(){},remove(){},parentNode(){},nextSibling(){}})
 const app=renderer.createApp({setup(){state=Explorer.setup({enabled:true},{expose(){},emit(){}});return()=>null}});app.provide(ssrContextKey,{})
 try{app.mount({});await state.load();state.page.value=4;await state.load();assert.ok(requests.some(u=>u.includes('page=4')));state.search.value='885389.TI';await state.searchCatalog();assert.equal(state.page.value,1);assert.ok(requests.at(-1).includes('q=885389.TI'));state.universe.value='industry';await nextTick();assert.equal(state.page.value,1)}finally{app.unmount();globalThis.fetch=previous}
})
test('dashboard uses complete v3 fallback with flag off and NO_SNAPSHOT, switches only the sector board when enabled',async()=>{
 const {createRenderer,ssrContextKey}=await import('vue');const {acceptanceFetch}=await import('../src/features/market-dashboard/acceptance.mjs');const previous=globalThis.fetch,env=process.env.VITE_HITHINK_SECTOR_V4
 for(const scenario of ['off','empty','ready']) {
 process.env.VITE_HITHINK_SECTOR_V4=scenario==='off'?'false':'true';const instance=await createServer({mode:'production-rotation',server:{middlewareMode:true,hmr:false,ws:false,watch:null},appType:'custom'});let app
 try{let calls=0;globalThis.fetch=async(input,init)=>{if(String(input).includes('/v4/')){calls++;return scenario==='ready'?Response.json(payload()):Response.json({error:'NO_SNAPSHOT'},{status:404})}return acceptanceFetch(input,init)}
 const {default:Dashboard}=await instance.ssrLoadModule('/src/components/MarketResearchDashboard.vue');let state;const renderer=createRenderer({createComment:()=>({}),insert(){},remove(){},parentNode(){},nextSibling(){}});app=renderer.createApp({setup(){state=Dashboard.setup({},{expose(){},emit(){}});return()=>null}});app.provide(ssrContextKey,{});app.mount({});for(let i=0;i<100&&state.loading.value;i++)await new Promise(r=>setTimeout(r,10));assert.equal(state.loading.value,false);assert.equal(state.v3Active.value,true);assert.equal(state.v4Active.value,scenario==='ready');assert.ok(state.dashboard.value.global);assert.equal(state.v3Latest.value.schemaVersion,'market-dashboard-v3');if(scenario==='off')assert.equal(calls,0)
 }finally{app?.unmount();await instance.close()}}
 globalThis.fetch=previous;if(env===undefined)delete process.env.VITE_HITHINK_SECTOR_V4;else process.env.VITE_HITHINK_SECTOR_V4=env
})
test('real provider precision and missing-code families are readable in sector cards',async()=>{
 const {default:Row}=await server.ssrLoadModule('/src/components/sector-rotation/HithinkSectorRow.vue');const r={...row(1),metrics:{return1d:1.9653787017455127},missing:['participation.turnoverMarketShare.missingInput','trendDeterioration.slope5d.missingInput']};const html=await renderToString(createSSRApp({render:()=>h(Row,{row:r})}));assert.match(html,/1.97%/);assert.match(html,/缺失2项/);assert.match(html,/全市场成交额占比/);assert.match(html,/短期趋势斜率/);assert.ok(!html.includes('1.9653787017455127'))
})
test('homepage radar can omit duplicate sector views and sector-only requests',async()=>{
 const {createRenderer,ssrContextKey}=await import('vue');const {acceptanceFetch}=await import('../src/features/market-dashboard/acceptance.mjs')
 const instance=await createServer({mode:'production-rotation',server:{middlewareMode:true,hmr:false,ws:false,watch:null},appType:'custom'})
 const previous=globalThis.fetch,calls=[];let app
 try{
  globalThis.fetch=async(input,init)=>{calls.push(String(input));return acceptanceFetch(input,init)}
  const {default:Dashboard}=await instance.ssrLoadModule('/src/components/MarketResearchDashboard.vue');let state
  const renderer=createRenderer({createComment:()=>({}),insert(){},remove(){},parentNode(){},nextSibling(){}})
  app=renderer.createApp({setup(){state=Dashboard.setup({showSectors:false},{expose(){},emit(){}});return()=>null}});app.provide(ssrContextKey,{});app.mount({})
  for(let i=0;i<100&&state.loading.value;i++)await new Promise(r=>setTimeout(r,10))
  assert.ok(state.dashboard.value.global);assert.ok(state.dashboard.value.aShare)
  assert.equal(calls.filter(url=>url.includes('/sector-rotation/')).length,0)
  assert.equal(state.rotationLatest.value,null)
 }finally{app?.unmount();await instance.close();globalThis.fetch=previous}
})
