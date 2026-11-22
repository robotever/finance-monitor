<template>
 <header class="module-header">
  <h2 :id="titleId"><slot>{{title}}</slot></h2>
  <div class="module-header__actions"><time :datetime="datetime" :title="timeTitle">{{timeText||'数据时间待更新'}}</time><button type="button" :disabled="loading" :aria-label="`刷新${title}`" @click="$emit('refresh')">{{loading?'刷新中…':'刷新'}}</button></div>
 </header>
</template>
<script setup lang="ts">
defineProps<{title:string;titleId?:string;timeText?:string;datetime?:string;timeTitle?:string;loading?:boolean}>()
defineEmits<{refresh:[]}>()
</script>
<style src="../module-header.css"></style>
