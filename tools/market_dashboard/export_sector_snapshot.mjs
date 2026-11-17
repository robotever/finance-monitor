// Generate deployment assets only; never upload private runtime stores or raw provider envelopes.
import {readFileSync,writeFileSync,mkdirSync,readdirSync,statSync} from 'node:fs'
import {resolve,join,dirname} from 'node:path'
import {fileURLToPath} from 'node:url'
import {execFileSync} from 'node:child_process'
import {localSnapshot,localCatalog,localHistory,localDetail} from './hithink_preview_data.mjs'
const root=resolve(dirname(fileURLToPath(import.meta.url)),'../..')
const options=process.argv.slice(2),provided={}
for(let i=0;i<options.length;i+=2){if(!['--state-root','--output-root'].includes(options[i])||!options[i+1])throw Error('INVALID_EXPORT_OPTIONS');provided[options[i]]=resolve(options[i+1])}
const stateRoot=provided['--state-root']??join(root,'data/market-dashboard')
const bundle=JSON.parse(readFileSync(join(stateRoot,'hithink-live/current-snapshot.json'),'utf8'))
const generation=bundle.generation
if(!/^[a-zA-Z0-9_-]{1,100}$/.test(generation))throw Error('INVALID_GENERATION')
const base=provided['--output-root']??join(root,'dist/data/sector-research'),output=join(base,generation)
mkdirSync(output,{recursive:true})
const save=(name,data)=>writeFileSync(join(output,name+'.json'),JSON.stringify(data))
const latest=localSnapshot(bundle),weights=JSON.parse(readFileSync(join(root,'config/hithink-sector-dashboard.json'),'utf8')).scoring.weights
save('latest',latest)
const sectors=[]
for(const universe of ['industry','concept']){
 const first=localCatalog(bundle,new URLSearchParams({universe,page:'1',pageSize:'100'}))
 const all=[...first.sectors]
 for(let page=2;all.length<first.total;page++)all.push(...localCatalog(bundle,new URLSearchParams({universe,page:String(page),pageSize:'100'})).sectors)
 save('catalog-'+universe,{...first,sectors:all});sectors.push(...all)
 for(const axis of ['return1d','strength','opportunity','risk'])save(`history-${universe}-${axis}`,localHistory(bundle,universe,axis))
}
for(const sector of sectors)save('detail-'+sector.id,localDetail(bundle,new URLSearchParams({universe:sector.universe,id:sector.id}),weights))
const result=execFileSync('python3',['-m','tools.market_dashboard.hithink_constituent_detail','--enrich-export',stateRoot,output],{cwd:root,timeout:300000,encoding:'utf8'})
let bytes=0
for(const name of readdirSync(output)){
 const path=join(output,name),size=statSync(path).size
 if(size>24*1024*1024)throw Error('ASSET_TOO_LARGE')
 const content=readFileSync(path,'utf8')
 if(/(?:Bearer\s|X-api-key|ak_[A-Za-z0-9]{15,}|\/Users\/|access_token|refresh_token)/i.test(content))throw Error('PRIVATE_FIELD_IN_EXPORT')
 bytes+=size
}
writeFileSync(join(base,'manifest.json'),JSON.stringify({generation,marketDate:latest.marketDate,observedAt:latest.observedAt,mode:'publication-snapshot',automaticUpdates:false,exportedAt:new Date().toISOString()}))
console.log(JSON.stringify({generation,marketDate:latest.marketDate,observedAt:latest.observedAt,sectors:sectors.length,bytes,constituents:JSON.parse(result)}))
