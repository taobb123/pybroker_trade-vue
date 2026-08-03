import { createRouter, createWebHistory } from 'vue-router'
import DashboardPage from '@/pages/DashboardPage.vue'
import WorkflowsPage from '@/pages/WorkflowsPage.vue'
import RunsPage from '@/pages/RunsPage.vue'
import ReportsPage from '@/pages/ReportsPage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardPage },
    { path: '/workflows', name: 'workflows', component: WorkflowsPage },
    { path: '/runs', name: 'runs', component: RunsPage },
    { path: '/reports', name: 'reports', component: ReportsPage },
  ],
})
