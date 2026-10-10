/**
 * 由当日高低价表推导做 T 条件单。
 * 幅度 0.3% 只作为条件单参数，不参与改价。
 * high_low_diff 为 0 的股票不生成。
 */

export const CONDITIONAL_ORDER_HEADERS = [
  '股票名称',
  '条件类型',
  '幅度',
  '触发价',
  '实行价',
  '触发档',
  '实行档',
] as const

export const CONDITIONAL_ORDER_PCT = '0.3%'

export interface ConditionalOrderRow {
  股票名称: string
  条件类型: '反弹买入' | '回落卖出'
  幅度: string
  触发价: string
  实行价: string
  触发档: string
  实行档: string
}

export interface ConditionalOrdersBuild {
  ready: boolean
  orders: ConditionalOrderRow[]
  skippedZeroDiff: number
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

/** 已是两位小数的报价转为分；无效返回 null。 */
function centsOf(cell: unknown): number | null {
  const raw = String(cell ?? '').trim()
  if (!raw) return null
  const n = Number(raw)
  if (!Number.isFinite(n)) return null
  return Math.round(n * 100)
}

function centsText(cents: number): string {
  const sign = cents < 0 ? '-' : ''
  const amount = Math.abs(cents)
  return `${sign}${Math.floor(amount / 100)}.${String(amount % 100).padStart(2, '0')}`
}

/** price + d/2，四舍五入到分。 */
function plusHalfDiff(priceCents: number, diffCents: number): number {
  const doubled = priceCents * 2 + diffCents
  if (doubled >= 0) return Math.floor((doubled + 1) / 2)
  return -Math.floor((Math.abs(doubled) + 1) / 2)
}

export function buildConditionalOrders(
  headers: string[],
  rows: Array<Array<string | number | null | undefined>>,
): ConditionalOrdersBuild {
  const idx = {
    name: colIndex(headers, 'stock_name'),
    high: colIndex(headers, 'today_high'),
    diff: colIndex(headers, 'high_low_diff'),
    sell1: colIndex(headers, '卖一'),
    sell3: colIndex(headers, '卖三'),
    buy1: colIndex(headers, '买一'),
    buy2: colIndex(headers, '买二'),
    buy3: colIndex(headers, '买三'),
  }
  if (Object.values(idx).some((i) => i < 0)) {
    return { ready: false, orders: [], skippedZeroDiff: 0 }
  }

  const orders: ConditionalOrderRow[] = []
  let skippedZeroDiff = 0

  for (const row of rows) {
    const name = String(row[idx.name] ?? '').trim()
    if (!name) continue
    const diff = centsOf(row[idx.diff])
    if (diff == null) continue
    if (diff === 0) {
      skippedZeroDiff += 1
      continue
    }
    const high = centsOf(row[idx.high])
    const sell1 = centsOf(row[idx.sell1])
    const sell3 = centsOf(row[idx.sell3])
    const buy1 = centsOf(row[idx.buy1])
    const buy2 = centsOf(row[idx.buy2])
    const buy3 = centsOf(row[idx.buy3])
    if (high == null || sell1 == null || sell3 == null || buy1 == null || buy2 == null || buy3 == null) {
      continue
    }
    const buy1Half = plusHalfDiff(buy1, diff)
    const sell1Half = plusHalfDiff(sell1, diff)
    const specs: Array<[ConditionalOrderRow['条件类型'], number, number, string, string]> = [
      ['反弹买入', buy2, buy3, '买二', '买三'],
      ['反弹买入', buy1, buy2, '买一', '买二'],
      ['回落卖出', buy1Half, high, '买一+d/2', 'high'],
      ['回落卖出', high, sell1Half, 'high', '卖一+d/2'],
      ['回落卖出', sell1Half, sell3, '卖一+d/2', '卖三'],
    ]
    for (const [kind, trigger, execute, triggerLabel, executeLabel] of specs) {
      orders.push({
        股票名称: name,
        条件类型: kind,
        幅度: CONDITIONAL_ORDER_PCT,
        触发价: centsText(trigger),
        实行价: centsText(execute),
        触发档: triggerLabel,
        实行档: executeLabel,
      })
    }
  }

  return { ready: true, orders, skippedZeroDiff }
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
