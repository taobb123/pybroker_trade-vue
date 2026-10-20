<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
  fetchCapmSleeves,
  fetchCapmStocks,
  refreshCapmStocks,
  type CapmReport,
  type CapmRow,
  type CapmWindow,
} from '@/api/capm'

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
const sleeveQuadrant = ref('all')
const stockQuadrant = ref('all')
const sortKey = ref<'beta' | 'alpha' | 'r2' | 'name'>('beta')
const sortDir = ref<-1 | 1>(-1)

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

function sortValue(row: CapmRow): number | string {
  if (sortKey.value === 'name') return row.symbol || row.name
  if (sortKey.value === 'alpha') return row.w250?.alphaAnn ?? row.w120?.alphaAnn ?? Number.NEGATIVE_INFINITY
  if (sortKey.value === 'r2') return row.w250?.r2 ?? row.w120?.r2 ?? Number.NEGATIVE_INFINITY
  return betaOf(row) ?? Number.NEGATIVE_INFINITY
}

function countQuadrant(rows: CapmRow[] | undefined, id: string): number {
  return (rows ?? []).filter((row) => row.quadrantId === id).length
}

function applyQuadrant(rows: CapmRow[], quadrant: string): CapmRow[] {
  if (quadrant === 'all') return rows
  return rows.filter((row) => row.quadrantId === quadrant)
}

const visibleSleeves = computed(() => applyQuadrant(sleeves.value?.rows ?? [], sleeveQuadrant.value))

const visibleStocks = computed(() => {
  const rows = applyQuadrant(stocks.value?.rows ?? [], stockQuadrant.value)
  const filtered = band.value === 'all' ? rows : rows.filter((row) => bandOf(betaOf(row)) === band.value)
  return [...filtered].sort((a, b) => {
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

function toggleSort(key: 'beta' | 'alpha' | 'r2' | 'name') {
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

onMounted(() => {
  void loadSleeves()
  void loadStocks('vp6')
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
        个股默认用「量价六组合」分类结果里的全部股票，粘贴代码仍可单独计算。
        主力表演看该股票最近 10 个交易日的组合序列；走完之后的 3 个交易日收益写在同一列。
        这一页只对照，不写入观察池，也不改仓位。
      </p>
    </div>

    <Tabs v-model="tab" class="w-full">
      <TabsList>
        <TabsTrigger value="sleeves">信号组复盘</TabsTrigger>
        <TabsTrigger value="stocks">个股对比</TabsTrigger>
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
              默认读量价六组合分类结果的全部股票，粘贴代码用同一套象限。只在本页筛选，不改观察池。
              250 日区间取最近 250 个重叠交易日，终点跟着本地行情的最后一天。
              「补到最新交易日」会把沪深300和个股日线补到最近一个已收盘交易日，并写入本页缓存。
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-3">
            <div class="flex flex-wrap gap-2">
              <Button size="sm" :disabled="loadingStocks" @click="loadStocks('vp6')">计算量价六组合</Button>
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
            <p v-if="stocks" class="text-xs text-muted-foreground">
              样本 {{ stocks.sampleStart || '—' }} 至 {{ stocks.sampleEnd || '—' }}。
              请求 {{ stocks.requested ?? stocks.rows.length }} 只，能估计窗口的 {{ stocks.ready ?? '—' }} 只。
              当前显示 {{ visibleStocks.length }} 只。分档用 250 日 β，没有则用 120 日 β。
            </p>
            <p v-if="stockError" class="text-xs text-destructive">{{ stockError }}</p>
            <p v-else-if="stockMessage" class="text-xs text-muted-foreground">{{ stockMessage }}</p>
            <div v-if="stocks" class="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      <button type="button" class="hover:underline" @click="toggleSort('name')">代码</button>
                    </TableHead>
                    <TableHead>名称</TableHead>
                    <TableHead>主力表演</TableHead>
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
                    <TableHead class="text-right">超额</TableHead>
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
    </Tabs>
  </div>
</template>
