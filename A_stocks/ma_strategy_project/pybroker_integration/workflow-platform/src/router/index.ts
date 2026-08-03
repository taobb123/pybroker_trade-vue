import { createRouter, createWebHistory } from 'vue-router'
import AppShell from '@/layouts/AppShell.vue'
import DashboardPage from '@/pages/DashboardPage.vue'
import WorkflowsPage from '@/pages/WorkflowsPage.vue'
import RunsPage from '@/pages/RunsPage.vue'
import ReportsPage from '@/pages/ReportsPage.vue'
import LoginPage from '@/pages/LoginPage.vue'
import OnboardingPage from '@/pages/OnboardingPage.vue'
import AccountPage from '@/pages/AccountPage.vue'
import BillingPlansPage from '@/pages/BillingPlansPage.vue'
import BillingOrdersPage from '@/pages/BillingOrdersPage.vue'
import UsagePage from '@/pages/UsagePage.vue'
import AdminPage from '@/pages/AdminPage.vue'
import { useAuthStore } from '@/stores/auth'
import { resolveOnboardingLanding } from '@/config/businessRules'
import { trackEvent } from '@/api/events'

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
      path: '/onboarding',
      name: 'onboarding',
      component: OnboardingPage,
      meta: { title: '首次引导', requiresAuth: true, onboarding: true },
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
        {
          path: 'admin',
          name: 'admin',
          component: AdminPage,
          meta: { title: '管理后台', requiresAuth: true, requiresAdmin: true },
        },
      ],
    },
  ],
})

const PAGE_VIEW_PATHS = new Set(['/workflows', '/billing/plans', '/reports'])

router.beforeEach((to) => {
  const auth = useAuthStore()
  if (!auth.bootstrapped) return true

  if (to.meta.requiresAuth && !auth.isAuthenticated) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  if (to.meta.requiresAdmin && auth.user?.role !== 'admin') {
    return { path: '/' }
  }

  if (to.name === 'login' && auth.isAuthenticated) {
    if (!auth.user?.onboardingDone) return { path: '/onboarding' }
    return { path: '/' }
  }

  if (
    auth.isAuthenticated &&
    !auth.user?.onboardingDone &&
    auth.user?.role !== 'admin' &&
    !to.meta.onboarding &&
    to.name !== 'login'
  ) {
    return { path: '/onboarding', query: { redirect: to.fullPath } }
  }

  if (to.meta.onboarding && auth.isAuthenticated && auth.user?.onboardingDone) {
    return resolveOnboardingLanding(to.query.redirect)
  }

  return true
})

router.afterEach((to) => {
  if (!PAGE_VIEW_PATHS.has(to.path)) return
  trackEvent('page_view', { path: to.path, name: String(to.name || '') })
})
