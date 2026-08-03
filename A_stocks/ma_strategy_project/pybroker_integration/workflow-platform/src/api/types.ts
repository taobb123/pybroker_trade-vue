export type WorkspacePathRef = {
  path: string
  label: string
}

export type WorkspaceGlobRef = {
  glob: string
  label: string
  copy_column?: string
}

export type WorkspaceOutput = WorkspacePathRef | WorkspaceGlobRef

export type RunMode = {
  id: string
  label: string
  script?: string
  args?: string[]
}

export type PoolPreset = {
  label: string
  path: string
}

export type ComboOption = {
  id: string
  label: string
}

export type WorkflowStep = {
  id: string
  title: string
  type?: string
  /** frontend_tool 时的工具名，如 filter_stock_codes */
  tool?: string
  category: 'daily' | 'biweekly' | 'tool' | 'core' | 'chain' | 'weekly'
  /** 会员门控：缺省 basic；advanced 需 Pro/Team */
  tier?: 'basic' | 'advanced'
  description?: string
  tags?: string[]
  note?: string
  frequency?: string
  frequencyNote?: string
  highlight?: string
  symbolsPaste?: boolean
  symbolsPasteHint?: string
  symbolsPasteEmptyHint?: string
  symbolsPasteComboOptions?: ComboOption[]
  runModes?: RunMode[]
  poolPresets?: PoolPreset[]
  workspaceInputs?: WorkspacePathRef[]
  workspaceOutputs?: WorkspaceOutput[]
  runnable: boolean
}

export type StepDraft = {
  symbolsText: string
  comboId: string
  runMode: string
  poolPath: string
  poolCustom: string
}

export type RunPayload = {
  extra_args?: string[]
  run_mode?: string
}

export type RunResult = {
  exit_code: number
  merged_log: string
  skipped?: boolean
}

export type TablePreview = {
  exists: boolean
  path: string
  headers: string[]
  rows: string[][]
  truncated?: boolean
  preview_unsupported?: boolean
  /** table API 对 md/png/txt 的软分流字段 */
  preview_kind?: 'markdown' | 'image' | 'text' | string
  preview_note?: string
  error?: string
}

export function isPathOutput(o: WorkspaceOutput): o is WorkspacePathRef {
  return 'path' in o && Boolean(o.path)
}

export function normalizeSymbols(text: string): string {
  return text
    .split(/[\s,，;；]+/)
    .map((s) => s.trim())
    .filter(Boolean)
    .join(',')
}

export function collectRunPayload(step: WorkflowStep, draft: StepDraft): RunPayload | null {
  const extra: string[] = []

  if (step.poolPresets?.length) {
    const path =
      draft.poolPath === '__custom__' ? draft.poolCustom.trim() : draft.poolPath.trim()
    if (!path) {
      alert('请选择或填写股票池路径')
      return null
    }
    extra.push('--pool', path)
  }

  if (step.symbolsPaste) {
    const symbols = normalizeSymbols(draft.symbolsText)
    if (symbols) {
      if (step.symbolsPasteComboOptions?.length && !draft.comboId) {
        alert('粘贴列表时请先选择形态 ID')
        return null
      }
      if (draft.comboId) {
        extra.push('--combo-id', draft.comboId)
      }
      extra.push('--symbols', symbols)
    }
  }

  const payload: RunPayload = {}
  if (extra.length) payload.extra_args = extra
  if (step.runModes?.length && draft.runMode) payload.run_mode = draft.runMode
  return payload
}

export function emptyDraft(step: WorkflowStep): StepDraft {
  return {
    symbolsText: '',
    comboId: '',
    runMode: step.runModes?.[0]?.id ?? '',
    poolPath: step.poolPresets?.[0]?.path ?? '',
    poolCustom: '',
  }
}
