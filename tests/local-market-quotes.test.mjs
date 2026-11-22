import test from 'node:test'
import assert from 'node:assert/strict'
import {mkdtemp,rm} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
import {createLocalMarketQuotes} from '../tools/market_dashboard/local_market_quotes.mjs'
const now=Date.parse('2026-11-22T12:00:00Z')
const hf=(symbol)=>`var hq_str_hf_${symbol}="3534.64,3625.010,3534.64,3534.99,3636.63,3502.73,05:55:00,3625.01,3628.88,0,0,0,2026-11-21,${symbol==='XAU'?'伦敦金（现货黄金）':'纽约原油'}";`
const history='var _data=('+JSON.stringify([{date:'2026-11-19',close:'3625.01'},{date:'2026-11-20',close:'3534.64'}])+');'
async function root(t){const path=await mkdtemp(join(tmpdir(),'quotes-'));t.after(()=>rm(path,{recursive:true,force:true}));return path}
test('gold uses USD spot history and retains source timestamp when offline',async t=>{
 const stateRoot=await root(t)
 const quote=createLocalMarketQuotes({stateRoot,now:()=>now,fetcher:async url=>new Response(url.includes('hq.sinajs')?hf('XAU'):history)})
 const value=await quote('gold')
 assert.equal(value.price,3534.64);assert.equal(value.previousClose,3625.01)
 assert.equal(value.observedAt,'2026-11-21T05:55:00+08:00');assert.equal(value.session,'daily')
 assert.match(value.description,/美元\/盎司/);assert.match(value.description,/现货/)
 const offline=createLocalMarketQuotes({stateRoot,now:()=>now+86400000,offline:true,fetcher:()=>{throw Error('must not fetch')}})
 const old=await offline('gold');assert.equal(old.status,'cached');assert.equal(old.observedAt,value.observedAt);assert.equal(old.fetchedAt,value.fetchedAt);assert.match(old.provider,/最近数据/)
})
test('oil identifies Sina CFD futures reference and rejects a mismatched instrument',async t=>{
 const stateRoot=await root(t)
 const quote=createLocalMarketQuotes({stateRoot,now,fetcher:async url=>new Response(url.includes('hq.sinajs')?hf('CL'):history)})
 assert.match((await quote('oil')).description,/CFD（期货参考报价）/)
 const wrong=createLocalMarketQuotes({stateRoot:join(stateRoot,'wrong'),now,fetcher:async url=>new Response(url.includes('hq.sinajs')?hf('XAU').replace('hf_XAU','hf_CL'):history)})
 await assert.rejects(wrong('oil'),/QUOTE/)
})
test('CNH uses quoted change amount for previous close and preserves six decimal prices',async t=>{
 const quote=createLocalMarketQuotes({stateRoot:await root(t),now,fetcher:async url=>new Response(url.includes('hq.sinajs')?'var hq_str_fx_susdcnh="05:59:59,6.673700,6.675700,6.673700,258,6.693000,6.694200,6.668400,6.673700,离岸人民币（香港）,-0.290000,-0.019700,0.003855,,6.995700,6.642700,,2026-11-21";':'var _data=("2026-11-19,6.6691,6.6639,6.6999,6.6934,|2026-11-20,6.693,6.6684,6.6942,6.6737");')})
 const value=await quote('cnh');assert.equal(value.price,6.6737);assert.equal(value.previousClose,6.6934);assert.equal(value.changePercent,-0.29);assert.match(value.description,/人民币\/美元/)
})
test('missing cached series, invalid identifiers, malformed and future quotes fail explicitly',async t=>{
 const stateRoot=await root(t)
 await assert.rejects(createLocalMarketQuotes({stateRoot,offline:true})('gold'),/QUOTE_UNAVAILABLE/)
 await assert.rejects(createLocalMarketQuotes({stateRoot})('../gold'),/INVALID_INSTRUMENT/)
 for(const text of ['bad',hf('XAU').replace('2026-11-21','2099-11-21')]){
  await assert.rejects(createLocalMarketQuotes({stateRoot,now,fetcher:async url=>new Response(url.includes('hq.sinajs')?text:history)})('gold'),/QUOTE/)
 }
})
test('upstream failure returns last successful series without stamping it as fresh',async t=>{
 const stateRoot=await root(t)
 const value=await createLocalMarketQuotes({stateRoot,now,fetcher:async url=>new Response(url.includes('hq.sinajs')?hf('XAU'):history)})('gold')
 const cached=await createLocalMarketQuotes({stateRoot,now:now+3600000,fetcher:async()=>{throw Error('network')}})('gold')
 assert.equal(cached.status,'cached');assert.equal(cached.observedAt,value.observedAt)
})
test('CNH missing quote change fields cannot fabricate an unchanged previous close',async t=>{
 const quote=createLocalMarketQuotes({stateRoot:await root(t),now,fetcher:async url=>new Response(url.includes('hq.sinajs')?'var hq_str_fx_susdcnh="05:59:59,6.673700,6.675700,6.673700,258,6.693000,6.694200,6.668400,6.673700,离岸人民币（香港）,,,0.003855,,6.995700,6.642700,,2026-11-21";':'var _data=("2026-11-19,6.6691,6.6639,6.6999,6.6934,|2026-11-20,6.693,6.6684,6.6942,6.6737");')})
 await assert.rejects(quote('cnh'),/QUOTE_UNAVAILABLE/)
})
