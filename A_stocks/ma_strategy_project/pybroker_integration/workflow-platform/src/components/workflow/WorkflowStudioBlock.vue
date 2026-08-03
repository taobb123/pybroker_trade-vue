<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  ChevronsUpDown,
  Play,
  PanelRightOpen,
  Square,
  Settings2,
  FileSpreadsheet,
  ChevronDown,
  ChevronUp,
} from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import type { WorkflowStep } from '@/api/types'
import { isPathOutput } from '@/api/types'
import { isPredictionKlinePath } from '@/api/kline'
import {
  fetchWorkspaceFile,
  fetchWorkspaceTable,
  saveWorkspaceFile,
  type TablePreview,
} from '@/api/workflow'
import { filterStockCodes } from '@/api/filterStockCodes'
import { copyTextToClipboard, formatPreviewCell } from '@/api/tableCopy'
import { hasColumnMap, resolveTableColumns } from '@/api/tableColumns'
import { formatDurationMs, formatTime } from '@/api/parse'
import {
  isImageWorkspacePath,
  isMarkdownWorkspacePath,
  isTextWorkspacePath,
  workspacePathSuffix,
} from '@/api/workspacePreview'
import { useWorkflowStore } from '@/stores/workflow'
import { cn } from '@/lib/utils'

const props = defineProps<{
  step: WorkflowStep
  busy?: boolean
  focused?: boolean
  expandAdvanced?: boolean
}>()

const store = useWorkflowStore()
const router = useRouter()
const draft = computed(() => store.ensureDraft(props.step))

const strategyOpen = ref(false)
const paramsOpen = ref(false)

const inputPath = ref('')
const inputContent = ref('')
const inputLoading = ref(false)
const inputSaving = ref(false)
const inputMsg = ref('')

const tableLoading = ref(false)
const tableData = ref<TablePreview | null>(null)
const activeOutputPath = ref('')
const running = ref(false)
const showAllColumns = ref(false)
/** 结果表是否展开（非聚焦默认收起） */
const tableExpanded = ref(false)

const tableHost = ref<HTMLElement | null>(null)
const tableVisible = ref(false)
const tableLoadedPath = ref('')
const TABLE_PREVIEW_ROWS = 40
let tableObserver: IntersectionObserver | null = null

const isCodeFilterTool = computed(
  () =>
    props.step.tool === 'filter_stock_codes' ||
    props.step.id === 'filter_stock_codes',
)
const filterInput = ref('')
const filterOutput = ref('')
const filterStats = ref('—')
const filterCopyFlash = ref('')

function onFilterProcess() {
  const r = filterStockCodes(filterInput.value)
  filterOutput.value = r.codes.join('\n')
  filterStats.value = `有效 ${r.inputCount} · 去重 ${r.dupSkipped} · 剔除 ${r.prefixSkipped} · 输出 ${r.outputCount}`
}

async function onFilterCopy() {
  if (!filterOutput.value.trim()) {
    alert('请先点击「处理」生成结果。')
    return
  }
  const ok = await copyTextToClipboard(filterOutput.value)
  if (!ok) {
    alert('复制失败，请手动选中结果复制。')
    return
  }
  filterCopyFlash.value = '已复制'
  setTimeout(() => {
    filterCopyFlash.value = ''
  }, 1600)
}

type StrategyOption = { id: string; label: string; kind: 'combo' | 'mode' }

const hasStrategySelect = computed(
  () =>
    Boolean(props.step.symbolsPasteComboOptions?.length) ||
    Boolean(props.step.runModes?.length),
)

const strategies = computed<StrategyOption[]>(() => {
  if (props.step.symbolsPasteComboOptions?.length) {
    return props.step.symbolsPasteComboOptions.map((c) => ({
      id: c.id,
      label: c.label,
      kind: 'combo' as const,
    }))
  }
  if (props.step.runModes?.length) {
    return props.step.runModes.map((m) => ({
      id: m.id,
      label: m.label,
      kind: 'mode' as const,
    }))
  }
  return []
})

const selectedStrategy = computed(() => {
  if (strategies.value[0]?.kind === 'combo') {
    return strategies.value.find((s) => s.id === draft.value.comboId) ?? null
  }
  if (strategies.value[0]?.kind === 'mode') {
    return strategies.value.find((s) => s.id === draft.value.runMode) ?? strategies.value[0] ?? null
  }
  return null
})

const strategyLabel = computed(() => selectedStrategy.value?.label || '选择策略')

const recentRun = computed(() => store.runs.find((r) => r.stepId === props.step.id) ?? null)

const statusLabel = computed(() => {
  if (busyOrRunning.value) return '运行中'
  if (!recentRun.value) return '未运行'
  return recentRun.value.status === 'success' ? '成功' : '失败'
})

const statusClass = computed(() => {
  if (busyOrRunning.value) return 'text-amber-700'
  if (!recentRun.value) return 'text-muted-foreground'
  return recentRun.value.status === 'success' ? 'text-emerald-700' : 'text-destructive'
})

const durationLabel = computed(() => {
  const ms = recentRun.value?.durationMs
  if (ms == null) return ''
  return formatDurationMs(ms)
})

const busyOrRunning = computed(() => Boolean(props.busy || running.value))

const tableOutputs = computed(() =>
  (props.step.workspaceOutputs ?? []).filter(
    (o) => isPathOutput(o) && !isPredictionKlinePath(o.path),
  ),
)

const tabularOutputs = computed(() =>
  tableOutputs.value.filter((o) => {
    if (!isPathOutput(o)) return false
    const suf = workspacePathSuffix(o.path)
    return suf === '.csv' || suf === '.tsv'
  }),
)

const klineOutputs = computed(() =>
  (props.step.workspaceOutputs ?? []).filter(
    (o) => isPathOutput(o) && isPredictionKlinePath(o.path),
  ),
)

const hasInputPanel = computed(() => {
  if (props.step.id === 'fetch_dc_concept_ma5') return false
  return (
    Boolean(props.step.symbolsPaste) ||
    Boolean(props.step.poolPresets?.length) ||
    Boolean(props.step.workspaceInputs?.length)
  )
})

const displayColumns = computed(() => {
  if (!tableData.value?.headers?.length) return []
  return resolveTableColumns(
    activeOutputPath.value,
    tableData.value.headers,
    showAllColumns.value,
  )
})

const previewRowCount = computed(() => tableData.value?.rows?.length ?? 0)

const mappedTable = computed(() => hasColumnMap(activeOutputPath.value))

watch(
  () => props.expandAdvanced,
  (v) => {
    if (v && hasInputPanel.value) paramsOpen.value = true
  },
  { immediate: true },
)

watch(
  () => props.focused,
  (f) => {
    if (f) {
      tableExpanded.value = true
      tableVisible.value = true
      void loadRecentPreview()
    }
  },
  { immediate: true },
)

function pickStrategy(opt: StrategyOption) {
  if (opt.kind === 'combo') draft.value.comboId = opt.id
  if (opt.kind === 'mode') draft.value.runMode = opt.id
  strategyOpen.value = false
}

async function loadInputFile(path: string) {
  if (!path) {
    inputContent.value = ''
    inputMsg.value = ''
    return
  }
  inputLoading.value = true
  inputMsg.value = ''
  const data = await fetchWorkspaceFile(path)
  inputContent.value = data.content
  inputLoading.value = false
  if (!data.exists) inputMsg.value = '文件不存在，保存将新建'
}

async function saveInputFile() {
  if (!inputPath.value) return
  inputSaving.value = true
  const ok = await saveWorkspaceFile(inputPath.value, inputContent.value)
  inputSaving.value = false
  inputMsg.value = ok ? '已保存' : '保存失败（请确认后端已启动）'
}

async function loadTable(path: string, force = false) {
  if (
    !path ||
    isPredictionKlinePath(path) ||
    isMarkdownWorkspacePath(path) ||
    isImageWorkspacePath(path) ||
    isTextWorkspacePath(path)
  ) {
    tableData.value = null
    tableLoadedPath.value = ''
    return
  }
  activeOutputPath.value = path
  if (!force && tableLoadedPath.value === path && tableData.value) return
  tableLoading.value = true
  tableData.value = await fetchWorkspaceTable(path, TABLE_PREVIEW_ROWS)
  tableLoadedPath.value = path
  tableLoading.value = false
}

async function loadRecentPreview(force = false) {
  if (!tableExpanded.value) return
  const first = tabularOutputs.value[0] ?? tableOutputs.value[0]
  if (first && isPathOutput(first)) await loadTable(first.path, force)
}

function resetTablePreview() {
  tableData.value = null
  tableLoadedPath.value = ''
  activeOutputPath.value = ''
  tableVisible.value = false
  showAllColumns.value = false
  if (!props.focused) tableExpanded.value = false
}

function ensureTableObserver() {
  tableObserver?.disconnect()
  tableObserver = null
  if (!tableExpanded.value) return
  if (typeof IntersectionObserver === 'undefined') {
    tableVisible.value = true
    return
  }
  const el = tableHost.value
  if (!el) return
  tableObserver = new IntersectionObserver(
    (entries) => {
      if (!entries.some((e) => e.isIntersecting)) return
      tableVisible.value = true
      tableObserver?.disconnect()
      tableObserver = null
    },
    { root: null, rootMargin: '160px 0px', threshold: 0.01 },
  )
  tableObserver.observe(el)
}

function expandTable() {
  tableExpanded.value = true
  tableVisible.value = true
  void loadRecentPreview(true)
}

function collapseTable() {
  tableExpanded.value = false
}

async function onRun() {
  if (strategies.value[0]?.kind === 'combo' && draft.value.symbolsText.trim() && !draft.value.comboId) {
    alert('粘贴股票列表时请先选择形态 ID（策略）')
    strategyOpen.value = true
    return
  }
  running.value = true
  const result = await store.runStep(props.step, { openSheet: false })
  running.value = false
  if (result?.exit_code === 0) {
    tableExpanded.value = true
    tableVisible.value = true
    await loadRecentPreview(true)
  }
}

async function onStop() {
  await store.stopStep()
}

function openSheetDetail() {
  if (recentRun.value) store.openRunSheet(recentRun.value)
  else store.openSheet(props.step)
}

function openParams() {
  paramsOpen.value = true
}

function openKlineReport(path: string) {
  store.openStepOutput(props.step, path)
  void router.push('/reports')
}

function openOutputInReport(path: string) {
  store.openStepOutput(props.step, path)
  void router.push('/reports')
}

async function onPickAttachment(path: string) {
  tableExpanded.value = true
  tableVisible.value = true
  await loadTable(path, true)
}

watch(
  () => props.step.id,
  () => {
    const first = props.step.workspaceInputs?.[0]
    inputPath.value = first?.path ?? ''
    inputContent.value = ''
    inputMsg.value = ''
    resetTablePreview()
  },
  { immediate: true },
)

watch(tableVisible, (vis) => {
  if (vis && tableExpanded.value) void loadRecentPreview()
})

watch(paramsOpen, (open) => {
  if (open && inputPath.value) void loadInputFile(inputPath.value)
})

watch(inputPath, (path) => {
  if (paramsOpen.value) void loadInputFile(path)
})

onMounted(() => {
  if (props.focused) {
    tableExpanded.value = true
    tableVisible.value = true
    void loadRecentPreview()
  }
  ensureTableObserver()
})

onBeforeUnmount(() => {
  tableObserver?.disconnect()
  tableObserver = null
})

watch([tableHost, tableExpanded], () => {
  ensureTableObserver()
})
</script>

<template>
  <section
    :id="`wf-card-${step.id}`"
    :class="cn(
      'w-full min-w-0 max-w-full scroll-mt-4 space-y-3 overflow-x-hidden rounded-xl py-1 transition-shadow',
      isCodeFilterTool
        ? 'border border-dashed border-teal-400/70 bg-teal-50/60 px-4 py-3 shadow-none'
        : '',
      focused && !isCodeFilterTool ? 'ring-2 ring-amber-400/80 ring-offset-4 ring-offset-background' : '',
      focused && isCodeFilterTool ? 'ring-2 ring-teal-400/70 ring-offset-2 ring-offset-background' : '',
    )"
  >
    <!-- 策略状态栏 / 小工具标题栏 -->
    <div
      :class="cn(
        'sticky top-0 z-10 space-y-2 py-2 backdrop-blur',
        isCodeFilterTool
          ? 'bg-teal-50/90 supports-[backdrop-filter]:bg-teal-50/75'
          : 'bg-background/95 supports-[backdrop-filter]:bg-background/80',
      )"
    >
      <div class="flex min-w-0 flex-wrap items-start justify-between gap-3">
        <div class="min-w-0 flex-1 space-y-1">
          <p class="font-mono text-[11px] text-muted-foreground">{{ step.id }}</p>
          <div class="flex flex-wrap items-center gap-2">
            <h3 class="text-lg font-semibold tracking-tight break-words">{{ step.title }}</h3>
            <Badge
              v-if="isCodeFilterTool"
              variant="outline"
              class="border-teal-500/50 bg-teal-100/80 text-teal-800"
            >
              小工具 · 即时
            </Badge>
          </div>
          <div v-if="!isCodeFilterTool" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            <span :class="cn('font-medium', statusClass)">● {{ statusLabel }}</span>
            <span v-if="recentRun" class="text-muted-foreground">
              {{ formatTime(recentRun.finishedAt) }}
            </span>
            <span v-if="durationLabel" class="text-muted-foreground">耗时 {{ durationLabel }}</span>
          </div>
          <p
            v-else
            class="text-xs text-teal-800/80"
          >
            本地即时处理，无需运行工作流
          </p>
          <div v-if="!isCodeFilterTool && step.tags?.length" class="flex flex-wrap gap-1">
            <Badge v-for="tag in step.tags" :key="tag" variant="secondary">{{ tag }}</Badge>
          </div>
          <p
            v-if="step.description"
            class="line-clamp-1 text-xs leading-relaxed text-muted-foreground"
            :title="step.description"
          >
            {{ step.description }}
          </p>
        </div>

        <div
          v-if="!isCodeFilterTool"
          class="flex shrink-0 flex-wrap items-center justify-end gap-2"
        >
          <Button
            v-if="hasInputPanel"
            variant="outline"
            size="sm"
            @click="openParams"
          >
            <Settings2 class="size-3.5" />
            参数
          </Button>
          <Button variant="outline" size="sm" @click="openSheetDetail">
            <PanelRightOpen class="size-3.5" />
            详情
          </Button>
          <Button
            v-if="step.runnable"
            size="sm"
            :disabled="busyOrRunning"
            @click="onRun"
          >
            <Play class="size-3.5" />
            运行
          </Button>
          <Button
            v-if="step.runnable"
            variant="outline"
            size="sm"
            class="border-rose-300/80 text-rose-700 hover:bg-rose-50 hover:text-rose-800 disabled:opacity-40"
            :disabled="!busyOrRunning"
            @click="onStop"
          >
            <Square class="size-3 fill-current" />
            停止
          </Button>
        </div>
      </div>
    </div>

    <!-- 前端工具：股票代码清洗 -->
    <div
      v-if="isCodeFilterTool"
      class="grid min-w-0 max-w-2xl gap-4 rounded-lg border border-teal-200/80 bg-white/70 p-3 sm:grid-cols-2"
    >
      <div class="space-y-1.5 rounded-lg border border-teal-200/60 bg-background/80 p-3">
        <Label class="text-xs text-muted-foreground">
          粘贴代码（仅识别纯 6 位，空格/逗号/换行分隔）
        </Label>
        <Textarea
          v-model="filterInput"
          class="field-sizing-fixed h-36 max-h-48 min-h-28 w-full resize-y overflow-y-auto font-mono text-xs"
          placeholder="600519&#10;000001&#10;002821"
          spellcheck="false"
        />
      </div>
      <div class="space-y-1.5 rounded-lg border border-teal-200/60 bg-background/80 p-3">
        <Label class="text-xs text-muted-foreground">结果（每行一个）</Label>
        <Textarea
          v-model="filterOutput"
          readonly
          class="field-sizing-fixed h-36 max-h-48 min-h-28 w-full resize-y overflow-y-auto font-mono text-xs"
          placeholder="点击「处理」后显示"
          spellcheck="false"
        />
      </div>
      <div class="flex flex-wrap items-center gap-2 sm:col-span-2">
        <p class="mr-auto text-xs text-muted-foreground">{{ filterStats }}</p>
        <Button size="sm" class="bg-teal-700 text-white hover:bg-teal-800" @click="onFilterProcess">
          处理
        </Button>
        <Button
          size="sm"
          variant="outline"
          class="border-teal-400/70 text-teal-800 hover:bg-teal-50"
          @click="onFilterCopy"
        >
          {{ filterCopyFlash || '复制结果' }}
        </Button>
      </div>
    </div>

    <!-- 主栏：策略（可选）+ 运行结果 -->
    <div
      v-if="!isCodeFilterTool"
      class="flex min-w-0 flex-wrap items-start gap-6 md:gap-8"
    >
      <form
        v-if="hasStrategySelect"
        class="w-44 shrink-0 space-y-2 rounded-lg border border-border/60 bg-background/60 p-3"
        @submit.prevent="onRun"
      >
        <Label class="text-xs text-muted-foreground">选择策略</Label>
        <Popover v-model:open="strategyOpen">
          <PopoverTrigger as-child>
            <Button
              type="button"
              variant="outline"
              role="combobox"
              :aria-expanded="strategyOpen"
              class="h-9 w-full justify-between font-normal"
            >
              <span class="truncate">{{ strategyLabel }}</span>
              <ChevronsUpDown class="size-4 shrink-0 opacity-50" />
            </Button>
          </PopoverTrigger>
          <PopoverContent class="w-64 p-0" align="start">
            <Command>
              <CommandInput placeholder="搜索策略…" />
              <CommandList>
                <CommandEmpty>无匹配策略</CommandEmpty>
                <CommandGroup>
                  <CommandItem
                    v-for="opt in strategies"
                    :key="opt.id"
                    :value="opt.label"
                    :data-checked="selectedStrategy?.id === opt.id ? true : undefined"
                    @click="pickStrategy(opt)"
                  >
                    {{ opt.label }}
                  </CommandItem>
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>
        <p class="text-[11px] text-muted-foreground">
          {{
            step.symbolsPaste
              ? draft.symbolsText.trim()
                ? '已粘贴股票 → 运行时按所选形态传入'
                : step.symbolsPasteEmptyHint || '未粘贴 → 使用默认上游逻辑'
              : '请选择运行策略后点击运行'
          }}
        </p>
      </form>

      <aside class="min-w-0 flex-1 rounded-lg border border-border/60 bg-muted/40 px-3 py-2.5 sm:max-w-md">
        <p class="text-[11px] font-medium text-muted-foreground">运行结果</p>
        <div class="mt-1.5 flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-xs">
          <span :class="cn('font-medium', statusClass)">{{ statusLabel }}</span>
          <span v-if="recentRun" class="text-muted-foreground">{{ formatTime(recentRun.finishedAt) }}</span>
          <span v-if="durationLabel" class="text-muted-foreground">{{ durationLabel }}</span>
          <span
            v-if="tableData?.exists && previewRowCount"
            class="text-muted-foreground"
          >
            预览 {{ previewRowCount }} 行
            <template v-if="tableData.truncated">（截断）</template>
          </span>
        </div>
        <p v-if="!recentRun" class="mt-1 text-xs text-muted-foreground">尚未运行本步骤</p>

        <div
          v-if="tableOutputs.length || klineOutputs.length"
          class="mt-2 space-y-1 border-t border-border/50 pt-2"
        >
          <p class="text-[10px] uppercase tracking-wide text-muted-foreground">附件</p>
          <button
            v-for="out in tableOutputs"
            :key="out.path"
            type="button"
            class="flex w-full min-w-0 items-center gap-1.5 truncate text-left text-[11px] font-medium text-emerald-700 hover:underline"
            @click="onPickAttachment(out.path)"
          >
            <FileSpreadsheet class="size-3 shrink-0 opacity-70" />
            <span class="truncate">{{ out.label }}</span>
          </button>
          <button
            v-for="out in klineOutputs"
            :key="out.path"
            type="button"
            class="flex w-full min-w-0 items-center gap-1.5 truncate text-left text-[11px] font-medium text-amber-700 hover:underline"
            @click="openKlineReport(out.path)"
          >
            <FileSpreadsheet class="size-3 shrink-0 opacity-70" />
            <span class="truncate">{{ out.label }} → 报告</span>
          </button>
        </div>
      </aside>
    </div>

    <!-- 结果表：非聚焦默认收起 -->
    <div v-if="!isCodeFilterTool" class="min-w-0 max-w-full space-y-2">
      <div class="flex min-w-0 items-center justify-between gap-2">
        <p class="min-w-0 truncate text-xs font-medium text-muted-foreground">
          候选结果
          <span v-if="activeOutputPath && tableExpanded" class="font-mono font-normal">
            · {{ activeOutputPath }}
          </span>
        </p>
        <div class="flex shrink-0 items-center gap-1">
          <Button
            v-if="tableExpanded && mappedTable"
            size="sm"
            variant="ghost"
            class="h-7 text-xs"
            @click="showAllColumns = !showAllColumns"
          >
            {{ showAllColumns ? '精简列' : '全部列' }}
          </Button>
          <Button
            v-if="tableExpanded && activeOutputPath"
            size="sm"
            variant="ghost"
            class="h-7 text-xs"
            @click="openOutputInReport(activeOutputPath)"
          >
            报告页
          </Button>
          <Button
            size="sm"
            variant="outline"
            class="h-7 text-xs"
            @click="tableExpanded ? collapseTable() : expandTable()"
          >
            <component :is="tableExpanded ? ChevronUp : ChevronDown" class="size-3.5" />
            {{ tableExpanded ? '收起' : '展开结果' }}
          </Button>
        </div>
      </div>

      <div v-if="tableExpanded" ref="tableHost" class="min-w-0 space-y-2">
        <p v-if="tableLoading" class="py-8 text-center text-sm text-muted-foreground">加载中…</p>
        <div
          v-else-if="tableData?.exists && displayColumns.length"
          class="max-h-[min(420px,50vh)] min-w-0 max-w-full overflow-auto rounded-lg border border-border/40 bg-muted/20"
        >
          <Table class="w-max min-w-full">
            <TableHeader class="sticky top-0 z-[1] bg-muted/95 backdrop-blur">
              <TableRow>
                <TableHead
                  v-for="col in displayColumns"
                  :key="col.key"
                  class="whitespace-nowrap bg-muted/95"
                >
                  {{ col.label }}
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="(row, ri) in tableData.rows" :key="ri">
                <TableCell
                  v-for="col in displayColumns"
                  :key="col.key"
                  class="max-w-[220px] truncate whitespace-nowrap font-mono text-xs"
                  :title="formatPreviewCell(tableData.headers[col.index] || col.label, row[col.index], tableLoadedPath || '')"
                >
                  {{ formatPreviewCell(tableData.headers[col.index] || col.label, row[col.index], tableLoadedPath || '') }}
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <p v-else class="py-6 text-center text-sm text-muted-foreground">
          {{
            tableVisible
              ? '运行成功后在此预览表；K 线请走报告页'
              : '展开后加载预览；也可点击上方附件'
          }}
        </p>
      </div>
    </div>

    <!-- 参数 Sheet -->
    <Sheet :open="paramsOpen" @update:open="(v) => (paramsOpen = v)">
      <SheetContent side="right" class="flex w-full flex-col sm:max-w-md">
        <SheetHeader>
          <SheetTitle>运行参数</SheetTitle>
          <SheetDescription class="font-mono">{{ step.id }}</SheetDescription>
        </SheetHeader>

        <div class="flex-1 space-y-4 overflow-y-auto px-4 pb-2">
          <div v-if="step.symbolsPaste" class="space-y-1.5">
            <Label class="text-xs text-muted-foreground">
              {{ step.symbolsPasteHint || '可选粘贴股票代码' }}
            </Label>
            <Textarea
              v-model="draft.symbolsText"
              class="min-h-28 w-full font-mono text-xs"
              placeholder="600519&#10;000001&#10;002821 或逗号分隔"
              spellcheck="false"
            />
          </div>

          <div v-if="step.poolPresets?.length" class="space-y-1.5">
            <Label class="text-xs text-muted-foreground">股票池</Label>
            <div class="flex flex-wrap gap-1.5">
              <Button
                v-for="p in step.poolPresets"
                :key="p.path"
                size="sm"
                type="button"
                :variant="draft.poolPath === p.path ? 'default' : 'outline'"
                @click="draft.poolPath = p.path"
              >
                {{ p.label }}
              </Button>
            </div>
          </div>

          <div v-if="step.workspaceInputs?.length" class="space-y-1.5">
            <Label class="text-xs text-muted-foreground">输入文件</Label>
            <Select
              :model-value="inputPath || undefined"
              @update:model-value="(v) => v && (inputPath = String(v))"
            >
              <SelectTrigger class="h-9 w-full">
                <SelectValue placeholder="选择输入…" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem
                  v-for="inp in step.workspaceInputs"
                  :key="inp.path"
                  :value="inp.path"
                >
                  {{ inp.label }}
                </SelectItem>
              </SelectContent>
            </Select>
            <Textarea
              v-model="inputContent"
              :disabled="inputLoading || !inputPath"
              class="field-sizing-fixed h-36 max-h-56 min-h-28 w-full resize-y overflow-y-auto font-mono text-xs leading-relaxed"
              placeholder="下拉选择后在此编辑内容"
              spellcheck="false"
            />
            <p class="truncate font-mono text-[10px] text-muted-foreground">
              {{ inputMsg || inputPath || '—' }}
            </p>
          </div>

          <p v-if="!hasInputPanel" class="text-sm text-muted-foreground">本步骤无需额外参数。</p>
        </div>

        <SheetFooter class="flex-row justify-end gap-2 sm:space-x-0">
          <Button
            v-if="step.workspaceInputs?.length"
            variant="outline"
            size="sm"
            :disabled="inputSaving || inputLoading || !inputPath"
            @click="saveInputFile"
          >
            {{ inputSaving ? '保存中…' : '保存文件' }}
          </Button>
          <Button size="sm" @click="paramsOpen = false">完成</Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  </section>
</template>
