/**
 * 由当日高低价表推导条件单。每只股票最多 4 行，顺序固定：
 * 定价条件单1（卖出）：成交价 = 昨日收盘价 + 价差，触发价留空（与成交价相同，不单列）；
 * 定价条件单2（卖出）：成交价 = 昨日收盘价 + 预测高价日变动中位数，触发价留空；
 * 反弹买入条件单1：触发价 = 买二，反弹 1% 后买入，成交价留空；
 * 反弹买入条件单2：触发价 = 买三，反弹 1% 后买入，成交价留空。
 * 价格保留到分。某一档所需价格缺失时跳过该行。
 */

export const CONDITIONAL_ORDER_HEADERS = ['股票名称', '条件类型', '成交价', '触发价'] as const

export type ConditionalOrderKind =
  | '定价条件单1'
  | '定价条件单2'
  | '反弹买入条件单1'
  | '反弹买入条件单2'

export interface ConditionalOrderRow {
  股票名称: string
  条件类型: ConditionalOrderKind
  成交价: string
  触发价: string
}

export interface ConditionalOrdersBuild {
  ready: boolean
  orders: ConditionalOrderRow[]
  missingClose: boolean
}

function normHeader(h: unknown): string {
  return String(h ?? '')
    .trim()
    .replace(/\s/g, '')
    .toLowerCase()
}

function colIndex(headers: string[], name: string): number {
  const target = normHeader(name)
  return headers.findIndex((h) => normHeader(h) === target)
}

/** 报价转为分；「1.21 (2.50%)」只取前面的元。无效返回 null。 */
function centsOf(cell: unknown): number | null {
  const raw = String(cell ?? '').trim()
  if (!raw) return null
  const n = parseFloat(raw)
  if (!Number.isFinite(n)) return null
  return Math.round(n * 100)
}

function centsText(cents: number): string {
  const sign = cents < 0 ? '-' : ''
  const amount = Math.abs(cents)
  return `${sign}${Math.floor(amount / 100)}.${String(amount % 100).padStart(2, '0')}`
}

export function buildConditionalOrders(
  headers: string[],
  rows: Array<Array<string | number | null | undefined>>,
): ConditionalOrdersBuild {
  const idx = {
    name: colIndex(headers, 'stock_name'),
    close: colIndex(headers, '昨日收盘价'),
    diff: colIndex(headers, 'high_low_diff'),
    median: colIndex(headers, '预测高价日变动中位数'),
    buy2: colIndex(headers, '买二'),
    buy3: colIndex(headers, '买三'),
  }
  if (idx.name < 0) {
    return { ready: false, orders: [], missingClose: false }
  }

  const orders: ConditionalOrderRow[] = []
  const missingClose = idx.close < 0

  for (const row of rows) {
    const name = String(row[idx.name] ?? '').trim()
    if (!name) continue
    const close = idx.close >= 0 ? centsOf(row[idx.close]) : null
    const diff = idx.diff >= 0 ? centsOf(row[idx.diff]) : null
    const median = idx.median >= 0 ? centsOf(row[idx.median]) : null
    const buy2 = idx.buy2 >= 0 ? centsOf(row[idx.buy2]) : null
    const buy3 = idx.buy3 >= 0 ? centsOf(row[idx.buy3]) : null

    const push = (kind: ConditionalOrderKind, execute: string, trigger: string) => {
      orders.push({ 股票名称: name, 条件类型: kind, 成交价: execute, 触发价: trigger })
    }

    if (close != null && diff != null) {
      push('定价条件单1', centsText(close + diff), '')
    }
    if (close != null && median != null) {
      push('定价条件单2', centsText(close + median), '')
    }
    if (buy2 != null) push('反弹买入条件单1', '', centsText(buy2))
    if (buy3 != null) push('反弹买入条件单2', '', centsText(buy3))
  }

  return { ready: true, orders, missingClose }
}

export function conditionalOrdersToCopyText(orders: ConditionalOrderRow[]): string {
  const lines = [CONDITIONAL_ORDER_HEADERS.join('\t')]
  for (const row of orders) {
    lines.push(CONDITIONAL_ORDER_HEADERS.map((h) => row[h]).join('\t'))
  }
  return lines.join('\n')
}

export function conditionalOrdersToCsv(orders: ConditionalOrderRow[]): string {
  const escape = (cell: string) => {
    if (/[",\n\r]/.test(cell)) return `"${cell.replace(/"/g, '""')}"`
    return cell
  }
  const lines = [
    CONDITIONAL_ORDER_HEADERS.map((h) => escape(h)).join(','),
    ...orders.map((row) => CONDITIONAL_ORDER_HEADERS.map((h) => escape(row[h])).join(',')),
  ]
  return lines.join('\n')
}
