<script setup lang="ts">
import { computed } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import KpiCard from '@/components/tremor/KpiCard.vue'
import BarList from '@/components/tremor/BarList.vue'
import UsageTrendChart from '@/components/charts/UsageTrendChart.vue'
import { useUsageStore } from '@/stores/usage'

const usage = useUsageStore()

const todayDelta = computed(() => {
  const pct = usage.kpi.todayDeltaPct
  const sign = pct > 0 ? '↑' : pct < 0 ? '↓' : ''
  return `${sign}${Math.abs(pct)}% vs 昨日`
})

const todayTone = computed(() => {
  const pct = usage.kpi.todayDeltaPct
  if (pct > 0) return 'up' as const
  if (pct < 0) return 'down' as const
  return 'neutral' as const
})
</script>

<template>
  <div class="space-y-5">
    <div>
      <h2 class="text-base font-semibold tracking-tight">用量 / 访问</h2>
      <p class="text-xs text-muted-foreground">
        平台访问与用量统计 · 与工作流总览分离 · 访问量为 Mock · 运行次数来自本地历史
      </p>
    </div>

    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard
        label="今日访问"
        :value="String(usage.kpi.todayVisits)"
        :delta="todayDelta"
        :delta-tone="todayTone"
        hint="Mock"
      />
      <KpiCard
        label="昨日访问"
        :value="String(usage.kpi.yesterdayVisits)"
        hint="Mock"
      />
      <KpiCard
        label="在线人数"
        :value="String(usage.kpi.onlineUsers)"
        hint="Mock 活跃近似"
      />
      <KpiCard
        label="工作流运行次数"
        :value="String(usage.kpi.workflowRuns)"
        hint="本地 run history"
      />
    </div>

    <Card class="shadow-none">
      <CardHeader class="pb-2">
        <CardTitle class="text-sm font-semibold">近 30 天访问</CardTitle>
        <CardDescription>Mock 趋势 · 后续可接 Umami / 后端聚合</CardDescription>
      </CardHeader>
      <CardContent>
        <UsageTrendChart :points="usage.trend" />
      </CardContent>
    </Card>

    <div class="grid gap-3 md:grid-cols-2">
      <Card class="shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-semibold">Top Workflow</CardTitle>
          <CardDescription>按本地运行次数</CardDescription>
        </CardHeader>
        <CardContent>
          <BarList :items="usage.topWorkflows" />
        </CardContent>
      </Card>
      <Card class="shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-semibold">Top Strategy</CardTitle>
          <CardDescription>成功运行聚合</CardDescription>
        </CardHeader>
        <CardContent>
          <BarList :items="usage.topStrategies" />
        </CardContent>
      </Card>
      <Card class="shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-semibold">Top API</CardTitle>
          <CardDescription>Mock 调用量</CardDescription>
        </CardHeader>
        <CardContent>
          <BarList :items="usage.topApis" />
        </CardContent>
      </Card>
      <Card class="shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-semibold">Top User</CardTitle>
          <CardDescription>Mock 用户活跃</CardDescription>
        </CardHeader>
        <CardContent>
          <BarList :items="usage.topUsers" />
        </CardContent>
      </Card>
    </div>
  </div>
</template>
