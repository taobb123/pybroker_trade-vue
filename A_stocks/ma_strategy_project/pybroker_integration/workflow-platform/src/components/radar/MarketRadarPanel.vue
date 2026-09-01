<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Activity, RefreshCw } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { fetchMarketRadar } from '@/api/marketRadar'
import { LAMP_LABEL, POLL_MS } from '@/config/marketRadarRules'
import {
  barWidthPct,
  formatPct,
  lampClass,
  pctClass,
  type MarketRadarPayload,
  type RadarLamp,
  type RadarStock,
} from '@/domain/marketRadar'

const GROWTH_STEP_ID = 'growth_factor'
/** 与后端 GROWTH_GROUPS 顺序一致；默认展开第一组 */
const GROWTH_GROUPS = ['M加', 'Q', '量能'] as const
const HIGHLIGHT_MS = 2500

const props = defineProps<{
  /** 父页刷新时递增，触发重新拉数 */
  tick?: number
}>()

const router = useRouter()

const loading = ref(false)
const payload = ref<MarketRadarPayload | null>(null)
const error = ref('')
const clock = ref('')
const activeGroup = ref<string>(GROWTH_GROUPS[0])
const watchlistEl = ref<HTMLElement | null>(null)
const highlightKey = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null
let clockTimer: ReturnType<typeof setInterval> | null = null
let highlightTimer: ReturnType<typeof setTimeout> | null = null

const emptyUniverse = computed(() => (payload.value?.universe?.count ?? 0) === 0)
const sessionClosed = computed(() => payload.value?.session === 'closed')
const sectorMaxAbs = computed(() => {
  const vals = (payload.value?.sectors ?? []).map((s) => Math.abs(s.pct ?? 0))
  return Math.max(3, ...vals, 0)
})

const stocksByGroup = computed(() => {
  const map = new Map<string, RadarStock[]>()
  for (const g of GROWTH_GROUPS) map.set(g, [])
  for (const st of payload.value?.stocks ?? []) {
    const g = st.group || ''
    if (!map.has(g)) map.set(g, [])
    map.get(g)!.push(st)
  }
  return map
})

const groupTabs = computed(() =>
  GROWTH_GROUPS.map((g) => ({
    name: g,
    count: stocksByGroup.value.get(g)?.length ?? 0,
  })),
)

const activeGroupStocks = computed(
  () => stocksByGroup.value.get(activeGroup.value) ?? [],
)

/** 全池去重后按强度取前三；随 payload 刷新重算 */
const strongestTop3 = computed(() => {
  const best = new Map<string, RadarStock>()
  for (const st of payload.value?.stocks ?? []) {
    if (st.strength == null) continue
    const prev = best.get(st.symbol)
    if (!prev || (prev.strength ?? -Infinity) < st.strength) {
      best.set(st.symbol, st)
    }
  }
  return [...best.values()]
    .sort((a, b) => (b.strength ?? 0) - (a.strength ?? 0))
    .slice(0, 3)
})

const strongestSummary = computed(() => {
  const list = strongestTop3.value
  if (!list.length) return ''
  return list
    .map((st) => `${st.name || st.symbol} ${st.symbol}(${st.strength})`)
    .join(' › ')
})

function stockRowKey(st: Pick<RadarStock, 'group' | 'symbol'>) {
  return `${st.group ?? ''}::${st.symbol}`
}

function groupOrder(group: string | null) {
  const i = GROWTH_GROUPS.indexOf(group as (typeof GROWTH_GROUPS)[number])
  return i >= 0 ? i : GROWTH_GROUPS.length
}

/** 该板块自选中强度最高的一只（并列时取更靠前的分组） */
function findStrongestInSector(sectorCode: string): RadarStock | null {
  const matches = (payload.value?.stocks ?? []).filter(
    (st) => st.sectorCode === sectorCode,
  )
  if (!matches.length) return null
  return matches.reduce((best, st) => {
    const bs = best.strength ?? -Infinity
    const ss = st.strength ?? -Infinity
    if (ss !== bs) return ss > bs ? st : best
    return groupOrder(st.group) < groupOrder(best.group) ? st : best
  })
}

function setHighlight(key: string) {
  highlightKey.value = key
  if (highlightTimer) clearTimeout(highlightTimer)
  highlightTimer = setTimeout(() => {
    highlightKey.value = ''
    highlightTimer = null
  }, HIGHLIGHT_MS)
}

async function jumpToSectorStock(sectorCode: string) {
  const target = findStrongestInSector(sectorCode)
  if (!target?.group) return
  activeGroup.value = target.group
  const key = stockRowKey(target)
  setHighlight(key)
  await nextTick()
  await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
  watchlistEl.value?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  const row = watchlistEl.value?.querySelector(
    `[data-radar-stock="${CSS.escape(key)}"]`,
  ) as HTMLElement | null
  row?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
}

function tickClock() {
  const now = new Date()
  clock.value = now.toLocaleTimeString('zh-CN', { hour12: false })
}

async function load(force = false) {
  loading.value = true
  error.value = ''
  try {
    const next = await fetchMarketRadar({ refresh: force })
    payload.value = next
    if (!next.ok) {
      error.value = next.error || '市场雷达暂不可用'
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : '后端未启动或网络异常'
  } finally {
    loading.value = false
  }
}

function lampBadge(lamp: RadarLamp) {
  return lampClass(lamp)
}

function openGrowthWorkflow() {
  void router.push({ path: '/workflows', query: { step: GROWTH_STEP_ID } })
}

onMounted(() => {
  tickClock()
  clockTimer = setInterval(tickClock, 1000)
  void load()
  pollTimer = setInterval(() => {
    if (document.hidden) return
    if (payload.value?.session !== 'open') return
    void load()
  }, POLL_MS)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (clockTimer) clearInterval(clockTimer)
  if (highlightTimer) clearTimeout(highlightTimer)
})

watch(
  () => props.tick,
  (n, prev) => {
    if (n && n !== prev) void load(true)
  },
)

defineExpose({ refresh: load })
</script>

<template>
  <section class="space-y-4 rounded-xl border bg-muted/20 p-4">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div>
        <p class="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          盘中市场雷达
        </p>
        <h3 class="mt-0.5 text-base font-semibold">成长因子自选 · 相对板块与大盘</h3>
        <p class="mt-0.5 max-w-xl text-[11px] leading-relaxed text-muted-foreground">
          工作流「按成长因子排序」仅 M加 / Q / 量能 各前 5（不足则全列）→ 申万行业分类 → 沪深300。盘中行情来自东方财富实时，约 1 分钟刷新，非投资建议。
        </p>
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <span class="tabular-nums text-xs text-muted-foreground">{{ clock }}</span>
        <Badge
          v-if="payload"
          :class="
            sessionClosed
              ? 'border-amber-300/80 text-amber-950 dark:text-amber-100'
              : 'border-transparent bg-emerald-600 text-white hover:bg-emerald-600'
          "
          variant="outline"
        >
          {{ sessionClosed ? '非交易时段' : '盘中' }}
        </Badge>
        <Badge v-if="payload?.cached" variant="outline" class="text-muted-foreground">缓存</Badge>
        <Button size="sm" variant="outline" :disabled="loading" @click="load(true)">
          <RefreshCw class="size-3.5" :class="loading && 'animate-spin'" />
          刷新
        </Button>
      </div>
    </div>

    <p v-if="payload?.asOf || payload?.universe?.label || payload?.source" class="text-[11px] text-muted-foreground">
      <template v-if="payload?.asOf">数据时间 {{ payload.asOf }}</template>
      <template v-if="payload?.universe?.label">
        <template v-if="payload?.asOf"> · </template>{{ payload.universe.label }}
      </template>
      <template v-if="payload?.source">
        <template v-if="payload?.asOf || payload?.universe?.label"> · </template>源 {{ payload.source }}
      </template>
    </p>

    <p
      v-if="payload?.universe?.hint"
      class="rounded-md border border-amber-200/70 bg-amber-50/60 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-950/80 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-100/80"
    >
      {{ payload.universe.hint }}
    </p>

    <p
      v-if="payload?.ok && payload?.sectorStale !== 'daily'"
      class="rounded-md border border-emerald-200/70 bg-emerald-50/50 px-2.5 py-1.5 text-[11px] leading-relaxed text-emerald-950/80 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-100/80"
    >
      板块盘中涨跌由申万二级成分股现价等权合成（名称仍固定申万，不跟东财概念板）。指数和个股走腾讯或东财现价。
    </p>

    <p
      v-if="payload?.sectorStale === 'daily'"
      class="rounded-md border border-amber-200/70 bg-amber-50/60 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-950/80 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-100/80"
    >
      申万成分实时合成暂未取到，板块暂回退申万日频收盘（非盘中）。个股仍尽量用参考现价。
    </p>

    <div
      v-if="error"
      class="rounded-md border border-dashed border-red-200 bg-red-50/50 px-3 py-2 text-sm text-red-800 dark:border-red-900/50 dark:bg-red-950/20 dark:text-red-100"
    >
      {{ error }}
    </div>

    <div class="grid gap-4 lg:grid-cols-2">
      <div class="space-y-2">
        <p class="text-xs font-medium text-foreground">大盘</p>
        <ul v-if="payload?.indexes.length" class="space-y-1.5">
          <li
            v-for="idx in payload.indexes"
            :key="idx.tsCode"
            class="flex items-center justify-between gap-3 rounded-lg border bg-background/80 px-3 py-2"
          >
            <span class="text-sm">{{ idx.label }}</span>
            <div class="flex items-center gap-2">
              <span class="tabular-nums text-sm font-medium" :class="pctClass(idx.pct)">
                {{ formatPct(idx.pct) }}
              </span>
              <Badge :class="lampBadge(idx.lamp)" class="min-w-10 justify-center">
                {{ LAMP_LABEL[idx.lamp] }}
              </Badge>
            </div>
          </li>
        </ul>
        <p v-else-if="loading" class="text-sm text-muted-foreground">正在读取指数…</p>
        <p v-else class="text-sm text-muted-foreground">暂无大盘数据</p>
      </div>

      <div class="space-y-2">
        <p class="text-xs font-medium text-foreground">成长因子板块</p>
        <ul v-if="payload?.sectors.length" class="space-y-2">
          <li
            v-for="sec in payload.sectors"
            :key="sec.code"
            class="space-y-1 rounded-md px-1.5 py-1 -mx-1.5 cursor-pointer transition-colors hover:bg-background/80"
            role="button"
            tabindex="0"
            :title="`定位该板块强度最高的自选股`"
            @click="jumpToSectorStock(sec.code)"
            @keydown.enter.prevent="jumpToSectorStock(sec.code)"
            @keydown.space.prevent="jumpToSectorStock(sec.code)"
          >
            <div class="flex items-center justify-between gap-2 text-sm">
              <span class="truncate">
                {{ sec.name }}
                <span class="text-[11px] text-muted-foreground">{{ sec.stockCount }} 只</span>
              </span>
              <span class="tabular-nums font-medium" :class="pctClass(sec.pct)">
                {{ formatPct(sec.pct) }}
              </span>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-muted">
              <div
                class="h-full rounded-full"
                :class="(sec.pct ?? 0) >= 0 ? 'bg-emerald-600' : 'bg-red-500'"
                :style="{ width: `${barWidthPct(sec.pct, sectorMaxAbs)}%` }"
              />
            </div>
          </li>
        </ul>
        <div
          v-else
          class="rounded-lg border border-dashed bg-background/60 px-3 py-6 text-center text-sm text-muted-foreground"
        >
          <p v-if="emptyUniverse">请先运行「按成长因子排序」，生成 M加 / Q / 量能 名单。</p>
          <p v-else-if="loading">正在映射申万行业…</p>
          <p v-else>暂无板块数据</p>
          <Button
            v-if="emptyUniverse"
            size="sm"
            variant="outline"
            class="mt-2"
            @click="openGrowthWorkflow"
          >
            打开成长因子工作流
          </Button>
        </div>
      </div>
    </div>

    <div ref="watchlistEl" class="space-y-2 scroll-mt-4">
      <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
        <div class="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
          <p class="text-xs font-medium text-foreground">自选股</p>
          <p
            v-if="strongestSummary"
            class="min-w-0 truncate text-[11px] text-muted-foreground"
            :title="`最强前三（强度）· ${strongestSummary}`"
          >
            最强前三 · {{ strongestSummary }}
          </p>
        </div>
        <span class="shrink-0 text-[11px] text-muted-foreground">
          {{ payload?.stocks.length ?? 0 }} 只 · M加/Q/量能 各前5
        </span>
      </div>
      <Tabs v-if="payload?.stocks.length" v-model="activeGroup" class="w-full">
        <TabsList class="flex h-auto w-full flex-wrap justify-start gap-1">
          <TabsTrigger
            v-for="tab in groupTabs"
            :key="tab.name"
            :value="tab.name"
            class="px-2.5 text-xs"
          >
            {{ tab.name }}
            <span class="ml-1 tabular-nums text-muted-foreground">{{ tab.count }}</span>
          </TabsTrigger>
        </TabsList>
        <TabsContent
          v-for="tab in groupTabs"
          :key="tab.name"
          :value="tab.name"
          class="mt-2"
        >
          <ul v-if="activeGroupStocks.length" class="space-y-1.5">
            <li
              v-for="st in activeGroupStocks"
              :key="`${st.group}-${st.symbol}`"
              :data-radar-stock="stockRowKey(st)"
              class="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-background/80 px-3 py-2 transition-colors"
              :class="
                highlightKey === stockRowKey(st) &&
                'border-amber-400/80 bg-amber-50/80 ring-2 ring-amber-300/60 dark:bg-amber-950/30 dark:ring-amber-700/50'
              "
            >
              <div class="min-w-0">
                <p class="truncate text-sm font-medium">
                  <Badge v-if="st.group" variant="outline" class="mr-1.5 align-middle">
                    {{ st.group }}{{ st.rank != null ? ` #${st.rank}` : '' }}
                  </Badge>
                  {{ st.name }}
                  <span class="ml-1 font-normal tabular-nums text-muted-foreground">{{ st.symbol }}</span>
                </p>
                <p class="text-[11px] text-muted-foreground">
                  {{ st.sectorName || st.industry || '未映射板块' }}
                  <template v-if="st.sectorPct != null"> {{ formatPct(st.sectorPct) }}</template>
                </p>
              </div>
              <div class="flex flex-wrap items-center gap-2">
                <span class="tabular-nums text-sm font-semibold" :class="pctClass(st.pct)">
                  {{ formatPct(st.pct) }}
                </span>
                <span class="tabular-nums text-[11px] text-muted-foreground">
                  强度 {{ st.strength ?? '—' }}
                </span>
                <Badge :class="lampBadge(st.lamp)" class="min-w-10 justify-center">
                  {{ LAMP_LABEL[st.lamp] }}
                </Badge>
              </div>
            </li>
          </ul>
          <p v-else class="rounded-lg border border-dashed bg-background/60 px-3 py-6 text-center text-sm text-muted-foreground">
            「{{ tab.name }}」暂无标的，请确认桌面已同步并运行成长排序。
          </p>
        </TabsContent>
      </Tabs>
      <div
        v-else
        class="flex flex-col items-center gap-2 rounded-xl border border-dashed bg-background/60 px-6 py-8 text-center"
      >
        <div class="flex size-10 items-center justify-center rounded-full bg-muted">
          <Activity class="size-5 text-muted-foreground" />
        </div>
        <p class="text-sm font-medium">还没有成长因子名单</p>
        <p class="max-w-sm text-[11px] text-muted-foreground">
          盘中雷达盯工作流「按成长因子排序」的 M加 / Q / 量能 各前五（Tab 切换），不足五只则全列，不使用观察池。
        </p>
        <Button size="sm" variant="outline" @click="openGrowthWorkflow">
          运行按成长因子排序
        </Button>
      </div>
    </div>

    <div class="space-y-2">
      <p class="text-xs font-medium text-foreground">市场异动</p>
      <ul v-if="payload?.alerts.length" class="space-y-1.5">
        <li
          v-for="(al, i) in payload.alerts"
          :key="`${al.kind}-${al.code}-${i}`"
          class="rounded-lg border bg-background/80 px-3 py-2 text-sm"
        >
          {{ al.message }}
        </li>
      </ul>
      <p v-else class="text-sm text-muted-foreground">
        {{ emptyUniverse ? '生成成长因子名单后显示放量与跑输板块。' : '当前无放量或跑输板块提示。' }}
      </p>
    </div>
  </section>
</template>
