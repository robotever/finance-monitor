<template><div class="app-shell"><AppHeader/><RouterView/></div></template>
<script setup lang="ts">
import {onMounted,onUnmounted} from 'vue'
import AppHeader from '@/components/AppHeader.vue'
import {useNewsStore} from '@/stores/news'
const store=useNewsStore()
onMounted(()=>{void store.fetchAll();void store.fetchLive();store.startAutoRefresh()})
onUnmounted(()=>store.stopAutoRefresh())
</script>
