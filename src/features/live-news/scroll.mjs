// Match the original ticker's 0.5px/frame at60Hz, without refresh-rate dependence.
export function advanceNewsOffset(offset,elapsedMs,height){
 if(!Number.isFinite(height)||height<=0)return 0
 const elapsed=Number.isFinite(elapsedMs)?Math.max(0,Math.min(100,elapsedMs)):0
 return -((Math.max(0,-offset)+elapsed*.03)%height)
}
