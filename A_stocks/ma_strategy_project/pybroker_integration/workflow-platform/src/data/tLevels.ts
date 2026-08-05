/**
 * 做 T 止盈止损档位（today_high_low_result.csv）
 */
import { fetchWorkspaceTable } from '@/api/workflow'

export const T_LEVELS_CSV = 'today_high_low_result.csv'

export interface TLevels {
  stockName: string
  todayHigh: number | null
  todayLow: number | null
  highLowDiff: number | null
  卖三: number | null
  卖二: number | null
  卖一: number | null
  买一: number | null
  买二: number | null
  买三: number | null
}

/** 展示顺序：卖档 → 高/低价 → 买档 */
export type TLevelDisplayKey =
  | '卖三'
  | '卖二'
  | '卖一'
  | '高价'
  | '低价'
  | '买一'
  | '买二'
  | '买三'

export const T_LEVEL_ORDER: TLevelDisplayKey[] = [
  '卖三',
  '卖二',
  '卖一',
  '高价',
  '低价',
  '买一',
  '买二',
  '买三',
]

export function levelValue(levels: TLevels | null | undefined, key: TLevelDisplayKey): number | null {
  if (!levels) return null
  if (key === '高价') return levels.todayHigh
  if (key === '低价') return levels.todayLow
  return levels[key]
}

function normHeader(h: unknown): string {
  return String(h ?? '')
    .trim()
    .replace(/\s/g, '')
    .toLowerCase()
}

function colIndex(headers: string[], name: string): number {
  const n = headers.map(normHeader)
  const t = normHeader(name)
  return n.indexOf(t)
}

function cellNum(row: unknown[], idx: number): number | null {
  if (idx < 0) return null
  const n = Number(row[idx])
  return Number.isFinite(n) ? n : null
}

/** name → levels；同时用规范化名称索引 */
export async function loadTLevelsByName(): Promise<Map<string, TLevels>> {
  const table = await fetchWorkspaceTable(T_LEVELS_CSV, 200)
  const map = new Map<string, TLevels>()
  if (!table.exists || !table.headers?.length || !table.rows?.length) return map

  const h = table.headers
  const nameIdx = colIndex(h, 'stock_name')
  if (nameIdx < 0) return map

  const idx = {
    todayHigh: colIndex(h, 'today_high'),
    todayLow: colIndex(h, 'today_low'),
    diff: colIndex(h, 'high_low_diff'),
    卖三: colIndex(h, '卖三'),
    卖二: colIndex(h, '卖二'),
    卖一: colIndex(h, '卖一'),
    买一: colIndex(h, '买一'),
    买二: colIndex(h, '买二'),
    买三: colIndex(h, '买三'),
  }

  for (const row of table.rows as unknown[][]) {
    const stockName = String(row[nameIdx] ?? '').trim()
    if (!stockName) continue
    const levels: TLevels = {
      stockName,
      todayHigh: cellNum(row, idx.todayHigh),
      todayLow: cellNum(row, idx.todayLow),
      highLowDiff: cellNum(row, idx.diff),
      卖三: cellNum(row, idx.卖三),
      卖二: cellNum(row, idx.卖二),
      卖一: cellNum(row, idx.卖一),
      买一: cellNum(row, idx.买一),
      买二: cellNum(row, idx.买二),
      买三: cellNum(row, idx.买三),
    }
    map.set(stockName, levels)
    map.set(stockName.replace(/\s/g, ''), levels)
  }
  return map
}

export function formatLevel(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—'
  return n.toFixed(2)
}
