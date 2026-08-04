import { getToken } from '@/api/auth'
import type { ServerUser } from '@/api/auth'
import type { ServerQuota } from '@/api/membership'
import type { OnboardingPersonaId } from '@/config/businessRules'
import { apiUrl } from '@/config/apiBase'

export type OnboardingStatus = {
  done: boolean
  persona: OnboardingPersonaId | null
  bonus_runs: number
  recommended_step_id: string
  recommended_title: string
  personas: { id: OnboardingPersonaId; label: string; hint: string }[]
}

export type OnboardingCompleteResult = OnboardingStatus & {
  already_done: boolean
  user: ServerUser
  quota: ServerQuota
}

function authHeaders(): HeadersInit {
  const t = getToken()
  return {
    'Content-Type': 'application/json',
    ...(t ? { Authorization: `Bearer ${t}` } : {}),
  }
}

async function readError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: string }
    if (typeof j.detail === 'string') return j.detail
  } catch {
    /* ignore */
  }
  if (res.status === 404) return '接口不存在（404）。请重启 workflow_server'
  return `HTTP ${res.status}`
}

export async function fetchOnboardingStatus(): Promise<OnboardingStatus> {
  const res = await fetch(apiUrl('/api/onboarding/status'), { headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as OnboardingStatus & { ok?: boolean }
  return j
}

export async function completeOnboarding(input: {
  persona?: OnboardingPersonaId | null
  skipPersona?: boolean
}): Promise<OnboardingCompleteResult> {
  const res = await fetch(apiUrl('/api/onboarding/complete'), {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({
      persona: input.skipPersona ? null : input.persona ?? null,
      skip_persona: !!input.skipPersona,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  return (await res.json()) as OnboardingCompleteResult
}
