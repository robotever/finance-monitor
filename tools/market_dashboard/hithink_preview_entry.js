import {createApp} from 'vue'
import '/src/style.css'
import {createSectorBoard} from '/tools/market_dashboard/hithink_board_app.js'
createApp(createSectorBoard()).mount('#app')
