<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import StatusPill from '@/components/tremor/StatusPill.vue'
import KpiCard from '@/components/tremor/KpiCard.vue'
import PredictionKlinePanel from '@/components/charts/PredictionKlinePanel.vue'
import MarkdownReportPanel from '@/components/reports/MarkdownReportPanel.vue'
import ImageReportPanel from '@/components/reports/ImageReportPanel.vue'
import TextReportPanel from '@/components/reports/TextReportPanel.vue'
import { formatDurationMs, formatTime } from '@/api/parse'
import type { RunRecord } from '@/api/history'
import { isPredictionKlinePath } from '@/api/kline'
import {
  copyTextToClipboard,
  formatPreviewCell,
  isTodayHighLowTable,
  stockCodesToCopyText,
  tableRowsToCopyText,
} from '@/api/tableCopy'
import { fetchWorkspaceTable, resolveLatestGlob, type TablePreview } from '@/api/workflow'
import { trackEvent } from '@/api/events'
import {
  isImageWorkspacePath,
  isMarkdownWorkspacePath,
  isTextWorkspacePath,
} from '@/api/workspacePreview'
import { isPathOutput, type WorkspaceOutput } from '@/api/types'
import { useWorkflowStore } from '@/stores/workflow'
import { useQuotaStore } from '@/stores/quota'
import { useRouter } from 'vue-router'

const store = useWorkflowStore()
const quota = useQuotaStore()
const router = useRouter()
const tableLoading = ref(false)
const tableData = ref<TablePreview | null>(null)
const copyFlash = ref('')
/** workspace | markdown | image | text | kline | log */
const activeTab = ref('workspace')
let copyFlashTimer: ReturnType<typeof setTimeout> | null = null

/** 可选运行：每步骤仅保留最近一条 */
const reportRuns = computed(() => {
  const seen = new Set<string>()
  const out: RunRecord[] = []
  for (const r of store.runs) {
    if (!(r.status === 'success' || r.outputs.length)) continue
    if (seen.has(r.stepId)) continue
    seen.add(r.stepId)
    out.push(r)
  }
  return out
})

const outputs = computed<WorkspaceOutput[]>(() => {
  if (store.previewOutputs?.length) return store.previewOutputs
  return store.selectedRun?.outputs ?? []
})

const pathOutputs = computed(() => outputs.value.filter(isPathOutput))

const activePath = computed({
  get: () => store.reportTableKey || pathOutputs.value[0]?.path || '',
  set: (v: string) => {
    store.reportTableKey = v
  },
})

const activeIsKline = computed(() => isPredictionKlinePath(activePath.value))
const activeIsMarkdown = computed(() => isMarkdownWorkspacePath(activePath.value))
const activeIsImage = computed(() => isImageWorkspacePath(activePath.value))
const activeIsText = computed(() => isTextWorkspacePath(activePath.value))
const activeIsTable = computed(
  () =>
    Boolean(activePath.value) &&
    !activeIsKline.value &&
    !activeIsMarkdown.value &&
    !activeIsImage.value &&
    !activeIsText.value,
)
const activeIsTodayHighLow = computed(() => isTodayHighLowTable(activePath.value))
const hasKlineOutput = computed(() =>
  pathOutputs.value.some((o) => isPredictionKlinePath(o.path)),
)
const hasMarkdownOutput = computed(() =>
  pathOutputs.value.some((o) => isMarkdownWorkspacePath(o.path)),
)
const hasImageOutput = computed(() =>
  pathOutputs.value.some((o) => isImageWorkspacePath(o.path)),
)
const hasTextOutput = computed(() =>
  pathOutputs.value.some((o) => isTextWorkspacePath(o.path)),
)
const canCopyTable = computed(
  () =>
    Boolean(
      tableData.value?.exists &&
        tableData.value.headers?.length &&
        tableData.value.rows &&
        !tableData.value.preview_unsupported,
    ),
)

function flashCopied(_label: string) {
  copyFlash.value = '已复制'
  if (copyFlashTimer) clearTimeout(copyFlashTimer)
  copyFlashTimer = setTimeout(() => {
    copyFlash.value = ''
  }, 1600)
}

async function onCopyTable() {
  const gate = quota.assertCanExport()
  if (!gate.ok) {
    alert(gate.reason)
    void router.push('/billing/plans')
    return
  }
  const data = tableData.value
  const path = activePath.value
  if (!data?.headers?.length || !data.rows) {
    alert('表格无内容可复制。')
    return
  }
  if (isTodayHighLowTable(path)) {
    const text = tableRowsToCopyText(data.headers, data.rows, path)
    if (!text.trim()) {
      alert('表格无内容可复制。')
      return
    }
    const ok = await copyTextToClipboard(text)
    if (!ok) {
      alert('复制失败，请手动选中表格复制。')
      return
    }
    trackEvent('export_report', { kind: 'table_copy', path })
    flashCopied('复制全部')
    return
  }
  const codes = stockCodesToCopyText(data.headers, data.rows)
  if (codes == null) {
    alert('未找到「股票代码」类列，请在表格中手动选择该列复制。')
    return
  }
  if (!codes) {
    alert('该列无有效代码。')
    return
  }
  const ok = await copyTextToClipboard(codes)
  if (!ok) {
    alert('复制失败，请手动选中表格复制。')
    return
  }
  trackEvent('export_report', { kind: 'codes_copy', path })
  flashCopied('复制股票代码列')
}

function onDownloadCsv() {
  const gate = quota.assertCanExport()
  if (!gate.ok) {
    alert(gate.reason)
    void router.push('/billing/plans')
    return
  }
  const data = tableData.value
  if (!data?.headers?.length || !data.rows) {
    alert('表格无内容可导出。')
    return
  }
  const escape = (cell: unknown) => {
    const s = String(cell ?? '')
    if (/[",\n\r]/.test(s)) return `"${s.replace(/"/g, '""')}"`
    return s
  }
  const lines = [
    data.headers.map(escape).join(','),
    ...data.rows.map((row) => row.map(escape).join(',')),
  ]
  const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  const base = (activePath.value.split(/[/\\]/).pop() || 'export.csv').replace(/\.csv$/i, '')
  a.href = url
  a.download = `${base}-export.csv`
  a.click()
  URL.revokeObjectURL(url)
  trackEvent('export_report', { kind: 'csv_download', path: activePath.value })
}

function syncTabToPath(path: string) {
  if (isPredictionKlinePath(path)) activeTab.value = 'kline'
  else if (isMarkdownWorkspacePath(path)) activeTab.value = 'markdown'
  else if (isImageWorkspacePath(path)) activeTab.value = 'image'
  else if (isTextWorkspacePath(path)) activeTab.value = 'text'
  else if (path) activeTab.value = 'workspace'
}

async function loadTable(path: string) {
  if (
    !path ||
    isPredictionKlinePath(path) ||
    isMarkdownWorkspacePath(path) ||
    isImageWorkspacePath(path) ||
    isTextWorkspacePath(path)
  ) {
    tableData.value = null
    return
  }
  tableLoading.value = true
  tableData.value = await fetchWorkspaceTable(path)
  tableLoading.value = false
}

watch(
  activePath,
  (p) => {
    syncTabToPath(p)
    void loadTable(p)
  },
  { immediate: true },
)

watch(
  () => store.selectedRunId,
  () => {
    if (!store.reportTableKey && pathOutputs.value[0]) {
      store.reportTableKey = pathOutputs.value[0].path
    }
  },
)

// 若当前选中是某步骤的旧记录，自动切到该步骤最近一条
watch(
  reportRuns,
  (list) => {
    if (!list.length) return
    const cur = store.selectedRunId
    if (cur && list.some((r) => r.id === cur)) return
    const stepId = store.selectedRun?.stepId
    const prefer = (stepId && list.find((r) => r.stepId === stepId)) || list[0]
    if (prefer) store.selectRun(prefer.id)
  },
  { immediate: true },
)

async function onPickOutput(out: WorkspaceOutput) {
  if (isPathOutput(out)) {
    activePath.value = out.path
    return
  }
  const latest = await resolveLatestGlob(out.glob)
  if (latest?.rel_path) {
    activePath.value = latest.rel_path
  } else {
    alert(`未找到匹配文件: ${out.glob}`)
  }
}
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-sm font-semibold">报告</h2>
        <p class="text-xs text-muted-foreground">
          按产物分流：工作区表（CSV）· 文档（Markdown）· 图形（PNG）· 文本（TXT）· 预测 K 线；日志为次要查看
        </p>
      </div>
      <div class="w-80">
        <p class="mb-1 text-xs text-muted-foreground">选择运行</p>
        <Select
          :model-value="store.selectedRunId ?? undefined"
          @update:model-value="(v) => v && store.selectRun(String(v))"
        >
          <SelectTrigger class="w-full">
            <SelectValue placeholder="选择一次运行" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="run in reportRuns" :key="run.id" :value="run.id">
              {{ formatTime(run.finishedAt) }} · {{ run.stepTitle }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>
    </div>

    <div class="grid gap-3 sm:grid-cols-3">
      <KpiCard
        label="当前 Workflow"
        :value="store.selectedRun?.stepId ?? (pathOutputs[0] ? '预览' : '—')"
        :hint="store.selectedRun?.stepTitle"
      />
      <KpiCard label="输出表数量" :value="String(outputs.length)" />
      <KpiCard
        label="状态"
        :value="store.selectedRun ? `exit ${store.selectedRun.exitCode}` : '—'"
        :delta="store.selectedRun ? formatTime(store.selectedRun.finishedAt) : undefined"
        :delta-tone="store.selectedRun?.status === 'success' ? 'up' : 'neutral'"
      />
    </div>

    <Card v-if="outputs.length || store.selectedRun">
      <CardHeader class="space-y-3">
        <div class="flex flex-row items-center justify-between gap-3">
          <div>
            <CardTitle class="text-base">
              {{ store.selectedRun?.stepTitle ?? '工作区输出预览' }}
            </CardTitle>
            <CardDescription class="font-mono">
              {{ store.selectedRun?.stepId ?? activePath }}
            </CardDescription>
          </div>
          <div v-if="store.selectedRun" class="flex items-center gap-2">
            <StatusPill :status="store.selectedRun.status" />
            <Badge variant="outline">{{ formatDurationMs(store.selectedRun.durationMs) }}</Badge>
          </div>
        </div>

        <div v-if="outputs.length" class="flex flex-wrap gap-1.5">
          <Button
            v-for="(out, idx) in outputs"
            :key="idx"
            size="sm"
            :variant="isPathOutput(out) && out.path === activePath ? 'default' : 'outline'"
            @click="onPickOutput(out)"
          >
            {{ out.label }}
          </Button>
        </div>
      </CardHeader>

      <CardContent>
        <Tabs v-model="activeTab" class="w-full">
          <TabsList>
            <TabsTrigger value="workspace" :disabled="!activeIsTable && !!activePath">
              工作区表
            </TabsTrigger>
            <TabsTrigger
              v-if="hasMarkdownOutput || activeIsMarkdown"
              value="markdown"
            >
              文档
            </TabsTrigger>
            <TabsTrigger
              v-if="hasTextOutput || activeIsText"
              value="text"
            >
              文本
            </TabsTrigger>
            <TabsTrigger
              v-if="hasImageOutput || activeIsImage"
              value="image"
            >
              图形
            </TabsTrigger>
            <TabsTrigger
              v-if="hasKlineOutput || activeIsKline"
              value="kline"
            >
              预测 K 线
            </TabsTrigger>
            <TabsTrigger value="log">日志</TabsTrigger>
          </TabsList>

          <TabsContent value="workspace" class="mt-4 space-y-2">
            <template v-if="activeIsKline">
              <p class="rounded-md border bg-muted/40 px-3 py-4 text-sm text-muted-foreground">
                当前选中的是预测 K 线 JSON，请切换到「预测 K 线」页签查看。
              </p>
            </template>
            <template v-else-if="activeIsMarkdown">
              <p class="rounded-md border bg-muted/40 px-3 py-4 text-sm text-muted-foreground">
                当前选中的是 Markdown 文档，请切换到「文档」页签查看。
              </p>
            </template>
            <template v-else-if="activeIsText">
              <p class="rounded-md border bg-muted/40 px-3 py-4 text-sm text-muted-foreground">
                当前选中的是文本文件，请切换到「文本」页签查看。
              </p>
            </template>
            <template v-else-if="activeIsImage">
              <p class="rounded-md border bg-muted/40 px-3 py-4 text-sm text-muted-foreground">
                当前选中的是图片，请切换到「图形」页签查看。
              </p>
            </template>
            <template v-else>
              <div class="flex flex-wrap items-center justify-between gap-2">
                <p class="font-mono text-[11px] text-muted-foreground">{{ activePath || '未选择表' }}</p>
                <div class="flex flex-wrap items-center gap-2">
                  <Button
                    v-if="canCopyTable && !quota.canExportReports()"
                    size="sm"
                    variant="outline"
                    @click="router.push('/billing/plans')"
                  >
                    导出需 Pro
                  </Button>
                  <template v-else-if="canCopyTable">
                    <Button
                      size="sm"
                      variant="outline"
                      class="border-rose-300 text-rose-700 hover:bg-rose-50"
                      @click="onCopyTable"
                    >
                      {{ copyFlash || (activeIsTodayHighLow ? '复制全部' : '复制股票代码列') }}
                    </Button>
                    <Button size="sm" variant="outline" @click="onDownloadCsv">
                      下载 CSV
                    </Button>
                  </template>
                </div>
              </div>
              <p
                v-if="canCopyTable && !quota.canExportReports()"
                class="text-[11px] text-muted-foreground"
              >
                可预览表格；复制 / 下载为 Pro 权益（report.export）
              </p>
              <p v-if="tableLoading" class="py-8 text-center text-sm text-muted-foreground">加载中…</p>
              <template v-else-if="tableData">
                <p
                  v-if="
                    tableData.preview_kind === 'markdown' ||
                    tableData.preview_kind === 'image' ||
                    tableData.preview_kind === 'text'
                  "
                  class="text-xs text-amber-700"
                >
                  {{ tableData.preview_note || '请切换到对应「文档 / 文本 / 图形」页签。' }}
                </p>
                <p v-else-if="tableData.preview_note || tableData.error" class="text-xs text-amber-700">
                  {{ tableData.preview_note || tableData.error }}
                </p>
                <p v-else-if="!tableData.exists" class="py-8 text-center text-sm text-muted-foreground">
                  文件不存在或尚未生成。请先运行对应 Workflow。
                </p>
                <template v-else>
                  <p class="text-[11px] text-muted-foreground">
                    共 {{ tableData.rows.length }} 行
                    <template v-if="tableData.truncated">，已截断；复制时仍仅含已加载行</template>
                    。可选中表格单元格复制，或使用上方「{{ activeIsTodayHighLow ? '复制全部' : '复制股票代码列' }}」。
                  </p>
                  <div class="overflow-auto rounded-lg border">
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead v-for="h in tableData.headers" :key="h">{{ h }}</TableHead>
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        <TableRow v-for="(row, ri) in tableData.rows" :key="ri">
                          <TableCell
                            v-for="(cell, ci) in row"
                            :key="ci"
                            class="font-mono text-xs"
                          >
                            {{ formatPreviewCell(tableData.headers[ci] || '', cell, activePath) }}
                          </TableCell>
                        </TableRow>
                      </TableBody>
                    </Table>
                  </div>
                </template>
              </template>
              <p v-else class="py-8 text-center text-sm text-muted-foreground">
                请选择上方输出表。需启动 workflow_server 才能读取工作区文件。
              </p>
            </template>
          </TabsContent>

          <TabsContent value="markdown" class="mt-4">
            <MarkdownReportPanel
              v-if="activeTab === 'markdown'"
              :key="(activeIsMarkdown ? activePath : pathOutputs.find((o) => isMarkdownWorkspacePath(o.path))?.path) || 'md'"
              :path="activeIsMarkdown ? activePath : (pathOutputs.find((o) => isMarkdownWorkspacePath(o.path))?.path || '')"
            />
          </TabsContent>

          <TabsContent value="text" class="mt-4">
            <TextReportPanel
              v-if="activeTab === 'text'"
              :key="(activeIsText ? activePath : pathOutputs.find((o) => isTextWorkspacePath(o.path))?.path) || 'txt'"
              :path="activeIsText ? activePath : (pathOutputs.find((o) => isTextWorkspacePath(o.path))?.path || '')"
            />
          </TabsContent>

          <TabsContent value="image" class="mt-4">
            <ImageReportPanel
              v-if="activeTab === 'image'"
              :key="(activeIsImage ? activePath : pathOutputs.find((o) => isImageWorkspacePath(o.path))?.path) || 'img'"
              :path="activeIsImage ? activePath : (pathOutputs.find((o) => isImageWorkspacePath(o.path))?.path || '')"
            />
          </TabsContent>

          <TabsContent value="kline" class="mt-4">
            <!-- 仅激活时挂载：避免 hidden/0 宽高导致 ECharts 空白 -->
            <PredictionKlinePanel
              v-if="activeTab === 'kline'"
              :key="(activeIsKline ? activePath : pathOutputs.find((o) => isPredictionKlinePath(o.path))?.path) || 'kline'"
              :path="activeIsKline ? activePath : (pathOutputs.find((o) => isPredictionKlinePath(o.path))?.path || '')"
            />
          </TabsContent>

          <TabsContent value="log" class="mt-4">
            <ScrollArea class="h-[360px] rounded-lg border bg-muted/30 p-4">
              <pre class="whitespace-pre-wrap break-words font-mono text-xs leading-relaxed">{{ store.selectedRun?.log || '无运行日志（可从工作流运行后查看）' }}</pre>
            </ScrollArea>
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>

    <Card v-else>
      <CardContent class="py-12 text-center text-sm text-muted-foreground">
        暂无输出。请在「工作流」运行步骤，或点击卡片底部「查看 ·」链接。
      </CardContent>
    </Card>
  </div>
</template>
