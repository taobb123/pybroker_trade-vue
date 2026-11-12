<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Bookmark, Crosshair } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { fetchDingpan, type DingpanItem } from '@/api/dingpan'
import { DISCLAIMER } from '@/config/opportunityRules'
import { dingpanSnapshots, dropDingpanSnapshot, saveDingpanSnapshots } from '@/stores/dingpanSnapshot'
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

function codeOf(symbol: string) {
  const digits = symbol.replace(/\D/g, '')
  return digits.length >= 6 ? digits.slice(0, 6) : ''
}

const symbolKey = computed(() =>
  [...new Set(sorted.value.map((item) => codeOf(item.symbol)).filter(Boolean))].join(','),
)

const pasted = ref('')

function codesFromText(text: string) {
  const seen = new Set<string>()
  const out: string[] = []
  for (const chunk of text.split(/[^0-9A-Za-z.]+/)) {
    const digits = chunk.replace(/\D/g, '')
    if (digits.length < 6) continue
    const code = digits.slice(0, 6)
    if (seen.has(code)) continue
    seen.add(code)
    out.push(code)
  }
  return out
}

const pastedCodes = computed(() => codesFromText(pasted.value))
const usingPaste = computed(() => pastedCodes.value.length > 0)
const querySymbols = computed(() =>
  (usingPaste.value ? pastedCodes.value : symbolKey.value.split(',').filter(Boolean)).join(','),
)

const nameBySymbol = computed(() => {
  const map = new Map<string, string>()
  for (const item of sorted.value) {
    const code = codeOf(item.symbol)
    if (code && item.name) map.set(code, item.name)
  }
  return map
})

const pendingPaste = computed(() => pastedCodes.value.filter((code) => !store.hasSymbol(code)))
const addNote = ref('')
const showingSaved = ref(false)
const dingpanRows = ref<DingpanItem[]>(dingpanSnapshots(symbolKey.value.split(',').filter(Boolean)))
const dingpanLoading = ref(false)
const dingpanError = ref('')
const dingpanNote = ref('')
const dingpanTruncated = ref(false)
showingSaved.value = dingpanRows.value.length > 0

function priceText(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toFixed(2)
}

function spanText(low: number | null | undefined, high: number | null | undefined) {
  if (low == null || high == null) return '—'
  return `${priceText(low)} – ${priceText(high)}`
}

function shortDate(value: string | null | undefined) {
  if (!value) return ''
  return value.length >= 10 ? value.slice(5) : value
}

function distanceText(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return '—'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

async function loadDingpan(refresh = false) {
  const symbols = querySymbols.value
  if (!symbols) {
    dingpanRows.value = []
    dingpanNote.value = ''
    dingpanError.value = ''
    dingpanTruncated.value = false
    showingSaved.value = false
    return
  }
  dingpanLoading.value = true
  dingpanError.value = ''
  try {
    const report = await fetchDingpan(symbols, refresh)
    dingpanRows.value = report.items
    dingpanNote.value = report.note
    dingpanTruncated.value = report.truncated
    rememberPoolRows(report.items)
    showingSaved.value = false
  } catch (err) {
    dingpanError.value = err instanceof Error ? err.message : '盯盘计算失败'
    if (!usingPaste.value) {
      const saved = dingpanSnapshots(symbols.split(',').filter(Boolean))
      if (saved.length) {
        dingpanRows.value = saved
        showingSaved.value = true
      }
    }
  } finally {
    dingpanLoading.value = false
  }
}

function rowName(row: DingpanItem) {
  const code = codeOf(row.symbol) || row.symbol
  const pooled = nameBySymbol.value.get(code) || nameBySymbol.value.get(row.symbol) || ''
  for (const raw of [row.name, pooled]) {
    const name = (raw || '').trim()
    if (name && name !== code && name !== row.symbol) return name
  }
  return ''
}

function rememberPoolRows(items: DingpanItem[]) {
  const keep = items.filter((item) => store.hasSymbol(item.symbol))
  if (keep.length) saveDingpanSnapshots(keep)
}

function addCodes(codes: string[]) {
  const added: string[] = []
  let stopped = ''
  for (const code of codes) {
    const row = dingpanRows.value.find((item) => codeOf(item.symbol) === code)
    const result = store.addSymbol({
      symbol: code,
      name: (row && rowName(row)) || code,
      price: row?.close ?? null,
    })
    if (!result.ok) {
      stopped = result.reason
      break
    }
    added.push(code)
  }
  const rows = dingpanRows.value.filter((item) => added.includes(codeOf(item.symbol)))
  if (rows.length) saveDingpanSnapshots(rows)
  if (added.length && stopped) addNote.value = `已加入 ${added.length} 只，盯盘结果已留下。${stopped}`
  else if (added.length) addNote.value = `已加入 ${added.length} 只，盯盘结果已留下。`
  else addNote.value = stopped || '这些股票已在观察池。'
}

function removeItem(item: WatchItem) {
  const code = codeOf(item.symbol)
  store.remove(item.id)
  if (code && !store.hasSymbol(code)) dropDingpanSnapshot(code)
}

watch(symbolKey, () => {
  if (usingPaste.value) return
  void loadDingpan(false)
}, { immediate: true })
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

    <section class="space-y-3 rounded-xl border bg-card p-4">
      <div>
        <h3 class="text-base font-semibold">盯盘</h3>
        <p class="mt-1 max-w-3xl text-sm text-muted-foreground">
          粘贴代码后点计算。框里有代码时只算这些代码，留空则计算观察池。计算不会自动写入。点加入观察池后，当次选中的股票和盯盘结果会留下来。低点取最近 20 个交易日里换手最大的两天，用这两天的最低价。回调是回撤过程的价格区间。压力分开记录事件 VWAP、收盘价和最高价，并给出最新收盘相对每个价格的偏离。突破是收盘价站上事件最高价，之后看回踩。
        </p>
      </div>
      <Textarea
        v-model="pasted"
        class="min-h-16 font-mono text-xs"
        placeholder="粘贴 6 位代码，用逗号、空格或换行分隔。最多 40 只。例如 002028"
      />
      <div class="flex flex-wrap items-center gap-2">
        <Button size="sm" :disabled="dingpanLoading || !querySymbols" @click="loadDingpan(true)">
          {{ dingpanLoading ? '计算中' : '计算盯盘' }}
        </Button>
        <Button
          v-if="pendingPaste.length"
          size="sm"
          variant="outline"
          @click="addCodes(pendingPaste)"
        >
          加入观察池
        </Button>
        <p v-if="usingPaste" class="text-xs text-muted-foreground">
          将计算粘贴的 {{ pastedCodes.length }} 只。点加入观察池后才写入，并留下盯盘结果。
        </p>
      </div>
      <p v-if="addNote" class="text-sm text-muted-foreground">{{ addNote }}</p>
      <p v-if="showingSaved && dingpanRows.length" class="text-sm text-muted-foreground">
        这是上次留下的盯盘结果。
      </p>
      <p v-if="dingpanError" class="text-sm text-destructive">{{ dingpanError }}</p>
      <p v-else-if="!querySymbols" class="text-sm text-muted-foreground">
        粘贴代码，或把股票加入观察池后，这里给出低点、回调、压力和突破。
      </p>
      <p v-else-if="dingpanLoading && !dingpanRows.length" class="text-sm text-muted-foreground">
        正在计算。
      </p>
      <p v-else-if="dingpanNote" class="text-sm text-muted-foreground">{{ dingpanNote }}</p>
      <p v-if="dingpanTruncated" class="text-xs text-muted-foreground">只计算前 40 只。</p>
      <div v-if="dingpanRows.length" class="overflow-x-auto">
        <table class="w-full min-w-[720px] text-left text-sm">
          <thead class="text-xs text-muted-foreground">
            <tr class="border-b">
              <th class="py-2 pr-3 font-medium">股票</th>
              <th class="py-2 pr-3 font-medium">阶段</th>
              <th class="py-2 pr-3 font-medium">收盘</th>
              <th class="py-2 pr-3 font-medium">低点</th>
              <th class="py-2 pr-3 font-medium">回调</th>
              <th class="py-2 pr-3 font-medium">压力</th>
              <th class="py-2 font-medium">突破</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in dingpanRows" :key="row.symbol" class="border-b last:border-0">
              <td class="py-2 pr-3">
                <div v-if="rowName(row)" class="font-medium">{{ rowName(row) }}</div>
                <div
                  class="font-mono"
                  :class="rowName(row) ? 'text-xs text-muted-foreground' : 'text-sm font-medium'"
                >
                  {{ codeOf(row.symbol) || row.symbol }}
                </div>
                <Button
                  v-if="usingPaste && !store.hasSymbol(row.symbol)"
                  size="sm"
                  variant="ghost"
                  class="mt-1 h-7 px-2"
                  @click="addCodes([codeOf(row.symbol)])"
                >
                  加入观察池
                </Button>
                <p v-else-if="usingPaste" class="mt-1 text-xs text-muted-foreground">已在观察池</p>
              </td>
              <td class="py-2 pr-3">
                <Badge variant="secondary">{{ row.stage }}</Badge>
                <p v-if="row.note" class="mt-1 text-xs text-muted-foreground">{{ row.note }}</p>
              </td>
              <td class="py-2 pr-3 tabular-nums">
                <template v-if="row.close != null">
                  {{ priceText(row.close) }}
                  <div class="text-xs text-muted-foreground">{{ row.asof }}</div>
                </template>
                <span v-else>—</span>
              </td>
              <td class="py-2 pr-3 tabular-nums">
                <template v-if="row.lows">
                  {{ spanText(row.lows.zoneLow, row.lows.zoneHigh) }}
                  <div class="text-xs text-muted-foreground">
                    {{ row.lows.kind === '高换手' ? '近期换手最大两天' : row.lows.kind }}
                    · {{ shortDate(row.lows.firstDate) }}
                    · {{ shortDate(row.lows.secondDate) }}
                  </div>
                </template>
                <span v-else>—</span>
              </td>
              <td class="py-2 pr-3 tabular-nums">
                <template v-if="row.pullback">
                  {{ spanText(row.pullback.lower, row.pullback.upper) }}
                  <div class="text-xs text-muted-foreground">
                    {{ shortDate(row.pullback.lowDate) }}
                    ·
                    {{ shortDate(row.pullback.highDate) }}
                  </div>
                </template>
                <span v-else>—</span>
              </td>
              <td class="py-2 pr-3 tabular-nums">
                <template v-if="row.pressure">
                  <div>VWAP {{ priceText(row.pressure.vwap) }} {{ distanceText(row.pressure.distanceVwap) }}</div>
                  <div>收盘 {{ priceText(row.pressure.close) }} {{ distanceText(row.pressure.distanceClose) }}</div>
                  <div>最高 {{ priceText(row.pressure.high) }} {{ distanceText(row.pressure.distanceHigh) }}</div>
                  <div class="text-xs text-muted-foreground">{{ shortDate(row.pressure.date) }}</div>
                </template>
                <span v-else>—</span>
              </td>
              <td class="py-2 tabular-nums">
                <template v-if="row.breakout">
                  {{ priceText(row.breakout.price) }}
                  {{ row.breakout.retest }}
                  <div class="text-xs text-muted-foreground">事件最高价 · {{ shortDate(row.breakout.date) }}</div>
                </template>
                <span v-else>—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
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
          <Button size="sm" variant="ghost" @click="removeItem(item)">
            移出观察池
          </Button>
        </div>
      </li>
    </ul>
  </div>
</template>
