import { getToken } from '@/api/auth'
import { apiUrl } from '@/config/apiBase'

export type EventName =
  | 'page_view'
  | 'run_strategy'
  | 'export_report'
  | 'click_upgrade'
  | 'payment_success'

export type FunnelStep = {
  key: string
  label: string
  count: number
}

function authHeaders(): HeadersInit {
  const t = getToken()
  return {
    'Content-Type': 'application/json',
    ...(t ? { Authorization: `Bearer ${t}` } : {}),
  }
}

/** 埋点：失败静默，不阻断业务 */
export function trackEvent(eventName: EventName, props?: Record<string, unknown>): void {
  void fetch(apiUrl('/api/events/track'), {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({ event_name: eventName, props: props ?? {} }),
  }).catch(() => {
    /* ignore */
  })
}

export async function fetchFunnel(): Promise<FunnelStep[]> {
  const res = await fetch(apiUrl('/api/events/funnel'), { headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(`funnel ${res.status}`)
  const j = (await res.json()) as { steps?: FunnelStep[] }
  return j.steps ?? []
}
