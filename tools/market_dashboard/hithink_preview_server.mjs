// Loopback-only read-only inspector. No D1 staging or public publishing.
import {readFileSync} from 'node:fs'
import {fileURLToPath} from 'node:url'
import {resolve,join,dirname} from 'node:path'
import {createServer} from 'vite'
import {localSnapshot,localHistory,localCatalog,localDetail} from './hithink_preview_data.mjs'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..')
const entry=join(root,'tools/market_dashboard/hithink_preview_entry.js')
const server=await createServer({root,server:{host:'127.0.0.1',port:5184,strictPort:true},plugins:[{
 name:'private-current-hithink-inspector',
 resolveId(id){if(id==='virtual:hithink-preview')return '\0'+id},
 load(id){if(id==='\0virtual:hithink-preview')return readFileSync(entry,'utf8')},
 configureServer(s){s.middlewares.use(async(req,res,next)=>{
  try{
   if(req.url==='/__hithink-preview'){
    res.setHeader('cache-control','no-store');res.setHeader('content-type','text/html')
    res.end(await s.transformIndexHtml(req.url,'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>同花顺本地实时看板</title><div id="app"></div><script type="module" src="/@id/virtual:hithink-preview"></script></html>'));return
   }
   const match=/^\/__local-reconstruction\/(latest|catalog|history|detail)(?:\?|$)/.exec(req.url??'')
   if(!match)return next()
   // Read precisely one committed generation for each request; never cache a
   // startup snapshot or read compatibility mirrors during a partial update.
   const bundle=JSON.parse(readFileSync(join(root,'data/market-dashboard/hithink-live/current-snapshot.json'),'utf8'))
   const params=new URL(req.url,'http://localhost').searchParams
   let value
   if(match[1]==='latest')value=localSnapshot(bundle)
   if(match[1]==='catalog')value=localCatalog(bundle,params)
   if(match[1]==='detail')value=localDetail(bundle,params)
   if(match[1]==='history'){
    const universe=params.get('universe'),axis=params.get('axis')
    if(!['industry','concept'].includes(universe)||!['strength','opportunity','risk'].includes(axis))throw Error('INVALID_QUERY')
    value=localHistory(bundle,universe,axis)
   }
   res.setHeader('cache-control','no-store');res.setHeader('content-type','application/json');res.end(JSON.stringify(value))
  }catch{res.statusCode=503;res.setHeader('content-type','application/json');res.end(JSON.stringify({error:'LOCAL_SNAPSHOT_UNAVAILABLE'}))}
 })}
}]})
await server.listen()
console.log('Local Hithink board: http://127.0.0.1:5184/__hithink-preview')
