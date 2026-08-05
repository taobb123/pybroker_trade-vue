import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { radarLimit } from '@/config/radarLimits'
import { useAuthStore } from '@/stores/auth'

export type WatchZoneStatus = 'waiting' | 'in_zone' | 'above'

export interface WatchItem {
  id: string
  opportunityId: string
  symbol: string
  name: string
  price: number | null
  idealLow: number | null
  idealHigh: number | null
  thesis: string
  risk: string
  stepId?: string
  addedAt: string
  note: string
}

const STORAGE_KEY = 'workflow-platform:watchlist:v1'
const HARD_MAX = 40

function zoneStatus(item: WatchItem): WatchZoneStatus {
  const { price, idealLow, idealHigh } = item
  if (price == null || idealLow == null || idealHigh == null) return 'waiting'
  if (price >= idealLow && price <= idealHigh) return 'in_zone'
  if (price > idealHigh) return 'above'
  return 'waiting'
}

export const WATCH_ZONE_LABEL: Record<WatchZoneStatus, string> = {
  waiting: '等待进入买入区',
  in_zone: '已进入理想买入区',
  above: '高于理想区',
}

function loadItems(): WatchItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw) as WatchItem[]
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function persist(items: WatchItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items.slice(0, HARD_MAX)))
}

export const useWatchlistStore = defineStore('watchlist', () => {
  const items = ref<WatchItem[]>(loadItems())
  const auth = useAuthStore()

  const count = computed(() => items.value.length)

  const planCap = computed(() => {
    const plan = auth.user?.plan ?? 'free'
    const lim = radarLimit(plan).maxWatchlist
    return lim < 0 ? HARD_MAX : lim
  })

  function has(opportunityId: string) {
    return items.value.some((i) => i.opportunityId === opportunityId)
  }

  function getZone(item: WatchItem): WatchZoneStatus {
    return zoneStatus(item)
  }

  function addFromOpportunity(input: {
    opportunityId: string
    symbol: string
    name: string
    price?: number
    idealLow?: number
    idealHigh?: number
    thesis: string
    risk: string
    stepId?: string
  }): { ok: true } | { ok: false; reason: string; upgrade?: boolean } {
    if (has(input.opportunityId)) {
      return { ok: false, reason: '已在观察池' }
    }
    const cap = planCap.value
    if (items.value.length >= cap) {
      return {
        ok: false,
        reason: `当前档位观察池上限 ${cap} 只。升级可扩大观察纪律容量。`,
        upgrade: true,
      }
    }
    const row: WatchItem = {
      id: `w-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
      opportunityId: input.opportunityId,
      symbol: input.symbol,
      name: input.name,
      price: input.price ?? null,
      idealLow: input.idealLow ?? null,
      idealHigh: input.idealHigh ?? null,
      thesis: input.thesis,
      risk: input.risk,
      stepId: input.stepId,
      addedAt: new Date().toISOString(),
      note: '',
    }
    items.value = [row, ...items.value]
    persist(items.value)
    return { ok: true }
  }

  function remove(id: string) {
    items.value = items.value.filter((i) => i.id !== id)
    persist(items.value)
  }

  function removeByOpportunity(opportunityId: string) {
    items.value = items.value.filter((i) => i.opportunityId !== opportunityId)
    persist(items.value)
  }

  function updateZone(
    id: string,
    patch: Partial<Pick<WatchItem, 'price' | 'idealLow' | 'idealHigh' | 'note'>>,
  ) {
    items.value = items.value.map((i) => (i.id === id ? { ...i, ...patch } : i))
    persist(items.value)
  }

  return {
    items,
    count,
    planCap,
    has,
    getZone,
    addFromOpportunity,
    remove,
    removeByOpportunity,
    updateZone,
  }
})
