<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Play } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import KpiCard from '@/components/tremor/KpiCard.vue'
import { formatTime } from '@/api/parse'
import type { RunRecord } from '@/api/history'
import { useWorkflowStore } from '@/stores/workflow'

const store = useWorkflowStore()
const router = useRouter()

const lastSuccess = computed(() => store.successRuns[0] ?? null)

/** 按步骤去重（保留各步骤最近一次），最多 8 条 */
const recent = computed(() => {
  const seen = new Set<string>()
  const out: RunRecord[] = []
  for (const run of store.runs) {
    if (seen.has(run.stepId)) continue
    seen.add(run.stepId)
    out.push(run)
    if (out.length >= 8) break
  }
  return out
})

onMounted(() => {
  if (!store.steps.length) void store.loadSteps()
})

function openRecentRun(stepId: string, runId: string) {
  store.selectRun(runId)
  void router.push({
    path: '/workflows',
    query: { step: stepId, run: runId },
  })
}

async function runRecentStep(run: RunRecord, ev: Event) {
  ev.stopPropagation()
  if (!store.steps.length) await store.loadSteps()
  const step = store.steps.find((s) => s.id === run.stepId)
  if (!step?.runnable) {
    void router.push({ path: '/workflows', query: { step: run.stepId } })
    return
  }
  await store.runStep(step, { openSheet: false })
}
</script>

<template>
  <div class="space-y-5">
    <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <KpiCard label="运行总数" :value="String(store.runs.length)" hint="本地历史" />
      <KpiCard label="成功" :value="String(store.successRuns.length)" delta-tone="up" />
      <KpiCard
        label="最近成功"
        :value="lastSuccess ? lastSuccess.stepId : '—'"
        :delta="lastSuccess ? formatTime(lastSuccess.finishedAt) : undefined"
        delta-tone="up"
      />
      <KpiCard
        label="失败"
        :value="String(store.errorRuns.length)"
        :delta-tone="store.errorRuns.length ? 'down' : 'neutral'"
      />
    </div>

    <section class="space-y-3">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 class="text-base font-semibold">最近运行</h2>
          <p class="text-xs text-muted-foreground">
            每步骤仅一条 · 最多 8 条 · 点击进入工作流 · 产物在「报告」查看
          </p>
        </div>
        <div class="flex gap-2">
          <Button size="sm" variant="outline" @click="router.push('/runs')">运行记录</Button>
          <Button size="sm" variant="outline" @click="router.push('/reports')">打开报告</Button>
        </div>
      </div>

      <ul v-if="recent.length" class="divide-y rounded-xl bg-muted/30">
        <li
          v-for="run in recent"
          :key="run.stepId"
          class="flex items-center gap-2 px-4 py-3 transition-colors hover:bg-muted/50"
        >
          <button
            type="button"
            class="min-w-0 flex-1 text-left"
            @click="openRecentRun(run.stepId, run.id)"
          >
            <p class="truncate text-sm font-medium">{{ run.stepTitle }}</p>
            <p class="font-mono text-[11px] text-muted-foreground">
              {{ run.stepId }} · {{ formatTime(run.finishedAt) }}
            </p>
          </button>
          <span
            class="shrink-0 text-xs font-medium"
            :class="run.status === 'success' ? 'text-emerald-700' : 'text-destructive'"
          >
            {{ run.status === 'success' ? '成功' : '失败' }}
          </span>
          <Button
            size="sm"
            class="shrink-0"
            :disabled="store.busy"
            @click="runRecentStep(run, $event)"
          >
            <Play class="size-3.5" />
            运行
          </Button>
        </li>
      </ul>
      <p v-else class="rounded-xl bg-muted/30 px-4 py-8 text-center text-sm text-muted-foreground">
        暂无运行。请先到「工作流」执行步骤。
      </p>
    </section>
  </div>
</template>
