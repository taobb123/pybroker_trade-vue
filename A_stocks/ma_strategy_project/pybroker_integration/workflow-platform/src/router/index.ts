import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'
import DashboardPage from '@/pages/DashboardPage.vue'
import WorkflowsPage from '@/pages/WorkflowsPage.vue'
import RunsPage from '@/pages/RunsPage.vue'
import ReportsPage from '@/pages/ReportsPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import AccountPage from '@/pages/AccountPage.vue'
import BillingPlansPage from '@/pages/BillingPlansPage.vue'
import BillingOrdersPage from '@/pages/BillingOrdersPage.vue'
import UsagePage from '@/pages/UsagePage.vue'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: LoginPage,
      meta: { public: true, title: '登录' },
    },
    {
      path: '/',
      component: AppShell,
      children: [
        { path: '', name: 'dashboard', component: DashboardPage, meta: { title: '总览' } },
        { path: 'usage', name: 'usage', component: UsagePage, meta: { title: '用量' } },
        { path: 'workflows', name: 'workflows', component: WorkflowsPage, meta: { title: '工作流' } },
        { path: 'runs', name: 'runs', component: RunsPage, meta: { title: '运行记录' } },
        { path: 'reports', name: 'reports', component: ReportsPage, meta: { title: '报告' } },
        {
          path: 'account',
          name: 'account',
          component: AccountPage,
          meta: { title: '用户中心', requiresAuth: true },
        },
        {
          path: 'billing/plans',
          name: 'billing-plans',
          component: BillingPlansPage,
          meta: { title: '会员套餐', requiresAuth: true },
        },
        {
          path: 'billing/orders',
          name: 'billing-orders',
          component: BillingOrdersPage,
          meta: { title: '订单', requiresAuth: true },
        },
      ],
    },
  ],
})
