import { getToken } from '@/api/auth'

export type PaymentChannelId = 'wechat' | 'alipay' | 'mock'
export type PaymentPlanId = 'free' | 'pro' | 'team'

export type ServerPaymentOrder = {
  id: string
  user_id: string
  plan: PaymentPlanId
  channel: PaymentChannelId
  amount_yuan: number
  period_days: number
  status: 'pending' | 'paid' | 'cancelled' | 'failed'
  created_at: string
  paid_at: string | null
  provider_ref: string | null
  provider?: string
}

export type PaymentChannel = {
  id: PaymentChannelId
  label: string
  mode: 'simulate' | 'native'
  hint: string
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

export async function fetchPaymentChannels(): Promise<PaymentChannel[]> {
  try {
    const res = await fetch('/api/payment/channels')
    if (!res.ok) throw new Error(await readError(res))
    const j = (await res.json()) as { channels?: PaymentChannel[] }
    return j.channels ?? []
  } catch {
    return [
      { id: 'mock', label: '演示支付', mode: 'simulate', hint: '后端未启动时的本地兜底' },
    ]
  }
}

export async function createPaymentOrder(input: {
  plan: PaymentPlanId
  channel: PaymentChannelId
}): Promise<{ order: ServerPaymentOrder; simulatePath: string }> {
  const res = await fetch('/api/payment/create', {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({
      plan: input.plan,
      channel: input.channel,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as {
    order: ServerPaymentOrder
    pay?: { simulate_path?: string }
  }
  return {
    order: j.order,
    simulatePath: j.pay?.simulate_path || `/api/payment/simulate-pay/${j.order.id}`,
  }
}

export async function getPaymentOrder(orderId: string): Promise<ServerPaymentOrder> {
  const res = await fetch(`/api/payment/order/${encodeURIComponent(orderId)}`, {
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { order: ServerPaymentOrder }
  return j.order
}

export async function listPaymentOrders(): Promise<ServerPaymentOrder[]> {
  const res = await fetch('/api/payment/orders', { headers: { ...authHeaders() } })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { orders: ServerPaymentOrder[] }
  return j.orders ?? []
}

export async function simulatePaymentPay(orderId: string): Promise<ServerPaymentOrder> {
  const res = await fetch(`/api/payment/simulate-pay/${encodeURIComponent(orderId)}`, {
    method: 'POST',
    headers: { ...authHeaders() },
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { order: ServerPaymentOrder }
  return j.order
}

/** 模拟支付渠道回调失败 → pending 变 failed */
export async function simulatePaymentCallbackFail(
  orderId: string,
  channel: PaymentChannelId,
): Promise<ServerPaymentOrder> {
  const res = await fetch(`/api/payment/callback/${encodeURIComponent(channel)}`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: JSON.stringify({
      order_id: orderId,
      success: false,
    }),
  })
  if (!res.ok) throw new Error(await readError(res))
  const j = (await res.json()) as { order: ServerPaymentOrder }
  return j.order
}
