// Private full homepage. All APIs below are read-only and independent of Pages/D1.
import {validateEtfBundle} from '../../src/features/etf-observation/model.mjs'
import {randomUUID} from 'node:crypto'
import {readFile,stat,mkdir,writeFile,rename} from 'node:fs/promises'
import {fileURLToPath} from 'node:url'
import {resolve,join,dirname} from 'node:path'
import {homedir} from 'node:os'
import {createServer} from 'vite'
import {execFile} from 'node:child_process'
import {localSnapshot,localHistory,localCatalog,localDetail} from './hithink_preview_data.mjs'
import {createLocalHttp,createProxyCache} from './local_home_http.mjs'
import {createLocalNews} from './local_home_news.mjs'
import {createLocalMarketQuotes} from './local_market_quotes.mjs'
import {createLocalResearchData} from './local_research_data.mjs'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..'),port=Number(process.env.FINANCE_MONITOR_LOCAL_PORT??5184)
const offline=process.env.FINANCE_MONITOR_OFFLINE==='1',stateRoot=resolve(process.env.FINANCE_MONITOR_LOCAL_STATE??join(root,'data/local-home'))
const origin=`http://127.0.0.1:${port}`,sectorRoot=join(root,'data/market-dashboard'),project=process.env.MARKET_DASHBOARD_PROJECT_ROOT??join(homedir(),'Codex/Financial Knowledge Repository')
const fetcher=createLocalHttp({offline}),proxies=createProxyCache({stateRoot,fetcher,offline}),research=createLocalResearchData({stateRoot,radarInputsPath:join(project,'state/market-radar-inputs/latest.json'),fetcher,offline})
const rawQuote=createLocalMarketQuotes({stateRoot,fetcher,offline}),memo=new Map(),running=new Map()
async function remember(key,ttl,loader){const saved=memo.get(key);if(saved&&Date.now()-saved.time<ttl)return structuredClone(saved.value);if(running.has(key))return structuredClone(await running.get(key));const task=loader().then(value=>{memo.set(key,{time:Date.now(),value});return value});running.set(key,task);try{return structuredClone(await task)}finally{running.delete(key)}}
const quote=id=>remember('quote-'+id,20000,()=>rawQuote(id)),news=createLocalNews({stateRoot,fetcher,loadQuote:quote,origin,offline})
let snapshotTime=0,snapshot=null,reading=null;const pinned=new Map()
async function current(){
 const file=join(sectorRoot,'hithink-live/current-snapshot.json'),info=await stat(file)
 if(snapshot&&snapshotTime===info.mtimeMs)return snapshot
 if(reading)return reading
 reading=(async()=>{const next=JSON.parse(await readFile(file,'utf8'));if(!/^[a-f0-9]{64}$/.test(next.generation)||next.payload?.rows?.length!==480)throw Error('INVALID_LOCAL_SNAPSHOT');snapshot=next;snapshotTime=info.mtimeMs;pinned.set(next.generation,next);while(pinned.size>2)pinned.delete(pinned.keys().next().value);return next})()
 try{return await reading}finally{reading=null}
}
async function constituents(bundle,id,date){
 const points=localDetail(bundle,new URLSearchParams({universe:id.startsWith('881')?'industry':'concept',id})).history
 const history=date?points.filter(p=>p.marketDate===date):points
 if(!history.length)throw Error('INVALID_DATE')
 return new Promise((yes,no)=>{const child=execFile('python3',['-m','tools.market_dashboard.hithink_constituent_detail',sectorRoot,id],{cwd:root,timeout:25000,maxBuffer:32*1024*1024},(error,stdout)=>{if(error)return no(error);try{yes(JSON.parse(stdout))}catch(e){no(e)}});child.stdin.end(JSON.stringify({marketDate:bundle.payload.marketDate,history:history.map(p=>({marketDate:p.marketDate,observedAt:p.observedAt,historicalReconstruction:p.historicalReconstruction}))}))})
}
const targets={ftchinese:'http://www.ftchinese.com',bloomberg:'https://feeds.bloomberg.com',marketwatch:'https://feeds.marketwatch.com',eastmoney:'https://newsapi.eastmoney.com',wallstreetcn:'https://api-one.wallstcn.com',jin10:'https://www.jin10.com',cankaoxiaoxi:'https://china.cankaoxiaoxi.com',mktnews:'https://api.mktnews.net'}
async function archivedRadar(){
 const data=await research.radar(),file=join(stateRoot,'radar-last.json'),usable=x=>[x.global,x.ashare,...x.styles].some(r=>Number.isFinite(r.strength))
 if(usable(data)){
  await mkdir(stateRoot,{recursive:true});const temp=file+'.'+randomUUID()+'.tmp';await writeFile(temp,JSON.stringify(data),{mode:0o600});await rename(temp,file);return data
 }
 try{
  const old=JSON.parse(await readFile(file,'utf8'));if(old.version!==data.version||!usable(old))return data
  const mark=x=>({...x,status:'failed'})
  return {...old,global:mark(old.global),ashare:mark(old.ashare),styles:old.styles.map(mark),sources:data.sources,sourceErrors:data.sourceErrors,localStatus:{mode:'cached',lastSuccessAt:old.checkedAt,note:'当前未更新；以下为上次保存的评分，日期保留原值'}}
 }catch{return data}
}
async function route(url){
 const p=url.searchParams,path=url.pathname
 if(path==='/api/local/status')return {local:true,offline}
 if(path==='/api/local/source-state'){const id=p.get('source');if(!Object.hasOwn(targets,id))throw Error('INVALID_SOURCE');return proxies.status(id)}
 if(path==='/api/news/live')return news()
 if(path==='/api/market-watch/quote')return quote(p.get('instrument'))
 if(path==='/api/market-radar/etf'){const data=validateEtfBundle(JSON.parse(await readFile(join(project,'state/etf-observation/latest.json'),'utf8')));return {...data,cached:offline}}
 if(path==='/api/market-radar')return remember('radar',20000,archivedRadar)
 if(path==='/api/cross-market/risk')return remember('risk',20000,()=>research.risk())
 if(path==='/api/sector-live/manifest'){const b=await current(),s=localSnapshot(b);return {generation:b.generation,marketDate:s.marketDate,observedAt:s.observedAt,mode:'live',automaticUpdates:true,local:true}}
 if(path==='/api/sector-live/document'){
  const generation=p.get('generation'),key=p.get('key');await current();const b=pinned.get(generation);if(!b)throw Error('UNKNOWN_GENERATION')
  if(key==='latest')return localSnapshot(b)
  const catalog=/^catalog-(industry|concept)$/.exec(key);if(catalog){const q=new URLSearchParams({universe:catalog[1],page:'1',pageSize:'100'}),first=localCatalog(b,q),sectors=[...first.sectors];for(let page=2;sectors.length<first.total;page++)sectors.push(...localCatalog(b,new URLSearchParams({universe:catalog[1],page:String(page),pageSize:'100'})).sectors);return {...first,sectors}}
  const history=/^history-(industry|concept)-(return1d|strength|opportunity|risk)$/.exec(key);if(history)return localHistory(b,history[1],history[2])
  const detail=/^detail-(881\d{3}|88[56]\d{3})\.TI$/.exec(key)
  if(detail){const id=detail[1]+'.TI',view=p.get('view'),date=p.get('date');if(date&&!/^\d{4}-\d{2}-\d{2}$/.test(date))throw Error('INVALID_DATE');return remember(generation+key+(view??'')+(date??''),300000,async()=>{
   const d=localDetail(b,new URLSearchParams({universe:id.startsWith('881')?'industry':'concept',id}),JSON.parse(await readFile(join(root,'config/hithink-sector-dashboard.json'),'utf8')).scoring.weights)
   if(!d.history.length)throw Error('INVALID_SECTOR')
   try{const members=await constituents(b,id,view==='members'?date:null);if(view==='members'){if(!members[date])throw Error('INVALID_DATE');return members[date]}d.constituentsByDate=Object.fromEntries(Object.entries(members).map(([day,m])=>[day,view==='summary'?{...m,rows:m.rows.slice(0,10)}:m]))}catch{if(view==='members')throw Error('CONSTITUENTS_UNAVAILABLE');d.constituentsByDate={};d.constituentsUnavailable=true}return d
  })}
  throw Error('INVALID_DOCUMENT')
 }
 if(path.startsWith('/proxy-')){
  const match=/^\/proxy-([a-z0-9]+)(\/.*)$/.exec(path),source=match?.[1];if(!source||!Object.hasOwn(targets,source))throw Error('INVALID_SOURCE')
  return proxies.get(source,targets[source]+match[2]+url.search)
 }
 throw Error('UNKNOWN_ROUTE')
}
const server=await createServer({root,mode:'production-rotation',define:{'import.meta.env.VITE_LOCAL_HOME':JSON.stringify('true')},server:{host:'127.0.0.1',port,strictPort:true},plugins:[{
 name:'finance-monitor-local-home',
 transformIndexHtml(html){return html.replace(/<link\b[^>]*href="https:\/\/fonts\.(?:googleapis|gstatic)\.com[^>]*>/g,'')},
 configureServer(s){s.middlewares.use(async(req,res,next)=>{
  const url=new URL(req.url??'/',origin)
  if(url.pathname==='/__hithink-preview'){res.statusCode=302;res.setHeader('Location','/sectors/research');res.end();return}
  if(!url.pathname.startsWith('/api/')&&!url.pathname.startsWith('/proxy-'))return next()
  if(req.method!=='GET'){res.statusCode=405;res.end('Read only');return}
  if(![`127.0.0.1:${port}`,`localhost:${port}`].includes(req.headers.host)||req.headers.origin&&![origin,`http://localhost:${port}`].includes(req.headers.origin)){res.statusCode=403;res.end('Local access only');return}
  try{
   const data=await route(url)
   res.setHeader('Cache-Control','no-store')
   if(data instanceof Response){res.statusCode=data.status;for(const [key,value] of data.headers)res.setHeader(key,value);res.end(Buffer.from(await data.arrayBuffer()))}
   else{res.setHeader('Content-Type','application/json; charset=utf-8');res.end(JSON.stringify(data))}
  }catch{res.statusCode=503;res.setHeader('Content-Type','application/json');res.end(JSON.stringify({error:'LOCAL_SOURCE_UNAVAILABLE'}))}
 })}
}]})
await server.listen();console.log('Finance Monitor local homepage: '+origin+' / '+(offline?'offline cached mode':'direct public sources'))
