<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import EmbeddedPitchKline from '@/components/radar/EmbeddedPitchKline.vue'
import {
  SCORE_DIMENSION_LABELS,
  VERDICT_LABEL,
  type ScoreDimensionKey,
} from '@/config/opportunityRules'
import { scoreOpportunity } from '@/domain/opportunity'
import type { PitchCandidate } from '@/data/selectPitches'
import type { TLevels } from '@/data/tLevels'
import type { PredictionKlinePayload } from '@/api/kline'
import { useWatchlistStore } from '@/stores/watchlist'
import { useWorkflowStore } from '@/stores/workflow'

const props = defineProps<{
  pitch: PitchCandidate
  levels: TLevels | null
  klinePayload: PredictionKlinePayload | null
}>()

const router = useRouter()
const watchlist = useWatchlistStore()
const workflow = useWorkflowStore()

const scored = computed(() => scoreOpportunity(props.pitch.opportunity))
const item = computed(() => scored.value)
const isGood = computed(() => item.value.verdict === 'good')
const inWatch = computed(() => watchlist.has(item.value.id))

const scoreRows = computed(() =>
  (['trend', 'fundamental', 'flow', 'valuation'] as ScoreDimensionKey[]).map((key) => ({
    key,
    label: SCORE_DIMENSION_LABELS[key],
    value: item.value.scores[key],
  })),
)

const hasReport = computed(() => {
  const stepId = item.value.stepId
  if (!stepId) return false
  return workflow.runs.some(
    (r) => r.stepId === stepId && (r.status === 'success' || r.outputs.length),
  )
})

function openResearch() {
  void router.push({ path: '/workflows', query: { step: item.value.stepId || 'market_neutral' } })
}

function openReport() {
  void router.push({
    path: '/reports',
    query: { step: item.value.stepId || 'compute_today' },
  })
}

function openComputeToday() {
  void router.push({ path: '/workflows', query: { step: 'compute_today' } })
}

function toggleWatch() {
  if (inWatch.value) {
    watchlist.removeByOpportunity(item.value.id)
    return
  }
  const o = item.value
  const result = watchlist.addFromOpportunity({
    opportunityId: o.id,
    symbol: o.symbol,
    name: o.name,
    price: o.price,
    idealLow: o.idealLow,
    idealHigh: o.idealHigh,
    thesis: o.thesis,
    risk: o.risk,
    stepId: o.stepId,
  })
  if (!result.ok) {
    if (result.upgrade) {
      if (confirm(`${result.reason}\n\n前往套餐页？`)) void router.push('/billing/plans')
      return
    }
    alert(result.reason)
  }
}
</script>

<template>
  <article class="rounded-xl border bg-card p-4 shadow-sm">
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
            :variant="isGood ? 'default' : 'secondary'"
            :class="isGood ? 'bg-emerald-600 text-white hover:bg-emerald-600' : ''"
          >
            {{ VERDICT_LABEL[item.verdict] }}
          </Badge>
          <Badge variant="outline">
            {{ pitch.factorLabel }} · 第{{ pitch.factorRank }}
          </Badge>
        </div>
        <p class="mt-1 text-sm text-muted-foreground">
          现在是不是好球？
          <span class="font-medium text-foreground">{{ isGood ? '是' : '等待' }}</span>
        </p>
      </div>
      <div class="text-right">
        <p class="text-[11px] text-muted-foreground">规则综合分</p>
        <p class="text-2xl font-semibold tabular-nums">{{ item.composite ?? '—' }}</p>
        <p class="text-[10px] text-muted-foreground">
          多头净值 {{ (pitch.longNav * 100).toFixed(1) }}%
        </p>
      </div>
    </div>

    <dl class="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
      <div
        v-for="row in scoreRows"
        :key="row.key"
        class="rounded-lg bg-muted/40 px-2.5 py-2"
      >
        <dt class="text-[11px] text-muted-foreground">{{ row.label }}</dt>
        <dd class="text-sm font-semibold tabular-nums">
          {{ row.value == null ? '—' : row.value }}
        </dd>
      </div>
    </dl>

    <div class="mt-3 space-y-1 text-sm">
      <p><span class="text-muted-foreground">逻辑：</span>{{ item.thesis }}</p>
      <p><span class="text-muted-foreground">风险：</span>{{ item.risk }}</p>
      <p
        v-if="item.price != null"
        class="text-muted-foreground"
      >
        现价 {{ item.price }}
        <template v-if="item.idealLow != null && item.idealHigh != null">
          · 理想买入区 {{ item.idealLow }}–{{ item.idealHigh }}
        </template>
      </p>
    </div>

    <div class="mt-4">
      <EmbeddedPitchKline
        :symbol="item.symbol"
        :stock-name="item.name"
        :levels="levels"
        :kline-payload="klinePayload"
      />
    </div>

    <div class="mt-4 flex flex-wrap gap-2">
      <Button size="sm" variant="outline" @click="openResearch">
        打开市场中性工作流
      </Button>
      <Button size="sm" variant="outline" @click="openComputeToday">
        做 T 止盈止损
      </Button>
      <Button size="sm" variant="outline" @click="openReport">
        {{ hasReport ? '查看相关报告' : '打开报告页' }}
      </Button>
      <Button
        size="sm"
        :variant="inWatch ? 'secondary' : 'default'"
        @click="toggleWatch"
      >
        {{ inWatch ? '已在观察池 · 移出' : '加入观察池' }}
      </Button>
    </div>
  </article>
</template>
