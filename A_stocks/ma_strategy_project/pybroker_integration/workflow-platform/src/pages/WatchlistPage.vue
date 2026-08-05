<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Bookmark, Crosshair } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { DISCLAIMER } from '@/config/opportunityRules'
import {
  useWatchlistStore,
  WATCH_ZONE_LABEL,
  type WatchItem,
  type WatchZoneStatus,
} from '@/stores/watchlist'

const store = useWatchlistStore()
const router = useRouter()

const sorted = computed(() => {
  const order: Record<WatchZoneStatus, number> = { in_zone: 0, waiting: 1, above: 2 }
  return [...store.items].sort(
    (a, b) => order[store.getZone(a)] - order[store.getZone(b)],
  )
})

function zoneBadgeClass(status: WatchZoneStatus) {
  if (status === 'in_zone') return 'bg-emerald-600 text-white hover:bg-emerald-600'
  if (status === 'above') return ''
  return ''
}

function openResearch(item: WatchItem) {
  if (!item.stepId) {
    void router.push('/workflows')
    return
  }
  void router.push({ path: '/workflows', query: { step: item.stepId } })
}

function openReport(item: WatchItem) {
  if (!item.stepId) {
    void router.push('/reports')
    return
  }
  void router.push({ path: '/reports', query: { step: item.stepId } })
}

function onPriceInput(item: WatchItem, ev: Event) {
  const v = Number((ev.target as HTMLInputElement).value)
  store.updateZone(item.id, { price: Number.isFinite(v) ? v : null })
}

function onLowInput(item: WatchItem, ev: Event) {
  const v = Number((ev.target as HTMLInputElement).value)
  store.updateZone(item.id, { idealLow: Number.isFinite(v) ? v : null })
}

function onHighInput(item: WatchItem, ev: Event) {
  const v = Number((ev.target as HTMLInputElement).value)
  store.updateZone(item.id, { idealHigh: Number.isFinite(v) ? v : null })
}
</script>

<template>
  <div class="space-y-6">
    <section class="space-y-2">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            观察池
          </p>
          <h2 class="text-xl font-semibold tracking-tight sm:text-2xl">
            等待价格进入理想区
          </h2>
          <p class="mt-1 max-w-xl text-sm text-muted-foreground">
            巴菲特最重要的纪律：不是每天买，而是等好球。未进入买入区前，默认状态是等待。
            当前档位上限 {{ store.planCap }} 只。
          </p>
        </div>
        <Button size="sm" variant="outline" @click="router.push('/')">
          <Crosshair class="size-3.5" />
          回机会雷达
        </Button>
      </div>
      <p class="text-[11px] text-muted-foreground">{{ DISCLAIMER }}</p>
    </section>

    <div
      v-if="!sorted.length"
      class="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-muted/20 px-6 py-14 text-center"
    >
      <div class="flex size-12 items-center justify-center rounded-full bg-muted">
        <Bookmark class="size-6 text-muted-foreground" />
      </div>
      <div class="space-y-1">
        <p class="text-base font-semibold">观察池为空</p>
        <p class="max-w-sm text-sm text-muted-foreground">
          从机会雷达把标的加入这里，设定理想买入区，用等待对抗冲动。
        </p>
      </div>
      <Button size="sm" @click="router.push('/')">去发现好球</Button>
    </div>

    <ul v-else class="space-y-3">
      <li
        v-for="item in sorted"
        :key="item.id"
        class="rounded-xl border bg-card p-4 shadow-sm"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2">
              <h3 class="text-base font-semibold">
                {{ item.name }}
                <span class="font-mono text-sm font-normal text-muted-foreground">
                  {{ item.symbol }}
                </span>
              </h3>
              <Badge
                :variant="store.getZone(item) === 'in_zone' ? 'default' : 'secondary'"
                :class="zoneBadgeClass(store.getZone(item))"
              >
                {{ WATCH_ZONE_LABEL[store.getZone(item)] }}
              </Badge>
            </div>
            <p class="mt-1 text-sm text-muted-foreground">{{ item.thesis }}</p>
            <p class="mt-0.5 text-xs text-muted-foreground">风险：{{ item.risk }}</p>
          </div>
        </div>

        <div class="mt-4 grid gap-3 sm:grid-cols-3">
          <label class="space-y-1 text-xs">
            <span class="text-muted-foreground">现价</span>
            <input
              type="number"
              step="any"
              class="flex h-9 w-full rounded-md border bg-background px-3 text-sm tabular-nums"
              :value="item.price ?? ''"
              @change="onPriceInput(item, $event)"
            >
          </label>
          <label class="space-y-1 text-xs">
            <span class="text-muted-foreground">理想区下限</span>
            <input
              type="number"
              step="any"
              class="flex h-9 w-full rounded-md border bg-background px-3 text-sm tabular-nums"
              :value="item.idealLow ?? ''"
              @change="onLowInput(item, $event)"
            >
          </label>
          <label class="space-y-1 text-xs">
            <span class="text-muted-foreground">理想区上限</span>
            <input
              type="number"
              step="any"
              class="flex h-9 w-full rounded-md border bg-background px-3 text-sm tabular-nums"
              :value="item.idealHigh ?? ''"
              @change="onHighInput(item, $event)"
            >
          </label>
        </div>

        <div class="mt-4 flex flex-wrap gap-2">
          <Button size="sm" variant="outline" @click="openResearch(item)">
            打开研究工作流
          </Button>
          <Button size="sm" variant="outline" @click="openReport(item)">
            查看相关报告
          </Button>
          <Button size="sm" variant="ghost" @click="store.remove(item.id)">
            移出观察池
          </Button>
        </div>
      </li>
    </ul>
  </div>
</template>
