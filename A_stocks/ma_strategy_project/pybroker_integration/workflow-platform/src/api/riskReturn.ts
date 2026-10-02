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

export type RiskCorrelation = {
  schemaVersion: string
  sleeves: string[]
  nDays: number
  sampleStart: string | null
  sampleEnd: string | null
  smallSample: boolean
  means: Record<string, number | null>
  lossRates: Record<string, number | null>
  correlation: Array<Array<number | null>>
  historicalAllNegative: number | null
  historicalAtLeastFourNegative: number | null
  independentAllNegative: number | null
  jointAllNegative: number | null
  nPaths: number
  horizonDays: number
  seed: number
  jointMedianMaxDrawdown: number | null
  independentMedianMaxDrawdown: number | null
  jointProbDdGt20: number | null
  independentProbDdGt20: number | null
  notes: string[]
  createdAt: string
}

export type RiskRegimeState = {
  label: string
  positionPct: number | null
  nDays: number
  smallSample: boolean
  meanScore: number | null
  means: Record<string, number | null>
  lossRates: Record<string, number | null>
  allNegative: number | null
}

export type RiskRegime = {
  schemaVersion: string
  sleeves: string[]
  temperatureFile: string
  nDays: number
  sampleStart: string | null
  sampleEnd: string | null
  states: RiskRegimeState[]
  notes: string[]
  createdAt: string
}

export type RiskBudgetRow = {
  name: string
  averagePosition: number | null
  terminalWealth: number | null
  totalReturn: number | null
  maxDrawdown: number | null
}

export type RiskBudget = {
  schemaVersion: string
  sleeves: string[]
  nDays: number
  sampleStart: string | null
  sampleEnd: string | null
  posteriorWinRate: number | null
  payoffB: number | null
  kellyRaw: number | null
  quarterPosition: number | null
  budgets: RiskBudgetRow[]
  notes: string[]
  createdAt: string
}

export type RiskWalkFold = {
  trainStart: string
  trainEnd: string
  testStart: string
  testEnd: string
  posteriorWinRate: number | null
  kellyRaw: number | null
  position: number | null
  predictedLossProb: number | null
  realizedLossRate: number | null
  testReturn: number | null
  testMaxDrawdown: number | null
  temperatureReturn: number | null
  temperatureMaxDrawdown: number | null
}

export type RiskWalkPerturb = {
  fraction: number | null
  terminalWealth: number | null
  totalReturn: number | null
  maxDrawdown: number | null
  worstFoldReturn: number | null
}

export type RiskWalkForward = {
  schemaVersion: string
  sleeves: string[]
  trainDays: number
  testDays: number
  stepDays: number
  nFolds: number
  oosStart: string | null
  oosEnd: string | null
  folds: RiskWalkFold[]
  perturbations: RiskWalkPerturb[]
  boundary: string
  notes: string[]
  createdAt: string
}

export type RiskCopulaPair = {
  left: string
  right: string
  historical: number | null
  gaussian: number | null
}

export type RiskCopula = {
  schemaVersion: string
  sleeves: string[]
  nDays: number
  sampleStart: string | null
  sampleEnd: string | null
  nPaths: number
  seed: number
  tailQ: number | null
  historicalAllNegative: number | null
  gaussianAllNegative: number | null
  independentAllNegative: number | null
  pairs: RiskCopulaPair[]
  boundary: string
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

export async function fetchRiskCorrelation(): Promise<{
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: RiskCorrelation | null
}> {
  const response = await fetch(apiUrl('/api/risk-return/correlation'))
  if (!response.ok) {
    throw new Error(`读取相关性失败 (${response.status})`)
  }
  const raw = (await response.json()) as Raw
  const reportRaw = raw.report
  let report: RiskCorrelation | null = null
  if (reportRaw && typeof reportRaw === 'object') {
    const row = reportRaw as Raw
    const sleeves = Array.isArray(row.sleeves) ? row.sleeves.map((item) => str(item)) : []
    const matrix = Array.isArray(row.correlation) ? row.correlation : []
    const numMap = (value: unknown): Record<string, number | null> => {
      if (!value || typeof value !== 'object') return {}
      const out: Record<string, number | null> = {}
      for (const [key, item] of Object.entries(value as Raw)) out[key] = num(item)
      return out
    }
    report = {
      schemaVersion: str(row.schema_version),
      sleeves,
      nDays: num(row.n_days) ?? 0,
      sampleStart: row.sample_start == null ? null : str(row.sample_start),
      sampleEnd: row.sample_end == null ? null : str(row.sample_end),
      smallSample: Boolean(row.small_sample),
      means: numMap(row.means),
      lossRates: numMap(row.loss_rates),
      correlation: matrix.map((line) =>
        Array.isArray(line) ? line.map((item) => num(item)) : [],
      ),
      historicalAllNegative: num(row.historical_all_negative),
      historicalAtLeastFourNegative: num(row.historical_at_least_four_negative),
      independentAllNegative: num(row.independent_all_negative),
      jointAllNegative: num(row.joint_all_negative),
      nPaths: num(row.n_paths) ?? 0,
      horizonDays: num(row.horizon_days) ?? 0,
      seed: num(row.seed) ?? 0,
      jointMedianMaxDrawdown: num(row.joint_median_max_drawdown),
      independentMedianMaxDrawdown: num(row.independent_median_max_drawdown),
      jointProbDdGt20: num(row.joint_prob_dd_gt_20),
      independentProbDdGt20: num(row.independent_prob_dd_gt_20),
      notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
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

export async function fetchRiskRegime(): Promise<{
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: RiskRegime | null
}> {
  const response = await fetch(apiUrl('/api/risk-return/regime'))
  if (!response.ok) {
    throw new Error(`读取温度档失败 (${response.status})`)
  }
  const raw = (await response.json()) as Raw
  const reportRaw = raw.report
  let report: RiskRegime | null = null
  if (reportRaw && typeof reportRaw === 'object') {
    const row = reportRaw as Raw
    const sleeves = Array.isArray(row.sleeves) ? row.sleeves.map((item) => str(item)) : []
    const states = Array.isArray(row.states) ? row.states : []
    const numMap = (value: unknown): Record<string, number | null> => {
      if (!value || typeof value !== 'object') return {}
      const out: Record<string, number | null> = {}
      for (const [key, item] of Object.entries(value as Raw)) out[key] = num(item)
      return out
    }
    report = {
      schemaVersion: str(row.schema_version),
      sleeves,
      temperatureFile: str(row.temperature_file),
      nDays: num(row.n_days) ?? 0,
      sampleStart: row.sample_start == null ? null : str(row.sample_start),
      sampleEnd: row.sample_end == null ? null : str(row.sample_end),
      states: states.map((item) => {
        const state = item as Raw
        return {
          label: str(state.label),
          positionPct: num(state.position_pct),
          nDays: num(state.n_days) ?? 0,
          smallSample: Boolean(state.small_sample),
          meanScore: num(state.mean_score),
          means: numMap(state.means),
          lossRates: numMap(state.loss_rates),
          allNegative: num(state.all_negative),
        }
      }),
      notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
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

export async function fetchRiskBudget(): Promise<{
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: RiskBudget | null
}> {
  const response = await fetch(apiUrl('/api/risk-return/budget'))
  if (!response.ok) {
    throw new Error(`读取风险预算失败 (${response.status})`)
  }
  const raw = (await response.json()) as Raw
  const reportRaw = raw.report
  let report: RiskBudget | null = null
  if (reportRaw && typeof reportRaw === 'object') {
    const row = reportRaw as Raw
    const sleeves = Array.isArray(row.sleeves) ? row.sleeves.map((item) => str(item)) : []
    const budgets = Array.isArray(row.budgets) ? row.budgets : []
    report = {
      schemaVersion: str(row.schema_version),
      sleeves,
      nDays: num(row.n_days) ?? 0,
      sampleStart: row.sample_start == null ? null : str(row.sample_start),
      sampleEnd: row.sample_end == null ? null : str(row.sample_end),
      posteriorWinRate: num(row.posterior_win_rate),
      payoffB: num(row.payoff_b),
      kellyRaw: num(row.kelly_raw),
      quarterPosition: num(row.quarter_position),
      budgets: budgets.map((item) => {
        const budget = item as Raw
        return {
          name: str(budget.name),
          averagePosition: num(budget.average_position),
          terminalWealth: num(budget.terminal_wealth),
          totalReturn: num(budget.total_return),
          maxDrawdown: num(budget.max_drawdown),
        }
      }),
      notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
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

export async function fetchRiskWalkForward(): Promise<{
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: RiskWalkForward | null
}> {
  const response = await fetch(apiUrl('/api/risk-return/walkforward'))
  if (!response.ok) {
    throw new Error(`读取滚动检验失败 (${response.status})`)
  }
  const raw = (await response.json()) as Raw
  const reportRaw = raw.report
  let report: RiskWalkForward | null = null
  if (reportRaw && typeof reportRaw === 'object') {
    const row = reportRaw as Raw
    const folds = Array.isArray(row.folds) ? row.folds : []
    const perturbations = Array.isArray(row.perturbations) ? row.perturbations : []
    report = {
      schemaVersion: str(row.schema_version),
      sleeves: Array.isArray(row.sleeves) ? row.sleeves.map((item) => str(item)) : [],
      trainDays: num(row.train_days) ?? 0,
      testDays: num(row.test_days) ?? 0,
      stepDays: num(row.step_days) ?? 0,
      nFolds: num(row.n_folds) ?? 0,
      oosStart: row.oos_start == null ? null : str(row.oos_start),
      oosEnd: row.oos_end == null ? null : str(row.oos_end),
      folds: folds.map((item) => {
        const fold = item as Raw
        return {
          trainStart: str(fold.train_start),
          trainEnd: str(fold.train_end),
          testStart: str(fold.test_start),
          testEnd: str(fold.test_end),
          posteriorWinRate: num(fold.posterior_win_rate),
          kellyRaw: num(fold.kelly_raw),
          position: num(fold.position),
          predictedLossProb: num(fold.predicted_loss_prob),
          realizedLossRate: num(fold.realized_loss_rate),
          testReturn: num(fold.test_return),
          testMaxDrawdown: num(fold.test_max_drawdown),
          temperatureReturn: num(fold.temperature_return),
          temperatureMaxDrawdown: num(fold.temperature_max_drawdown),
        }
      }),
      perturbations: perturbations.map((item) => {
        const perturb = item as Raw
        return {
          fraction: num(perturb.fraction),
          terminalWealth: num(perturb.terminal_wealth),
          totalReturn: num(perturb.total_return),
          maxDrawdown: num(perturb.max_drawdown),
          worstFoldReturn: num(perturb.worst_fold_return),
        }
      }),
      boundary: str(row.boundary),
      notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
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

export async function fetchRiskCopula(): Promise<{
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: RiskCopula | null
}> {
  const response = await fetch(apiUrl('/api/risk-return/copula'))
  if (!response.ok) {
    throw new Error(`读取正态相关失败 (${response.status})`)
  }
  const raw = (await response.json()) as Raw
  const reportRaw = raw.report
  let report: RiskCopula | null = null
  if (reportRaw && typeof reportRaw === 'object') {
    const row = reportRaw as Raw
    const pairs = Array.isArray(row.pairs) ? row.pairs : []
    report = {
      schemaVersion: str(row.schema_version),
      sleeves: Array.isArray(row.sleeves) ? row.sleeves.map((item) => str(item)) : [],
      nDays: num(row.n_days) ?? 0,
      sampleStart: row.sample_start == null ? null : str(row.sample_start),
      sampleEnd: row.sample_end == null ? null : str(row.sample_end),
      nPaths: num(row.n_paths) ?? 0,
      seed: num(row.seed) ?? 0,
      tailQ: num(row.tail_q),
      historicalAllNegative: num(row.historical_all_negative),
      gaussianAllNegative: num(row.gaussian_all_negative),
      independentAllNegative: num(row.independent_all_negative),
      pairs: pairs.map((item) => {
        const pair = item as Raw
        return {
          left: str(pair.left),
          right: str(pair.right),
          historical: num(pair.historical),
          gaussian: num(pair.gaussian),
        }
      }),
      boundary: str(row.boundary),
      notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
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

export type RiskDecisionCandidate = {
  name: string
  position: number | null
  expectedReturn: number | null
  cvar95: number | null
  utility: number | null
  chosen: boolean
}

export type RiskDecisionEstimate = {
  posteriorWinRate: number | null
  payoffB: number | null
  kellyRaw: number | null
  pdfMean: number | null
  pdfVar95: number | null
  pdfCvar95: number | null
  maxCorrelation: number | null
  maxPair: string
  historicalAllNegative: number | null
  independentAllNegative: number | null
  gaussianAllNegative: number | null
  sampler: string
}

export type RiskDecisionFeedback = {
  date: string
  state: string
  action: string
  realized: number | null
  nextState: string
}

export type RiskDecisionNext = {
  asOf: string
  state: string
  score: number | null
  temperaturePosition: number | null
  action: string
  position: number | null
  weights: Record<string, number>
  nPrior: number
  estimate: RiskDecisionEstimate | null
  candidates: RiskDecisionCandidate[]
  feedback: RiskDecisionFeedback | null
}

export type RiskDecisionState = {
  label: string
  nDays: number
  meanPosition: number | null
  meanRealized: number | null
  lastAction: string
  lastDate: string
}

export type RiskDecisionRow = {
  date: string
  state: string
  score: number | null
  action: string
  position: number | null
  weights: Record<string, number>
  realized: number | null
  nPrior: number
}

export type RiskDecision = {
  schemaVersion: string
  sleeves: string[]
  nDays: number
  sampleStart: string | null
  sampleEnd: string | null
  lambdaTail: number | null
  horizonDays: number
  nPaths: number
  minPrior: number
  seed: number
  nextAction: RiskDecisionNext | null
  states: RiskDecisionState[]
  ledger: RiskDecisionRow[]
  terminalWealth: number | null
  totalReturn: number | null
  maxDrawdown: number | null
  boundary: string
  notes: string[]
  createdAt: string
}

export async function fetchRiskDecision(): Promise<{
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: RiskDecision | null
}> {
  const response = await fetch(apiUrl('/api/risk-return/decision'))
  if (!response.ok) {
    throw new Error(`读取决策中心失败 (${response.status})`)
  }
  const raw = (await response.json()) as Raw
  const reportRaw = raw.report
  let report: RiskDecision | null = null
  if (reportRaw && typeof reportRaw === 'object') {
    const row = reportRaw as Raw
    const weightMap = (value: unknown): Record<string, number> => {
      if (!value || typeof value !== 'object') return {}
      const out: Record<string, number> = {}
      for (const [key, item] of Object.entries(value as Raw)) {
        const parsed = num(item)
        if (parsed != null) out[key] = parsed
      }
      return out
    }
    const nextRaw = row.next_action
    let nextAction: RiskDecisionNext | null = null
    if (nextRaw && typeof nextRaw === 'object') {
      const next = nextRaw as Raw
      const candidates = Array.isArray(next.candidates) ? next.candidates : []
      const estimateRaw = next.estimate
      let estimate: RiskDecisionEstimate | null = null
      if (estimateRaw && typeof estimateRaw === 'object') {
        const item = estimateRaw as Raw
        estimate = {
          posteriorWinRate: num(item.posterior_win_rate),
          payoffB: num(item.payoff_b),
          kellyRaw: num(item.kelly_raw),
          pdfMean: num(item.pdf_mean),
          pdfVar95: num(item.pdf_var_95),
          pdfCvar95: num(item.pdf_cvar_95),
          maxCorrelation: num(item.max_correlation),
          maxPair: str(item.max_pair),
          historicalAllNegative: num(item.historical_all_negative),
          independentAllNegative: num(item.independent_all_negative),
          gaussianAllNegative: num(item.gaussian_all_negative),
          sampler: str(item.sampler),
        }
      }
      const feedbackRaw = next.feedback
      let feedback: RiskDecisionFeedback | null = null
      if (feedbackRaw && typeof feedbackRaw === 'object') {
        const item = feedbackRaw as Raw
        feedback = {
          date: str(item.date),
          state: str(item.state),
          action: str(item.action),
          realized: num(item.realized),
          nextState: str(item.next_state),
        }
      }
      nextAction = {
        asOf: str(next.as_of),
        state: str(next.state),
        score: num(next.score),
        temperaturePosition: num(next.temperature_position),
        action: str(next.action),
        position: num(next.position),
        weights: weightMap(next.weights),
        nPrior: num(next.n_prior) ?? 0,
        estimate,
        candidates: candidates.map((item) => {
          const candidate = item as Raw
          return {
            name: str(candidate.name),
            position: num(candidate.position),
            expectedReturn: num(candidate.expected_return),
            cvar95: num(candidate.cvar_95),
            utility: num(candidate.utility),
            chosen: Boolean(candidate.chosen),
          }
        }),
        feedback,
      }
    }
    const states = Array.isArray(row.states) ? row.states : []
    const ledger = Array.isArray(row.ledger) ? row.ledger : []
    report = {
      schemaVersion: str(row.schema_version),
      sleeves: Array.isArray(row.sleeves) ? row.sleeves.map((item) => str(item)) : [],
      nDays: num(row.n_days) ?? 0,
      sampleStart: row.sample_start == null ? null : str(row.sample_start),
      sampleEnd: row.sample_end == null ? null : str(row.sample_end),
      lambdaTail: num(row.lambda_tail),
      horizonDays: num(row.horizon_days) ?? 0,
      nPaths: num(row.n_paths) ?? 0,
      minPrior: num(row.min_prior) ?? 0,
      seed: num(row.seed) ?? 0,
      nextAction,
      states: states.map((item) => {
        const state = item as Raw
        return {
          label: str(state.label),
          nDays: num(state.n_days) ?? 0,
          meanPosition: num(state.mean_position),
          meanRealized: num(state.mean_realized),
          lastAction: str(state.last_action),
          lastDate: str(state.last_date),
        }
      }),
      ledger: ledger.map((item) => {
        const line = item as Raw
        return {
          date: str(line.date),
          state: str(line.state),
          score: num(line.score),
          action: str(line.action),
          position: num(line.position),
          weights: weightMap(line.weights),
          realized: num(line.realized),
          nPrior: num(line.n_prior) ?? 0,
        }
      }),
      terminalWealth: num(row.terminal_wealth),
      totalReturn: num(row.total_return),
      maxDrawdown: num(row.max_drawdown),
      boundary: str(row.boundary),
      notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
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
