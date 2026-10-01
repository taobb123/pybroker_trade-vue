import { apiUrl } from '@/config/apiBase'

export type RiskHistogramBin = {
  left: number
  right: number
  count: number
}

export type RiskScenario = {
  name: string
  fractionOfKelly: number
  position: number
  medianTerminalWealth: number | null
  p05TerminalWealth: number | null
  p25TerminalWealth: number | null
  p75TerminalWealth: number | null
  p95TerminalWealth: number | null
  medianMaxDrawdown: number | null
  probDdGt20: number | null
  probDdGt30: number | null
}

export type RiskDecile = {
  decile: number
  label: string
  n: number
  smallSample: boolean
  mean: number | null
  median: number | null
  winRate: number | null
  posteriorWinRate: number | null
  probWinRateGtHalf: number | null
  probLoss: number | null
  std: number | null
  skew: number | null
  excessKurtosis: number | null
  var95: number | null
  cvar95: number | null
  payoffB: number | null
  kellyRaw: number | null
  kellyFull: number | null
  histogram: RiskHistogramBin[]
  scenarios: RiskScenario[]
  note: string | null
}

export type RiskReport = {
  schemaVersion: string
  factor: string
  factorField: string
  factorNote: string
  holdTradingDays: number
  sampleStepTradingDays: number | null
  sampleSource: string
  sampleEnd: string | null
  nRows: number
  nSignalDates: number
  nPaths: number
  nTrades: number
  seed: number
  seedRule: string
  priorAlpha: number
  priorBeta: number
  smallSampleN: number
  wealthStart: number
  deciles: RiskDecile[]
  notes: string[]
  createdAt: string
}

export type RiskResponse = {
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: RiskReport | null
}

type Raw = Record<string, unknown>

function num(v: unknown): number | null {
  if (v == null || v === '') return null
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

function str(v: unknown): string {
  return v == null ? '' : String(v)
}

function mapScenario(row: Raw): RiskScenario {
  return {
    name: str(row.name),
    fractionOfKelly: num(row.fraction_of_kelly) ?? 0,
    position: num(row.position) ?? 0,
    medianTerminalWealth: num(row.median_terminal_wealth),
    p05TerminalWealth: num(row.p05_terminal_wealth),
    p25TerminalWealth: num(row.p25_terminal_wealth),
    p75TerminalWealth: num(row.p75_terminal_wealth),
    p95TerminalWealth: num(row.p95_terminal_wealth),
    medianMaxDrawdown: num(row.median_max_drawdown),
    probDdGt20: num(row.prob_dd_gt_20),
    probDdGt30: num(row.prob_dd_gt_30),
  }
}

function mapDecile(row: Raw): RiskDecile {
  const histogram = Array.isArray(row.histogram) ? row.histogram : []
  const scenarios = Array.isArray(row.scenarios) ? row.scenarios : []
  return {
    decile: num(row.decile) ?? 0,
    label: str(row.label),
    n: num(row.n) ?? 0,
    smallSample: Boolean(row.small_sample),
    mean: num(row.mean),
    median: num(row.median),
    winRate: num(row.win_rate),
    posteriorWinRate: num(row.posterior_win_rate),
    probWinRateGtHalf: num(row.prob_win_rate_gt_half),
    probLoss: num(row.prob_loss),
    std: num(row.std),
    skew: num(row.skew),
    excessKurtosis: num(row.excess_kurtosis),
    var95: num(row.var_95),
    cvar95: num(row.cvar_95),
    payoffB: num(row.payoff_b),
    kellyRaw: num(row.kelly_raw),
    kellyFull: num(row.kelly_full),
    histogram: histogram.map((bin) => {
      const item = bin as Raw
      return {
        left: num(item.left) ?? 0,
        right: num(item.right) ?? 0,
        count: num(item.count) ?? 0,
      }
    }),
    scenarios: scenarios.map((item) => mapScenario(item as Raw)),
    note: row.note == null || row.note === '' ? null : str(row.note),
  }
}

export function mapRiskResponse(raw: Raw): RiskResponse {
  const reportRaw = raw.report
  let report: RiskReport | null = null
  if (reportRaw && typeof reportRaw === 'object') {
    const row = reportRaw as Raw
    const deciles = Array.isArray(row.deciles) ? row.deciles : []
    const notes = Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : []
    report = {
      schemaVersion: str(row.schema_version),
      factor: str(row.factor),
      factorField: str(row.factor_field),
      factorNote: str(row.factor_note),
      holdTradingDays: num(row.hold_trading_days) ?? 3,
      sampleStepTradingDays:
        row.sample_step_trading_days == null ? null : num(row.sample_step_trading_days),
      sampleSource: str(row.sample_source),
      sampleEnd: row.sample_end == null ? null : str(row.sample_end),
      nRows: num(row.n_rows) ?? 0,
      nSignalDates: num(row.n_signal_dates) ?? 0,
      nPaths: num(row.n_paths) ?? 0,
      nTrades: num(row.n_trades) ?? 0,
      seed: num(row.seed) ?? 0,
      seedRule: str(row.seed_rule),
      priorAlpha: num(row.prior_alpha) ?? 1,
      priorBeta: num(row.prior_beta) ?? 1,
      smallSampleN: num(row.small_sample_n) ?? 30,
      wealthStart: num(row.wealth_start) ?? 1,
      deciles: deciles.map((item) => mapDecile(item as Raw)),
      notes,
      createdAt: str(row.created_at),
    }
  }
  return {
    ok: Boolean(raw.ok),
    empty: Boolean(raw.empty),
    error: raw.error == null ? null : str(raw.error),
    message: raw.message == null ? null : str(raw.message),
    report,
  }
}

async function readBody(response: Response): Promise<RiskResponse> {
  const raw = (await response.json()) as Raw
  return mapRiskResponse(raw)
}

export async function fetchRiskReturnLatest(): Promise<RiskResponse> {
  const response = await fetch(apiUrl('/api/risk-return/latest'))
  if (!response.ok) {
    throw new Error(`读取研究结果失败 (${response.status})`)
  }
  return readBody(response)
}

export async function runRiskReturn(): Promise<RiskResponse> {
  const response = await fetch(apiUrl('/api/risk-return/run'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!response.ok) {
    throw new Error(`研究任务失败 (${response.status})`)
  }
  return readBody(response)
}
