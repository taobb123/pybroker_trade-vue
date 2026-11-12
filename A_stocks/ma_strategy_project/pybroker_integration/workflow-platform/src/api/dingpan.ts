import { apiUrl } from '@/config/apiBase'

export type DingpanZone = {
  zoneLow: number
  zoneHigh: number
}

export type DingpanLows = DingpanZone & {
  kind: string
  first: number
  second: number
  firstDate: string
  secondDate: string
}

export type DingpanPullback = DingpanZone & {
  lower: number
  upper: number
  lowDate: string
  highDate: string
}

export type DingpanPressure = {
  vwap: number | null
  close: number
  high: number
  date: string
  distanceVwap: number | null
  distanceClose: number | null
  distanceHigh: number | null
}

export type DingpanBreakout = {
  price: number
  date: string
  confirmed: boolean
  retest: string
}

export type DingpanItem = {
  symbol: string
  name: string
  asof: string | null
  close: number | null
  stage: string
  lows: DingpanLows | null
  pullback: DingpanPullback | null
  pressure: DingpanPressure | null
  breakout: DingpanBreakout | null
  note: string
}

export type DingpanReport = {
  items: DingpanItem[]
  truncated: boolean
  note: string
}

type RawZone = {
  zone_low?: number
  zone_high?: number
  first?: number
  second?: number
  first_date?: string
  second_date?: string
  kind?: string
  lower?: number
  upper?: number
  low_date?: string
  high_date?: string
  vwap?: number | null
  close?: number
  high?: number
  date?: string
  distance_vwap?: number | null
  distance_close?: number | null
  distance_high?: number | null
}

type RawItem = {
  symbol?: string
  name?: string
  asof?: string | null
  close?: number | null
  stage?: string
  lows?: RawZone | null
  pullback?: RawZone | null
  pressure?: RawZone | null
  breakout?: { price?: number; date?: string; confirmed?: boolean; retest?: string } | null
  note?: string
}

function num(value: unknown): number | null {
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

function mapItem(raw: RawItem): DingpanItem {
  const lows = raw.lows
  const pullback = raw.pullback
  const pressure = raw.pressure
  const breakout = raw.breakout
  return {
    symbol: String(raw.symbol ?? ''),
    name: String(raw.name ?? '').trim(),
    asof: raw.asof ?? null,
    close: num(raw.close),
    stage: String(raw.stage ?? '未形成'),
    lows:
      lows && num(lows.zone_low) != null && num(lows.zone_high) != null
        ? {
            zoneLow: num(lows.zone_low) as number,
            zoneHigh: num(lows.zone_high) as number,
            kind: String(lows.kind ?? ''),
            first: num(lows.first) as number,
            second: num(lows.second) as number,
            firstDate: String(lows.first_date ?? ''),
            secondDate: String(lows.second_date ?? ''),
          }
        : null,
    pullback:
      pullback && num(pullback.zone_low) != null && num(pullback.zone_high) != null
        ? {
            zoneLow: num(pullback.zone_low) as number,
            zoneHigh: num(pullback.zone_high) as number,
            lower: num(pullback.lower) as number,
            upper: num(pullback.upper) as number,
            lowDate: String(pullback.low_date ?? ''),
            highDate: String(pullback.high_date ?? ''),
          }
        : null,
    pressure:
      pressure && num(pressure.close) != null && num(pressure.high) != null
        ? {
            vwap: num(pressure.vwap),
            close: num(pressure.close) as number,
            high: num(pressure.high) as number,
            date: String(pressure.date ?? ''),
            distanceVwap: num(pressure.distance_vwap),
            distanceClose: num(pressure.distance_close),
            distanceHigh: num(pressure.distance_high),
          }
        : null,
    breakout:
      breakout && num(breakout.price) != null
        ? {
            price: num(breakout.price) as number,
            date: String(breakout.date ?? ''),
            confirmed: Boolean(breakout.confirmed),
            retest: String(breakout.retest ?? ''),
          }
        : null,
    note: String(raw.note ?? ''),
  }
}

export async function fetchDingpan(symbols: string, refresh = false): Promise<DingpanReport> {
  const response = await fetch(apiUrl('/api/dingpan'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ symbols, refresh }),
  })
  if (!response.ok) throw new Error(`盯盘计算失败 (${response.status})`)
  const raw = (await response.json()) as { items?: RawItem[]; truncated?: boolean; note?: string }
  return {
    items: (raw.items ?? []).map(mapItem),
    truncated: Boolean(raw.truncated),
    note: String(raw.note ?? ''),
  }
}
