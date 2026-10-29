import { apiUrl } from '@/config/apiBase'

export type CapmWindow = {
  n: number
  start: string
  end: string
  total: number | null
  benchmark: number | null
  excess: number | null
  beta: number | null
  betaSe: number | null
  alphaAnn: number | null
  tAlpha: number | null
  r2: number | null
  residVolAnn: number | null
}

export type CapmRow = {
  key: string
  name: string
  symbol: string
  stockName: string
  nOverlap: number
  label: string
  labelWindow: number | null
  quadrantId: string
  quadrant: string
  quadrantAction: string
  quadrantHint: string
  reason: string
  w250: CapmWindow | null
  w120: CapmWindow | null
  actLabel: string
  actReturn: number | null
  actEnd: string | null
  sessionReturn: number | null
}

export type CapmReport = {
  schemaVersion: string
  benchmark: string
  rf: number
  primaryWindow: number
  altWindow: number
  minObs: number
  sampleStart: string | null
  sampleEnd: string | null
  rows: CapmRow[]
  notes: string[]
  createdAt: string
  universe?: string
  requested?: number
  ready?: number
}

export type CapmResponse = {
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: CapmReport | null
}

type Raw = Record<string, unknown>

function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : null
  }
  return null
}

function str(value: unknown): string {
  return value == null ? '' : String(value)
}

function mapWindow(value: unknown): CapmWindow | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Raw
  return {
    n: num(row.n) ?? 0,
    start: str(row.start),
    end: str(row.end),
    total: num(row.total),
    benchmark: num(row.benchmark),
    excess: num(row.excess),
    beta: num(row.beta),
    betaSe: num(row.beta_se),
    alphaAnn: num(row.alpha_ann),
    tAlpha: num(row.t_alpha),
    r2: num(row.r2),
    residVolAnn: num(row.resid_vol_ann),
  }
}

function mapReport(value: unknown): CapmReport | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Raw
  const rows = Array.isArray(row.rows) ? row.rows : []
  return {
    schemaVersion: str(row.schema_version),
    benchmark: str(row.benchmark),
    rf: num(row.rf) ?? 0,
    primaryWindow: num(row.primary_window) ?? 250,
    altWindow: num(row.alt_window) ?? 120,
    minObs: num(row.min_obs) ?? 60,
    sampleStart: row.sample_start == null ? null : str(row.sample_start),
    sampleEnd: row.sample_end == null ? null : str(row.sample_end),
    rows: rows.map((item) => {
      const line = item as Raw
      return {
        key: str(line.key),
        name: str(line.name),
        symbol: str(line.symbol),
        stockName: str(line.stock_name),
        nOverlap: num(line.n_overlap) ?? 0,
        label: str(line.label),
        labelWindow: num(line.label_window),
        quadrantId: str(line.quadrant_id),
        quadrant: str(line.quadrant),
        quadrantAction: str(line.quadrant_action),
        quadrantHint: str(line.quadrant_hint),
        reason: str(line.reason),
        w250: mapWindow(line.w250),
        w120: mapWindow(line.w120),
        actLabel: str(line.act_label),
        actReturn: num(line.act_return),
        actEnd: line.act_end == null || line.act_end === '' ? null : str(line.act_end),
        sessionReturn: num(line.session_return),
      }
    }),
    notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
    createdAt: str(row.created_at),
    universe: row.universe == null ? undefined : str(row.universe),
    requested: num(row.requested) ?? undefined,
    ready: num(row.ready) ?? undefined,
  }
}

function mapResponse(raw: Raw): CapmResponse {
  return {
    ok: Boolean(raw.ok),
    empty: Boolean(raw.empty),
    error: raw.error == null ? null : str(raw.error),
    message: raw.message == null ? null : str(raw.message),
    report: mapReport(raw.report),
  }
}

async function readBody(response: Response): Promise<CapmResponse> {
  const raw = (await response.json()) as Raw
  return mapResponse(raw)
}

export async function fetchCapmSleeves(): Promise<CapmResponse> {
  const response = await fetch(apiUrl('/api/capm/sleeves'))
  if (!response.ok) throw new Error(`读取信号组复盘失败 (${response.status})`)
  return readBody(response)
}

export async function fetchCapmStocks(universe: 'vp6' | 'paste' | 'watch46', symbols = ''): Promise<CapmResponse> {
  const query = new URLSearchParams({ universe, symbols })
  const response = await fetch(apiUrl(`/api/capm/stocks?${query.toString()}`))
  if (!response.ok) throw new Error(`读取个股对比失败 (${response.status})`)
  return readBody(response)
}

export type DeskRow = {
  symbol: string
  stockName: string
  state: string
  stateLabel: string
  current: boolean
  signalDate: string | null
  buyDate: string | null
  beta250: number | null
  alpha250: number | null
  alpha120: number | null
  alphaGap: number | null
  delta120: number | null
  speed: number | null
  persisted: boolean
  noNewLow: boolean
  breakout: boolean
  volumeOk: boolean
  closeAboveOpen: boolean
  openMissing: boolean
  reason: string
}

export type DeskGroup = {
  id: string
  label: string
  n: number
  hitRate: number | null
  meanExcess: number | null
}

export type DeskHypothesis = {
  supported: boolean
  hitMonotone: boolean
  meanMonotone: boolean
  nDates: number
  nSkippedDates: number
  nObs: number
  nNames: number
  sampleStart: string | null
  sampleEnd: string | null
  groups: DeskGroup[]
  verdict: string
}

export type DeskReport = {
  schemaVersion: string
  benchmark: string
  asOf: string | null
  counts: Record<string, number>
  openMissing: boolean
  rows: DeskRow[]
  buys: DeskRow[]
  hypothesis: DeskHypothesis | null
  notes: string[]
  createdAt: string
}

export type DeskResponse = {
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: DeskReport | null
}

function mapDeskRow(value: unknown): DeskRow {
  const line = (value ?? {}) as Raw
  return {
    symbol: str(line.symbol),
    stockName: str(line.stock_name),
    state: str(line.state),
    stateLabel: str(line.state_label),
    current: Boolean(line.current),
    signalDate: line.signal_date == null || line.signal_date === '' ? null : str(line.signal_date),
    buyDate: line.buy_date == null || line.buy_date === '' ? null : str(line.buy_date),
    beta250: num(line.beta250),
    alpha250: num(line.alpha250),
    alpha120: num(line.alpha120),
    alphaGap: num(line.alphaGap),
    delta120: num(line.delta120),
    speed: num(line.speed),
    persisted: Boolean(line.persisted),
    noNewLow: Boolean(line.no_new_low),
    breakout: Boolean(line.breakout),
    volumeOk: Boolean(line.volume_ok),
    closeAboveOpen: Boolean(line.close_above_open),
    openMissing: Boolean(line.open_missing),
    reason: str(line.reason),
  }
}

function mapDesk(value: unknown): DeskReport | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Raw
  const counts = (row.counts ?? {}) as Raw
  const hypothesis = (row.hypothesis ?? null) as Raw | null
  const groups = hypothesis && Array.isArray(hypothesis.groups) ? hypothesis.groups : []
  return {
    schemaVersion: str(row.schema_version),
    benchmark: str(row.benchmark),
    asOf: row.as_of == null || row.as_of === '' ? null : str(row.as_of),
    counts: {
      S2: num(counts.S2) ?? 0,
      S1: num(counts.S1) ?? 0,
      S0: num(counts.S0) ?? 0,
      excluded: num(counts.excluded) ?? 0,
      insufficient: num(counts.insufficient) ?? 0,
    },
    openMissing: Boolean(row.open_missing),
    rows: Array.isArray(row.rows) ? row.rows.map((item) => mapDeskRow(item)) : [],
    buys: Array.isArray(row.buys) ? row.buys.map((item) => mapDeskRow(item)) : [],
    hypothesis: hypothesis
      ? {
          supported: Boolean(hypothesis.supported),
          hitMonotone: Boolean(hypothesis.hit_monotone),
          meanMonotone: Boolean(hypothesis.mean_monotone),
          nDates: num(hypothesis.n_dates) ?? 0,
          nSkippedDates: num(hypothesis.n_skipped_dates) ?? 0,
          nObs: num(hypothesis.n_obs) ?? 0,
          nNames: num(hypothesis.n_names) ?? 0,
          sampleStart: hypothesis.sample_start == null ? null : str(hypothesis.sample_start),
          sampleEnd: hypothesis.sample_end == null ? null : str(hypothesis.sample_end),
          groups: groups.map((item) => {
            const group = item as Raw
            return {
              id: str(group.id),
              label: str(group.label),
              n: num(group.n) ?? 0,
              hitRate: num(group.hit_rate),
              meanExcess: num(group.mean_excess),
            }
          }),
          verdict: str(hypothesis.verdict),
        }
      : null,
    notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
    createdAt: str(row.created_at),
  }
}

export async function fetchCapmDesk(): Promise<DeskResponse> {
  const response = await fetch(apiUrl('/api/capm/desk'))
  if (!response.ok) throw new Error(`读取交易部门失败 (${response.status})`)
  const raw = (await response.json()) as Raw
  return {
    ok: Boolean(raw.ok),
    empty: Boolean(raw.empty),
    error: raw.error == null ? null : str(raw.error),
    message: raw.message == null ? null : str(raw.message),
    report: mapDesk(raw.report),
  }
}

export type LaunchRow = {
  symbol: string
  stockName: string
  similarity: number
  spiral: number
  price: number
  volume: number
  yang: number
  yangCount: number
  vr: number | null
  pasted: boolean
  reason: string
}

export type LaunchTemplate = {
  symbol: string
  name: string
  ignition: string
  third: string
  volume: number
  yang: number
  source: string
}

export type LaunchReport = {
  schemaVersion: string
  asOf: string | null
  template: LaunchTemplate
  watched: number
  pasted: number
  relatedCount: number
  unrelatedCount: number
  missingCount: number
  rows: LaunchRow[]
  unrelatedPasted: string[]
  missingPasted: string[]
  notes: string[]
  createdAt: string
}

export type LaunchResponse = {
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: LaunchReport | null
}

function mapLaunch(value: unknown): LaunchReport | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Raw
  const template = (row.template ?? {}) as Raw
  const rows = Array.isArray(row.rows) ? row.rows : []
  return {
    schemaVersion: str(row.schema_version),
    asOf: row.as_of == null || row.as_of === '' ? null : str(row.as_of),
    template: {
      symbol: str(template.symbol),
      name: str(template.name),
      ignition: str(template.ignition),
      third: str(template.third),
      volume: num(template.volume) ?? 0,
      yang: num(template.yang) ?? 3,
      source: str(template.source),
    },
    watched: num(row.watched) ?? 0,
    pasted: num(row.pasted) ?? 0,
    relatedCount: num(row.related_count) ?? 0,
    unrelatedCount: num(row.unrelated_count) ?? 0,
    missingCount: num(row.missing_count) ?? 0,
    rows: rows.map((item) => {
      const line = item as Raw
      return {
        symbol: str(line.symbol),
        stockName: str(line.stock_name),
        similarity: num(line.similarity) ?? 0,
        spiral: num(line.spiral) ?? 0,
        price: num(line.price) ?? 0,
        volume: num(line.volume) ?? 0,
        yang: num(line.yang) ?? 0,
        yangCount: num(line.yang_n) ?? 0,
        vr: num(line.vr),
        pasted: Boolean(line.pasted),
        reason: str(line.reason),
      }
    }),
    unrelatedPasted: Array.isArray(row.unrelated_pasted) ? row.unrelated_pasted.map((item) => str(item)) : [],
    missingPasted: Array.isArray(row.missing_pasted) ? row.missing_pasted.map((item) => str(item)) : [],
    notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
    createdAt: str(row.created_at),
  }
}

export type TipRow = {
  symbol: string
  stockName: string
  drop: number
  tip: number
  tipBars: number
  similarity: number
  peak: string
  anchor: string
  pasted: boolean
  reason: string
}

export type TipReport = {
  schemaVersion: string
  asOf: string | null
  watched: number
  pasted: number
  matchedCount: number
  unrelatedCount: number
  missingCount: number
  rows: TipRow[]
  unrelatedPasted: string[]
  missingPasted: string[]
  notes: string[]
  createdAt: string
}

export type TipResponse = {
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: TipReport | null
}

function mapTip(value: unknown): TipReport | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Raw
  const rows = Array.isArray(row.rows) ? row.rows : []
  return {
    schemaVersion: str(row.schema_version),
    asOf: row.as_of == null || row.as_of === '' ? null : str(row.as_of),
    watched: num(row.watched) ?? 0,
    pasted: num(row.pasted) ?? 0,
    matchedCount: num(row.matched_count) ?? 0,
    unrelatedCount: num(row.unrelated_count) ?? 0,
    missingCount: num(row.missing_count) ?? 0,
    rows: rows.map((item) => {
      const line = item as Raw
      return {
        symbol: str(line.symbol),
        stockName: str(line.stock_name),
        drop: num(line.drop) ?? 0,
        tip: num(line.tip) ?? 0,
        tipBars: num(line.tip_n) ?? 0,
        similarity: num(line.similarity) ?? 0,
        peak: str(line.peak),
        anchor: str(line.anchor),
        pasted: Boolean(line.pasted),
        reason: str(line.reason),
      }
    }),
    unrelatedPasted: Array.isArray(row.unrelated_pasted) ? row.unrelated_pasted.map((item) => str(item)) : [],
    missingPasted: Array.isArray(row.missing_pasted) ? row.missing_pasted.map((item) => str(item)) : [],
    notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
    createdAt: str(row.created_at),
  }
}

export async function fetchCapmTip(symbols = '', refresh = false): Promise<TipResponse> {
  const response = refresh
    ? await fetch(apiUrl('/api/capm/tip'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols }),
      })
    : await fetch(apiUrl(`/api/capm/tip?${new URLSearchParams({ symbols }).toString()}`))
  if (!response.ok) throw new Error(`读取山尖失败 (${response.status})`)
  const raw = (await response.json()) as Raw
  return {
    ok: Boolean(raw.ok),
    empty: Boolean(raw.empty),
    error: raw.error == null ? null : str(raw.error),
    message: raw.message == null ? null : str(raw.message),
    report: mapTip(raw.report),
  }
}

export async function fetchCapmLaunch(symbols = '', refresh = false): Promise<LaunchResponse> {
  const response = refresh
    ? await fetch(apiUrl('/api/capm/launch'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbols }),
      })
    : await fetch(apiUrl(`/api/capm/launch?${new URLSearchParams({ symbols }).toString()}`))
  if (!response.ok) throw new Error(`读取百亚启动段失败 (${response.status})`)
  const raw = (await response.json()) as Raw
  return {
    ok: Boolean(raw.ok),
    empty: Boolean(raw.empty),
    error: raw.error == null ? null : str(raw.error),
    message: raw.message == null ? null : str(raw.message),
    report: mapLaunch(raw.report),
  }
}

export async function refreshCapmStocks(universe: 'vp6' | 'paste' | 'watch46', symbols = ''): Promise<CapmResponse> {
  const response = await fetch(apiUrl('/api/capm/stocks'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ universe, symbols, refresh: true }),
  })
  if (!response.ok) throw new Error(`补齐日线失败 (${response.status})`)
  return readBody(response)
}
