import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  ENFORCE_AUTH_FOR_RUN,
  PLAN_RULES,
  dailyQuotaLabel,
  hasCapability,
  isAdvancedStep,
} from '@/config/businessRules'
import { type PlanTier, useAuthStore } from '@/stores/auth'
import type { WorkflowStep } from '@/api/types'
import { consumeQuotaRun, fetchQuotaToday, type ServerQuota } from '@/api/membership'

export const useQuotaStore = defineStore('quota', () => {
  const serverQuota = ref<ServerQuota | null>(null)
  const blockMessage = ref('')
  const loading = ref(false)

  function effectivePlan(): PlanTier {
    const auth = useAuthStore()
    auth.ensurePlanNotExpired()
    if (serverQuota.value?.plan) return serverQuota.value.plan as PlanTier
    return auth.user?.plan ?? 'free'
  }

  const usedToday = computed(() => serverQuota.value?.used_runs ?? 0)
  const dailyLimit = computed(() => {
    if (serverQuota.value) return serverQuota.value.daily_limit
    return PLAN_RULES[effectivePlan()].dailyRunQuota
  })
  const remainingToday = computed(() => {
    if (serverQuota.value?.unlimited) return Number.POSITIVE_INFINITY
    if (serverQuota.value?.remaining != null) return serverQuota.value.remaining
    const limit = dailyLimit.value
    if (limit < 0) return Number.POSITIVE_INFINITY
    return Math.max(0, limit - usedToday.value)
  })
  const isUnlimited = computed(
    () => serverQuota.value?.unlimited ?? dailyLimit.value < 0,
  )
  const summaryLabel = computed(() => {
    if (isUnlimited.value) return '今日配额：不限'
    return `今日剩余 ${remainingToday.value} / ${dailyLimit.value}`
  })
  const planQuotaHint = computed(() => dailyQuotaLabel(effectivePlan()))

  function clearBlockMessage() {
    blockMessage.value = ''
  }

  function resetLocal() {
    serverQuota.value = null
    clearBlockMessage()
  }

  function applyServerQuota(q: ServerQuota) {
    serverQuota.value = q
    const auth = useAuthStore()
    if (auth.user) {
      auth.setPlan(q.plan as PlanTier, { expireAt: q.expire_at })
    }
  }

  async function refresh() {
    const auth = useAuthStore()
    if (!auth.isAuthenticated) {
      serverQuota.value = null
      return
    }
    loading.value = true
    try {
      serverQuota.value = await fetchQuotaToday()
      if (auth.user) {
        auth.setPlan(serverQuota.value.plan as PlanTier, {
          expireAt: serverQuota.value.expire_at,
        })
      }
    } catch {
      /* 后端不可用时保持上次 */
    } finally {
      loading.value = false
    }
  }

  function assertCanRun(step?: WorkflowStep): { ok: true } | { ok: false; reason: string } {
    const auth = useAuthStore()
    auth.ensurePlanNotExpired()

    if (ENFORCE_AUTH_FOR_RUN && !auth.isAuthenticated) {
      const reason = '请先登录后再运行工作流（MVP 已强制登录）'
      blockMessage.value = reason
      return { ok: false, reason }
    }

    const plan = effectivePlan()

    if (step && isAdvancedStep(step) && !hasCapability(plan, 'workflow.advanced')) {
      const reason = '该策略为高级策略，当前档位不可用。请升级 Pro / Team 后运行。'
      blockMessage.value = reason
      return { ok: false, reason }
    }

    if (serverQuota.value && !serverQuota.value.available && !serverQuota.value.unlimited) {
      const reason = `今日运行次数已用尽（${serverQuota.value.daily_limit} 次，${PLAN_RULES[plan].name}）。请升级会员或明日再试。`
      blockMessage.value = reason
      return { ok: false, reason }
    }

    const limit = dailyLimit.value
    if (!serverQuota.value && limit >= 0 && usedToday.value >= limit) {
      const reason = `今日运行次数已用尽（${limit} 次，${PLAN_RULES[plan].name}）。请升级会员或明日再试。`
      blockMessage.value = reason
      return { ok: false, reason }
    }

    clearBlockMessage()
    return { ok: true }
  }

  function canRunAdvanced(): boolean {
    return hasCapability(effectivePlan(), 'workflow.advanced')
  }

  function canExportReports(): boolean {
    return hasCapability(effectivePlan(), 'report.export')
  }

  function assertCanExport(): { ok: true } | { ok: false; reason: string } {
    const auth = useAuthStore()
    auth.ensurePlanNotExpired()
    if (canExportReports()) {
      clearBlockMessage()
      return { ok: true }
    }
    const reason = '报告导出为 Pro / Team 权益。请升级会员后复制或下载。'
    blockMessage.value = reason
    return { ok: false, reason }
  }

  /** 服务端计次；失败则拦截（不本地假扣） */
  async function consume(): Promise<{ ok: true } | { ok: false; reason: string }> {
    const auth = useAuthStore()
    if (!auth.isAuthenticated) {
      return { ok: false, reason: '请先登录' }
    }
    try {
      serverQuota.value = await consumeQuotaRun()
      clearBlockMessage()
      return { ok: true }
    } catch (e) {
      const reason = e instanceof Error ? e.message : String(e)
      blockMessage.value = reason
      await refresh()
      return { ok: false, reason }
    }
  }

  return {
    serverQuota,
    loading,
    usedToday,
    dailyLimit,
    remainingToday,
    isUnlimited,
    summaryLabel,
    planQuotaHint,
    blockMessage,
    clearBlockMessage,
    resetLocal,
    applyServerQuota,
    refresh,
    assertCanRun,
    consume,
    effectivePlan,
    canRunAdvanced,
    canExportReports,
    assertCanExport,
  }
})
