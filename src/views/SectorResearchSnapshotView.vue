<script setup lang="ts">
import {createSectorBoard} from '../../tools/market_dashboard/hithink_board_app.js'
const Board=createSectorBoard({snapshot:true})
</script>
<template><Board /></template>
