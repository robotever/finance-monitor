import test from 'node:test'
import assert from 'node:assert/strict'
import {classifyFinancialNews,financeNewsPolicy,marketObservation,mergeFinancialNews,selectFinancialNews,mediaUnavailable,CATEGORY_LABELS} from '../src/features/live-news/policy.mjs'
import {normalizeFeed,freshNews,activeNews} from '../src/features/live-news/model.mjs'
const now=Date.parse('2026-11-21T11:30:00Z')
const item=title=>({id:title,title,url:'https://example.com/'+encodeURIComponent(title),publishedAt:now-1000,source:'jin10',sourceName:'金十数据',important:false})
test('company, industry, price movements and macro receive clear categories',()=>{
 for(const [title,category] of [['长高电气：四季度交付速度有一定回升','company'],['重庆发布86项低空产业发展机会清单 总投资约289亿元','industry'],['半导体板块盘中涨幅超过3%，成交额突破千亿','market'],['央行宣布下调政策利率','macro'],['港口运价持续上行，航运业供需改善','industry']]){
  assert.equal(classifyFinancialNews(item(title)),category,title)
 }
 assert.equal(CATEGORY_LABELS.market,'盘中异动')
})
test('ordinary affairs are excluded even if source flags them important; concrete finance links survive',()=>{
 for(const title of ['俄国防部：击落275架无人机','奥地利外交部：此次事件未影响公民个人信息','丹麦提议暂停向俄罗斯公民发放旅游签证','青海发生5.6级地震'])assert.equal(classifyFinancialNews({...item(title),important:true}),null,title)
 assert.ok(classifyFinancialNews(item('一艘油轮遇袭，霍尔木兹海峡航运受阻')))
 assert.ok(classifyFinancialNews(item('美国总统宣布提高半导体进口关税')))
})
test('Futu flash and search preserve original publication time, content and semantic hash links',()=>{
 const flash=normalizeFeed('futu_flash',{code:0,data:{code:'0',data:{news:[{id:'11',time:String(now/1000),title:'',content:'长高电气：四季度交付回升',detailUrl:'https://news.futunn.com/flash/11'}]}}})
 assert.equal(flash[0].publishedAt,now);assert.equal(flash[0].sourceName,'富途快讯')
 const search=normalizeFeed('futu_company',{code:0,data:[{news_id:'a',publish_time:String(now/1000),title:'某<em>公司</em>发布订单',url:'https://gu.qq.com/detail?src=39#/index?id=a'},{news_id:'b',publish_time:String(now/1000),title:'另一公司发布业绩',url:'https://gu.qq.com/detail?src=39#/index?id=b'}]})
 assert.equal(search[0].title,'某公司发布订单');assert.equal(freshNews(search,now).length,2)
 assert.throws(()=>normalizeFeed('futu_flash',{code:1,data:{data:{news:[]}}}))
 assert.throws(()=>normalizeFeed('futu_company',{code:5,data:[]}))
})
test('finance filtering happens before the100item limit and keeps date order and expiry',()=>{
 const rows=Array.from({length:110},(_,n)=>({...item('外国军方发布军事消息'+n),publishedAt:now-n})).concat([{...item('某公司净利润增长'),publishedAt:now-100000},{...item('某行业产能增加'),publishedAt:now-7200001}])
 const out=freshNews(financeNewsPolicy(rows),now)
 assert.equal(out.length,1);assert.equal(out[0].category,'company');assert.equal(out[0].categoryLabel,'公司动态')
})
test('market observations only use fresh intraday quotes and disclose snapshot rather than crossing',()=>{
 const quote={price:3500,changePercent:-1.2,status:'intraday',observedAt:new Date(now-20000).toISOString()}
 const out=marketObservation('shanghai',quote,'https://example.com',now)
 assert.equal(out.category,'market');assert.equal(out.publishedAt,now-20000);assert.equal(out.sourceName,'系统监测');assert.match(out.title,/行情快照/)
 assert.equal(marketObservation('shanghai',{...quote,status:'closed'},'https://example.com',now),null)
 assert.equal(marketObservation('shanghai',{...quote,observedAt:new Date(now-240000).toISOString()},'https://example.com',now),null)
 assert.equal(marketObservation('shanghai',{...quote,changePercent:.4},'https://example.com',now),null)
 assert.equal(marketObservation('shanghai',{...quote,price:null},'https://example.com',now),null)
 assert.equal(marketObservation('hstech',{...quote,changePercent:1.2},'https://example.com',now),null)
 assert.equal(marketObservation('shanghai',{...quote,observedAt:new Date(now+5000).toISOString()},'https://example.com',now),null)
})
test('all three genuine monitor snapshots survive financial classification',()=>{
 const rows=['shanghai','chinext','hstech'].map(id=>marketObservation(id,{price:3500,changePercent:2.3,status:'intraday',observedAt:new Date(now-1000).toISOString()},'https://example.com',now))
 assert.equal(financeNewsPolicy(rows).length,3)
})

test('server-to-client merge retains all index snapshots but never replays absent previous snapshots',()=>{
 const snapshots=['shanghai','chinext','hstech'].map(id=>marketObservation(id,{price:3500,changePercent:2.3,status:'intraday',observedAt:new Date(now-1000).toISOString()},'https://example.com',now))
 const media=item('某公司业绩增长')
 const first=mergeFinancialNews([...snapshots,media],[],now)
 assert.equal(first.length,4);assert.equal(first.filter(i=>i.source==='market_monitor').length,3)
 assert.deepEqual(mergeFinancialNews([],first,now+10000).map(i=>i.id),[media.id])
 assert.equal(activeNews(first,now+180001).filter(i=>i.source==='market_monitor').length,0)
})
test('healthy quotes never hide a total media outage, while genuine empty feeds are not failures',()=>{
 assert.equal(mediaUnavailable([{id:'futu_flash',status:'failed'},{id:'jin10',status:'failed'},{id:'market_monitor',status:'ok'}]),true)
 assert.equal(mediaUnavailable([{id:'futu_flash',status:'empty'},{id:'market_monitor',status:'ok'}]),false)
})
test('finance-related geopolitical background cannot crowd out companies and industries',()=>{
 const stories=Array.from({length:8},(_,n)=>({...item('伊朗海军称第'+n+'艘油轮触雷'),publishedAt:now-n})).concat([item('某公司业绩增长'),item('低空产业新政策发布')])
 const out=selectFinancialNews(stories,now);assert.equal(out.filter(i=>i.contextOnly).length,2);assert.equal(out.filter(i=>!i.contextOnly).length,2)
})
test('background quota applies before the100item output limit',()=>{
 const rows=Array.from({length:110},(_,n)=>({...item('伊朗海军称第'+n+'艘油轮触雷'),publishedAt:now-n})).concat([{...item('某公司业绩增长'),publishedAt:now-100000}])
 const out=selectFinancialNews(rows,now);assert.equal(out.length,3);assert.ok(out.some(i=>i.category==='company'))
})
