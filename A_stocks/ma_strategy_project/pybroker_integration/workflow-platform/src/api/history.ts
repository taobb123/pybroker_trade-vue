import type { RunResult, WorkspaceOutput } from '@/api/types'

export type RunRecord = {
  id: string
  stepId: string
  stepTitle: string
  startedAt: string
  finishedAt: string
  exitCode: number
  status: 'success' | 'error'
  log: string
  durationMs: number
  outputs: WorkspaceOutput[]
}

const STORAGE_KEY = 'workflow-platform:run-history:v2'
const MAX_RECORDS = 80

export function loadRunHistory(): RunRecord[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return seedDemoHistory()
    const parsed = JSON.parse(raw) as RunRecord[]
    if (!Array.isArray(parsed)) return seedDemoHistory()
    return parsed.map((r) => ({
      ...r,
      outputs: Array.isArray(r.outputs) ? r.outputs : [],
    }))
  } catch {
    return seedDemoHistory()
  }
}

export function saveRunHistory(records: RunRecord[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(records.slice(0, MAX_RECORDS)))
}

export function createRunRecord(
  step: { id: string; title: string; workspaceOutputs?: WorkspaceOutput[] },
  result: RunResult,
  startedAt: string,
): RunRecord {
  const finishedAt = new Date().toISOString()
  const start = new Date(startedAt).getTime()
  const end = new Date(finishedAt).getTime()
  return {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    stepId: step.id,
    stepTitle: step.title,
    startedAt,
    finishedAt,
    exitCode: result.exit_code,
    status: result.exit_code === 0 ? 'success' : 'error',
    log: result.merged_log,
    durationMs: Math.max(0, end - start),
    outputs: step.workspaceOutputs ?? [],
  }
}

function seedDemoHistory(): RunRecord[] {
  const now = Date.now()
  const rocLog = [
    '# mock run · roc_20',
    'OK · ranked',
    JSON.stringify(
      [
        { rank: 1, symbol: '600519', name: '贵州茅台', roc_20: 0.182, weight: 0.12 },
        { rank: 2, symbol: '300750', name: '宁德时代', roc_20: 0.165, weight: 0.1 },
        { rank: 3, symbol: '601318', name: '中国平安', roc_20: 0.141, weight: 0.09 },
      ],
      null,
      2,
    ),
  ].join('\n')

  const patternOutputs: WorkspaceOutput[] = [
    { path: 'pattern_entry_scan.csv', label: '形态建仓信号表' },
    { path: 'pattern_entry_valuation_rank.csv', label: '观察池估值排名表' },
    { path: 'pattern_entry_q_rank.csv', label: '观察池Q排名表' },
    { path: 'pattern_entry_mplus_rank.csv', label: '观察池M+排名表' },
    { path: 'pattern_entry_mminus_rank.csv', label: '观察池M-排名表' },
  ]

  const records: RunRecord[] = [
    {
      id: 'demo-roc20',
      stepId: 'roc_20',
      stepTitle: '20日 ROC 排序',
      startedAt: new Date(now - 3 * 60_000).toISOString(),
      finishedAt: new Date(now - 2 * 60_000).toISOString(),
      exitCode: 0,
      status: 'success',
      log: rocLog,
      durationMs: 1800,
      outputs: [{ path: 'factor_investing_ranking_latest.csv', label: 'ROC20 表' }],
    },
    {
      id: 'demo-compute',
      stepId: 'compute_today',
      stepTitle: '做 T 止盈止损',
      startedAt: new Date(now - 5 * 60_000).toISOString(),
      finishedAt: new Date(now - 4 * 60_000).toISOString(),
      exitCode: 0,
      status: 'success',
      log: '# compute_today\nOK · see prediction_kline_compare.json / today_high_low_result.csv',
      durationMs: 3100,
      outputs: [
        { path: 'prediction_kline_compare.json', label: '预测 K 线' },
        { path: 'today_high_low_result.csv', label: '当日高低价' },
      ],
    },
    {
      id: 'demo-pattern',
      stepId: 'fetch_pattern_entry',
      stepTitle: '形态建仓信号（突破回踩 / 下跌放量反转）',
      startedAt: new Date(now - 8 * 60_000).toISOString(),
      finishedAt: new Date(now - 7 * 60_000).toISOString(),
      exitCode: 0,
      status: 'success',
      log: '# fetch_pattern_entry\nOK · see workspace CSV outputs',
      durationMs: 2200,
      outputs: patternOutputs,
    },
  ]

  saveRunHistory(records)
  return records
}
