import {randomUUID} from 'node:crypto'
import {readFile,mkdir,writeFile,rename} from 'node:fs/promises'
import {join} from 'node:path'
import {buildFinancialNews,loadFeed} from '../../functions/_lib/financial-news.js'
import {mergeFinancialNews,mediaUnavailable} from '../../src/features/live-news/policy.mjs'
export function createLocalNews({stateRoot,fetcher,loadQuote,origin='http://127.0.0.1:5184',offline=false}){
 const file=join(stateRoot,'news-last.json');let pending=null,memo=null,memoAt=0
 return async function news(){
  if(memo&&Date.now()-memoAt<20000)return structuredClone(memo)
  if(pending)return structuredClone(await pending)
  pending=(async()=>{
   let old;try{old=JSON.parse(await readFile(file,'utf8'));if(!Array.isArray(old.items)||!Number.isFinite(old.fetchedAt))old=null}catch{}
   const fresh=await buildFinancialNews({origin,loadNews:id=>loadFeed(id,fetcher),loadQuote})
   const failed=mediaUnavailable(fresh.sources),items=mergeFinancialNews(fresh.items,old?.items??[],Date.now())
   const value={...fresh,items,localStatus:{mode:failed?(old?'cached':'empty'):fresh.sources.some(s=>s.status==='failed')?'partial':'live',lastSuccessAt:failed?old?.fetchedAt??null:fresh.fetchedAt,note:failed?'快讯连接未更新；实时区仅保留两小时内消息':undefined},archiveItems:failed?(old?.items??[]).filter(x=>x.source!=='market_monitor'&&Date.now()-x.publishedAt>7200000).slice(0,30):[]}
   if(!failed){await mkdir(stateRoot,{recursive:true});const temp=file+'.'+randomUUID()+'.tmp';await writeFile(temp,JSON.stringify({...fresh,items}),{mode:0o600});await rename(temp,file)}
   memo=value;memoAt=Date.now();return value
  })()
  try{return structuredClone(await pending)}finally{pending=null}
 }
}
