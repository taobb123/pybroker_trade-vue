import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { type PlanTier, useAuthStore } from '@/stores/auth'

export type OrderStatus = 'paid' | 'pending' | 'cancelled'

export interface BillingOrder {
  id: string
  plan: PlanTier
  amountYuan: number
  status: OrderStatus
  paidAt: string
  channel: 'mock'
}

const ORDERS_KEY = 'workflow-platform:billing-orders:v1'

export const PLAN_CATALOG: Array<{
  id: PlanTier
  name: string
  priceLabel: string
  amountYuan: number
  purchasable: boolean
  features: string[]
  cta: string
}> = [
  {
    id: 'free',
    name: 'Free',
    priceLabel: '¥0',
    amountYuan: 0,
    purchasable: true,
    features: ['基础工作流', '每天有限次数', '本地运行历史'],
    cta: '使用 Free',
  },
  {
    id: 'pro',
    name: 'Pro',
    priceLabel: '¥39 / 月',
    amountYuan: 39,
    purchasable: true,
    features: ['更高运行次数', '高级策略', '云端保存（预留）'],
    cta: '升级 Pro',
  },
  {
    id: 'team',
    name: 'Team',
    priceLabel: '联系客服',
    amountYuan: 0,
    purchasable: false,
    features: ['席位协作（预留）', '统一账单', '优先支持'],
    cta: '联系客服',
  },
]

function loadOrders(): BillingOrder[] {
  try {
    const raw = localStorage.getItem(ORDERS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as BillingOrder[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function persistOrders(list: BillingOrder[]) {
  localStorage.setItem(ORDERS_KEY, JSON.stringify(list))
}

function orderId() {
  const t = new Date()
  const stamp = [
    t.getFullYear(),
    String(t.getMonth() + 1).padStart(2, '0'),
    String(t.getDate()).padStart(2, '0'),
    String(t.getHours()).padStart(2, '0'),
    String(t.getMinutes()).padStart(2, '0'),
    String(t.getSeconds()).padStart(2, '0'),
  ].join('')
  return `ORD-${stamp}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`
}

export const useBillingStore = defineStore('billing', () => {
  const orders = ref<BillingOrder[]>(loadOrders())

  const sortedOrders = computed(() =>
    [...orders.value].sort((a, b) => (a.paidAt < b.paidAt ? 1 : -1)),
  )

  function mockCheckout(plan: PlanTier): { ok: boolean; reason?: string } {
    const auth = useAuthStore()
    if (!auth.user) return { ok: false, reason: '请先登录' }

    const item = PLAN_CATALOG.find((p) => p.id === plan)
    if (!item) return { ok: false, reason: '未知套餐' }
    if (!item.purchasable) return { ok: false, reason: 'Team 请联系客服' }

    if (plan !== 'free') {
      const order: BillingOrder = {
        id: orderId(),
        plan,
        amountYuan: item.amountYuan,
        status: 'paid',
        paidAt: new Date().toISOString(),
        channel: 'mock',
      }
      orders.value = [order, ...orders.value]
      persistOrders(orders.value)
    }

    auth.setPlan(plan)
    return { ok: true }
  }

  return {
    orders,
    sortedOrders,
    mockCheckout,
  }
})
