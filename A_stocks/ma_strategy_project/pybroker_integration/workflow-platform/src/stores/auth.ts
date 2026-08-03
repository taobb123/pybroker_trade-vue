import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

export type PlanTier = 'free' | 'pro' | 'team'

export interface UserProfile {
  id: string
  nickname: string
  email: string
  phone: string
  /** 头像用首字/缩写，首期不接上传 */
  avatarText: string
  plan: PlanTier
  inviteCode: string
}

const STORAGE_KEY = 'workflow-platform:auth:v1'

const PLAN_LABEL: Record<PlanTier, string> = {
  free: 'Free',
  pro: 'Pro',
  team: 'Team',
}

function loadStored(): UserProfile | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return null
    const parsed = JSON.parse(raw) as UserProfile
    if (!parsed?.id || !parsed?.email) return null
    return parsed
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

function avatarFrom(name: string, email: string) {
  const base = (name || email || '?').trim()
  return base.slice(0, 1).toUpperCase() || '?'
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<UserProfile | null>(loadStored())

  const isAuthenticated = computed(() => !!user.value)
  const planLabel = computed(() =>
    user.value ? PLAN_LABEL[user.value.plan] : '—',
  )

  function mockLogin(input: { email?: string; phone?: string; nickname?: string }) {
    const email = (input.email || '').trim() || 'demo@workflow.local'
    const phone = (input.phone || '').trim()
    const nickname =
      (input.nickname || '').trim() ||
      email.split('@')[0] ||
      '演示用户'

    const next: UserProfile = {
      id: `mock-${Date.now()}`,
      nickname,
      email,
      phone,
      avatarText: avatarFrom(nickname, email),
      plan: 'free',
      inviteCode: 'WF-DEMO',
    }
    user.value = next
    persist(next)
  }

  function updateProfile(patch: Partial<Pick<UserProfile, 'nickname' | 'email' | 'phone'>>) {
    if (!user.value) return
    const next: UserProfile = {
      ...user.value,
      ...patch,
      nickname: patch.nickname?.trim() || user.value.nickname,
      email: patch.email?.trim() || user.value.email,
      phone: patch.phone !== undefined ? patch.phone.trim() : user.value.phone,
    }
    next.avatarText = avatarFrom(next.nickname, next.email)
    user.value = next
    persist(next)
  }

  function setPlan(plan: PlanTier) {
    if (!user.value) return
    const next: UserProfile = { ...user.value, plan }
    user.value = next
    persist(next)
  }

  function logout() {
    user.value = null
    persist(null)
  }

  return {
    user,
    isAuthenticated,
    planLabel,
    mockLogin,
    updateProfile,
    setPlan,
    logout,
  }
})

export { PLAN_LABEL }
