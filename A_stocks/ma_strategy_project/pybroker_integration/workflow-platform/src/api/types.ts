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

export type CustomParamOption = {
  value: string
  label: string
}

export type CustomParam = {
  id: string
  label: string
  hint?: string
  /** 传给脚本的参数名，如 --top-n */
  flag: string
  type: 'select' | 'multi'
  /** select 为单个值；multi 为逗号拼接 */
  default: string
  options: CustomParamOption[]
  /** int 时运行前校验为正整数 */
  valueType?: 'int' | 'text'
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
  /** 粘贴代码出现在「输入文件」下拉里，而不是单独一块 */
  symbolsPasteAsInput?: boolean
  /** 粘贴代码的独立结果表，相对项目根 */
  symbolsPasteOutput?: string
  symbolsPasteComboOptions?: ComboOption[]
  runModes?: RunMode[]
  poolPresets?: PoolPreset[]
  customParams?: CustomParam[]
  workspaceInputs?: WorkspacePathRef[]
  workspaceOutputs?: WorkspaceOutput[]
  runnable: boolean
}

export type StepDraft = {
  symbolsText: string
  /** 输入文件下拉里选了「粘贴代码」 */
  pasteInput: boolean
  comboId: string
  runMode: string
  poolPath: string
  poolCustom: string
  /** 自定义参数当前选项；multi 为逗号拼接 */
  paramValues: Record<string, string>
  /** select 选「自定义」时的手填值 */
  paramCustom: Record<string, string>
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

  if (step.customParams?.length) {
    for (const param of step.customParams) {
      const selected = (draft.paramValues?.[param.id] ?? param.default).trim()
      if (param.type === 'multi') {
        const picked = selected.split(',').map((s) => s.trim()).filter(Boolean)
        const defaults = param.default.split(',').map((s) => s.trim()).filter(Boolean)
        if (!picked.length) {
          alert(`请至少选择一项：${param.label}`)
          return null
        }
        const same =
          picked.length === defaults.length && picked.every((v) => defaults.includes(v))
        if (same) continue
        extra.push(param.flag, picked.join(','))
        continue
      }
      const value =
        selected === '__custom__' ? (draft.paramCustom?.[param.id] ?? '').trim() : selected
      if (!value) {
        alert(`请填写${param.label}`)
        return null
      }
      if (param.valueType === 'int') {
        const n = Number(value)
        if (!Number.isInteger(n) || n < 1) {
          alert(`${param.label}须为正整数`)
          return null
        }
      }
      if (value === param.default) continue
      extra.push(param.flag, value)
    }
  }

  if (step.symbolsPaste) {
    const usePaste = !step.symbolsPasteAsInput || Boolean(draft.pasteInput)
    const symbols = normalizeSymbols(draft.symbolsText)
    if (usePaste && symbols) {
      if (step.symbolsPasteComboOptions?.length && !draft.comboId) {
        alert('粘贴列表时请先选择形态 ID')
        return null
      }
      if (draft.comboId) {
        extra.push('--combo-id', draft.comboId)
      }
      if (step.symbolsPasteOutput) {
        extra.push('--ranking-file', step.symbolsPasteOutput)
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
    pasteInput: false,
    comboId: '',
    runMode: step.runModes?.[0]?.id ?? '',
    poolPath: step.poolPresets?.[0]?.path ?? '',
    poolCustom: '',
    paramValues: Object.fromEntries((step.customParams ?? []).map((p) => [p.id, p.default])),
    paramCustom: {},
  }
}
