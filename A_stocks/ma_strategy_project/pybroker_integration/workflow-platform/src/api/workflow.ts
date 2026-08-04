import type {
  ComboOption,
  PoolPreset,
  RunMode,
  RunPayload,
  RunResult,
  TablePreview,
  WorkflowStep,
  WorkspaceOutput,
  WorkspacePathRef,
} from '@/api/types'
import { resolveStepTier } from '@/config/businessRules'
import { apiUrl, apiRunUrl } from '@/config/apiBase'

export type { WorkflowStep, RunResult, RunPayload, TablePreview } from '@/api/types'

function mapCategory(s: Record<string, unknown>): WorkflowStep['category'] {
  const type = String(s.type ?? '')
  const hl = String(s.highlight ?? '')
  const freq = String(s.frequency ?? '')
  // 前端小工具可挂在每日等分类下（如代码清洗），勿一律归为 tool
  if (type === 'frontend_tool') {
    if (hl === 'core') return 'core'
    if (hl === 'chain') return 'chain'
    if (freq === 'biweekly') return 'biweekly'
    if (freq === 'weekly') return 'weekly'
    return 'daily'
  }
  if (hl === 'core') return 'core'
  if (hl === 'chain') return 'chain'
  if (freq === 'daily') return 'daily'
  if (freq === 'biweekly') return 'biweekly'
  if (freq === 'weekly') return 'weekly'
  return 'tool'
}

function mapStep(s: Record<string, unknown>): WorkflowStep {
  const type = String(s.type ?? 'script')
  const tags: string[] = []
  // 小工具不打「每日」等频率标签，避免与策略卡混淆
  if (s.frequency && type !== 'frontend_tool') {
    const note = s.frequency_note ? String(s.frequency_note).split('·')[0]?.trim() : ''
    const freqLabel =
      s.frequency === 'daily'
        ? '每日'
        : s.frequency === 'biweekly'
          ? '双周'
          : s.frequency === 'weekly'
            ? '每周'
            : String(s.frequency)
    const hl =
      s.highlight === 'core' ? '核心' : s.highlight === 'chain' ? '链式' : ''
    tags.push([freqLabel, hl].filter(Boolean).join('·') || freqLabel)
  }
  if (s.frequency_note && type !== 'frontend_tool') {
    const short = String(s.frequency_note)
    // 无独立 note 时 frequency_note 会作为 description 展示，勿再打成标签造成重复
    if (short.length < 40 && s.note) tags.push(short)
  }

  return {
    id: String(s.id ?? s.name),
    title: String(s.title ?? s.name ?? s.id),
    type,
    tool: s.tool ? String(s.tool) : undefined,
    category: mapCategory(s),
    tier: resolveStepTier({
      id: String(s.id ?? s.name),
      tier: s.tier,
      highlight: s.highlight,
    }),
    description: s.note ? String(s.note) : s.frequency_note ? String(s.frequency_note) : undefined,
    tags,
    note: s.note ? String(s.note) : undefined,
    frequency: s.frequency ? String(s.frequency) : undefined,
    frequencyNote: s.frequency_note ? String(s.frequency_note) : undefined,
    highlight: s.highlight ? String(s.highlight) : undefined,
    symbolsPaste: Boolean(s.symbols_paste),
    symbolsPasteHint: s.symbols_paste_hint ? String(s.symbols_paste_hint) : undefined,
    symbolsPasteEmptyHint: s.symbols_paste_empty_hint
      ? String(s.symbols_paste_empty_hint)
      : undefined,
    symbolsPasteComboOptions: Array.isArray(s.symbols_paste_combo_options)
      ? (s.symbols_paste_combo_options as ComboOption[]).map((o) => ({
          id: String(o.id),
          label: String(o.label),
        }))
      : undefined,
    runModes: Array.isArray(s.run_modes)
      ? (s.run_modes as RunMode[]).map((m) => ({
          id: String(m.id),
          label: String(m.label),
          script: m.script ? String(m.script) : undefined,
          args: Array.isArray(m.args) ? m.args.map(String) : undefined,
        }))
      : undefined,
    poolPresets: Array.isArray(s.pool_presets)
      ? (s.pool_presets as PoolPreset[]).map((p) => ({
          label: String(p.label),
          path: String(p.path),
        }))
      : undefined,
    workspaceInputs: Array.isArray(s.workspace_inputs)
      ? (s.workspace_inputs as WorkspacePathRef[]).map((i) => ({
          path: String(i.path),
          label: String(i.label),
        }))
      : undefined,
    workspaceOutputs: Array.isArray(s.workspace_outputs)
      ? (s.workspace_outputs as WorkspaceOutput[]).map((o) => {
          if ('glob' in o && o.glob) {
            return {
              glob: String(o.glob),
              label: String(o.label),
              copy_column: o.copy_column ? String(o.copy_column) : undefined,
            }
          }
          return { path: String((o as WorkspacePathRef).path), label: String(o.label) }
        })
      : undefined,
    runnable: type !== 'manual' && type !== 'frontend_tool',
  }
}

const MOCK_STEPS: WorkflowStep[] = [
  mapStep({
    id: 'market_temperature',
    title: '市场温度计 - 每日仓位报告',
    type: 'script',
    highlight: 'core',
    tier: 'advanced',
    frequency: 'daily',
    frequency_note: 'V2.3',
    run_modes: [
      { id: 'daily', label: '每日报告' },
      { id: 'backtest_fast', label: '快速回测' },
    ],
    workspace_outputs: [
      { path: 'market_temperature_latest.csv', label: '每日仓位报告' },
      { path: 'market_temperature_backtest.csv', label: '回测明细' },
    ],
  }),
  mapStep({
    id: 'fetch_pattern_entry',
    title: '形态建仓信号（突破回踩 / 下跌放量反转）',
    type: 'script',
    highlight: 'chain',
    tier: 'advanced',
    frequency: 'daily',
    frequency_note: '跟随 fetch_vp_six_combo · combo4+6',
    symbols_paste: true,
    symbols_paste_hint: '可选粘贴；空则按上游 combo4/6 观察表扫描两种形态',
    symbols_paste_empty_hint: '未粘贴 → 扫描上游 combo4+6 观察表',
    symbols_paste_combo_options: [
      { id: '4', label: '4 · 上涨放量突破（形态1）' },
      { id: '6', label: '6 · 下跌放量反转（形态2）' },
    ],
    workspace_inputs: [
      { path: 'config/fetch_pattern_entry_symbols.txt', label: '观察代码·combo4（可选）' },
      { path: 'config/fetch_pattern_entry_symbols_6.txt', label: '观察代码·combo6（可选）' },
      { path: 'vp_combo_watch_4.csv', label: '上涨放量突破观察表' },
      { path: 'vp_combo_watch_6.csv', label: '下跌放量观察表' },
    ],
    workspace_outputs: [
      { path: 'pattern_entry_scan.csv', label: '形态建仓信号表' },
      { path: 'pattern_entry_valuation_rank.csv', label: '观察池估值排名表' },
      { path: 'pattern_entry_q_rank.csv', label: '观察池Q排名表' },
      { path: 'pattern_entry_mplus_rank.csv', label: '观察池M+排名表' },
      { path: 'pattern_entry_mminus_rank.csv', label: '观察池M-排名表' },
    ],
  }),
  mapStep({
    id: 'roc_20',
    title: '20日 ROC 排序',
    type: 'script',
    highlight: 'chain',
    frequency: 'daily',
    pool_presets: [
      { label: '默认池', path: 'stocks_pool.txt' },
      { label: '自定义', path: '__custom__' },
    ],
    workspace_outputs: [{ path: 'factor_investing_ranking_latest.csv', label: 'ROC20 表' }],
  }),
]

function withoutWeeklyAndTool(steps: WorkflowStep[]): WorkflowStep[] {
  return steps.filter((s) => {
    // 前端小工具保留展示，与策略脚本区分
    if (s.type === 'frontend_tool') return true
    return s.category !== 'weekly' && s.category !== 'tool'
  })
}

export async function fetchWorkflowSteps(): Promise<WorkflowStep[]> {
  try {
    const res = await fetch(apiUrl('/api/config'))
    if (!res.ok) throw new Error(`config ${res.status}`)
    const cfg = await res.json()
    const steps = (cfg.steps ?? []) as Array<Record<string, unknown>>
    if (!Array.isArray(steps) || !steps.length) return withoutWeeklyAndTool(MOCK_STEPS)
    return withoutWeeklyAndTool(steps.map(mapStep))
  } catch {
    return withoutWeeklyAndTool(MOCK_STEPS)
  }
}

/** 与旧版 stock_pool_workflow「停止」一致：终止当前子进程 */
export async function stopWorkflowRun(): Promise<{ ok: boolean; message: string }> {
  try {
    const res = await fetch(apiRunUrl('/api/run/stop'), { method: 'POST' })
    const j = (await res.json().catch(() => ({}))) as Record<string, unknown>
    if (!res.ok) {
      return { ok: false, message: `[停止请求失败] ${JSON.stringify(j)}` }
    }
    return { ok: true, message: '已发送终止信号（子进程结束需稍候）。' }
  } catch (e) {
    return { ok: false, message: `[停止请求异常] ${String(e)}` }
  }
}

export async function runWorkflowStep(
  stepId: string,
  payload: RunPayload = {},
): Promise<RunResult> {
  try {
    const res = await fetch(apiRunUrl(`/api/run/step/${encodeURIComponent(stepId)}`), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    const text = await res.text()
    let j: Record<string, unknown> = {}
    try {
      j = text ? (JSON.parse(text) as Record<string, unknown>) : {}
    } catch {
      return {
        exit_code: 1,
        merged_log: [
          `# run failed · ${stepId}`,
          `HTTP ${res.status}（响应不是 JSON，常见于网关超时/Worker 未反代）`,
          text.slice(0, 2000),
        ].join('\n'),
      }
    }
    if (!res.ok) {
      return {
        exit_code: 1,
        merged_log: JSON.stringify(j, null, 2),
      }
    }
    return {
      exit_code: Number(j.exit_code ?? 1),
      merged_log: String(j.merged_log ?? ''),
      skipped: Boolean(j.skipped),
    }
  } catch (e) {
    // 仅本地开发兜底 mock；线上必须暴露真实错误，避免误以为「跑成功」
    const isLocal =
      typeof location !== 'undefined' &&
      (location.hostname === '127.0.0.1' || location.hostname === 'localhost')
    if (isLocal) {
      return {
        exit_code: 0,
        merged_log: [
          `# mock run · ${stepId}`,
          'OK · server offline',
          JSON.stringify(
            [
              { rank: 1, symbol: '600519', name: '贵州茅台', roc_20: 0.182 },
              { rank: 2, symbol: '300750', name: '宁德时代', roc_20: 0.165 },
            ],
            null,
            2,
          ),
        ].join('\n'),
      }
    }
    return {
      exit_code: 1,
      merged_log: [
        `# run failed · ${stepId}`,
        '请求后端失败（非 mock）。请检查 api.freealpha.lol 与 CORS。',
        String(e),
      ].join('\n'),
    }
  }
}

export async function fetchWorkspaceTable(path: string, maxRows = 500): Promise<TablePreview> {
  try {
    const q = new URLSearchParams({ path, max_rows: String(maxRows) })
    const res = await fetch(apiRunUrl(`/api/workspace/table?${q}`))
    if (!res.ok) {
      return {
        exists: false,
        path,
        headers: [],
        rows: [],
        error: `HTTP ${res.status}`,
      }
    }
    return (await res.json()) as TablePreview
  } catch (e) {
    return {
      exists: false,
      path,
      headers: [],
      rows: [],
      error: String(e),
    }
  }
}

export async function fetchWorkspaceFile(path: string): Promise<{ exists: boolean; content: string }> {
  try {
    const q = new URLSearchParams({ path })
    const res = await fetch(apiRunUrl(`/api/workspace/file?${q}`))
    if (!res.ok) return { exists: false, content: '' }
    return (await res.json()) as { exists: boolean; content: string }
  } catch {
    return { exists: false, content: '' }
  }
}

export async function saveWorkspaceFile(path: string, content: string): Promise<boolean> {
  try {
    const res = await fetch(apiRunUrl('/api/workspace/file'), {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path, content }),
    })
    return res.ok
  } catch {
    return false
  }
}

export async function resolveLatestGlob(
  glob: string,
): Promise<{ rel_path?: string; exists?: boolean } | null> {
  try {
    const q = new URLSearchParams({ glob })
    const res = await fetch(apiRunUrl(`/api/workspace/latest?${q}`))
    if (!res.ok) return null
    return (await res.json()) as { rel_path?: string; exists?: boolean }
  } catch {
    return null
  }
}
