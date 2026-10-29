<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'
import {
  fetchCapmDesk,
  fetchCapmLaunch,
  fetchCapmTip,
  fetchCapmSleeves,
  fetchCapmStocks,
  refreshCapmStocks,
  type CapmReport,
  type CapmRow,
  type CapmWindow,
  type DeskReport,
  type LaunchReport,
  type TipReport,
} from '@/api/capm'
import { copyTextToClipboard, stockCodesToCopyText } from '@/api/tableCopy'

const tab = ref('sleeves')
const sleeves = ref<CapmReport | null>(null)
const stocks = ref<CapmReport | null>(null)
const sleeveMessage = ref('')
const stockMessage = ref('')
const sleeveError = ref('')
const stockError = ref('')
const loadingSleeves = ref(false)
const loadingStocks = ref(false)
const pasted = ref('')
const universe = ref<'vp6' | 'paste'>('vp6')
const band = ref('all')
const actBand = ref('all')
const alphaAnnNeg = ref(false)
const alpha120Neg = ref(false)
const sleeveQuadrant = ref('all')
const stockQuadrant = ref('all')
const desk = ref<DeskReport | null>(null)
const deskMessage = ref('')
const deskError = ref('')
const loadingDesk = ref(false)
const launch = ref<LaunchReport | null>(null)
const launchMessage = ref('')
const launchError = ref('')
const loadingLaunch = ref(false)
const launchPasted = ref('')
const launchCopyFlash = ref('')
let launchCopyTimer: ReturnType<typeof setTimeout> | undefined
const tip = ref<TipReport | null>(null)
const tipMessage = ref('')
const tipError = ref('')
const loadingTip = ref(false)
const tipPasted = ref('')
const tipCopyFlash = ref('')
let tipCopyTimer: ReturnType<typeof setTimeout> | undefined
const deskState = ref('pool')
const deskReason = ref('all')
const deskCopyFlash = ref('')
let deskCopyTimer: ReturnType<typeof setTimeout> | undefined
const deskX = ref<HTMLElement | null>(null)
const deskBar = ref<HTMLElement | null>(null)
const deskBarOn = ref(false)
const deskScrollWidth = ref(0)
const deskBarLeft = ref(0)
const deskBarWidth = ref(0)
let deskLock = false
let deskScrollRoot: EventTarget | null = null
let deskResize: ResizeObserver | null = null

const deskReasonOrder = [
  '改善还没连续两次',
  '价格和回归不是同一天',
  '仍在创新低',
  '收盘没突破前 20 日最高价',
  '量能没到 1.3 倍',
  '缓存没有开盘价',
  '收盘不高于开盘',
]
const sortKey = ref<'beta' | 'alpha' | 'r2' | 'excess' | 'name' | 'session'>('session')
const sortDir = ref<-1 | 1>(-1)
const codeCopyFlash = ref('')
let codeCopyTimer: ReturnType<typeof setTimeout> | undefined

const quadrantCards = [
  {
    id: 'high_alpha_high_beta',
    title: '高 α / 高 β',
    action: '待验证',
    hint: '有超额收益，但市场暴露也高。先看这段超额是否持续。',
    tone: 'border-emerald-200/80 bg-emerald-50/80 text-emerald-950 dark:border-emerald-900/50 dark:bg-emerald-950/30 dark:text-emerald-100',
  },
  {
    id: 'high_alpha_low_beta',
    title: '高 α / 低 β',
    action: '优先跟踪',
    hint: '超额还在，市场暴露相对低。',
    tone: 'border-lime-200/80 bg-lime-50/80 text-lime-950 dark:border-lime-900/50 dark:bg-lime-950/30 dark:text-lime-100',
  },
  {
    id: 'low_alpha_high_beta',
    title: '低 α / 高 β',
    action: '审查',
    hint: '承担了更高的市场风险，却没有对应补偿。',
    tone: 'border-rose-200/80 bg-rose-50/80 text-rose-950 dark:border-rose-900/50 dark:bg-rose-950/30 dark:text-rose-100',
  },
  {
    id: 'low_alpha_low_beta',
    title: '低 α / 低 β',
    action: '观察',
    hint: '对市场不敏感。还要看收益够不够覆盖交易成本。',
    tone: 'border-stone-200/80 bg-stone-50/80 text-stone-900 dark:border-stone-700/60 dark:bg-stone-900/40 dark:text-stone-100',
  },
]

const bands = [
  { id: 'all', label: '全部' },
  { id: 'neg', label: 'β < 0' },
  { id: 'low', label: '0 ≤ β ≤ 0.5' },
  { id: 'mid', label: '0.5 < β ≤ 1' },
  { id: 'high', label: '1 < β ≤ 1.5' },
  { id: 'very', label: 'β > 1.5' },
]

const actBands = [
  { id: 'all', label: '表演全部' },
  { id: 'wash_drop_2_5', label: '震仓下跌 2%–5%' },
  { id: 'release_gt0', label: '释放套牢盘 > 0%' },
]

const deskStates = [
  { id: 'pool', label: '候选' },
  { id: 'S2', label: '买入' },
  { id: 'S1', label: '观察' },
  { id: 'S0', label: '禁止买入' },
  { id: 'excluded', label: '排除' },
  { id: 'all', label: '全部' },
]

const stateRank: Record<string, number> = { S2: 0, S1: 1, S0: 2, excluded: 3, insufficient: 4 }

function pct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return '—'
  return `${(value * 100).toFixed(2)}%`
}

function num(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return '—'
  return value.toFixed(digits)
}

function actText(row: CapmRow): string {
  const label = row.actLabel || '无'
  if (label === '无') return '—'
  if (row.actReturn == null) return label
  return `${label} ${pct(row.actReturn)}`
}

function span(window: CapmWindow | null): string {
  if (!window) return '—'
  return `${window.start} ~ ${window.end}`
}

function betaOf(row: CapmRow): number | null {
  return row.w250?.beta ?? row.w120?.beta ?? null
}

function bandOf(beta: number | null): string {
  if (beta == null) return 'na'
  if (beta < 0) return 'neg'
  if (beta <= 0.5) return 'low'
  if (beta <= 1) return 'mid'
  if (beta <= 1.5) return 'high'
  return 'very'
}

function actPercent(row: CapmRow): number | null {
  if (row.actReturn == null || Number.isNaN(row.actReturn)) return null
  return Number((row.actReturn * 100).toFixed(2))
}

function matchesActBand(row: CapmRow, id: string): boolean {
  if (id === 'all') return true
  const value = actPercent(row)
  if (value == null) return false
  if (id === 'wash_drop_2_5') return row.actLabel === '震仓洗盘' && value < -2 && value > -5
  if (id === 'release_gt0') return row.actLabel === '释放套牢盘' && value > 0
  return false
}

function negativeAlpha(value: number | null | undefined): boolean {
  return value != null && !Number.isNaN(value) && value < 0
}

function matchesAlpha(row: CapmRow): boolean {
  if (alphaAnnNeg.value && !negativeAlpha(row.w250?.alphaAnn)) return false
  if (alpha120Neg.value && !negativeAlpha(row.w120?.alphaAnn)) return false
  return true
}

function sessionSortable(row: CapmRow): boolean {
  if (row.actLabel !== '震仓洗盘' && row.actLabel !== '释放套牢盘') return false
  return row.sessionReturn != null && !Number.isNaN(row.sessionReturn)
}

function sortValue(row: CapmRow): number | string {
  if (sortKey.value === 'name') return row.symbol || row.name
  if (sortKey.value === 'session') return row.sessionReturn ?? Number.NEGATIVE_INFINITY
  if (sortKey.value === 'alpha') return row.w250?.alphaAnn ?? row.w120?.alphaAnn ?? Number.NEGATIVE_INFINITY
  if (sortKey.value === 'r2') return row.w250?.r2 ?? row.w120?.r2 ?? Number.NEGATIVE_INFINITY
  if (sortKey.value === 'excess') return row.w250?.excess ?? Number.NEGATIVE_INFINITY
  return betaOf(row) ?? Number.NEGATIVE_INFINITY
}

function countQuadrant(rows: CapmRow[] | undefined, id: string): number {
  return (rows ?? []).filter((row) => row.quadrantId === id).length
}

function gateText(value: boolean, missing = false): string {
  if (missing) return '无开盘'
  return value ? '是' : '否'
}

function reasonClauses(reason: string): string[] {
  const body = reason.includes('：') ? reason.split('：').slice(1).join('：') : reason
  return body
    .split('、')
    .map((part) => part.replace(/。/g, '').trim())
    .filter(Boolean)
}

const deskReasonOptions = computed(() => {
  const seen = new Set<string>()
  for (const row of desk.value?.rows ?? []) {
    if (row.state !== 'S1') continue
    for (const clause of reasonClauses(row.reason)) seen.add(clause)
  }
  const known = deskReasonOrder.filter((item) => seen.has(item))
  const extra = [...seen].filter((item) => !deskReasonOrder.includes(item))
  return [...known, ...extra]
})

const visibleDesk = computed(() => {
  const rows = desk.value?.rows ?? []
  const filtered = rows.filter((row) => {
    if (deskState.value === 'all') return true
    if (deskState.value === 'pool') return row.state === 'S0' || row.state === 'S1' || row.state === 'S2'
    if (row.state !== deskState.value) return false
    if (deskState.value === 'S1' && deskReason.value !== 'all') {
      return reasonClauses(row.reason).includes(deskReason.value)
    }
    return true
  })
  return [...filtered].sort((a, b) => {
    const rank = (stateRank[a.state] ?? 9) - (stateRank[b.state] ?? 9)
    if (rank !== 0) return rank
    return (b.speed ?? Number.NEGATIVE_INFINITY) - (a.speed ?? Number.NEGATIVE_INFINITY)
  })
})

const todayBuys = computed(() => (desk.value?.buys ?? []).filter((row) => row.current))

function applyQuadrant(rows: CapmRow[], quadrant: string): CapmRow[] {
  if (quadrant === 'all') return rows
  return rows.filter((row) => row.quadrantId === quadrant)
}

const visibleSleeves = computed(() => applyQuadrant(sleeves.value?.rows ?? [], sleeveQuadrant.value))

const visibleStocks = computed(() => {
  const rows = applyQuadrant(stocks.value?.rows ?? [], stockQuadrant.value)
  const byBeta = band.value === 'all' ? rows : rows.filter((row) => bandOf(betaOf(row)) === band.value)
  const filtered = byBeta.filter((row) => matchesActBand(row, actBand.value) && matchesAlpha(row))
  return [...filtered].sort((a, b) => {
    if (sortKey.value === 'session') {
      const leftOn = sessionSortable(a)
      const rightOn = sessionSortable(b)
      if (leftOn !== rightOn) return leftOn ? -1 : 1
      if (!leftOn || !rightOn) return 0
      return ((a.sessionReturn ?? 0) - (b.sessionReturn ?? 0)) * sortDir.value
    }
    const left = sortValue(a)
    const right = sortValue(b)
    if (left === Number.NEGATIVE_INFINITY || right === Number.NEGATIVE_INFINITY) {
      if (left === right) return 0
      return left === Number.NEGATIVE_INFINITY ? 1 : -1
    }
    if (typeof left === 'string' || typeof right === 'string') {
      return String(left).localeCompare(String(right)) * sortDir.value
    }
    return (left - right) * sortDir.value
  })
})

function flashCodeCopy(text: string) {
  codeCopyFlash.value = text
  if (codeCopyTimer) clearTimeout(codeCopyTimer)
  codeCopyTimer = setTimeout(() => {
    codeCopyFlash.value = ''
  }, 1600)
}

async function copySortedCodes() {
  const text = stockCodesToCopyText(
    ['代码'],
    visibleStocks.value.map((row) => [row.symbol]),
  )
  if (!text) {
    flashCodeCopy('无代码')
    return
  }
  const ok = await copyTextToClipboard(text)
  flashCodeCopy(ok ? '已复制' : '复制失败')
}

function flashDeskCopy(text: string) {
  deskCopyFlash.value = text
  if (deskCopyTimer) clearTimeout(deskCopyTimer)
  deskCopyTimer = setTimeout(() => {
    deskCopyFlash.value = ''
  }, 1600)
}

async function copyDeskCodes() {
  const text = stockCodesToCopyText(
    ['代码'],
    visibleDesk.value.map((row) => [row.symbol]),
  )
  if (!text) {
    flashDeskCopy('无代码')
    return
  }
  const ok = await copyTextToClipboard(text)
  flashDeskCopy(ok ? '已复制' : '复制失败')
}

function scrollParent(el: HTMLElement | null): EventTarget {
  let node = el?.parentElement ?? null
  while (node) {
    const overflow = getComputedStyle(node).overflowY
    if (overflow === 'auto' || overflow === 'scroll') return node
    node = node.parentElement
  }
  return window
}

function updateDeskBar() {
  const el = deskX.value
  if (!el || tab.value !== 'desk') {
    deskBarOn.value = false
    return
  }
  const rect = el.getBoundingClientRect()
  const overflows = el.scrollWidth > el.clientWidth + 1
  const intersects = rect.bottom > 48 && rect.top < window.innerHeight - 8
  deskScrollWidth.value = el.scrollWidth
  const rightGap = Math.max(0, rect.right - (window.innerWidth - 72))
  deskBarLeft.value = rect.left
  deskBarWidth.value = Math.max(0, rect.width - rightGap)
  const wasOn = deskBarOn.value
  deskBarOn.value = overflows && intersects && deskBarWidth.value > 24
  const syncBar = () => {
    const bar = deskBar.value
    const host = deskX.value
    if (!bar || !host || !deskBarOn.value) return
    deskLock = true
    bar.scrollLeft = host.scrollLeft
    deskLock = false
  }
  syncBar()
  if (deskBarOn.value && !wasOn) void nextTick(syncBar)
}

function onDeskTableScroll() {
  const el = deskX.value
  const bar = deskBar.value
  if (deskLock || !el || !bar) return
  deskLock = true
  bar.scrollLeft = el.scrollLeft
  deskLock = false
}

function onDeskBarScroll() {
  const el = deskX.value
  const bar = deskBar.value
  if (deskLock || !el || !bar) return
  deskLock = true
  el.scrollLeft = bar.scrollLeft
  deskLock = false
}

function unbindDeskBar() {
  if (deskScrollRoot) {
    deskScrollRoot.removeEventListener('scroll', updateDeskBar)
    deskScrollRoot = null
  }
  window.removeEventListener('resize', updateDeskBar)
  deskResize?.disconnect()
  deskResize = null
  deskBarOn.value = false
}

function bindDeskBar() {
  unbindDeskBar()
  const el = deskX.value
  if (!el || tab.value !== 'desk') return
  deskScrollRoot = scrollParent(el)
  deskScrollRoot.addEventListener('scroll', updateDeskBar, { passive: true })
  window.addEventListener('resize', updateDeskBar)
  deskResize = new ResizeObserver(() => updateDeskBar())
  deskResize.observe(el)
  updateDeskBar()
}

function toggleSort(key: 'beta' | 'alpha' | 'r2' | 'excess' | 'name' | 'session') {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 1 ? -1 : 1
    return
  }
  sortKey.value = key
  sortDir.value = key === 'name' ? 1 : -1
}

async function loadSleeves() {
  loadingSleeves.value = true
  sleeveError.value = ''
  sleeveMessage.value = ''
  try {
    const payload = await fetchCapmSleeves()
    sleeves.value = payload.report
    if (payload.empty || !payload.report) sleeveMessage.value = payload.message || '没有可复盘的信号组。'
  } catch (err) {
    sleeveError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingSleeves.value = false
  }
}

async function loadStocks(nextUniverse: 'vp6' | 'paste') {
  universe.value = nextUniverse
  loadingStocks.value = true
  stockError.value = ''
  stockMessage.value = ''
  try {
    const payload = await fetchCapmStocks(nextUniverse, nextUniverse === 'paste' ? pasted.value : '')
    stocks.value = payload.report
    if (payload.empty || !payload.report) stockMessage.value = payload.message || '没有可对比的股票。'
  } catch (err) {
    stockError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingStocks.value = false
  }
}

async function fillBars() {
  loadingStocks.value = true
  stockError.value = ''
  stockMessage.value = ''
  try {
    const payload = await refreshCapmStocks(universe.value, universe.value === 'paste' ? pasted.value : '')
    stocks.value = payload.report
    stockMessage.value = payload.message || payload.report?.notes[0] || ''
    if (payload.empty) stockMessage.value = payload.message || '没有补到可用日线。'
  } catch (err) {
    stockError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingStocks.value = false
  }
}

async function loadDesk() {
  loadingDesk.value = true
  deskError.value = ''
  deskMessage.value = ''
  try {
    const payload = await fetchCapmDesk()
    desk.value = payload.report
    if (payload.empty || !payload.report) deskMessage.value = payload.message || '没有可计算的交易部门。'
  } catch (err) {
    deskError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingDesk.value = false
  }
}

async function loadLaunch(refresh = false) {
  loadingLaunch.value = true
  launchError.value = ''
  launchMessage.value = ''
  try {
    const payload = await fetchCapmLaunch(launchPasted.value, refresh)
    launch.value = payload.report
    if (payload.empty || !payload.report) launchMessage.value = payload.message || '没有可对照的股票。'
  } catch (err) {
    launchError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingLaunch.value = false
  }
}

async function loadTip(refresh = false) {
  loadingTip.value = true
  tipError.value = ''
  tipMessage.value = ''
  try {
    const payload = await fetchCapmTip(tipPasted.value, refresh)
    tip.value = payload.report
    if (payload.empty || !payload.report) tipMessage.value = payload.message || '没有可对照的股票。'
  } catch (err) {
    tipError.value = err instanceof Error ? err.message : String(err)
  } finally {
    loadingTip.value = false
  }
}

async function copyTipCodes() {
  const rows = tip.value?.rows ?? []
  const text = stockCodesToCopyText(
    ['代码'],
    rows.map((row) => [row.symbol]),
  )
  if (!text) {
    tipCopyFlash.value = '没有代码'
    return
  }
  const ok = await copyTextToClipboard(text)
  tipCopyFlash.value = ok ? '已复制' : '复制失败'
  if (tipCopyTimer) clearTimeout(tipCopyTimer)
  tipCopyTimer = setTimeout(() => {
    tipCopyFlash.value = ''
  }, 1600)
}

async function copyLaunchCodes() {
  const rows = launch.value?.rows ?? []
  const text = stockCodesToCopyText(
    ['代码'],
    rows.map((row) => [row.symbol]),
  )
  if (!text) {
    launchCopyFlash.value = '没有代码'
    return
  }
  const ok = await copyTextToClipboard(text)
  launchCopyFlash.value = ok ? '已复制' : '复制失败'
  if (launchCopyTimer) clearTimeout(launchCopyTimer)
  launchCopyTimer = setTimeout(() => {
    launchCopyFlash.value = ''
  }, 1600)
}

onMounted(() => {
  void loadSleeves()
  void loadStocks('vp6')
})

onUnmounted(() => {
  unbindDeskBar()
  if (deskCopyTimer) clearTimeout(deskCopyTimer)
  if (launchCopyTimer) clearTimeout(launchCopyTimer)
  if (tipCopyTimer) clearTimeout(tipCopyTimer)
})

watch(tab, (value) => {
  if (value === 'desk' && !desk.value && !loadingDesk.value) void loadDesk()
  if (value === 'desk' && !launch.value && !loadingLaunch.value) void loadLaunch(false)
  if (value === 'desk' && !tip.value && !loadingTip.value) void loadTip(false)
})

watch([tab, desk], async () => {
  await nextTick()
  if (tab.value === 'desk' && deskX.value) bindDeskBar()
  else unbindDeskBar()
})

watch(visibleDesk, async () => {
  await nextTick()
  updateDeskBar()
})

watch(deskReasonOptions, (options) => {
  if (deskReason.value !== 'all' && !options.includes(deskReason.value)) deskReason.value = 'all'
})
</script>

<template>
  <div class="space-y-5">
    <div class="min-w-0">
      <h2 class="text-base font-semibold tracking-tight">收益归因 · CAPM</h2>
      <p class="mt-1 text-xs text-muted-foreground">
        用沪深300拆开市场贝塔和超额。主列是最近 250 个交易日，旁边是 120 日。无风险利率按 0。
        象限只用最近 120 日的年化 α、t(α) 和 β。高 α 要年化 α 为正且 t(α) ≥ 1，高 β 是 β > 1。
        250 日数字仍显示，不决定象限。
        个股默认用 2+4 与 1+3+5 观察表，合并去重，不按排名截取。交易部门用同一份观察池。粘贴代码仍可单独计算。
        主力表演看该股票最近 10 个交易日的组合序列；走完之后的 3 个交易日收益写在同一列。
        全部震仓洗盘和全部释放套牢盘默认按最近一个已收盘交易日的收盘涨幅从高到低排。
        这一页只对照，不写入观察池，也不改仓位。
        交易部门只记下价格确认后的买入，不算止盈止损。百亚启动段和山尖只做形态对照。
      </p>
    </div>

    <Tabs v-model="tab" class="w-full">
      <TabsList>
        <TabsTrigger value="sleeves">信号组复盘</TabsTrigger>
        <TabsTrigger value="stocks">个股对比</TabsTrigger>
        <TabsTrigger value="desk">交易部门</TabsTrigger>
      </TabsList>

      <TabsContent value="sleeves" class="space-y-3">
        <Card>
          <CardHeader>
            <CardTitle>五个信号组</CardTitle>
            <CardDescription v-if="sleeves">
              基准 {{ sleeves.benchmark }}，{{ sleeves.sampleStart }} 至 {{ sleeves.sampleEnd }}。
              各组按自己有收益的日期与基准对齐。生成于 {{ sleeves.createdAt }}。
            </CardDescription>
            <CardDescription v-else>{{ loadingSleeves ? '读取信号组…' : '尚未载入' }}</CardDescription>
          </CardHeader>
          <CardContent class="space-y-3 px-0">
            <p v-if="sleeveError" class="px-4 text-xs text-destructive">{{ sleeveError }}</p>
            <p v-else-if="sleeveMessage" class="px-4 text-xs text-muted-foreground">{{ sleeveMessage }}</p>
            <div v-if="sleeves" class="grid gap-2 px-4 sm:grid-cols-2">
              <button
                v-for="card in quadrantCards"
                :key="card.id"
                type="button"
                class="rounded-lg border px-3 py-2 text-left"
                :class="[card.tone, sleeveQuadrant === card.id ? 'ring-2 ring-foreground/40' : '']"
                @click="sleeveQuadrant = sleeveQuadrant === card.id ? 'all' : card.id"
              >
                <div class="flex items-baseline justify-between gap-2">
                  <span class="text-sm font-semibold">{{ card.title }}</span>
                  <span class="text-xs">{{ card.action }} · {{ countQuadrant(sleeves.rows, card.id) }}</span>
                </div>
                <p class="mt-1 text-xs leading-relaxed opacity-80">{{ card.hint }}</p>
              </button>
            </div>
            <p v-if="sleeves" class="px-4 text-xs text-muted-foreground">
              点一格只看这一类，再点一次回到全部。样本不足 {{ countQuadrant(sleeves.rows, 'insufficient') }}。
            </p>
            <div v-if="sleeves" class="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>信号组</TableHead>
                    <TableHead>象限</TableHead>
                    <TableHead>情形</TableHead>
                    <TableHead>250 日区间</TableHead>
                    <TableHead class="text-right">实际</TableHead>
                    <TableHead class="text-right">基准</TableHead>
                    <TableHead class="text-right">超额</TableHead>
                    <TableHead class="text-right">β</TableHead>
                    <TableHead class="text-right">β 标准误</TableHead>
                    <TableHead class="text-right">年化 α</TableHead>
                    <TableHead class="text-right">t(α)</TableHead>
                    <TableHead class="text-right">R²</TableHead>
                    <TableHead class="text-right">残差波动</TableHead>
                    <TableHead class="text-right">120 日 β</TableHead>
                    <TableHead class="text-right">120 日 α</TableHead>
                    <TableHead class="text-right">120 日 R²</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="row in visibleSleeves" :key="row.key">
                    <TableCell class="font-medium">{{ row.name }}</TableCell>
                    <TableCell>
                      <p class="text-sm font-medium">{{ row.quadrant }}</p>
                      <p class="text-xs text-muted-foreground">
                        {{ row.quadrantAction }}
                        <span v-if="row.quadrantId !== 'insufficient'"> · 按 120 日</span>
                      </p>
                    </TableCell>
                    <TableCell>
                      <Badge variant="secondary">{{ row.label }}</Badge>
                      <p v-if="row.reason" class="mt-1 text-xs text-muted-foreground">{{ row.reason }}</p>
                    </TableCell>
                    <TableCell class="whitespace-nowrap text-xs">{{ span(row.w250) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w250?.total) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w250?.benchmark) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w250?.excess) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w250?.beta, 3) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w250?.betaSe, 3) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w250?.alphaAnn) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w250?.tAlpha, 2) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w250?.r2, 2) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w250?.residVolAnn) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w120?.beta, 3) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w120?.alphaAnn) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w120?.r2, 2) }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
            <ul v-if="sleeves" class="space-y-1 px-4 text-xs text-muted-foreground">
              <li v-for="note in sleeves.notes" :key="note">{{ note }}</li>
            </ul>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="stocks" class="space-y-3">
        <Card>
          <CardHeader>
            <CardTitle>个股贝塔对照</CardTitle>
            <CardDescription>
              默认读 2+4 观察表（底部放量上涨、上涨放量突破）和 1+3+5 观察表（底部缩量、上涨缩量整理、高位放量滞涨），合并去重。不使用题材全表。粘贴代码用同一套象限。只在本页筛选，不改观察池。
              250 日区间取最近 250 个重叠交易日，终点跟着本地行情的最后一天。
              「补到最新交易日」会把沪深300和个股日线补到最近一个已收盘交易日，并写入本页缓存。
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <div class="flex flex-wrap gap-2">
              <Button size="sm" :disabled="loadingStocks" @click="loadStocks('vp6')">计算 2+4 与 1+3+5</Button>
              <Button size="sm" variant="outline" :disabled="loadingStocks" @click="loadStocks('paste')">计算粘贴代码</Button>
              <Button size="sm" variant="outline" :disabled="loadingStocks" @click="fillBars">
                {{ loadingStocks ? '计算中' : '补到最新交易日' }}
              </Button>
            </div>
            <Textarea
              v-model="pasted"
              class="min-h-20 font-mono text-xs"
              placeholder="粘贴 6 位代码，用逗号、空格或换行分隔。最多 80 只。"
            />
            <div v-if="stocks" class="grid gap-2 sm:grid-cols-2">
              <button
                v-for="card in quadrantCards"
                :key="card.id"
                type="button"
                class="rounded-lg border px-3 py-2 text-left"
                :class="[card.tone, stockQuadrant === card.id ? 'ring-2 ring-foreground/40' : '']"
                @click="stockQuadrant = stockQuadrant === card.id ? 'all' : card.id"
              >
                <div class="flex items-baseline justify-between gap-2">
                  <span class="text-sm font-semibold">{{ card.title }}</span>
                  <span class="text-xs">{{ card.action }} · {{ countQuadrant(stocks.rows, card.id) }}</span>
                </div>
                <p class="mt-1 text-xs leading-relaxed opacity-80">{{ card.hint }}</p>
              </button>
            </div>
            <p v-if="stocks" class="text-xs text-muted-foreground">
              点一格只看这一类，再点一次回到全部。粘贴代码用同一套规则。样本不足 {{ countQuadrant(stocks.rows, 'insufficient') }}。
            </p>
            <div class="flex flex-wrap gap-1">
              <Button
                v-for="item in bands"
                :key="item.id"
                size="sm"
                :variant="band === item.id ? 'default' : 'outline'"
                @click="band = item.id"
              >
                {{ item.label }}
              </Button>
            </div>
            <div class="flex flex-wrap gap-1">
              <Button
                size="sm"
                :variant="alphaAnnNeg ? 'default' : 'outline'"
                @click="alphaAnnNeg = !alphaAnnNeg"
              >
                年化 α&lt;0
              </Button>
              <Button
                size="sm"
                :variant="alpha120Neg ? 'default' : 'outline'"
                @click="alpha120Neg = !alpha120Neg"
              >
                120 日 α&lt;0
              </Button>
            </div>
            <div class="flex flex-wrap gap-1">
              <Button
                v-for="item in actBands"
                :key="item.id"
                size="sm"
                :variant="actBand === item.id ? 'default' : 'outline'"
                @click="actBand = item.id"
              >
                {{ item.label }}
              </Button>
            </div>
            <p v-if="stocks" class="text-xs text-muted-foreground">
              样本 {{ stocks.sampleStart || '—' }} 至 {{ stocks.sampleEnd || '—' }}。
              请求 {{ stocks.requested ?? stocks.rows.length }} 只，能估计窗口的 {{ stocks.ready ?? '—' }} 只。
              当前显示 {{ visibleStocks.length }} 只。分档用 250 日 β，没有则用 120 日 β。
              年化 α&lt;0 只保留 250 日年化 α 小于 0 的股票。120 日 α&lt;0 只保留 120 日 α 小于 0 的股票。两个可以同时打开，再点一次取消。没有对应数字的不进入。
              主力表演按走完后 3 个交易日的涨跌筛选。震仓洗盘只看跌幅大于 2% 且小于 5%（涨跌在 -5% 和 -2% 之间）。释放套牢盘只看大于 0%。刚好等于 -2%、-5%、0%，以及没有这段收益的，只留在「表演全部」。
              当日涨幅是该股票最近一根收盘相对前一交易日收盘的涨跌。默认把全部震仓洗盘和全部释放套牢盘按这个涨幅从高到低排在前面。打断、未走完、无，以及没有当日涨幅的，留在后面。
            </p>
            <p v-if="stockError" class="text-xs text-destructive">{{ stockError }}</p>
            <p v-else-if="stockMessage" class="text-xs text-muted-foreground">{{ stockMessage }}</p>
            <div v-if="stocks" class="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      <button type="button" class="hover:underline" @click="toggleSort('name')">代码</button>
                      <button
                        type="button"
                        class="ml-1 text-xs text-muted-foreground hover:underline"
                        title="复制当前表格里排好序的股票代码，每行一个"
                        @click="copySortedCodes"
                      >
                        {{ codeCopyFlash || '复制' }}
                      </button>
                    </TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead>主力表演</TableHead>
                    <TableHead>
                      <button type="button" class="hover:underline" @click="toggleSort('session')">当日涨幅</button>
                    </TableHead>
                    <TableHead>象限</TableHead>
                    <TableHead>情形</TableHead>
                    <TableHead>
                      <button type="button" class="hover:underline" @click="toggleSort('beta')">β</button>
                    </TableHead>
                    <TableHead>
                      <button type="button" class="hover:underline" @click="toggleSort('alpha')">年化 α</button>
                    </TableHead>
                    <TableHead>
                      <button type="button" class="hover:underline" @click="toggleSort('r2')">R²</button>
                    </TableHead>
                    <TableHead class="text-right">
                      <button type="button" class="hover:underline" @click="toggleSort('excess')">超额</button>
                    </TableHead>
                    <TableHead class="text-right">120 日 β</TableHead>
                    <TableHead class="text-right">120 日 α</TableHead>
                    <TableHead>说明</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="row in visibleStocks" :key="row.key">
                    <TableCell class="font-medium tabular-nums">{{ row.symbol }}</TableCell>
                    <TableCell>{{ row.stockName || row.name }}</TableCell>
                    <TableCell class="whitespace-nowrap text-sm">{{ actText(row) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.sessionReturn) }}</TableCell>
                    <TableCell>
                      <p class="text-sm font-medium">{{ row.quadrant }}</p>
                      <p class="text-xs text-muted-foreground">
                        {{ row.quadrantAction }}
                        <span v-if="row.quadrantId !== 'insufficient'"> · 按 120 日</span>
                      </p>
                    </TableCell>
                    <TableCell><Badge variant="secondary">{{ row.label }}</Badge></TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w250?.beta, 3) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w250?.alphaAnn) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w250?.r2, 2) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w250?.excess) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.w120?.beta, 3) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.w120?.alphaAnn) }}</TableCell>
                    <TableCell class="max-w-56 text-xs text-muted-foreground">{{ row.reason || span(row.w250) }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="desk" class="space-y-3">
        <Card>
          <CardHeader>
            <CardTitle>Alpha 状态机</CardTitle>
            <CardDescription>
              只做到买入的价格确认。名单和个股对比相同，是 2+4 与 1+3+5 观察表合并去重。
              候选是 250 日 β 在 0 到 0.5，并且年化 120 日 α 减年化 250 日 α 小于 0。
              120 日 α 比 20 个交易日前更高才离开「禁止买入」。连续两次改善，并且收盘突破前 20 日最高价、不再创新低、放量 1.3 倍、收盘高于开盘，才记下买入。
              买入日记在下一交易日。不加仓，不止盈，不止损。
              本地收盘若晚于 2024-01-02，打开这一页会自动把更早的收盘补进缓存。
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <div class="flex flex-wrap gap-2">
              <Button size="sm" variant="outline" :disabled="loadingDesk" @click="loadDesk">
                {{ loadingDesk ? '计算中' : '重新计算' }}
              </Button>
            </div>
            <p v-if="deskError" class="text-xs text-destructive">{{ deskError }}</p>
            <p v-else-if="deskMessage" class="text-xs text-muted-foreground">{{ deskMessage }}</p>
            <p v-if="desk?.openMissing" class="text-xs text-muted-foreground">
              当前量价缓存没有开盘价，收盘高于开盘这一关过不了，所以不会记下买入。
            </p>
            <div v-if="desk" class="grid gap-2 sm:grid-cols-5">
              <div class="rounded-lg border px-3 py-2">
                <p class="text-xs text-muted-foreground">买入</p>
                <p class="text-sm font-semibold tabular-nums">{{ desk.counts.S2 ?? 0 }}</p>
              </div>
              <div class="rounded-lg border px-3 py-2">
                <p class="text-xs text-muted-foreground">观察</p>
                <p class="text-sm font-semibold tabular-nums">{{ desk.counts.S1 ?? 0 }}</p>
              </div>
              <div class="rounded-lg border px-3 py-2">
                <p class="text-xs text-muted-foreground">禁止买入</p>
                <p class="text-sm font-semibold tabular-nums">{{ desk.counts.S0 ?? 0 }}</p>
              </div>
              <div class="rounded-lg border px-3 py-2">
                <p class="text-xs text-muted-foreground">排除</p>
                <p class="text-sm font-semibold tabular-nums">{{ desk.counts.excluded ?? 0 }}</p>
              </div>
              <div class="rounded-lg border px-3 py-2">
                <p class="text-xs text-muted-foreground">样本不足</p>
                <p class="text-sm font-semibold tabular-nums">{{ desk.counts.insufficient ?? 0 }}</p>
              </div>
            </div>
            <p v-if="desk" class="text-xs text-muted-foreground">
              截止 {{ desk.asOf || '—' }}。今天记下的买入 {{ todayBuys.length }} 只。
              <template v-if="todayBuys.length">
                {{ todayBuys.map((row) => row.symbol).join('、') }}。成交看下一交易日。
              </template>
            </p>
            <div class="flex flex-wrap gap-1">
              <Button
                v-for="item in deskStates"
                :key="item.id"
                size="sm"
                :variant="deskState === item.id ? 'default' : 'outline'"
                @click="deskState = item.id"
              >
                {{ item.label }}
              </Button>
            </div>
            <div v-if="desk && deskState === 'S1'" class="flex flex-wrap items-center gap-1">
              <Button
                size="sm"
                :variant="deskReason === 'all' ? 'default' : 'outline'"
                @click="deskReason = 'all'"
              >
                全部说明
              </Button>
              <Button
                v-for="item in deskReasonOptions"
                :key="item"
                size="sm"
                :variant="deskReason === item ? 'default' : 'outline'"
                @click="deskReason = deskReason === item ? 'all' : item"
              >
                {{ item }}
              </Button>
              <Button size="sm" variant="outline" @click="copyDeskCodes">
                {{ deskCopyFlash || `复制代码（${visibleDesk.length}）` }}
              </Button>
            </div>
            <div
              v-if="desk"
              ref="deskX"
              class="w-full min-w-0 overflow-x-auto [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
              @scroll.passive="onDeskTableScroll"
            >
              <Table bare>
                <TableHeader>
                  <TableRow>
                    <TableHead>代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead>状态</TableHead>
                    <TableHead class="text-right">β</TableHead>
                    <TableHead class="text-right">250 日 α</TableHead>
                    <TableHead class="text-right">120 日 α</TableHead>
                    <TableHead class="text-right">120−250</TableHead>
                    <TableHead class="text-right">20 日变化</TableHead>
                    <TableHead class="text-right">速度</TableHead>
                    <TableHead>连续改善</TableHead>
                    <TableHead>不创新低</TableHead>
                    <TableHead>突破</TableHead>
                    <TableHead>放量</TableHead>
                    <TableHead>收盘&gt;开盘</TableHead>
                    <TableHead>信号日</TableHead>
                    <TableHead>说明</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="row in visibleDesk" :key="row.symbol">
                    <TableCell class="font-medium tabular-nums">{{ row.symbol }}</TableCell>
                    <TableCell>{{ row.stockName || '—' }}</TableCell>
                    <TableCell><Badge variant="secondary">{{ row.stateLabel }}</Badge></TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.beta250, 3) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.alpha250) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.alpha120) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.alphaGap) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.delta120) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.speed) }}</TableCell>
                    <TableCell>{{ row.persisted ? '是' : '否' }}</TableCell>
                    <TableCell>{{ gateText(row.noNewLow) }}</TableCell>
                    <TableCell>{{ gateText(row.breakout) }}</TableCell>
                    <TableCell>{{ gateText(row.volumeOk) }}</TableCell>
                    <TableCell>{{ gateText(row.closeAboveOpen, row.openMissing) }}</TableCell>
                    <TableCell class="whitespace-nowrap text-xs">{{ row.signalDate || '—' }}</TableCell>
                    <TableCell class="max-w-64 text-xs text-muted-foreground">{{ row.reason }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
            <p v-if="desk && !visibleDesk.length" class="text-xs text-muted-foreground">这一档没有股票。</p>
          </CardContent>
        </Card>
        <Teleport to="body">
          <div
            v-show="deskBarOn"
            ref="deskBar"
            class="fixed bottom-0 z-40 overflow-x-scroll overflow-y-hidden border-t bg-background"
            :style="{ left: `${deskBarLeft}px`, width: `${deskBarWidth}px`, height: '18px' }"
            aria-label="表格左右滚动"
            @scroll.passive="onDeskBarScroll"
          >
            <div :style="{ width: `${deskScrollWidth}px`, height: '1px' }" />
          </div>
        </Teleport>

        <Card>
          <CardHeader>
            <CardTitle>百亚启动段</CardTitle>
            <CardDescription v-if="launch">
              模板 {{ launch.template.name }} {{ launch.template.symbol }}，放量日 {{ launch.template.ignition }}，
              第三根阳线 {{ launch.template.third }}，放量 {{ launch.template.volume.toFixed(2) }} 倍。
              截止 {{ launch.asOf || '—' }}。有相关性 {{ launch.relatedCount }} 只，其余 {{ launch.unrelatedCount }} 只没有相关性。
            </CardDescription>
            <CardDescription v-else>{{ loadingLaunch ? '对照启动段…' : '尚未载入' }}</CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <Textarea
              v-model="launchPasted"
              class="min-h-16 font-mono text-xs"
              placeholder="粘贴 6 位代码，用逗号、空格或换行分隔。和观察池一起对照，最多 80 只。"
            />
            <div class="flex flex-wrap gap-2">
              <Button size="sm" :disabled="loadingLaunch" @click="loadLaunch(true)">
                {{ loadingLaunch ? '对照中' : '对照' }}
              </Button>
              <Button size="sm" variant="outline" :disabled="!launch?.rows.length" @click="copyLaunchCodes">
                {{ launchCopyFlash || `复制代码（${launch?.rows.length ?? 0}）` }}
              </Button>
            </div>
            <p v-if="launchError" class="text-xs text-destructive">{{ launchError }}</p>
            <p v-else-if="launchMessage" class="text-xs text-muted-foreground">{{ launchMessage }}</p>
            <div v-if="launch?.rows.length" class="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead class="text-right">相似度</TableHead>
                    <TableHead>说明</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="row in launch.rows" :key="row.symbol">
                    <TableCell class="font-medium tabular-nums">{{ row.symbol }}</TableCell>
                    <TableCell>
                      {{ row.stockName || '—' }}
                      <span v-if="row.pasted" class="ml-1 text-xs text-muted-foreground">粘贴</span>
                    </TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.similarity, 2) }}</TableCell>
                    <TableCell class="max-w-xl text-xs text-muted-foreground">{{ row.reason }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
            <p v-else-if="launch" class="text-xs text-muted-foreground">观察池里没有和百亚启动段相近的股票。</p>
            <p v-if="launch?.unrelatedPasted.length" class="text-xs text-muted-foreground">
              粘贴里没有相关性：{{ launch.unrelatedPasted.join('、') }}
            </p>
            <p v-if="launch?.missingPasted.length" class="text-xs text-muted-foreground">
              粘贴缺日线：{{ launch.missingPasted.join('、') }}
            </p>
            <ul v-if="launch" class="space-y-1 text-xs text-muted-foreground">
              <li v-for="note in launch.notes" :key="note">{{ note }}</li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>山尖</CardTitle>
            <CardDescription v-if="tip">
              截止 {{ tip.asOf || '—' }}。两三个月整理优先。山尖和圆弧底在同一带 {{ tip.matchedCount }} 只，其余 {{ tip.unrelatedCount }} 只不是这幅左边画面。
            </CardDescription>
            <CardDescription v-else>{{ loadingTip ? '对照山尖…' : '尚未载入' }}</CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <Textarea
              v-model="tipPasted"
              class="min-h-16 font-mono text-xs"
              placeholder="粘贴 6 位代码，用逗号、空格或换行分隔。和观察池一起对照，最多 80 只。"
            />
            <div class="flex flex-wrap gap-2">
              <Button size="sm" :disabled="loadingTip" @click="loadTip(true)">
                {{ loadingTip ? '对照中' : '对照' }}
              </Button>
              <Button size="sm" variant="outline" :disabled="!tip?.rows.length" @click="copyTipCodes">
                {{ tipCopyFlash || `复制代码（${tip?.rows.length ?? 0}）` }}
              </Button>
            </div>
            <p v-if="tipError" class="text-xs text-destructive">{{ tipError }}</p>
            <p v-else-if="tipMessage" class="text-xs text-muted-foreground">{{ tipMessage }}</p>
            <div v-if="tip?.rows.length" class="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>代码</TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead class="text-right">降幅</TableHead>
                    <TableHead class="text-right">山尖</TableHead>
                    <TableHead class="text-right">相似度</TableHead>
                    <TableHead>说明</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="row in tip.rows" :key="row.symbol">
                    <TableCell class="font-medium tabular-nums">{{ row.symbol }}</TableCell>
                    <TableCell>
                      {{ row.stockName || '—' }}
                      <span v-if="row.pasted" class="ml-1 text-xs text-muted-foreground">粘贴</span>
                    </TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(row.drop) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ row.tipBars }} 根</TableCell>
                    <TableCell class="text-right tabular-nums">{{ num(row.similarity, 2) }}</TableCell>
                    <TableCell class="max-w-xl text-xs text-muted-foreground">{{ row.reason }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
            <p v-else-if="tip" class="text-xs text-muted-foreground">观察池里没有这幅左边画面。</p>
            <p v-if="tip?.unrelatedPasted.length" class="text-xs text-muted-foreground">
              粘贴里不是这条左线：{{ tip.unrelatedPasted.join('、') }}
            </p>
            <p v-if="tip?.missingPasted.length" class="text-xs text-muted-foreground">
              粘贴缺日线：{{ tip.missingPasted.join('、') }}
            </p>
            <ul v-if="tip" class="space-y-1 text-xs text-muted-foreground">
              <li v-for="note in tip.notes" :key="note">{{ note }}</li>
            </ul>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>收敛速度与未来 10 日超额</CardTitle>
            <CardDescription v-if="desk?.hypothesis">
              {{ desk.hypothesis.verdict }}
              样本 {{ desk.hypothesis.sampleStart || '—' }} 至 {{ desk.hypothesis.sampleEnd || '—' }}，
              {{ desk.hypothesis.nDates }} 个取样日，{{ desk.hypothesis.nNames }} 只股票，{{ desk.hypothesis.nObs }} 笔。
            </CardDescription>
            <CardDescription v-else>{{ loadingDesk ? '计算假设…' : '尚未载入' }}</CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <div v-if="desk?.hypothesis" class="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>分组</TableHead>
                    <TableHead class="text-right">样本</TableHead>
                    <TableHead class="text-right">超额为正</TableHead>
                    <TableHead class="text-right">平均超额</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow v-for="group in desk.hypothesis.groups" :key="group.id">
                    <TableCell class="font-medium">
                      {{ group.id }}<template v-if="group.label !== group.id"> {{ group.label }}</template>
                    </TableCell>
                    <TableCell class="text-right tabular-nums">{{ group.n }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(group.hitRate) }}</TableCell>
                    <TableCell class="text-right tabular-nums">{{ pct(group.meanExcess) }}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>
            <ul v-if="desk" class="space-y-1 text-xs text-muted-foreground">
              <li v-for="note in desk.notes" :key="note">{{ note }}</li>
            </ul>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </div>
</template>
