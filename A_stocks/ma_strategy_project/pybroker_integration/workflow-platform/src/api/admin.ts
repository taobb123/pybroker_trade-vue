import { getToken } from '@/api/auth'
import type { ServerUser } from '@/api/auth'
import type { ServerPaymentOrder } from '@/api/payment'
import type { ServerQuota } from '@/api/membership'
import type { PlanTier } from '@/stores/auth'
import { apiUrl } from '@/config/apiBase'

export type AdminUserRow = ServerUser & {
  today_used: number
  today_bonus: number
  today_remaining: number | null
  daily_limit: number
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

export async function adminListUsers(): Promise<AdminUserRow[]> {
  const res = await fetch(apiUrl('/api/admin/users'), { headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { users: AdminUserRow[] }
  return j.users ?? []
}

export async function adminSetStatus(
  userId: string,
  status: 'active' | 'disabled',
): Promise<void> {
  const res = await fetch(apiUrl(`/api/admin/users/${encodeURIComponent(userId)}/status`), {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({ status }),
  })
  if (!res.ok) throw new Error(await readError(res))
}

export async function adminSetMembership(
  userId: string,
  plan: PlanTier,
  periodDays?: number,
): Promise<void> {
  const res = await fetch(apiUrl(`/api/admin/users/${encodeURIComponent(userId)}/membership`), {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({ plan, period_days: periodDays ?? null }),
  })
  if (!res.ok) throw new Error(await readError(res))
}

export async function adminAddBonus(userId: string, n = 3): Promise<ServerQuota> {
  const res = await fetch(apiUrl(`/api/admin/users/${encodeURIComponent(userId)}/bonus`), {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({ n }),
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { quota: ServerQuota }
  return j.quota
}

export async function adminResetOnboarding(userId: string): Promise<void> {
  const res = await fetch(
    apiUrl(`/api/admin/users/${encodeURIComponent(userId)}/reset-onboarding`),
    { method: 'POST', headers: { ...authHeaders() } },
  )
  if (!res.ok) throw new Error(await readError(res))
}

export async function adminListOrders(status?: string): Promise<ServerPaymentOrder[]> {
  const q = status ? `?status=${encodeURIComponent(status)}` : ''
  const res = await fetch(apiUrl(`/api/admin/orders${q}`), { headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { orders: ServerPaymentOrder[] }
  return j.orders ?? []
}

export async function adminOrderAction(
  orderId: string,
  action: 'mark_paid' | 'cancel',
): Promise<ServerPaymentOrder> {
  const res = await fetch(apiUrl(`/api/admin/orders/${encodeURIComponent(orderId)}/action`), {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({ action }),
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { order: ServerPaymentOrder }
  return j.order
}
