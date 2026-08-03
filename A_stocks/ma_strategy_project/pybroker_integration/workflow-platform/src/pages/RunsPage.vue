<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Eye, FileBarChart2, Trash2 } from '@lucide/vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import StatusPill from '@/components/tremor/StatusPill.vue'
import OutputSheet from '@/components/workflow/OutputSheet.vue'
import KpiCard from '@/components/tremor/KpiCard.vue'
import { formatDurationMs, formatTime } from '@/api/parse'
import { useWorkflowStore } from '@/stores/workflow'

const store = useWorkflowStore()
const router = useRouter()
const filter = ref<'all' | 'success' | 'error'>('all')

const filtered = computed(() => {
  if (filter.value === 'success') return store.successRuns
  if (filter.value === 'error') return store.errorRuns
  return store.runs
})

function goReport(id: string) {
  store.selectRun(id)
  const run = store.runs.find((r) => r.id === id)
  const first = run?.outputs.find((o) => 'path' in o && o.path)
  if (first && 'path' in first) store.reportTableKey = first.path
  void router.push('/reports')
}

function onClear() {
  if (confirm('确认清空全部运行记录？')) store.clearRuns()
}
</script>

<template>
  <div class="space-y-4">
    <div class="grid gap-3 sm:grid-cols-3">
      <KpiCard label="总运行" :value="String(store.runs.length)" />
      <KpiCard
        label="成功"
        :value="String(store.successRuns.length)"
        delta-tone="up"
      />
      <KpiCard
        label="失败"
        :value="String(store.errorRuns.length)"
        :delta-tone="store.errorRuns.length ? 'down' : 'neutral'"
      />
    </div>

    <Card>
      <CardHeader class="flex flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle>运行记录</CardTitle>
          <CardDescription>本地保存最近运行日志，点击可查看详情或跳转报告</CardDescription>
        </div>
        <div class="flex flex-wrap items-center gap-1">
          <Button
            v-for="f in [
              ['all', '全部'],
              ['success', '成功'],
              ['error', '失败'],
            ] as const"
            :key="f[0]"
            size="sm"
            :variant="filter === f[0] ? 'default' : 'outline'"
            @click="filter = f[0]"
          >
            {{ f[1] }}
          </Button>
          <Button size="sm" variant="outline" :disabled="!store.runs.length" @click="onClear">
            <Trash2 class="size-3.5" />
            清空
          </Button>
        </div>
      </CardHeader>
      <CardContent class="px-0 pb-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead class="pl-6">时间</TableHead>
              <TableHead>Workflow</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>耗时</TableHead>
              <TableHead class="pr-6 text-right">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="run in filtered" :key="run.id">
              <TableCell class="pl-6 font-mono text-xs text-muted-foreground">
                {{ formatTime(run.finishedAt) }}
              </TableCell>
              <TableCell>
                <p class="text-sm font-medium">{{ run.stepTitle }}</p>
                <p class="font-mono text-[11px] text-muted-foreground">{{ run.stepId }}</p>
              </TableCell>
              <TableCell>
                <div class="flex items-center gap-2">
                  <StatusPill :status="run.status" />
                  <Badge variant="outline" class="font-mono">{{ run.exitCode }}</Badge>
                </div>
              </TableCell>
              <TableCell class="font-mono text-xs tabular-nums text-muted-foreground">
                {{ formatDurationMs(run.durationMs) }}
              </TableCell>
              <TableCell class="pr-6 text-right">
                <div class="flex justify-end gap-1">
                  <Button size="sm" variant="ghost" @click="store.openRunSheet(run)">
                    <Eye class="size-3.5" />
                    日志
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    :disabled="run.status !== 'success'"
                    @click="goReport(run.id)"
                  >
                    <FileBarChart2 class="size-3.5" />
                    报告
                  </Button>
                </div>
              </TableCell>
            </TableRow>
            <TableRow v-if="!filtered.length">
              <TableCell colspan="5" class="py-12 text-center text-sm text-muted-foreground">
                暂无运行记录。去「工作流」执行一步后会显示在这里。
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </CardContent>
    </Card>

    <OutputSheet />
  </div>
</template>
