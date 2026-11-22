<template><p v-if="status&&status.mode!=='live'" class="local-data-note" role="status">{{status.note||'使用本地保存的数据'}}<span v-if="status.lastSuccessAt"> · 保存于 {{time(status.lastSuccessAt)}}</span></p></template>
<script setup lang="ts">
defineProps<{status?:{mode:string;lastSuccessAt?:number|null;note?:string}}>()
const time=(value:number)=>new Date(value).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false})
</script>
<style scoped>.local-data-note{margin:0 14px 8px;color:#c7b17e;font-size:10px;line-height:1.7}.local-data-note span{white-space:nowrap}</style>
