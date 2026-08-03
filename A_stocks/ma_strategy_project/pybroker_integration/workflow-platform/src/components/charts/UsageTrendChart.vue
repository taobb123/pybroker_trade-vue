<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { LineChart } from 'echarts/charts'
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'
import type { TrendPoint } from '@/stores/usage'

use([CanvasRenderer, LineChart, GridComponent, TooltipComponent, LegendComponent])

const props = defineProps<{
  points: TrendPoint[]
}>()

const option = computed(() => {
  const labels = props.points.map((p) => p.date.slice(5))
  const values = props.points.map((p) => p.visits)
  return {
    grid: { left: 40, right: 16, top: 24, bottom: 28 },
    tooltip: { trigger: 'axis' },
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: false,
      axisLabel: { color: '#71717a', fontSize: 10 },
      axisTick: { show: false },
      axisLine: { lineStyle: { color: '#e4e4e7' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#71717a', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f4f4f5' } },
    },
    series: [
      {
        name: '访问',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: values,
        lineStyle: { width: 2, color: '#18181b' },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(24,24,27,0.12)' },
              { offset: 1, color: 'rgba(24,24,27,0)' },
            ],
          },
        },
      },
    ],
  }
})
</script>

<template>
  <VChart class="h-64 w-full" :option="option" autoresize />
</template>
