<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import * as echarts from 'echarts'
import { Button } from '@/components/ui/button'
import {
  toCandlestickOption,
  type PredictionChart,
  type PredictionKlinePayload,
} from '@/api/kline'
import {
  canSeePitchKlineLevels,
  UPGRADE_KLINE_LEVELS_CTA,
} from '@/config/radarLimits'
import {
  formatLevel,
  levelValue,
  T_LEVEL_ORDER,
  type TLevels,
} from '@/data/tLevels'
import { useAuthStore } from '@/stores/auth'
import { trackEvent } from '@/api/events'

const props = defineProps<{
  symbol: string
  stockName: string
  levels: TLevels | null
  klinePayload: PredictionKlinePayload | null
}>()

const router = useRouter()
const auth = useAuthStore()
const host = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null

const locked = computed(() => {
  const plan = auth.user?.plan ?? 'free'
  return !canSeePitchKlineLevels(plan)
})

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
  opt.grid = { left: 36, right: 4, top: 8, bottom: 22, containLabel: false }
  chart.setOption(opt, true)
  chart.resize()
}

watch(
  () => [matchedChart.value, props.levels, host.value, locked.value] as const,
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

function goPro() {
  trackEvent('click_upgrade', { from: 'pitch_kline_levels_lock' })
  void router.push('/billing/plans')
}

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chart?.dispose()
  chart = null
})
</script>

<template>
  <div class="relative">
    <div
      class="flex items-stretch gap-3"
      :class="locked && 'select-none'"
    >
      <div
        class="min-w-0 flex-[1.1] max-w-[58%]"
        :class="locked && 'pointer-events-none blur-[6px] opacity-70'"
      >
        <div
          v-if="matchedChart"
          ref="host"
          class="h-[148px] w-full sm:h-[160px]"
        />
        <div
          v-else
          class="flex h-[148px] items-center justify-center rounded-md border border-dashed bg-muted/30 px-2 text-center text-[11px] text-muted-foreground sm:h-[160px]"
        >
          暂无该标的预测 K 线。请先运行「做 T 止盈止损」。
        </div>
      </div>

      <aside
        class="flex w-[7.25rem] shrink-0 flex-col justify-center gap-1 rounded-lg border-2 border-foreground/15 bg-background px-2 py-2.5 shadow-sm sm:w-[8rem]"
        :class="locked && 'pointer-events-none blur-[6px] opacity-70'"
      >
        <p class="mb-0.5 text-center text-[11px] font-semibold tracking-wide text-foreground">
          做T档位
        </p>
        <div
          v-for="key in T_LEVEL_ORDER"
          :key="key"
          class="flex items-center justify-between gap-1 rounded-md px-1.5 py-1"
          :class="{
            'bg-emerald-100 text-emerald-950 dark:bg-emerald-950/50 dark:text-emerald-100':
              key.startsWith('买'),
            'bg-rose-100 text-rose-950 dark:bg-rose-950/50 dark:text-rose-100':
              key.startsWith('卖'),
            'bg-amber-100 text-amber-950 ring-1 ring-amber-300/60 dark:bg-amber-950/40 dark:text-amber-100':
              key === '高价' || key === '低价',
          }"
        >
          <span class="text-[11px] font-medium opacity-80">{{ key }}</span>
          <span class="text-[12px] font-bold tabular-nums sm:text-[13px]">
            {{ formatLevel(levelValue(levels, key)) }}
          </span>
        </div>
        <p
          v-if="!levels"
          class="mt-1 text-center text-[10px] text-muted-foreground"
        >
          无做T结果
        </p>
      </aside>
    </div>

    <div
      v-if="locked"
      class="absolute inset-0 z-10 flex items-center justify-center rounded-lg bg-background/35 px-3 backdrop-blur-[1px]"
    >
      <div
        class="max-w-[16rem] rounded-lg border bg-background/95 px-3 py-3 text-center shadow-md"
      >
        <p class="text-xs font-semibold text-foreground">{{ UPGRADE_KLINE_LEVELS_CTA }}</p>
        <p class="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Free 可看选球摘要；清晰预测 K 线与买一/买二等档位需升级 Pro。
        </p>
        <Button size="sm" class="mt-2.5" @click="goPro">升级 Pro</Button>
      </div>
    </div>
  </div>
</template>
