import {spawn} from 'node:child_process'
import {createHash,randomUUID} from 'node:crypto'
import {mkdtemp,readFile,rm,mkdir,writeFile,rename} from 'node:fs/promises'
import {tmpdir} from 'node:os'
import {join} from 'node:path'
const hosts=new Set(['www.cls.cn','m.cls.cn','web.ifzq.gtimg.cn','hq.sinajs.cn','vip.stock.finance.sina.com.cn','stock2.finance.sina.com.cn','cdn.cboe.com','home.treasury.gov','api.data.chicagofed.org','markets.newyorkfed.org','api-one.wallstcn.com','www.jin10.com','api.mktnews.net','news.futunn.com','ai-news-search.futunn.com','www.ftchinese.com','feeds.bloomberg.com','feeds.marketwatch.com','newsapi.eastmoney.com','china.cankaoxiaoxi.com'])
function checkUrl(value){const u=new URL(value);if(!['http:','https:'].includes(u.protocol)||!hosts.has(u.hostname)||u.port||u.username||u.password)throw Error('INVALID_UPSTREAM');return u}
export function createLocalHttp({offline=false,maxBytes=5000000}={}){
 return async function directFetch(url,{headers={},signal}={}){
  checkUrl(url);if(offline)throw Error('OFFLINE')
  const temp=await mkdtemp(join(tmpdir(),'finance-local-http-')),file=join(temp,'headers')
  try{return await new Promise((resolve,reject)=>{
   const args=['--noproxy','*','--silent','--show-error','--compressed','--location','--max-redirs','3','--proto','=http,https','--proto-redir','=http,https','--connect-timeout','3','--max-time','8','--max-filesize',String(maxBytes),'--dump-header',file]
   for(const [k,v] of new Headers(headers))args.push('--header',`${k}: ${v}`)
   args.push(String(url));const child=spawn('/usr/bin/curl',args,{stdio:['ignore','pipe','pipe']}),chunks=[];let size=0,settled=false
   const abort=()=>{child.kill('SIGTERM')};if(signal?.aborted)abort();signal?.addEventListener('abort',abort,{once:true})
   child.stdout.on('data',chunk=>{size+=chunk.length;if(size>maxBytes)abort();else chunks.push(chunk)})
   child.stderr.resume()
   child.on('error',error=>{settled=true;reject(error)})
   child.on('close',async code=>{
    signal?.removeEventListener('abort',abort);if(settled)return
    if(code!==0||size>maxBytes||signal?.aborted){reject(Error('DIRECT_SOURCE_UNAVAILABLE'));return}
    try{
     const raw=await readFile(file,'utf8'),blocks=raw.split(/\r?\n\r?\n/).filter(x=>/^HTTP\//.test(x)),last=blocks.at(-1)??'',status=Number(last.match(/^HTTP\/\S+\s+(\d{3})/)?.[1]);if(!status)throw Error('INVALID_UPSTREAM_RESPONSE')
     const out=new Headers();for(const line of last.split(/\r?\n/).slice(1)){const i=line.indexOf(':');if(i>0&&['content-type','last-modified'].includes(line.slice(0,i).toLowerCase()))out.set(line.slice(0,i),line.slice(i+1).trim())}
     resolve(new Response(Buffer.concat(chunks),{status,headers:out}))
    }catch(error){reject(error)}
   })
  })}finally{await rm(temp,{recursive:true,force:true})}
 }
}
export function createProxyCache({stateRoot,fetcher,now=Date.now,offline=false}){
 const statusRows=new Map(),pending=new Map(),clock=()=>typeof now==='function'?now():now
 function key(url){const u=checkUrl(url);u.searchParams.delete('t');u.searchParams.delete('_');return u.toString()}
 const path=k=>join(stateRoot,'proxy-cache',createHash('sha256').update(k).digest('hex')+'.json')
 function response(saved,cached){return new Response(Buffer.from(saved.body,'base64'),{headers:{'Content-Type':saved.contentType,'X-Local-Cached':String(cached),'X-Local-Fetched-At':String(saved.fetchedAt),'Cache-Control':'no-store'}})}
 return {
  async get(source,url){
   const k=key(url);if(pending.has(k))return (await pending.get(k)).clone()
   const task=(async()=>{
    let old;try{old=JSON.parse(await readFile(path(k),'utf8'));if(old.url!==k||!Number.isFinite(old.fetchedAt)||old.fetchedAt>clock()||typeof old.body!=='string'||old.body.length>8000000)old=null}catch{}
    const use=(data,cached)=>{statusRows.set(k,{source,cached,fetchedAt:data.fetchedAt});return response(data,cached)}
    if(old&&!offline&&clock()-old.fetchedAt<20000)return use(old,false)
    try{
     const r=await fetcher(url,{headers:{Referer:new URL(url).origin+'/', 'User-Agent':'Mozilla/5.0'}});if(!r.ok)throw Error('SOURCE_FAILED')
     const bytes=Buffer.from(await r.arrayBuffer());if(bytes.length>5000000)throw Error('SOURCE_TOO_LARGE')
     const saved={url:k,body:bytes.toString('base64'),contentType:r.headers.get('content-type')??'application/octet-stream',fetchedAt:clock()}
     const dest=path(k);await mkdir(join(stateRoot,'proxy-cache'),{recursive:true});const temp=dest+'.'+randomUUID()+'.tmp';await writeFile(temp,JSON.stringify(saved),{mode:0o600});await rename(temp,dest)
     return use(saved,false)
    }catch{if(old)return use(old,true);throw Error('SOURCE_UNAVAILABLE')}
   })();pending.set(k,task)
   try{return (await task).clone()}finally{pending.delete(k)}
  },
  status(source){const rows=[...statusRows.values()].filter(x=>x.source===source);return rows.length?{cached:rows.some(r=>r.cached),fetchedAt:Math.min(...rows.map(r=>r.fetchedAt))}:{cached:false,fetchedAt:null}},
 }
}
