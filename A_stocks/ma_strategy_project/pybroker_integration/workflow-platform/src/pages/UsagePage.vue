<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import KpiCard from '@/components/tremor/KpiCard.vue'
import BarList from '@/components/tremor/BarList.vue'
import { useUsageStore } from '@/stores/usage'
import { fetchFunnel, type FunnelStep } from '@/api/events'
import { useAuthStore } from '@/stores/auth'

const usage = useUsageStore()
const auth = useAuthStore()
const funnel = ref<FunnelStep[]>([])
const funnelError = ref('')

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
      <h2 class="text-base font-semibold tracking-tight">用量 / 转化</h2>
      <p class="text-xs text-muted-foreground">
        转化漏斗来自服务端 events · 运行 Top 来自本机 run history
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

    <div class="grid gap-3 sm:grid-cols-2">
      <KpiCard
        label="本机工作流运行次数"
        :value="String(usage.kpi.workflowRuns)"
        hint="local run history"
      />
    </div>

    <div class="grid gap-3 md:grid-cols-2">
      <Card class="shadow-none">
        <CardHeader class="pb-2">
          <CardTitle class="text-sm font-semibold">Top Workflow</CardTitle>
          <CardDescription>按本机运行次数</CardDescription>
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
    </div>
  </div>
</template>
