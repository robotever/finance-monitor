// Official exchange calendars; an unverified year is never labelled current.
// Sources and annual maintenance instructions: docs/market-radar-methodology.md.
const china={2026:[['01-01','01-03'],['02-15','02-23'],['04-04','04-06'],['05-01','05-05'],['06-19','06-21'],['09-25','09-27'],['10-01','10-07']]}
const us={
 2026:['01-01','01-19','02-16','04-03','05-25','06-19','07-03','09-07','11-26','12-25'],
 2027:['01-01','01-18','02-15','03-26','05-31','06-18','07-05','09-06','11-25','12-24'],
}
const bankExtra={2026:['10-12','11-11'],2027:['10-11','11-11']}
export function expectedCompletedSession(market,clock){
 const cutoff=market==='china'?15*60+15:17*60+15
 let day=Date.parse(clock.date+'T12:00:00Z')-(clock.minute<cutoff?86400000:0)
 for(let i=0;i<35;i++,day-=86400000){
  const date=new Date(day),year=date.getUTCFullYear(),md=date.toISOString().slice(5,10),week=date.getUTCDay()
  if(market==='china'?!china[year]:!us[year])return null
  if(week===0||week===6)continue
  if(market==='china'){if(china[year].some(([a,b])=>md>=a&&md<=b))continue}
  else if(us[year].includes(md)||market==='global'&&bankExtra[year].includes(md))continue
  return date.toISOString().slice(0,10)
 }
 return null
}
