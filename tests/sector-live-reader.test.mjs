import test from 'node:test'
import assert from 'node:assert/strict'
import {createLiveReader} from '../tools/market_dashboard/hithink_live_reader.mjs'
const a='a'.repeat(64),b='b'.repeat(64)
const response=(data,status=200)=>({ok:status===200,status,json:async()=>data})
test('refresh pins documents and retains previous generation on outage',async()=>{
 let generation=a,down=false;const calls=[]
 const reader=createLiveReader(async url=>{
  calls.push(url)
  if(down)throw Error('offline')
  if(url.endsWith('manifest'))return response({generation,mode:'live',automaticUpdates:true})
  return response({generation:new URL(url,'https://example.org').searchParams.get('generation')})
 })
 await reader.refresh(['latest','history?universe=concept&axis=return1d'])
 assert.equal((await reader('latest')).generation,a)
 const n=calls.length;await reader.refresh(['latest']);assert.equal(calls.length,n+1)
 generation=b;await reader.refresh(['latest']);assert.equal((await reader('latest')).generation,b)
 down=true;await assert.rejects(reader.refresh(['latest']));assert.equal((await reader('latest')).generation,b)
 assert.equal(reader.getStatus().refreshFailed,true)
})
test('404 uses static archive before activation only',async()=>{
 let live=false,missing=false
 const reader=createLiveReader(async url=>{
  if(url==='/api/sector-live/manifest')return live&&!missing?response({generation:a,mode:'live',automaticUpdates:true}):response({error:'NO_SNAPSHOT'},404)
  if(url.endsWith('manifest.json'))return response({generation:'archive'})
  return response({source:url.startsWith('/api/')?'live':'static'})
 })
 await reader.refresh();assert.equal((await reader('latest')).source,'static')
 live=true;await reader.refresh();missing=true;await assert.rejects(reader.refresh());assert.equal((await reader('latest')).source,'live')
})
test('malformed document never activates new generation',async()=>{
 const reader=createLiveReader(async url=>url.endsWith('manifest')?response({generation:a,mode:'live',automaticUpdates:true}):{ok:true,json:async()=>{throw SyntaxError('bad json')}})
 await assert.rejects(reader.refresh());assert.equal(reader.getStatus().mode,'loading')
})
test('partial generation failure cannot replace the complete active generation',async()=>{
 let generation=a,fail=false;const pins=[]
 const reader=createLiveReader(async url=>{
  if(url.endsWith('manifest'))return response({generation,mode:'live',automaticUpdates:true})
  const p=new URL(url,'https://example.org').searchParams;pins.push(p.get('generation'))
  if(fail&&p.get('key').startsWith('history-'))return response({},503)
  return response({generation:p.get('generation')})
 })
 await reader.refresh(['latest'])
 generation=b;fail=true
 await assert.rejects(reader.refresh(['latest','history?universe=concept&axis=return1d']))
 assert.equal((await reader('latest')).generation,a)
 assert.deepEqual(pins,[a,b,b])
})
test('hanging manifest times out and next refresh recovers',async()=>{
 let hang=true,aborted=false
 const reader=createLiveReader(async(url,options)=>{
  if(url.endsWith('manifest')&&hang){options.signal.addEventListener('abort',()=>aborted=true);return new Promise(()=>{})}
  return response(url.endsWith('manifest')?{generation:a,mode:'live',automaticUpdates:true}:{generation:a})
 },{timeoutMs:10})
 await assert.rejects(reader.refresh());assert.equal(aborted,true)
 hang=false;await reader.refresh();assert.equal((await reader('latest')).generation,a)
})
test('hanging document body times out without replacing active data',async()=>{
 let generation=a,hang=false
 const reader=createLiveReader(async url=>{
  if(url.endsWith('manifest'))return response({generation,mode:'live',automaticUpdates:true})
  return hang?{ok:true,status:200,json:()=>new Promise(()=>{})}:response({generation})
 },{timeoutMs:10})
 await reader.refresh();generation=b;hang=true;await assert.rejects(reader.refresh())
 assert.equal((await reader('latest')).generation,a)
 hang=false;await reader.refresh();assert.equal((await reader('latest')).generation,b)
})
test('cache retains only two committed generations',async()=>{
 let generation=a,documents=0
 const reader=createLiveReader(async url=>{
  if(url.endsWith('manifest'))return response({generation,mode:'live',automaticUpdates:true})
  documents++;return response({generation})
 })
 await reader.refresh();generation=b;await reader.refresh();generation='c'.repeat(64);await reader.refresh()
 generation=b;await reader.refresh();assert.equal(documents,3)
 generation=a;await reader.refresh();assert.equal(documents,4)
})
test('large detail has its own finite timeout without slowing ordinary manifest recovery',async()=>{
 const reader=createLiveReader(async url=>{
  if(url.endsWith('manifest'))return response({generation:a,mode:'live',automaticUpdates:true})
  if(url.includes('detail-'))return {ok:true,status:200,json:()=>new Promise(resolve=>setTimeout(()=>resolve({history:[]}),15))}
  return response({generation:a})
 },{timeoutMs:5,detailTimeoutMs:40})
 await reader.refresh();assert.deepEqual(await reader('detail?universe=concept&id=885001.TI'),{history:[]})
})
test('expanded constituents pin the active generation and selected market date',async()=>{
 const urls=[],reader=createLiveReader(async url=>{urls.push(String(url));return response(url.endsWith('manifest')?{generation:a,mode:'live',automaticUpdates:true}:url.includes('view=members')?{rows:[{code:'000001.SZ'}]}:{generation:a})})
 await reader.refresh();const result=await reader.constituents('885001.TI','2026-11-16')
 assert.equal(result.generation,a);assert.equal(result.data.rows.length,1)
 const p=new URL(urls.at(-1),'https://test.invalid').searchParams;assert.equal(p.get('date'),'2026-11-16');assert.equal(p.get('generation'),a);assert.equal(p.get('view'),'members')
 await assert.rejects(()=>reader.constituents('885001.TI','bad-date'),/LIVE_UNAVAILABLE/)
})
