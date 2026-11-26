const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0
export function turnoverSeries(points, market, mode='amount') {
 return points.map((point,index) => {
  const current=point[market],previous=points[index-1]?.[market]
  if(mode !== 'change')return {date:point.date,value:valid(current) ? current / 1e8 : null}
  const known=valid(current)&&valid(previous),delta=known?current-previous:null
  return {date:point.date,value:delta === null ? null : delta/1e8,changePct:known&&previous>0 ? delta/previous*100 : null}
 })
}
export function rangeStart(points, months) {
 const last=points.at(-1)
 if(!last || !months)return 0
 const [year,month,day]=last.date.split('-').map(Number)
 const cutoff=new Date(Date.UTC(year,month-1-months,1))
 const maxDay=new Date(Date.UTC(cutoff.getUTCFullYear(),cutoff.getUTCMonth()+1,0)).getUTCDate()
 cutoff.setUTCDate(Math.min(day,maxDay))
 const first=points.findIndex(point=>point.date >= cutoff.toISOString().slice(0,10))
 return first < 0 ? points.length : first
}
export function chartGeometry(points) {
 const finite=value=>typeof value==='number'&&Number.isFinite(value)
 const values=points.filter(p=>finite(p.value)).map(p=>p.value)
 const high=Math.max(1,...values)*1.1,low=Math.min(0,...values)*1.1
 const y=value=>192-(value-low)/(high-low)*172
 const coordinates=points.map((point,index)=>finite(point.value) ? {x:points.length < 2 ? 357 : 90+index*534/(points.length-1),y:y(point.value)} : null)
 let path='',connected=false
 for(const point of coordinates){
  if(!point){connected=false;continue}
  path+=`${connected?'L':'M'}${point.x.toFixed(2)},${point.y.toFixed(2)} `;connected=true
 }
 return {path,coordinates,zeroY:y(0),ticks:Array.from({length:4},(_,i)=>({value:low+(high-low)*i/3,y:192-i*172/3}))}
}
export function resizeWindow(length,start,end,factor) {
 const size=Math.min(length,Math.max(Math.min(5,length),Math.round((end-start)*factor)))
 const next=Math.max(0,Math.min(length-size,Math.round((start+end-size)/2)))
 return {start:next,end:next+size}
}
export function moveWindow(length,start,end,direction) {
 const size=end-start,next=Math.max(0,Math.min(length-size,start+direction*Math.max(1,Math.round(size/3))))
 return {start:next,end:next+size}
}
export function formatTurnover(value,signed=false) {
 if(value === null || !Number.isFinite(value))return '—'
 return `${signed && value > 0 ? '+' : ''}${(value/1e8).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2,useGrouping:false})}`
}
