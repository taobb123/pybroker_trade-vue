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

export async function refreshCapmStocks(universe: 'vp6' | 'paste' | 'watch46', symbols = ''): Promise<CapmResponse> {
  const response = await fetch(apiUrl('/api/capm/stocks'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ universe, symbols, refresh: true }),
  })
  if (!response.ok) throw new Error(`补齐日线失败 (${response.status})`)
  return readBody(response)
}
