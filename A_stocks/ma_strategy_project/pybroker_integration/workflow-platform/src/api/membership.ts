import { getToken } from '@/api/auth'

export type ServerQuota = {
  user_id: string
  day: string
  plan: string
  expire_at: string | null
  used_runs: number
  bonus_runs: number
  daily_limit: number
  remaining: number | null
  unlimited: boolean
  available: boolean
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
  return `HTTP ${res.status}`
}

export async function fetchQuotaToday(): Promise<ServerQuota> {
  const res = await fetch('/api/quota/today', { headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { quota: ServerQuota }
  return j.quota
}

export async function consumeQuotaRun(): Promise<ServerQuota> {
  const res = await fetch('/api/quota/consume', {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { quota: ServerQuota }
  return j.quota
}

export async function apiSetMembershipFree(): Promise<void> {
  const res = await fetch('/api/membership/set-free', {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({ confirm: true }),
  })
  if (!res.ok) throw new Error(await readError(res))
}
