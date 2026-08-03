import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { dailyQuotaLabel, PLAN_RULES } from '@/config/businessRules'
import {
  apiLogin,
  apiMe,
  apiPatchMe,
  apiRegister,
  getToken,
  setToken,
  type ServerUser,
} from '@/api/auth'

export type PlanTier = 'free' | 'pro' | 'team'

export interface UserProfile {
  id: string
  nickname: string
  email: string
  phone: string
  avatarText: string
  plan: PlanTier
  inviteCode: string
  expireAt: string | null
  onboardingDone?: boolean
  persona?: string | null
  role?: string
}

const STORAGE_KEY = 'workflow-platform:auth:v1'

const PLAN_LABEL: Record<PlanTier, string> = {
  free: 'Free',
  pro: 'Pro',
  team: 'Team',
}

function fromServer(u: ServerUser): UserProfile {
  return {
    id: u.id,
    nickname: u.nickname,
    email: u.email,
    phone: u.phone || '',
    avatarText: u.avatar_text || '?',
    plan: (u.plan || 'free') as PlanTier,
    inviteCode: u.invite_code || '',
    expireAt: u.expire_at,
    onboardingDone: u.onboarding_done,
    persona: u.persona,
    role: u.role,
  }
}

function loadStored(): UserProfile | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as UserProfile
    if (!parsed?.id || !parsed?.email) return null
    return {
      ...parsed,
      expireAt: parsed.expireAt ?? null,
      plan: parsed.plan || 'free',
    }
  } catch {
    return null
  }
}

function persist(user: UserProfile | null) {
  if (!user) {
    localStorage.removeItem(STORAGE_KEY)
    return
  }
  localStorage.setItem(STORAGE_KEY, JSON.stringify(user))
}

function addDaysIso(from: Date, days: number) {
  const d = new Date(from)
  d.setDate(d.getDate() + days)
  return d.toISOString()
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserProfile | null>(loadStored())
  const bootstrapped = ref(false)
  const authError = ref('')

  const isAuthenticated = computed(() => !!user.value && !!getToken())
  const planLabel = computed(() =>
    user.value ? PLAN_LABEL[user.value.plan] : '—',
  )
  const quotaHint = computed(() =>
    user.value ? dailyQuotaLabel(user.value.plan) : dailyQuotaLabel('free'),
  )

  function applyUser(next: UserProfile | null) {
    user.value = next
    persist(next)
  }

  function applyServerUser(u: ServerUser) {
    applyUser(fromServer(u))
  }

  function ensurePlanNotExpired() {
    if (!user.value?.expireAt) return
    if (user.value.plan === 'free') return
    if (new Date(user.value.expireAt).getTime() > Date.now()) return
    applyUser({ ...user.value, plan: 'free', expireAt: null })
  }

  ensurePlanNotExpired()

  async function bootstrap() {
    const token = getToken()
    if (!token) {
      // 无 token 则清掉残留本地用户，避免假登录
      if (user.value) applyUser(null)
      bootstrapped.value = true
      return
    }
    try {
      const u = await apiMe()
      applyUser(fromServer(u))
    } catch {
      setToken(null)
      applyUser(null)
    } finally {
      bootstrapped.value = true
    }
  }

  async function login(email: string, password: string) {
    authError.value = ''
    const { token, user: u } = await apiLogin({ email, password })
    setToken(token)
    applyUser(fromServer(u))
  }

  async function register(input: {
    email: string
    password: string
    nickname?: string
    phone?: string
  }) {
    authError.value = ''
    const { token, user: u } = await apiRegister(input)
    setToken(token)
    applyUser(fromServer(u))
  }

  async function updateProfile(patch: Partial<Pick<UserProfile, 'nickname' | 'email' | 'phone'>>) {
    if (!user.value) return
    // 邮箱 MVP 不允许改
    const u = await apiPatchMe({
      nickname: patch.nickname,
      phone: patch.phone,
    })
    applyUser(fromServer(u))
  }

  /** 同步会员展示（以服务端为准；也可本地临时覆盖） */
  function setPlan(
    plan: PlanTier,
    opts?: { periodDays?: number; expireAt?: string | null },
  ) {
    if (!user.value) return
    let expireAt: string | null
    if (opts && 'expireAt' in opts) {
      expireAt = opts.expireAt ?? null
    } else {
      const period = opts?.periodDays ?? PLAN_RULES[plan].periodDays
      expireAt = plan === 'free' || !period ? null : addDaysIso(new Date(), period)
    }
    applyUser({ ...user.value, plan, expireAt })
  }

  function logout() {
    setToken(null)
    applyUser(null)
    void import('./quota').then(({ useQuotaStore }) => {
      useQuotaStore().resetLocal()
    })
  }

  return {
    user,
    bootstrapped,
    authError,
    isAuthenticated,
    planLabel,
    quotaHint,
    bootstrap,
    login,
    register,
    updateProfile,
    applyServerUser,
    setPlan,
    ensurePlanNotExpired,
    logout,
  }
})

export { PLAN_LABEL }
