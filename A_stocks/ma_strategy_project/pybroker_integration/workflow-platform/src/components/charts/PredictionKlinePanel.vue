<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { fetchWorkspaceFile } from '@/api/workflow'
import {
  chartBlockTitle,
  getChartSignal,
  isPredictionKlinePath,
  parsePredictionKlineJson,
  toCandlestickOption,
  type PredictionChart,
  type PredictionKlinePayload,
} from '@/api/kline'

const props = defineProps<{ path: string }>()

const loading = ref(false)
const error = ref('')
const payload = ref<PredictionKlinePayload | null>(null)
const hostEls = new Map<number, HTMLElement>()

const charts: echarts.ECharts[] = []
let resizeObserver: ResizeObserver | null = null
let renderToken = 0

const historyDays = computed(
  () => payload.value?.history_days || payload.value?.charts?.[0]?.history_days || 20,
)

const headerTitle = computed(() => {
  if (!payload.value) return ''
  const n = payload.value.charts.length
  const model = payload.value.model_label || payload.value.charts[0]?.model_label || '结果1+2 · 综合预测高低'
  return `预测 K 线（结果1+2 综合高低）· ${n} 只 · ${model} · ${historyDays.value}+1 根`
})

function setHostRef(el: unknown, idx: number) {
  if (el instanceof HTMLElement) hostEls.set(idx, el)
  else hostEls.delete(idx)
}

function disposeCharts() {
  while (charts.length) {
    charts.pop()?.dispose()
  }
}

function waitForSize(el: HTMLElement, tries = 20): Promise<boolean> {
  return new Promise((resolve) => {
    let n = 0
    const tick = () => {
      if (el.clientWidth >= 8 && el.clientHeight >= 8) {
        resolve(true)
        return
      }
      n += 1
      if (n >= tries) {
        el.style.width = '100%'
        el.style.height = '220px'
        resolve(el.clientWidth >= 8 || el.offsetParent != null)
        return
      }
      requestAnimationFrame(tick)
    }
    tick()
  })
}

async function renderCharts() {
  const token = ++renderToken
  disposeCharts()
  await nextTick()
  if (token !== renderToken) return

  const list = payload.value?.charts ?? []
  if (!list.length) return

  for (let w = 0; w < 30 && hostEls.size < list.length; w++) {
    await new Promise<void>((r) => requestAnimationFrame(() => r()))
    if (token !== renderToken) return
  }

  resizeObserver?.disconnect()
  resizeObserver = new ResizeObserver(() => {
    charts.forEach((c) => c.resize())
  })

  for (let i = 0; i < list.length; i++) {
    if (token !== renderToken) return
    const el = hostEls.get(i)
    const chartData = list[i]
    if (!el || !chartData) continue

    await waitForSize(el)
    if (token !== renderToken) return

    const instance = echarts.init(el, undefined, { renderer: 'canvas' })
    instance.setOption(toCandlestickOption(chartData), { notMerge: true })
    instance.resize()
    charts.push(instance)
    resizeObserver.observe(el)
  }
}

async function load() {
  error.value = ''
  payload.value = null
  disposeCharts()
  hostEls.clear()
  if (!props.path || !isPredictionKlinePath(props.path)) {
    error.value = '当前路径不是预测 K 线 JSON'
    return
  }
  loading.value = true
  const file = await fetchWorkspaceFile(props.path)
  loading.value = false
  if (!file.exists || !file.content) {
    error.value = '文件不存在或为空。请先运行「做 T 止盈止损」(compute_today)。'
    return
  }
  const parsed = parsePredictionKlineJson(file.content)
  if (!parsed) {
    error.value = 'JSON 解析失败或缺少 charts 数据'
    return
  }
  payload.value = parsed
  await nextTick()
  await renderCharts()
}

function onWinResize() {
  charts.forEach((c) => c.resize())
}

function predBadgeClass(chart: PredictionChart): string {
  const dir = getChartSignal(chart)?.predicted_direction || 'flat'
  if (dir === 'up') return 'bg-gradient-to-b from-red-500 to-red-700 text-white border-red-400'
  if (dir === 'down') return 'bg-gradient-to-b from-emerald-500 to-emerald-700 text-white border-emerald-400'
  return 'bg-muted text-muted-foreground border-border'
}

function barBadgeClass(chart: PredictionChart): string {
  const dir = getChartSignal(chart)?.t1_pred_direction || 'flat'
  if (dir === 'red') return 'border-red-300 bg-red-50 text-red-700'
  if (dir === 'green') return 'border-emerald-300 bg-emerald-50 text-emerald-700'
  return 'border-border bg-muted text-muted-foreground'
}

function predBadgeText(chart: PredictionChart): string {
  const sig = getChartSignal(chart)
  return `预测${sig?.predicted_direction_label || sig?.predicted_direction || '?'}`
}

function barBadgeText(chart: PredictionChart): string {
  const sig = getChartSignal(chart)
  return `T+1 ${sig?.t1_pred_direction_label || sig?.t1_pred_direction || '信号'}`
}

onMounted(() => {
  window.addEventListener('resize', onWinResize)
  void load()
})

onBeforeUnmount(() => {
  renderToken += 1
  window.removeEventListener('resize', onWinResize)
  resizeObserver?.disconnect()
  resizeObserver = null
  disposeCharts()
})

watch(
  () => props.path,
  () => {
    void load()
  },
)
</script>

<template>
  <div class="space-y-3">
    <div v-if="payload" class="space-y-1">
      <p class="text-sm font-semibold text-foreground">{{ headerTitle }}</p>
      <p class="text-[11px] text-muted-foreground">
        🟧 高/低 = 四数综合区间 · 非真实开收 · 红涨绿跌 · 末根 = 未来预测日
      </p>
    </div>

    <p v-if="loading" class="py-10 text-center text-sm text-muted-foreground">加载预测 K 线…</p>
    <p
      v-else-if="error"
      class="rounded-md border border-amber-200 bg-amber-50 px-3 py-4 text-sm text-amber-800"
    >
      {{ error }}
    </p>
    <div v-else-if="payload" class="space-y-4">
      <div
        v-for="(chart, idx) in payload.charts"
        :key="`${chart.symbol}-${idx}`"
        class="overflow-hidden rounded-lg border bg-white p-3"
      >
        <div class="mb-2 flex flex-wrap items-center gap-2">
          <template v-if="getChartSignal(chart)">
            <span
              class="rounded px-2.5 py-0.5 text-[13px] font-extrabold tracking-wide border shadow-sm"
              :class="predBadgeClass(chart)"
            >
              {{ predBadgeText(chart) }}
            </span>
            <span
              class="rounded border px-1.5 py-0.5 text-[11px] font-semibold"
              :class="barBadgeClass(chart)"
            >
              {{ barBadgeText(chart) }}
            </span>
          </template>
          <span class="text-xs font-semibold text-foreground">
            {{ chartBlockTitle(chart, historyDays) }}
          </span>
        </div>
        <div
          :ref="(el) => setHostRef(el, idx)"
          class="w-full"
          style="height: 220px; min-height: 220px; width: 100%"
        />
      </div>
    </div>
  </div>
</template>
