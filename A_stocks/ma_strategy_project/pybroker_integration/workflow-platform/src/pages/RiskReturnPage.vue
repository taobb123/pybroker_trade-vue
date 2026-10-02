<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
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
  fetchRiskBudget,
  fetchRiskCopula,
  fetchRiskCorrelation,
  fetchRiskDecision,
  fetchRiskWalkForward,
  fetchRiskRegime,
  fetchRiskReturnLatest,
  runRiskReturn,
  type RiskBudget,
  type RiskCopula,
  type RiskCorrelation,
  type RiskDecision,
  type RiskDecile,
  type RiskRegime,
  type RiskReport,
  type RiskWalkForward,
} from '@/api/riskReturn'

const report = ref<RiskReport | null>(null)
const correlation = ref<RiskCorrelation | null>(null)
const correlationMessage = ref('')
const correlationError = ref('')
const regime = ref<RiskRegime | null>(null)
const regimeMessage = ref('')
const regimeError = ref('')
const budget = ref<RiskBudget | null>(null)
const budgetMessage = ref('')
const budgetError = ref('')
const walk = ref<RiskWalkForward | null>(null)
const walkMessage = ref('')
const walkError = ref('')
const copula = ref<RiskCopula | null>(null)
const copulaMessage = ref('')
const copulaError = ref('')
const decision = ref<RiskDecision | null>(null)
const decisionMessage = ref('')
const decisionError = ref('')
const message = ref('')
const error = ref('')
const loading = ref(false)
const running = ref(false)
const selectedDecile = ref(10)
const moduleTab = ref('decision')
const moduleTabs = [
  { id: 'decision', label: '决策中心' },
  { id: 'correlation', label: '五个信号组的相关性' },
  { id: 'regime', label: '按温度仓位档看收益' },
  { id: 'budget', label: '风险预算' },
  { id: 'walk', label: '参数扰动与滚动检验' },
  { id: 'copula', label: '正态相关下的同亏' },
  { id: 'mplus', label: 'M+ 十分位' },
  { id: 'kelly', label: 'Kelly 对照' },
]

const selected = computed(() => {
  return report.value?.deciles.find((row) => row.decile === selectedDecile.value) ?? null
})

const histMax = computed(() => {
  const counts = selected.value?.histogram.map((bin) => bin.count) ?? []
  return Math.max(1, ...counts)
})

const kellyMaxP20 = computed(() => {
  const values = selected.value?.scenarios.map((row) => row.probDdGt20).filter((value): value is number => value != null) ?? []
  return values.length ? Math.max(...values) : null
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

async function loadDecision() {
  decisionError.value = ''
  try {
    const payload = await fetchRiskDecision()
    if (!payload.ok) {
      decisionError.value = payload.error || '读取决策中心失败'
      return
    }
    decision.value = payload.report
    decisionMessage.value = payload.report ? '' : payload.message || '还没有决策账。'
  } catch (err) {
    decisionError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadCorrelation() {
  correlationError.value = ''
  try {
    const payload = await fetchRiskCorrelation()
    if (!payload.ok) {
      correlationError.value = payload.error || '读取相关性失败'
      return
    }
    correlation.value = payload.report
    correlationMessage.value = payload.report ? '' : payload.message || '还没有信号组收益表。'
  } catch (err) {
    correlationError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadRegime() {
  regimeError.value = ''
  try {
    const payload = await fetchRiskRegime()
    if (!payload.ok) {
      regimeError.value = payload.error || '读取温度档失败'
      return
    }
    regime.value = payload.report
    regimeMessage.value = payload.report ? '' : payload.message || '还没有温度档结果。'
  } catch (err) {
    regimeError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadBudget() {
  budgetError.value = ''
  try {
    const payload = await fetchRiskBudget()
    if (!payload.ok) {
      budgetError.value = payload.error || '读取风险预算失败'
      return
    }
    budget.value = payload.report
    budgetMessage.value = payload.report ? '' : payload.message || '还没有风险预算。'
  } catch (err) {
    budgetError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadWalk() {
  walkError.value = ''
  try {
    const payload = await fetchRiskWalkForward()
    if (!payload.ok) {
      walkError.value = payload.error || '读取滚动检验失败'
      return
    }
    walk.value = payload.report
    walkMessage.value = payload.report ? '' : payload.message || '还没有滚动检验。'
  } catch (err) {
    walkError.value = err instanceof Error ? err.message : String(err)
  }
}

async function loadCopula() {
  copulaError.value = ''
  try {
    const payload = await fetchRiskCopula()
    if (!payload.ok) {
      copulaError.value = payload.error || '读取正态相关失败'
      return
    }
    copula.value = payload.report
    copulaMessage.value = payload.report ? '' : payload.message || '还没有正态相关结果。'
  } catch (err) {
    copulaError.value = err instanceof Error ? err.message : String(err)
  }
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
  void loadDecision()
  void loadCorrelation()
  void loadRegime()
  void loadBudget()
  void loadWalk()
  void loadCopula()
})
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <h2 class="text-base font-semibold tracking-tight">风险收益 · M+ / T+3</h2>
        <p class="mt-1 text-xs text-muted-foreground">
          样本用市场中性截面里已经算好的 M+，T+3 用系统日线补上。结果写在 risk_return/output/latest.json。决策中心另读五组等权日收益和温度档，不随「运行研究」改写。日常的东财概念扫描、量价六组合、形态建仓和回测对比保持原样。
        </p>
      </div>
      <Button :disabled="running" @click="runJob">
        {{ running ? '计算中' : '运行研究' }}
      </Button>
    </div>

    <Tabs v-model="moduleTab" class="w-full">
      <TabsList class="flex h-auto w-full max-w-none flex-wrap justify-start gap-1">
        <TabsTrigger
          v-for="tab in moduleTabs"
          :key="tab.id"
          :value="tab.id"
          class="px-2.5 text-xs"
        >
          {{ tab.label }}
        </TabsTrigger>
      </TabsList>

      <TabsContent value="decision" class="space-y-3">
    <Card>
      <CardHeader>
        <CardTitle>决策中心</CardTitle>
        <p v-if="decision" class="text-sm">{{ decision.boundary }}</p>
        <CardDescription v-if="decision">
          {{ decision.sampleStart }} 至 {{ decision.sampleEnd }}，{{ decision.nDays }} 个交易日。
          状态是早于当天的温度档。候选是空仓、当时同档的四分之一凯利、温度计自己的仓位。
          效用是持有 {{ decision.horizonDays }} 日的终值收益均值，减去 {{ num(decision.lambdaTail, 0) }} 倍终值亏损的 95% CVaR。
          账上期末资金 {{ num(decision.terminalWealth, 3) }}，累计 {{ pct(decision.totalReturn, 1) }}，最大回撤 {{ pct(decision.maxDrawdown, 1) }}。
        </CardDescription>
        <CardDescription v-else>读取决策中心…</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <p v-if="decisionError" class="text-xs text-destructive">{{ decisionError }}</p>
        <p v-else-if="decisionMessage" class="text-xs text-muted-foreground">{{ decisionMessage }}</p>
        <div v-if="decision?.nextAction" class="space-y-2 px-4 text-sm">
          <p>
            市场数据：五个信号组与温度档，用到 {{ decision.nextAction.asOf }}。
          </p>
          <p>
            市场状态：{{ decision.nextAction.state }}，温度分 {{ num(decision.nextAction.score, 0) }}，
            温度计仓位 {{ pct(decision.nextAction.temperaturePosition, 0) }}，同档已有 {{ decision.nextAction.nPrior }} 天。
          </p>
          <p v-if="decision.nextAction.estimate">
            估计器：后验胜率 {{ pct(decision.nextAction.estimate.posteriorWinRate, 1) }}，
            赔率 {{ num(decision.nextAction.estimate.payoffB, 2) }}，
            研究凯利 {{ pct(decision.nextAction.estimate.kellyRaw, 1) }}。
            同档等权日收益均值 {{ pct(decision.nextAction.estimate.pdfMean, 2) }}，
            95% VaR {{ pct(decision.nextAction.estimate.pdfVar95, 2) }}，
            95% CVaR {{ pct(decision.nextAction.estimate.pdfCvar95, 2) }}。
            相关最高是 {{ decision.nextAction.estimate.maxPair || '—' }}
            {{ num(decision.nextAction.estimate.maxCorrelation, 2) }}。
            五组同日为负：历史 {{ pct(decision.nextAction.estimate.historicalAllNegative, 1) }}，
            互相独立 {{ pct(decision.nextAction.estimate.independentAllNegative, 1) }}，
            正态相关 {{ pct(decision.nextAction.estimate.gaussianAllNegative, 1) }}。
            {{ decision.nextAction.estimate.sampler }}。
          </p>
          <p>
            组间轮动：
            <span v-for="(weight, name) in decision.nextAction.weights" :key="name">
              {{ name }} {{ pct(weight, 0) }}
            </span>
            。条件均值为负的组权重为 0，后验只缩小仍为正的组。
            动态决策在这个权重上比较三个总仓位，当前动作是 {{ decision.nextAction.action }}，
            总仓位 {{ pct(decision.nextAction.position, 1) }}。
          </p>
          <p v-if="decision.nextAction.feedback">
            反馈：{{ decision.nextAction.feedback.date }} 处于{{ decision.nextAction.feedback.state }}，
            动作 {{ decision.nextAction.feedback.action }}，当日结果 {{ pct(decision.nextAction.feedback.realized, 2) }}。
            下一日状态更新为{{ decision.nextAction.feedback.nextState }}。
          </p>
        </div>
        <Table v-if="decision?.nextAction">
          <TableHeader>
            <TableRow>
              <TableHead>候选</TableHead>
              <TableHead class="text-right">仓位</TableHead>
              <TableHead class="text-right">终值收益均值</TableHead>
              <TableHead class="text-right">95% CVaR</TableHead>
              <TableHead class="text-right">效用</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in decision.nextAction.candidates" :key="row.name">
              <TableCell>
                {{ row.name }}
                <span v-if="row.chosen"> · 选中</span>
              </TableCell>
              <TableCell class="text-right">{{ pct(row.position, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.expectedReturn, 2) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.cvar95, 2) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.utility, 2) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <Table v-if="decision">
          <TableHeader>
            <TableRow>
              <TableHead>温度档</TableHead>
              <TableHead class="text-right">天数</TableHead>
              <TableHead class="text-right">平均仓位</TableHead>
              <TableHead class="text-right">当日结果均值</TableHead>
              <TableHead>最近动作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="state in decision.states" :key="state.label">
              <TableCell>{{ state.label }}</TableCell>
              <TableCell class="text-right">{{ state.nDays }}</TableCell>
              <TableCell class="text-right">{{ pct(state.meanPosition, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(state.meanRealized, 2) }}</TableCell>
              <TableCell>{{ state.lastAction }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div v-if="decision" class="max-h-96 overflow-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>日期</TableHead>
                <TableHead>状态</TableHead>
                <TableHead>动作</TableHead>
                <TableHead class="text-right">仓位</TableHead>
                <TableHead class="text-right">当日结果</TableHead>
                <TableHead class="text-right">当时样本</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in decision.ledger" :key="row.date">
                <TableCell>{{ row.date }}</TableCell>
                <TableCell>{{ row.state }}</TableCell>
                <TableCell>{{ row.action }}</TableCell>
                <TableCell class="text-right">{{ pct(row.position, 1) }}</TableCell>
                <TableCell class="text-right">{{ pct(row.realized, 2) }}</TableCell>
                <TableCell class="text-right">{{ row.nPrior }}</TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <ul v-if="decision" class="space-y-1 px-4 text-xs text-muted-foreground">
          <li v-for="note in decision.notes" :key="note">{{ note }}</li>
        </ul>
      </CardContent>
    </Card>
      </TabsContent>

      <TabsContent value="correlation" class="space-y-3">
    <p v-if="correlationError" class="text-xs text-destructive">{{ correlationError }}</p>
    <p v-else-if="correlationMessage && !correlation" class="text-xs text-muted-foreground">
      {{ correlationMessage }}
    </p>

    <Card v-if="correlation" class="shadow-none">
      <CardHeader class="pb-2">
        <CardTitle class="text-sm font-semibold">五个信号组的相关性</CardTitle>
        <p class="text-sm">
          五个信号组同日一起亏的边界是会一起跌：历史五组同日为负 {{ pct(correlation.historicalAllNegative, 1) }}，若互相独立约为 {{ pct(correlation.independentAllNegative, 1) }}。
        </p>
        <CardDescription>
          {{ correlation.sampleStart }} 至 {{ correlation.sampleEnd }}，重叠 {{ correlation.nDays }} 个交易日。
          五组同日为负：历史 {{ pct(correlation.historicalAllNegative, 1) }}，
          若互相独立约为 {{ pct(correlation.independentAllNegative, 1) }}。
          W2+W3 是「底部放量上涨」并上「上涨缩量整理」，W4+W6 是「上涨放量突破」并上「下跌放量」；近 6 个交易日每票只留最新分类，组内股票等权。
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4 px-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>信号组</TableHead>
              <TableHead v-for="name in correlation.sleeves" :key="name" class="text-right">{{ name }}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="(name, rowIndex) in correlation.sleeves" :key="name">
              <TableCell class="font-medium">{{ name }}</TableCell>
              <TableCell
                v-for="(value, colIndex) in correlation.correlation[rowIndex]"
                :key="`${name}-${colIndex}`"
                class="text-right tabular-nums"
              >
                {{ num(value, 2) }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <div class="grid gap-2 px-4 text-xs text-muted-foreground sm:grid-cols-2">
          <p>至少四组同日为负 {{ pct(correlation.historicalAtLeastFourNegative, 1) }}</p>
          <p>联合抽样同日为负 {{ pct(correlation.jointAllNegative, 1) }}</p>
          <p>
            等权持有 {{ correlation.horizonDays }} 日，回撤中位：
            联合 {{ pct(correlation.jointMedianMaxDrawdown, 1) }}，
            独立 {{ pct(correlation.independentMedianMaxDrawdown, 1) }}
          </p>
          <p>
            回撤超过 20%：联合 {{ pct(correlation.jointProbDdGt20, 1) }}，
            独立 {{ pct(correlation.independentProbDdGt20, 1) }}
          </p>
        </div>
        <ul class="space-y-1 px-4 text-xs text-muted-foreground">
          <li v-for="note in correlation.notes" :key="note">{{ note }}</li>
        </ul>
      </CardContent>
    </Card>
      </TabsContent>

      <TabsContent value="regime" class="space-y-3">
    <Card>
      <CardHeader>
        <CardTitle>按温度仓位档看收益</CardTitle>
        <p v-if="regime" class="text-sm">
          五组日收益均值一起为正的边界在温度分 67–75，低于约 37 时五组日收益均值一起为负。
        </p>
        <CardDescription v-if="regime">
          {{ regime.sampleStart }} 至 {{ regime.sampleEnd }}，{{ regime.nDays }} 个交易日。
          收益日只用严格早于该日的温度计仓位档。表内是各信号组的日收益均值。
        </CardDescription>
        <CardDescription v-else>读取温度档…</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <p v-if="regimeError" class="text-xs text-destructive">{{ regimeError }}</p>
        <p v-else-if="regimeMessage" class="text-xs text-muted-foreground">{{ regimeMessage }}</p>
        <Table v-if="regime">
          <TableHeader>
            <TableRow>
              <TableHead>仓位档</TableHead>
              <TableHead class="text-right">天数</TableHead>
              <TableHead class="text-right">温度分</TableHead>
              <TableHead v-for="name in regime.sleeves" :key="name" class="text-right">
                {{ name }}
              </TableHead>
              <TableHead class="text-right">五组同日为负</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="state in regime.states" :key="state.label">
              <TableCell>{{ state.label }}</TableCell>
              <TableCell class="text-right">
                {{ state.nDays }}
                <span v-if="state.smallSample" class="text-muted-foreground">样本少</span>
              </TableCell>
              <TableCell class="text-right">{{ num(state.meanScore, 1) }}</TableCell>
              <TableCell
                v-for="name in regime.sleeves"
                :key="`${state.label}-${name}`"
                class="text-right"
              >
                {{ pct(state.means[name] ?? null, 2) }}
              </TableCell>
              <TableCell class="text-right">{{ pct(state.allNegative, 1) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <ul v-if="regime" class="space-y-1 px-4 text-xs text-muted-foreground">
          <li v-for="note in regime.notes" :key="note">{{ note }}</li>
        </ul>
      </CardContent>
    </Card>
      </TabsContent>

      <TabsContent value="budget" class="space-y-3">
    <Card>
      <CardHeader>
        <CardTitle>风险预算</CardTitle>
        <p v-if="budget" class="text-sm">
          这条等权日收益能撑住的仓位边界大约是 {{ pct(budget.kellyRaw, 1) }}，温度计离开空仓后的最小档是 20%，已经在这条边界外面。
        </p>
        <CardDescription v-if="budget">
          {{ budget.sampleStart }} 至 {{ budget.sampleEnd }}，{{ budget.nDays }} 个交易日。
          同一条五组等权日收益，分别用满仓、温度仓位、四分之一凯利，以及两者中较小的仓位走一遍。
          后验胜率 {{ pct(budget.posteriorWinRate, 1) }}，赔率 {{ num(budget.payoffB, 2) }}，
          研究凯利 {{ pct(budget.kellyRaw, 1) }}，四分之一为 {{ pct(budget.quarterPosition, 1) }}。
        </CardDescription>
        <CardDescription v-else>读取风险预算…</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <p v-if="budgetError" class="text-xs text-destructive">{{ budgetError }}</p>
        <p v-else-if="budgetMessage" class="text-xs text-muted-foreground">{{ budgetMessage }}</p>
        <Table v-if="budget">
          <TableHeader>
            <TableRow>
              <TableHead>预算</TableHead>
              <TableHead class="text-right">平均仓位</TableHead>
              <TableHead class="text-right">期末资金</TableHead>
              <TableHead class="text-right">累计收益</TableHead>
              <TableHead class="text-right">最大回撤</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in budget.budgets" :key="row.name">
              <TableCell>{{ row.name }}</TableCell>
              <TableCell class="text-right">{{ pct(row.averagePosition, 1) }}</TableCell>
              <TableCell class="text-right">{{ num(row.terminalWealth, 3) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.totalReturn, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.maxDrawdown, 1) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <ul v-if="budget" class="space-y-1 px-4 text-xs text-muted-foreground">
          <li v-for="note in budget.notes" :key="note">{{ note }}</li>
        </ul>
      </CardContent>
    </Card>
      </TabsContent>

      <TabsContent value="walk" class="space-y-3">
    <Card>
      <CardHeader>
        <CardTitle>参数扰动与滚动检验</CardTitle>
        <p v-if="walk" class="text-sm">{{ walk.boundary }}</p>
        <CardDescription v-if="walk">
          测试段 {{ walk.oosStart }} 至 {{ walk.oosEnd }}，{{ walk.nFolds }} 轮。
          每轮用过去 {{ walk.trainDays }} 个交易日估计，后面 {{ walk.testDays }} 个交易日才记账。
          下表仓位是 0.25 倍研究凯利。
        </CardDescription>
        <CardDescription v-else>读取滚动检验…</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <p v-if="walkError" class="text-xs text-destructive">{{ walkError }}</p>
        <p v-else-if="walkMessage" class="text-xs text-muted-foreground">{{ walkMessage }}</p>
        <Table v-if="walk">
          <TableHeader>
            <TableRow>
              <TableHead>分数</TableHead>
              <TableHead class="text-right">期末资金</TableHead>
              <TableHead class="text-right">测试期累计</TableHead>
              <TableHead class="text-right">最大回撤</TableHead>
              <TableHead class="text-right">最差一轮</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="row in walk.perturbations" :key="row.fraction">
              <TableCell>{{ num(row.fraction, 2) }}</TableCell>
              <TableCell class="text-right">{{ num(row.terminalWealth, 3) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.totalReturn, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.maxDrawdown, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(row.worstFoldReturn, 1) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <Table v-if="walk">
          <TableHeader>
            <TableRow>
              <TableHead>测试段</TableHead>
              <TableHead class="text-right">预测亏损</TableHead>
              <TableHead class="text-right">实际亏损</TableHead>
              <TableHead class="text-right">仓位</TableHead>
              <TableHead class="text-right">测试收益</TableHead>
              <TableHead class="text-right">温度仓位收益</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="fold in walk.folds" :key="fold.testStart">
              <TableCell>{{ fold.testStart }}</TableCell>
              <TableCell class="text-right">{{ pct(fold.predictedLossProb, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(fold.realizedLossRate, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(fold.position, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(fold.testReturn, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(fold.temperatureReturn, 1) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <ul v-if="walk" class="space-y-1 px-4 text-xs text-muted-foreground">
          <li v-for="note in walk.notes" :key="note">{{ note }}</li>
        </ul>
      </CardContent>
    </Card>
      </TabsContent>

      <TabsContent value="copula" class="space-y-3">
    <Card>
      <CardHeader>
        <CardTitle>正态相关下的同亏</CardTitle>
        <p v-if="copula" class="text-sm">{{ copula.boundary }}</p>
        <CardDescription v-if="copula">
          {{ copula.sampleStart }} 至 {{ copula.sampleEnd }}，{{ copula.nDays }} 个交易日。
          底部 {{ pct(copula.tailQ, 0) }} 是每个信号组自己最差的一成日子。
        </CardDescription>
        <CardDescription v-else>读取正态相关…</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <p v-if="copulaError" class="text-xs text-destructive">{{ copulaError }}</p>
        <p v-else-if="copulaMessage" class="text-xs text-muted-foreground">{{ copulaMessage }}</p>
        <Table v-if="copula">
          <TableHeader>
            <TableRow>
              <TableHead>对照</TableHead>
              <TableHead class="text-right">五组同日为负</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow>
              <TableCell>历史</TableCell>
              <TableCell class="text-right">{{ pct(copula.historicalAllNegative, 1) }}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>正态相关</TableCell>
              <TableCell class="text-right">{{ pct(copula.gaussianAllNegative, 1) }}</TableCell>
            </TableRow>
            <TableRow>
              <TableCell>互相独立</TableCell>
              <TableCell class="text-right">{{ pct(copula.independentAllNegative, 1) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <Table v-if="copula">
          <TableHeader>
            <TableRow>
              <TableHead>一对</TableHead>
              <TableHead class="text-right">底部同时出现</TableHead>
              <TableHead class="text-right">正态相关</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="pair in copula.pairs" :key="`${pair.left}-${pair.right}`">
              <TableCell>{{ pair.left }} · {{ pair.right }}</TableCell>
              <TableCell class="text-right">{{ pct(pair.historical, 1) }}</TableCell>
              <TableCell class="text-right">{{ pct(pair.gaussian, 1) }}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
        <ul v-if="copula" class="space-y-1 px-4 text-xs text-muted-foreground">
          <li v-for="note in copula.notes" :key="note">{{ note }}</li>
        </ul>
      </CardContent>
    </Card>
      </TabsContent>

      <TabsContent value="mplus" class="space-y-3">
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
          <p class="text-sm">
            M+ 从低到高没有把 T+3 分布变好，边界在 Q8：胜率从这里跌破 50%，到 Q10 时 VaR 95% 为 -11.9%、CVaR 95% 为 -15.4%。
          </p>
          <CardDescription>Q1 为最低，Q10 为最高。点一行查看该分位的 T+3 分布。</CardDescription>
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

      <Card v-if="selected" class="shadow-none">
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

      <ul class="space-y-1 text-xs text-muted-foreground">
        <li v-for="note in report.notes" :key="note">{{ note }}</li>
        <li>结果时间 {{ report.createdAt }}</li>
      </ul>
    </template>
      </TabsContent>

      <TabsContent value="kelly" class="space-y-3">
    <p v-if="loading" class="text-xs text-muted-foreground">正在读取上次结果…</p>
    <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
    <p v-else-if="message && !report" class="text-xs text-muted-foreground">{{ message }}</p>
    <template v-if="report">
      <div class="flex flex-wrap gap-1">
        <Button
          v-for="row in report.deciles"
          :key="row.decile"
          size="sm"
          :variant="row.decile === selectedDecile ? 'default' : 'outline'"
          @click="selectRow(row)"
        >
          {{ row.label }}
        </Button>
      </div>
      <Card v-if="selected" class="shadow-none">
          <CardHeader class="pb-2">
            <CardTitle class="text-sm font-semibold">Kelly 对照</CardTitle>
            <p v-if="selected.scenarios.length" class="text-sm">
              {{ selected.label }} 的分数凯利边界在终值而不在 20% 回撤：满凯利仓位 {{ pct(selected.scenarios[0].position, 1) }}、终值中位 {{ num(selected.scenarios[0].medianTerminalWealth, 3) }}、回撤中位 {{ pct(selected.scenarios[0].medianMaxDrawdown, 1) }}，降到四分之一后终值中位 {{ num(selected.scenarios[3].medianTerminalWealth, 3) }}、回撤中位 {{ pct(selected.scenarios[3].medianMaxDrawdown, 1) }}，四档回撤超过 20% 的路径最高 {{ pct(kellyMaxP20, 1) }}。
            </p>
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
    </template>
      </TabsContent>
    </Tabs>
  </div>
</template>
