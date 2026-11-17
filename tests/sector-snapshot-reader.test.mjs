import test from 'node:test'
import assert from 'node:assert/strict'
import {createSnapshotReader} from '../tools/market_dashboard/hithink_snapshot_reader.mjs'
test('snapshot catalog filters locally, paginates, and keeps the generation pinned',async()=>{
 const urls=[]
 const reader=createSnapshotReader(async url=>{urls.push(url);return {ok:true,json:async()=>url.endsWith('manifest.json')?{generation:'safe-123'}:{sectors:[{id:'885001.TI',name:'芯片'},{id:'885002.TI',name:'其他芯片'},{id:'885003.TI',name:'医药'}]}}})
 const result=await reader('catalog?universe=concept&q=芯片&page=2&pageSize=1')
 assert.equal(result.total,2);assert.equal(result.sectors[0].id,'885002.TI')
 await reader('detail?universe=concept&id=885001.TI')
 assert.deepEqual(urls,['/data/sector-research/manifest.json','/data/sector-research/safe-123/catalog-concept.json','/data/sector-research/safe-123/detail-885001.TI.json'])
 await assert.rejects(()=>reader('detail?universe=concept&id=../../secret'),/INVALID_QUERY/)
})
test('missing snapshot fails visibly instead of falling back to demo or local data',async()=>{
 const reader=createSnapshotReader(async()=>({ok:false}))
 await assert.rejects(()=>reader('latest'),/SNAPSHOT_UNAVAILABLE/)
})
