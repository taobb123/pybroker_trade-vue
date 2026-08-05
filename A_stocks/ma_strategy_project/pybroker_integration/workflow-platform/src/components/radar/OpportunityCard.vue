<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  SCORE_DIMENSION_LABELS,
  VERDICT_LABEL,
  type ScoreDimensionKey,
} from '@/config/opportunityRules'
import type { ScoredOpportunity } from '@/domain/opportunity'
import { useWatchlistStore } from '@/stores/watchlist'
import { useWorkflowStore } from '@/stores/workflow'

const props = defineProps<{
  item: ScoredOpportunity
}>()

const router = useRouter()
const watchlist = useWatchlistStore()
const workflow = useWorkflowStore()

const scoreRows = computed(() =>
  props.item.dimensions.map((key: ScoreDimensionKey) => ({
    key,
    label: SCORE_DIMENSION_LABELS[key],
    value: props.item.scores[key],
  })),
)

const isGood = computed(() => props.item.verdict === 'good')
const inWatch = computed(() => watchlist.has(props.item.id))

const hasReport = computed(() => {
  const stepId = props.item.stepId
  if (!stepId) return false
  return workflow.runs.some((r) => r.stepId === stepId && (r.status === 'success' || r.outputs.length))
})

function openResearch() {
  if (!props.item.stepId) {
    void router.push('/workflows')
    return
  }
  void router.push({ path: '/workflows', query: { step: props.item.stepId } })
}

function openReport() {
  if (!props.item.stepId) {
    void router.push('/reports')
    return
  }
  void router.push({ path: '/reports', query: { step: props.item.stepId } })
}

function toggleWatch() {
  if (inWatch.value) {
    watchlist.removeByOpportunity(props.item.id)
    return
  }
  const result = watchlist.addFromOpportunity({
    opportunityId: props.item.id,
    symbol: props.item.symbol,
    name: props.item.name,
    price: props.item.price,
    idealLow: props.item.idealLow,
    idealHigh: props.item.idealHigh,
    thesis: props.item.thesis,
    risk: props.item.risk,
    stepId: props.item.stepId,
  })
  if (!result.ok) {
    if (result.upgrade) {
      if (confirm(`${result.reason}\n\n前往套餐页？`)) {
        void router.push('/billing/plans')
      }
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
            <span class="font-mono text-sm font-normal text-muted-foreground">{{ item.symbol }}</span>
          </h3>
          <Badge
            :variant="isGood ? 'default' : 'secondary'"
            :class="isGood ? 'bg-emerald-600 text-white hover:bg-emerald-600' : ''"
          >
            {{ VERDICT_LABEL[item.verdict] }}
          </Badge>
        </div>
        <p class="mt-1 text-sm text-muted-foreground">
          现在是不是好球？
          <span class="font-medium text-foreground">{{ isGood ? '是' : '等待' }}</span>
        </p>
      </div>
      <div class="text-right">
        <p class="text-[11px] text-muted-foreground">规则综合分</p>
        <p class="text-2xl font-semibold tabular-nums">
          {{ item.composite ?? '—' }}
        </p>
      </div>
    </div>

    <dl class="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
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

    <div class="mt-3 space-y-1.5 text-sm">
      <p>
        <span class="text-muted-foreground">逻辑：</span>{{ item.thesis }}
      </p>
      <p>
        <span class="text-muted-foreground">风险：</span>{{ item.risk }}
      </p>
      <p
        v-if="item.price != null && item.idealLow != null && item.idealHigh != null"
        class="text-muted-foreground"
      >
        现价 {{ item.price }} · 理想买入区 {{ item.idealLow }}–{{ item.idealHigh }}
      </p>
    </div>

    <div class="mt-4 flex flex-wrap gap-2">
      <Button size="sm" variant="outline" @click="openResearch">
        打开研究工作流
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
