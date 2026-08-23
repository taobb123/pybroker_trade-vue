import { apiUrl } from '@/config/apiBase'
import type {
  MarketRadarPayload,
  RadarAlert,
  RadarIndex,
  RadarPick,
  RadarSector,
  RadarStock,
  RadarUniverse,
} from '@/domain/marketRadar'

type Raw = Record<string, unknown>

function num(v: unknown): number | null {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : null
}

function str(v: unknown): string {
  return v == null ? '' : String(v)
}

function asLamp(v: unknown): RadarIndex['lamp'] {
  const s = str(v)
  if (s === 'strong' || s === 'watch' || s === 'weak' || s === 'unknown') return s
  return 'unknown'
}

function asKind(v: unknown): RadarIndex['quoteKind'] {
  const s = str(v)
  if (s === 'realtime' || s === 'daily' || s === 'missing') return s
  return 'missing'
}

function mapIndex(row: Raw): RadarIndex {
  return {
    tsCode: str(row.ts_code),
    label: str(row.label),
    pct: num(row.pct),
    close: num(row.close),
    lamp: asLamp(row.lamp),
    quoteKind: asKind(row.quote_kind),
  }
}

function mapSector(row: Raw): RadarSector {
  return {
    code: str(row.code),
    name: str(row.name),
    level: str(row.level) || 'L2',
    pct: num(row.pct),
    amountChange: num(row.amount_change),
    rsIndex: num(row.rs_index),
    quoteKind: asKind(row.quote_kind),
    stockCount: num(row.stock_count) ?? 0,
    lamp: asLamp(row.lamp),
  }
}

function mapStock(row: Raw): RadarStock {
  return {
    symbol: str(row.symbol),
    tsCode: str(row.ts_code),
    name: str(row.name),
    group: row.group ? str(row.group) : null,
    rank: num(row.rank) != null ? Math.round(num(row.rank) as number) : null,
    industry: row.industry ? str(row.industry) : null,
    pct: num(row.pct),
    sectorCode: row.sector_code ? str(row.sector_code) : null,
    sectorName: row.sector_name ? str(row.sector_name) : null,
    sectorLevel: row.sector_level ? str(row.sector_level) : null,
    sectorPct: num(row.sector_pct),
    rsIndex: num(row.rs_index),
    rsSector: num(row.rs_sector),
    strength: num(row.strength) != null ? Math.round(num(row.strength) as number) : null,
    lamp: asLamp(row.lamp),
    quoteKind: asKind(row.quote_kind),
  }
}

function mapPick(row: Raw): RadarPick {
  return {
    symbol: str(row.symbol),
    name: str(row.name),
    group: str(row.group),
    rank: num(row.rank) != null ? Math.round(num(row.rank) as number) : 0,
    industry: str(row.industry),
  }
}

function mapUniverse(raw: unknown): RadarUniverse | null {
  if (!raw || typeof raw !== 'object') return null
  const row = raw as Raw
  return {
    source: str(row.source),
    label: str(row.label),
    file: str(row.file),
    hint: row.hint ? str(row.hint) : null,
    count: num(row.count) ?? 0,
    picks: Array.isArray(row.picks) ? (row.picks as Raw[]).map(mapPick) : [],
  }
}

function mapAlert(row: Raw): RadarAlert {
  return {
    kind: str(row.kind) || 'lag_sector',
    level: str(row.level) || 'stock',
    code: str(row.code),
    name: str(row.name),
    message: str(row.message),
    value: num(row.value),
  }
}

export async function fetchMarketRadar(): Promise<MarketRadarPayload> {
  const res = await fetch(apiUrl('/api/market-radar'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let msg = `市场雷达 ${res.status}`
    try {
      const parsed = JSON.parse(text) as { detail?: unknown; error?: unknown }
      if (typeof parsed.detail === 'string') msg = parsed.detail
      else if (typeof parsed.error === 'string') msg = parsed.error
    } catch {
      if (res.status === 502 || res.status === 504) msg = '后端未启动或代理超时（8765）'
      else if (text && text.length < 180) msg = text
    }
    throw new Error(msg)
  }
  const j = (await res.json()) as Raw
  const stale = j.sector_stale === 'daily' ? 'daily' : null
  return {
    ok: j.ok !== false,
    error: j.error ? str(j.error) : undefined,
    asOf: j.as_of ? str(j.as_of) : null,
    session: j.session === 'open' ? 'open' : 'closed',
    cached: Boolean(j.cached),
    sectorStale: stale,
    source: str(j.source),
    universe: mapUniverse(j.universe),
    indexes: Array.isArray(j.indexes) ? (j.indexes as Raw[]).map(mapIndex) : [],
    sectors: Array.isArray(j.sectors) ? (j.sectors as Raw[]).map(mapSector) : [],
    stocks: Array.isArray(j.stocks) ? (j.stocks as Raw[]).map(mapStock) : [],
    alerts: Array.isArray(j.alerts) ? (j.alerts as Raw[]).map(mapAlert) : [],
  }
}
