<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { fetchWorkspaceFile } from '@/api/workflow'
import {
  chartRiseFallLabel,
  chartStockName,
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

const headerTitle = computed(() => {
  if (!payload.value) return ''
  const n = payload.value.charts.length
  return n > 1 ? `预测 K 线 · ${n} 只` : '预测 K 线'
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

function riseFallClass(chart: PredictionChart): string {
  const label = chartRiseFallLabel(chart)
  if (label === '涨') return 'bg-red-600 text-white'
  if (label === '跌') return 'bg-emerald-600 text-white'
  return 'bg-muted text-muted-foreground'
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
    <p v-if="payload" class="text-sm font-semibold text-foreground">{{ headerTitle }}</p>

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
          <span class="text-sm font-semibold text-foreground">
            {{ chartStockName(chart) }}
          </span>
          <span
            class="rounded px-2 py-0.5 text-xs font-bold"
            :class="riseFallClass(chart)"
          >
            {{ chartRiseFallLabel(chart) }}
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
