import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { type PlanTier, useAuthStore } from '@/stores/auth'
import { PLAN_RULES } from '@/config/businessRules'
import { useQuotaStore } from '@/stores/quota'
import { apiSetMembershipFree } from '@/api/membership'
import {
  createPaymentOrder,
  listPaymentOrders,
  simulatePaymentCallbackFail,
  simulatePaymentPay,
  type PaymentChannelId,
  type ServerPaymentOrder,
} from '@/api/payment'

export type OrderStatus = 'paid' | 'pending' | 'cancelled' | 'failed'
export type BillingChannel = PaymentChannelId | 'local'

export interface BillingOrder {
  id: string
  plan: PlanTier
  amountYuan: number
  status: OrderStatus
  paidAt: string
  channel: BillingChannel
  periodDays?: number
}

export const PLAN_CATALOG = (['free', 'pro', 'team'] as PlanTier[]).map((id) => {
  const r = PLAN_RULES[id]
  return {
    id: r.id,
    name: r.name,
    priceLabel: r.priceLabel,
    amountYuan: r.priceYuanPerMonth,
    purchasable: r.purchasable,
    features: r.features,
    cta: r.cta,
    dailyRunQuota: r.dailyRunQuota,
  }
})

function fromServerOrder(order: ServerPaymentOrder): BillingOrder {
  return {
    id: order.id,
    plan: order.plan as PlanTier,
    amountYuan: order.amount_yuan,
    status: order.status,
    paidAt: order.paid_at || order.created_at,
    channel: order.channel,
    periodDays: order.period_days,
  }
}

export const useBillingStore = defineStore('billing', () => {
  const orders = ref<BillingOrder[]>([])

  const sortedOrders = computed(() =>
    [...orders.value].sort((a, b) => (a.paidAt < b.paidAt ? 1 : -1)),
  )

  async function refreshOrders() {
    try {
      const list = await listPaymentOrders()
      orders.value = list.map(fromServerOrder)
    } catch {
      /* ignore */
    }
  }

  async function applyPaidAndSync(serverOrder: ServerPaymentOrder) {
    const auth = useAuthStore()
    const quota = useQuotaStore()
    if (serverOrder.status !== 'paid') {
      return { ok: false as const, reason: '订单未支付' }
    }
    await auth.bootstrap()
    await quota.refresh()
    await refreshOrders()
    return { ok: true as const, order: fromServerOrder(serverOrder) }
  }

  async function switchToFree(): Promise<{ ok: boolean; reason?: string }> {
    const auth = useAuthStore()
    const quota = useQuotaStore()
    if (!auth.user) return { ok: false, reason: '请先登录' }
    try {
      await apiSetMembershipFree()
      await auth.bootstrap()
      await quota.refresh()
      return { ok: true }
    } catch (e) {
      return { ok: false, reason: e instanceof Error ? e.message : String(e) }
    }
  }

  async function checkoutPro(channel: PaymentChannelId): Promise<{ ok: boolean; reason?: string }> {
    const auth = useAuthStore()
    if (!auth.user) return { ok: false, reason: '请先登录' }

    try {
      const created = await createPaymentOrder({
        plan: 'pro',
        channel,
      })
      orders.value = [fromServerOrder(created.order), ...orders.value.filter((o) => o.id !== created.order.id)]

      const paid = await simulatePaymentPay(created.order.id)
      const applied = await applyPaidAndSync(paid)
      if (!applied.ok) return applied
      return { ok: true }
    } catch (e) {
      return { ok: false, reason: e instanceof Error ? e.message : String(e) }
    }
  }

  /** 只下单，不回调——留下 pending 供 Admin 纠偏 */
  async function createProPending(
    channel: PaymentChannelId,
  ): Promise<{ ok: boolean; reason?: string; orderId?: string }> {
    const auth = useAuthStore()
    if (!auth.user) return { ok: false, reason: '请先登录' }
    try {
      const created = await createPaymentOrder({ plan: 'pro', channel })
      orders.value = [
        fromServerOrder(created.order),
        ...orders.value.filter((o) => o.id !== created.order.id),
      ]
      await refreshOrders()
      return { ok: true, orderId: created.order.id }
    } catch (e) {
      return { ok: false, reason: e instanceof Error ? e.message : String(e) }
    }
  }

  /** 下单后模拟渠道回调失败 → failed */
  async function createProThenFailCallback(
    channel: PaymentChannelId,
  ): Promise<{ ok: boolean; reason?: string; orderId?: string }> {
    const auth = useAuthStore()
    if (!auth.user) return { ok: false, reason: '请先登录' }
    try {
      const created = await createPaymentOrder({ plan: 'pro', channel })
      const failed = await simulatePaymentCallbackFail(created.order.id, channel)
      orders.value = [
        fromServerOrder(failed),
        ...orders.value.filter((o) => o.id !== failed.id),
      ]
      await refreshOrders()
      return {
        ok: true,
        orderId: failed.id,
        reason: `回调失败，订单 ${failed.id} 已标记 failed`,
      }
    } catch (e) {
      return { ok: false, reason: e instanceof Error ? e.message : String(e) }
    }
  }

  return {
    orders,
    sortedOrders,
    refreshOrders,
    switchToFree,
    checkoutPro,
    createProPending,
    createProThenFailCallback,
  }
})
