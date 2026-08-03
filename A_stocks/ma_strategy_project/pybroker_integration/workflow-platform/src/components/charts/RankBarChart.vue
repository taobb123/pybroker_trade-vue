<script setup lang="ts">
import { computed } from 'vue'
import { use } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent } from 'echarts/components'
import VChart from 'vue-echarts'
import type { RankRow } from '@/api/parse'

use([CanvasRenderer, BarChart, GridComponent, TooltipComponent, LegendComponent])

const props = defineProps<{
  rows: RankRow[]
  valueKey: string
  title?: string
}>()

const option = computed(() => {
  const data = [...props.rows]
    .filter((r) => typeof r[props.valueKey] === 'number')
    .slice(0, 12)
    .reverse()

  const labels = data.map((r) => r.name || r.symbol || String(r.rank))
  const values = data.map((r) => Number(r[props.valueKey]))

  return {
    title: props.title
      ? {
          text: props.title,
          left: 0,
          textStyle: { fontSize: 13, fontWeight: 600, color: '#18181b' },
        }
      : undefined,
    grid: { left: 88, right: 24, top: props.title ? 40 : 16, bottom: 24 },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
    },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#71717a' },
      splitLine: { lineStyle: { color: '#f4f4f5' } },
    },
    yAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#3f3f46', width: 72, overflow: 'truncate' },
      axisTick: { show: false },
      axisLine: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: values,
        barWidth: 14,
        itemStyle: {
          color: '#18181b',
          borderRadius: [0, 4, 4, 0],
        },
      },
    ],
  }
})
</script>

<template>
  <VChart class="h-[360px] w-full" :option="option" autoresize />
</template>
