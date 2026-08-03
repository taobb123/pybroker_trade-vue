<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import KpiCard from '@/components/tremor/KpiCard.vue'
import BarList from '@/components/tremor/BarList.vue'
import UsageTrendChart from '@/components/charts/UsageTrendChart.vue'
import { useUsageStore } from '@/stores/usage'
import { fetchFunnel, type FunnelStep } from '@/api/events'
import { useAuthStore } from '@/stores/auth'

const usage = useUsageStore()
const auth = useAuthStore()
const funnel = ref<FunnelStep[]>([])
const funnelError = ref('')

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

const funnelBars = computed(() => {
  const max = Math.max(1, ...funnel.value.map((s) => s.count))
  return funnel.value.map((s) => ({
    name: s.label,
    value: s.count,
    share: Math.round((s.count / max) * 100),
  }))
})

onMounted(async () => {
  if (!auth.isAuthenticated) return
  try {
    funnel.value = await fetchFunnel()
  } catch (e) {
    funnelError.value = e instanceof Error ? e.message : String(e)
  }
})
</script>

<template>
  <div class="space-y-5">
    <div>
      <h2 class="text-base font-semibold tracking-tight">用量 / 访问</h2>
      <p class="text-xs text-muted-foreground">
        M4 转化漏斗来自服务端 events · 下方访问趋势仍为 Mock 样板
      </p>
    </div>

    <Card class="shadow-none">
      <CardHeader class="pb-2">
        <CardTitle class="text-sm font-semibold">转化漏斗（独立用户数）</CardTitle>
        <CardDescription>
          page_view → 注册 → run → 升级点击 → 支付成功
        </CardDescription>
      </CardHeader>
      <CardContent>
        <p v-if="!auth.isAuthenticated" class="text-xs text-muted-foreground">登录后查看漏斗</p>
        <p v-else-if="funnelError" class="text-xs text-destructive">{{ funnelError }}</p>
        <div v-else-if="!funnel.length" class="text-xs text-muted-foreground">暂无数据</div>
        <div v-else class="space-y-3">
          <div class="grid gap-2 sm:grid-cols-5">
            <div
              v-for="s in funnel"
              :key="s.key"
              class="rounded-lg border px-3 py-2 text-center"
            >
              <p class="text-lg font-semibold tabular-nums">{{ s.count }}</p>
              <p class="text-[11px] text-muted-foreground">{{ s.label }}</p>
            </div>
          </div>
          <BarList
            :items="
              funnelBars.map((b) => ({
                name: b.name,
                value: b.value,
              }))
            "
          />
        </div>
      </CardContent>
    </Card>

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
        <CardDescription>Mock 趋势 · 真漏斗见上方 events</CardDescription>
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
