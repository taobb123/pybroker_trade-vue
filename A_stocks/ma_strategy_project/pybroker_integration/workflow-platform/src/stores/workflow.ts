import { defineStore } from 'pinia'
import { computed, reactive, ref } from 'vue'
import {
  fetchWorkflowSteps,
  runWorkflowStep,
  stopWorkflowRun,
  type RunResult,
  type WorkflowStep,
} from '@/api/workflow'
import {
  createRunRecord,
  loadRunHistory,
  saveRunHistory,
  type RunRecord,
} from '@/api/history'
import { parseReportFromLog } from '@/api/parse'
import {
  collectRunPayload,
  emptyDraft,
  type StepDraft,
  type WorkspaceOutput,
} from '@/api/types'
import { chainDcConceptToVpSixCombo } from '@/api/dcConceptChain'

export const useWorkflowStore = defineStore('workflow', () => {
  const steps = ref<WorkflowStep[]>([])
  const busy = ref(false)
  const sheetOpen = ref(false)
  const activeStep = ref<WorkflowStep | null>(null)
  const lastResult = ref<RunResult | null>(null)
  const status = ref<'idle' | 'running' | 'success' | 'error'>('idle')
  const runs = ref<RunRecord[]>(loadRunHistory())
  const selectedRunId = ref<string | null>(runs.value[0]?.id ?? null)
  const drafts = reactive<Record<string, StepDraft>>({})
  const reportTableKey = ref<string>('')
  const previewOutputs = ref<WorkspaceOutput[] | null>(null)

  const selectedRun = computed(
    () => runs.value.find((r) => r.id === selectedRunId.value) ?? runs.value[0] ?? null,
  )

  const selectedReport = computed(() =>
    selectedRun.value
      ? parseReportFromLog(selectedRun.value.log)
      : { rows: [], numericKeys: [], chartKey: null },
  )

  const selectedOutputs = computed(() => selectedRun.value?.outputs ?? [])

  const successRuns = computed(() => runs.value.filter((r) => r.status === 'success'))
  const errorRuns = computed(() => runs.value.filter((r) => r.status === 'error'))

  function ensureDraft(step: WorkflowStep): StepDraft {
    if (!drafts[step.id]) drafts[step.id] = emptyDraft(step)
    return drafts[step.id]!
  }

  async function loadSteps() {
    steps.value = await fetchWorkflowSteps()
    for (const s of steps.value) ensureDraft(s)
  }

  function persistRuns() {
    saveRunHistory(runs.value)
  }

  function pushRun(record: RunRecord) {
    runs.value = [record, ...runs.value].slice(0, 80)
    selectedRunId.value = record.id
    const firstPath = record.outputs.find((o) => 'path' in o && o.path)
    reportTableKey.value = firstPath && 'path' in firstPath ? firstPath.path : ''
    persistRuns()
  }

  async function runStep(step: WorkflowStep, opts?: { openSheet?: boolean }) {
    if (!step.runnable) return
    const draft = ensureDraft(step)
    const payload = collectRunPayload(step, draft)
    if (payload === null) return

    activeStep.value = step
    if (opts?.openSheet !== false) sheetOpen.value = true
    busy.value = true
    status.value = 'running'
    lastResult.value = null
    const startedAt = new Date().toISOString()
    let result = await runWorkflowStep(step.id, payload)

    // 东财概念扫描成功后：members → 股票清洗 → 量价六组合 symbols
    if (step.id === 'fetch_dc_concept_ma5' && result.exit_code === 0) {
      const chain = await chainDcConceptToVpSixCombo()
      result = {
        ...result,
        merged_log:
          result.merged_log +
          '\n\n# auto chain · filter_stock_codes → fetch_vp_six_combo_symbols\n' +
          chain.message,
      }
    }

    lastResult.value = result
    status.value = result.exit_code === 0 ? 'success' : 'error'
    busy.value = false
    pushRun(createRunRecord(step, result, startedAt))
    return result
  }

  /** 复用旧版「停止」：POST /api/run/stop */
  async function stopStep() {
    if (!busy.value) return
    const r = await stopWorkflowRun()
    if (lastResult.value) {
      lastResult.value = {
        ...lastResult.value,
        merged_log: `${lastResult.value.merged_log}\n\n>>> POST /api/run/stop\n${r.message}`,
      }
    }
    return r
  }

  function openSheet(step: WorkflowStep) {
    activeStep.value = step
    sheetOpen.value = true
  }

  function openRunSheet(record: RunRecord) {
    selectedRunId.value = record.id
    activeStep.value = steps.value.find((s) => s.id === record.stepId) ?? {
      id: record.stepId,
      title: record.stepTitle,
      category: 'tool',
      runnable: true,
      workspaceOutputs: record.outputs,
    }
    lastResult.value = {
      exit_code: record.exitCode,
      merged_log: record.log,
    }
    status.value = record.status
    sheetOpen.value = true
  }

  function selectRun(id: string) {
    if (!id) return
    selectedRunId.value = id
    previewOutputs.value = null
    const run = runs.value.find((r) => r.id === id)
    const first = run?.outputs.find((o) => 'path' in o && o.path)
    reportTableKey.value = first && 'path' in first ? first.path : ''
  }

  function openStepOutput(step: WorkflowStep, tablePath: string) {
    previewOutputs.value = step.workspaceOutputs ?? []
    reportTableKey.value = tablePath
    const hit =
      runs.value.find((r) => r.stepId === step.id && r.status === 'success') ??
      runs.value.find((r) => r.stepId === step.id)
    if (hit) selectedRunId.value = hit.id
  }

  function clearRuns() {
    runs.value = []
    selectedRunId.value = null
    reportTableKey.value = ''
    previewOutputs.value = null
    saveRunHistory([])
  }

  return {
    steps,
    busy,
    sheetOpen,
    activeStep,
    lastResult,
    status,
    runs,
    selectedRunId,
    selectedRun,
    selectedReport,
    selectedOutputs,
    successRuns,
    errorRuns,
    drafts,
    reportTableKey,
    previewOutputs,
    ensureDraft,
    loadSteps,
    runStep,
    stopStep,
    openSheet,
    openRunSheet,
    selectRun,
    openStepOutput,
    clearRuns,
  }
})
