import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '@/views/HomeView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/sectors/research', name: 'sector-research-snapshot', component: () => import('@/views/SectorResearchSnapshotView.vue') },
    { path: '/sectors/hithink', name: 'hithink-sectors', redirect: '/sectors/research' },
  ],
})

export default router
