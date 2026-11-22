<template>
 <nav class="sector-module terminal-panel" aria-label="板块研究入口">
  <ModuleHeader title="板块研究" :time-text="observedAt?formatTime(observedAt)+' 北京':undefined" :datetime="observedAt||undefined" :loading="loading" @refresh="refresh"><a href="/sectors/research">板块研究 <span class="sector-module__link">进入 →</span></a></ModuleHeader>
  <p v-if="error" class="sector-module__error" role="status">{{error}}</p>
 </nav>
</template>
<script setup lang="ts">
import {onMounted,onUnmounted,ref} from 'vue'
import ModuleHeader from './ModuleHeader.vue'
const observedAt=ref(''),loading=ref(false),error=ref('')
let controller:AbortController|undefined,timer:ReturnType<typeof setInterval>|undefined
function formatTime(value:string){return new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})}
async function refresh(){if(loading.value)return;loading.value=true;controller=new AbortController();try{const r=await fetch('/api/sector-live/manifest',{cache:'no-store',signal:AbortSignal.any([controller.signal,AbortSignal.timeout(12000)])});if(!r.ok)throw Error();const data=await r.json();if(!Number.isFinite(Date.parse(data.observedAt)))throw Error();observedAt.value=data.observedAt;error.value=''}catch{if(!controller.signal.aborted)error.value='本次更新未完成，请重试'}finally{loading.value=false}}
onMounted(()=>{void refresh();timer=setInterval(()=>{if(!document.hidden)void refresh()},30000)})
onUnmounted(()=>{controller?.abort();clearInterval(timer)})
</script>
<style scoped>
.sector-module{margin:10px 0 12px}.sector-module__link{font-size:10px;font-weight:400;color:#64d4ed;margin-left:8px}.sector-module__error{font-size:10px;color:#ddc293;padding:0 16px 8px;margin:0}
</style>
