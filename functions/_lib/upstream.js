// Bound network time and bytes before parsing third-party data.
export async function upstreamText(url,{fetcher=fetch,headers={},maxBytes=1500000,encoding='utf-8'}={}){
 const response=await fetcher(url,{headers,signal:AbortSignal.timeout(8500)})
 if(!response.ok)throw Error('UPSTREAM_FAILED')
 const reader=response.body.getReader(),chunks=[];let size=0
 try{while(true){const {value,done}=await reader.read();if(done)break;size+=value.length;if(size>maxBytes)throw Error('RESPONSE_TOO_LARGE');chunks.push(value)}}finally{await reader.cancel().catch(()=>{})}
 const bytes=new Uint8Array(size);let n=0;for(const chunk of chunks){bytes.set(chunk,n);n+=chunk.length}
 return new TextDecoder(encoding).decode(bytes)
}
