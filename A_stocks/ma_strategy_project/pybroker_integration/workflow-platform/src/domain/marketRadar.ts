import type { RadarLamp, RadarSession } from '@/config/marketRadarRules'

export type RadarQuoteKind = 'realtime' | 'daily' | 'missing'

export interface RadarIndex {
  tsCode: string
  label: string
  pct: number | null
  close: number | null
  lamp: RadarLamp
  quoteKind: RadarQuoteKind
}

export interface RadarSector {
  code: string
  name: string
  level: string
  pct: number | null
  amountChange: number | null
  rsIndex: number | null
  quoteKind: RadarQuoteKind
  stockCount: number
  lamp: RadarLamp
}

export interface RadarStock {
  symbol: string
  tsCode: string
  name: string
  group: string | null
  rank: number | null
  industry: string | null
  pct: number | null
  sectorCode: string | null
  sectorName: string | null
  sectorLevel: string | null
  sectorPct: number | null
  rsIndex: number | null
  rsSector: number | null
  strength: number | null
  lamp: RadarLamp
  quoteKind: RadarQuoteKind
}

export interface RadarPick {
  symbol: string
  name: string
  group: string
  rank: number
  industry: string
}

export interface RadarUniverse {
  source: string
  label: string
  file: string
  hint: string | null
  count: number
  picks: RadarPick[]
}

export interface RadarAlert {
  kind: 'volume_surge' | 'lag_sector' | string
  level: 'sector' | 'stock' | string
  code: string
  name: string
  message: string
  value: number | null
}

export interface MarketRadarPayload {
  ok: boolean
  error?: string
  asOf: string | null
  session: RadarSession
  cached: boolean
  sectorStale: 'daily' | null
  source: string
  universe: RadarUniverse | null
  indexes: RadarIndex[]
  sectors: RadarSector[]
  stocks: RadarStock[]
  alerts: RadarAlert[]
}

export function formatPct(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(digits)}%`
}

export function formatSignedPctPoints(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}`
}

export function barWidthPct(value: number | null, maxAbs: number): number {
  if (value == null || !Number.isFinite(value) || maxAbs <= 0) return 4
  return Math.max(4, Math.min(100, Math.round((Math.abs(value) / maxAbs) * 100)))
}

export function lampClass(lamp: RadarLamp): string {
  if (lamp === 'strong') return 'border-transparent bg-emerald-600 text-white'
  if (lamp === 'weak') return 'border-transparent bg-red-600 text-white'
  if (lamp === 'watch') return 'border-amber-300/80 bg-amber-50 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100'
  return 'bg-muted text-muted-foreground'
}

export function pctClass(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n) || n === 0) return 'text-muted-foreground'
  return n > 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400'
}
