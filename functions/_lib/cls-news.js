// Read public server-rendered JSON only. Never execute upstream JavaScript.
export function parseClsTelegraph(html){
 if(typeof html!=='string'||html.length>1500000)throw Error('INVALID_CLS_PAGE')
 const embedded=html.match(/<script\b[^>]*\bid=["']__NEXT_DATA__["'][^>]*>([\s\S]*?)<\/script\s*>/i)
 let payload
 if(embedded)payload=JSON.parse(embedded[1])
 else{
  const assignment=/(?:^|[\s;>])(?:window\.)?__NEXT_DATA__\s*=\s*/g.exec(html)
  if(!assignment)throw Error('INVALID_CLS_PAGE')
  const start=assignment.index+assignment[0].length
  if(html[start]!=='{')throw Error('INVALID_CLS_PAGE')
  let depth=0,quoted=false,escaped=false,end=-1
  for(let i=start;i<html.length;i++){
   const char=html[i]
   if(quoted){if(escaped)escaped=false;else if(char==='\\')escaped=true;else if(char==='"')quoted=false;continue}
   if(char==='"')quoted=true
   else if(char==='{')depth++
   else if(char==='}'&&--depth===0){end=i+1;break}
  }
  if(end<0)throw Error('INVALID_CLS_PAGE')
  payload=JSON.parse(html.slice(start,end))
 }
 const rows=payload?.props?.initialState?.roll_data
 if(!Array.isArray(rows))throw Error('INVALID_CLS_FEED')
 return {data:rows.slice(0,100)}
}
