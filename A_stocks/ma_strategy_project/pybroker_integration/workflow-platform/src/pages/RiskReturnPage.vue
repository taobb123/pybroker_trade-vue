<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  fetchRiskReturnLatest,
  runRiskReturn,
  type RiskDecile,
  type RiskReport,
} from '@/api/riskReturn'

const report = ref<RiskReport | null>(null)
const message = ref('')
const error = ref('')
const loading = ref(false)
const running = ref(false)
const selectedDecile = ref(10)

const selected = computed(() => {
  return report.value?.deciles.find((row) => row.decile === selectedDecile.value) ?? null
})

const histMax = computed(() => {
  const counts = selected.value?.histogram.map((bin) => bin.count) ?? []
  return Math.max(1, ...counts)
})

function pct(value: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return `${(value * 100).toFixed(digits)}%`
}

function num(value: number | null, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}

function pickDefault(next: RiskReport) {
  const q10 = next.deciles.find((row) => row.decile === 10)
  if (q10 && q10.n > 0) {
    selectedDecile.value = 10
    return
  }
  const ranked = [...next.deciles].sort((a, b) => b.n - a.n)
  selectedDecile.value = ranked[0]?.decile ?? 10
}

function applyResponse(emptyMessage: string | null, next: RiskReport | null, err: string | null) {
  error.value = err ?? ''
  if (next) {
    report.value = next
    message.value = ''
    pickDefault(next)
    return
  }
  message.value = emptyMessage || '还没有研究结果。'
}

async function loadLatest() {
  loading.value = true
  error.value = ''
  try {
    const payload = await fetchRiskReturnLatest()
    if (!payload.ok) {
      applyResponse(null, null, payload.error || '读取失败')
      return
    }
    applyResponse(payload.message, payload.report, null)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    loading.value = false
  }
}

async function runJob() {
  running.value = true
  error.value = ''
  try {
    const payload = await runRiskReturn()
    if (!payload.ok) {
      error.value = payload.error || '研究任务失败'
      return
    }
    if (payload.empty || !payload.report) {
      message.value = payload.message || '没有可计算的行情。'
      return
    }
    applyResponse(null, payload.report, null)
  } catch (err) {
    error.value = err instanceof Error ? err.message : String(err)
  } finally {
    running.value = false
  }
}

function selectRow(row: RiskDecile) {
  selectedDecile.value = row.decile
}

onMounted(() => {
  void loadLatest()
})
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-base font-semibold tracking-tight">风险收益 · M+ / T+3</h2>
        <p class="mt-1 text-xs text-muted-foreground">
          样本用市场中性截面里已经算好的 M+，T+3 用系统日线补上。结果写在 risk_return/output/latest.json。日常的东财概念扫描、量价六组合、形态建仓和回测对比保持原样。
        </p>
      </div>
      <Button :disabled="running" @click="runJob">
        {{ running ? '计算中' : '运行研究' }}
      </Button>
    </div>

    <p v-if="loading" class="text-xs text-muted-foreground">正在读取上次结果…</p>
    <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
    <p v-else-if="message && !report" class="text-xs text-muted-foreground">{{ message }}</p>

    <template v-if="report">
      <div class="flex flex-wrap gap-2 text-xs text-muted-foreground">
        <Badge variant="outline">{{ report.factor }} · {{ report.factorField }}</Badge>
        <Badge variant="outline">T+{{ report.holdTradingDays }}</Badge>
        <Badge variant="outline">样本截止 {{ report.sampleEnd || '—' }}</Badge>
        <Badge v-if="report.sampleSource" variant="outline">{{ report.sampleSource }}</Badge>
        <Badge variant="outline">{{ report.nRows }} 行 / {{ report.nSignalDates }} 个信号日</Badge>
        <Badge variant="outline">{{ report.nPaths }} 路径 × {{ report.nTrades }} 笔</Badge>
        <Badge variant="outline">种子 {{ report.seed }}</Badge>
      </div>
      <p class="text-xs text-muted-foreground">{{ report.factorNote }}</p>

      <Card class="shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-semibold">M+ 十分位</CardTitle>
          <CardDescription>Q1 为最低，Q10 为最高。点一行查看该分位的分布和 Kelly 对照。</CardDescription>
        </CardHeader>
        <CardContent class="px-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>分位</TableHead>
                <TableHead class="text-right">样本</TableHead>
                <TableHead class="text-right">期望</TableHead>
                <TableHead class="text-right">中位</TableHead>
                <TableHead class="text-right">胜率</TableHead>
                <TableHead class="text-right">后验胜率</TableHead>
                <TableHead class="text-right">亏损概率</TableHead>
                <TableHead class="text-right">VaR 95%</TableHead>
                <TableHead class="text-right">CVaR 95%</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow
                v-for="row in report.deciles"
                :key="row.decile"
                class="cursor-pointer"
                :class="row.decile === selectedDecile ? 'bg-muted/60' : ''"
                @click="selectRow(row)"
              >
                <TableCell>
                  <span class="font-medium">{{ row.label }}</span>
                  <Badge v-if="row.smallSample" variant="outline" class="ml-2">样本少</Badge>
                </TableCell>
                <TableCell class="text-right tabular-nums">{{ row.n }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ pct(row.mean) }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ pct(row.median) }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ pct(row.winRate, 1) }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ pct(row.posteriorWinRate, 1) }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ pct(row.probLoss, 1) }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ pct(row.var95) }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ pct(row.cvar95) }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <div v-if="selected" class="grid gap-4 lg:grid-cols-2">
        <Card class="shadow-none">
          <CardHeader class="pb-2">
            <CardTitle class="text-sm font-semibold">{{ selected.label }} 的 T+3 收益分布</CardTitle>
            <CardDescription>
              偏度 {{ num(selected.skew) }} · 超额峰度 {{ num(selected.excessKurtosis) }} ·
              P(胜率&gt;50%) {{ pct(selected.probWinRateGtHalf, 1) }}
            </CardDescription>
          </CardHeader>
          <CardContent class="space-y-2">
            <p v-if="selected.smallSample" class="text-xs text-muted-foreground">
              样本 {{ selected.n }} 条，少于 {{ report.smallSampleN }}。后验胜率已向 50% 收缩，路径分布仍然画出来。
            </p>
            <p v-if="selected.note" class="text-xs text-muted-foreground">{{ selected.note }}</p>
            <p v-if="!selected.histogram.length" class="text-xs text-muted-foreground">这个分位没有完成的 T+3 样本。</p>
            <div
              v-for="(bin, index) in selected.histogram"
              :key="index"
              class="flex items-center gap-2 text-xs"
            >
              <span class="w-16 shrink-0 text-right tabular-nums text-muted-foreground">{{ pct(bin.left, 1) }}</span>
              <div class="h-2 min-w-0 flex-1 rounded bg-muted">
                <div
                  class="h-2 rounded bg-primary"
                  :style="{ width: `${Math.max(2, (bin.count / histMax) * 100)}%` }"
                />
              </div>
              <span class="w-8 shrink-0 text-right tabular-nums">{{ bin.count }}</span>
            </div>
          </CardContent>
        </Card>

        <Card class="shadow-none">
          <CardHeader class="pb-2">
            <CardTitle class="text-sm font-semibold">Kelly 对照</CardTitle>
            <CardDescription>
              后验胜率 {{ pct(selected.posteriorWinRate, 1) }} · 盈亏比 {{ num(selected.payoffB) }} ·
              满 Kelly {{ pct(selected.kellyFull, 1) }}。初始资金记为 1。
            </CardDescription>
          </CardHeader>
          <CardContent class="px-0">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>仓位</TableHead>
                  <TableHead class="text-right">比例</TableHead>
                  <TableHead class="text-right">终值中位</TableHead>
                  <TableHead class="text-right">终值 5%</TableHead>
                  <TableHead class="text-right">终值 95%</TableHead>
                  <TableHead class="text-right">回撤中位</TableHead>
                  <TableHead class="text-right">回撤&gt;20%</TableHead>
                  <TableHead class="text-right">回撤&gt;30%</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-if="!selected.scenarios.length">
                  <TableCell colspan="8" class="text-xs text-muted-foreground">这个分位没有路径。</TableCell>
                </TableRow>
                <TableRow v-for="scene in selected.scenarios" :key="scene.name">
                  <TableCell>{{ scene.name }}</TableCell>
                  <TableCell class="text-right tabular-nums">{{ pct(scene.position, 1) }}</TableCell>
                  <TableCell class="text-right tabular-nums">{{ num(scene.medianTerminalWealth, 3) }}</TableCell>
                  <TableCell class="text-right tabular-nums">{{ num(scene.p05TerminalWealth, 3) }}</TableCell>
                  <TableCell class="text-right tabular-nums">{{ num(scene.p95TerminalWealth, 3) }}</TableCell>
                  <TableCell class="text-right tabular-nums">{{ pct(scene.medianMaxDrawdown, 1) }}</TableCell>
                  <TableCell class="text-right tabular-nums">{{ pct(scene.probDdGt20, 1) }}</TableCell>
                  <TableCell class="text-right tabular-nums">{{ pct(scene.probDdGt30, 1) }}</TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <ul class="space-y-1 text-xs text-muted-foreground">
        <li v-for="note in report.notes" :key="note">{{ note }}</li>
        <li>结果时间 {{ report.createdAt }}</li>
      </ul>
    </template>
  </div>
</template>
