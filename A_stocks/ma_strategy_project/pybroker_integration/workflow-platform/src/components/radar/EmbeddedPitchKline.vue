<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import {
  toCandlestickOption,
  type PredictionChart,
  type PredictionKlinePayload,
} from '@/api/kline'
import {
  formatLevel,
  levelValue,
  T_LEVEL_ORDER,
  type TLevels,
} from '@/data/tLevels'

const props = defineProps<{
  symbol: string
  stockName: string
  levels: TLevels | null
  klinePayload: PredictionKlinePayload | null
}>()

const host = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const matchedChart = computed((): PredictionChart | null => {
  const list = props.klinePayload?.charts ?? []
  const sym = props.symbol.replace(/\D/g, '').slice(-6)
  return (
    list.find((c) => String(c.symbol).replace(/\D/g, '').slice(-6) === sym) ||
    list.find((c) => (c.symbol_name || '') === props.stockName) ||
    null
  )
})

async function render() {
  const el = host.value
  const c = matchedChart.value
  if (!el || !c) {
    chart?.clear()
    return
  }
  if (!chart) chart = echarts.init(el)
  const opt = toCandlestickOption(c) as Record<string, unknown>
  opt.grid = { left: 44, right: 8, top: 12, bottom: 28, containLabel: false }
  chart.setOption(opt, true)
  chart.resize()
}

watch(
  () => [matchedChart.value, props.levels, host.value] as const,
  () => {
    void render()
  },
  { flush: 'post' },
)

onMounted(() => {
  void render()
  window.addEventListener('resize', onResize)
})

function onResize() {
  chart?.resize()
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="flex min-h-[200px] gap-2">
    <div class="min-w-0 flex-1">
      <div
        v-if="matchedChart"
        ref="host"
        class="h-[200px] w-full"
      />
      <div
        v-else
        class="flex h-[200px] items-center justify-center rounded-md border border-dashed bg-muted/30 px-3 text-center text-xs text-muted-foreground"
      >
        预测 K 线暂无该标的。请先把代码加入做 T 列表并运行「做 T 止盈止损」。
      </div>
    </div>

    <aside
      class="flex w-[4.75rem] shrink-0 flex-col justify-center gap-0.5 rounded-md border bg-muted/30 px-1.5 py-2 text-[10px] leading-tight"
    >
      <p class="mb-1 text-center text-[9px] font-medium text-muted-foreground">
        做T档位
      </p>
      <div
        v-for="key in T_LEVEL_ORDER"
        :key="key"
        class="flex flex-col items-center rounded px-0.5 py-0.5"
        :class="{
          'bg-emerald-100/80 text-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100':
            key.startsWith('买'),
          'bg-rose-100/80 text-rose-900 dark:bg-rose-950/40 dark:text-rose-100':
            key.startsWith('卖'),
          'bg-amber-100/80 text-amber-950 dark:bg-amber-950/40 dark:text-amber-100':
            key === '高价' || key === '低价',
        }"
      >
        <span class="opacity-70">{{ key }}</span>
        <span class="font-semibold tabular-nums">
          {{ formatLevel(levelValue(levels, key)) }}
        </span>
      </div>
      <p
        v-if="!levels"
        class="mt-1 text-center text-[9px] text-muted-foreground"
      >
        无做T结果
      </p>
    </aside>
  </div>
</template>
