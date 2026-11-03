import { apiUrl } from '@/config/apiBase'

type Raw = Record<string, unknown>

function str(value: unknown): string {
  return value == null ? '' : String(value)
}

function num(value: unknown): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : 0
}

export type ThemeReviewRow = {
  themes: string
  symbol: string
  stockName: string
  similarity: number
  comboName: string
  comboNote: string
  reason: string
}

export type ThemeSlot = {
  name: string
  matched: boolean
  memberCount: number
}

export type ThemeReviewReport = {
  tradeDate: string
  threshold: number
  memberCount: number
  trackedCount: number
  themes: ThemeSlot[]
  rows: ThemeReviewRow[]
  notes: string[]
}

export type ThemeReviewResponse = {
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  report: ThemeReviewReport | null
}

function mapReport(value: unknown): ThemeReviewReport | null {
  if (!value || typeof value !== 'object') return null
  const row = value as Raw
  const themes = Array.isArray(row.themes) ? row.themes : []
  const rows = Array.isArray(row.rows) ? row.rows : []
  return {
    tradeDate: str(row.trade_date),
    threshold: num(row.threshold),
    memberCount: num(row.member_count),
    trackedCount: num(row.tracked_count),
    themes: themes.map((item) => {
      const theme = item as Raw
      return {
        name: str(theme.name),
        matched: Boolean(theme.matched),
        memberCount: num(theme.member_count),
      }
    }),
    rows: rows.map((item) => {
      const line = item as Raw
      return {
        themes: str(line.themes),
        symbol: str(line.symbol),
        stockName: str(line.stock_name),
        similarity: num(line.similarity),
        comboName: str(line.combo_name),
        comboNote: str(line.combo_note),
        reason: str(line.reason),
      }
    }),
    notes: Array.isArray(row.notes) ? row.notes.map((item) => str(item)) : [],
  }
}

export type ThemeCatalog = {
  ok: boolean
  empty: boolean
  error: string | null
  message: string | null
  tradeDate: string
  count: number
  names: string[]
}

export async function fetchThemeCatalog(): Promise<ThemeCatalog> {
  const response = await fetch(apiUrl('/api/theme-review/concepts'))
  if (!response.ok) throw new Error(`读取东财概念失败 (${response.status})`)
  const raw = (await response.json()) as Raw
  return {
    ok: Boolean(raw.ok),
    empty: Boolean(raw.empty),
    error: raw.error == null ? null : str(raw.error),
    message: raw.message == null ? null : str(raw.message),
    tradeDate: str(raw.trade_date),
    count: num(raw.count),
    names: Array.isArray(raw.names) ? raw.names.map((item) => str(item)).filter(Boolean) : [],
  }
}

export async function runThemeReview(themes: string): Promise<ThemeReviewResponse> {
  const response = await fetch(apiUrl('/api/theme-review'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ themes }),
  })
  if (!response.ok) throw new Error(`题材复盘失败 (${response.status})`)
  const raw = (await response.json()) as Raw
  return {
    ok: Boolean(raw.ok),
    empty: Boolean(raw.empty),
    error: raw.error == null ? null : str(raw.error),
    message: raw.message == null ? null : str(raw.message),
    report: mapReport(raw.report),
  }
}
