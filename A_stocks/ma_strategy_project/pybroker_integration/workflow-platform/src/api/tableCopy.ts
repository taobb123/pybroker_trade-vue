/** 与旧版 stock_pool_workflow.html 表格复制逻辑对齐 */

export function isTodayHighLowTable(relPath: string): boolean {
  return relPath.replace(/\\/g, '/').includes('today_high_low_result.csv')
}

function normalizeHeaderCell(h: unknown): string {
  return String(h ?? '')
    .trim()
    .replace(/\s/g, '')
    .toLowerCase()
}

export function findStockCodeColumnIndex(headers: string[]): number {
  const norm = headers.map(normalizeHeaderCell)
  const exact = ['股票代码', 'code6', 'symbol', 'ts_code', '代码', 'stock_code', '证券代码']
  for (const name of exact) {
    const idx = norm.indexOf(normalizeHeaderCell(name))
    if (idx >= 0) return idx
  }
  for (let j = 0; j < norm.length; j++) {
    const h = norm[j]
    if (!h) continue
    if (h.includes('股票代码') || h === '代码' || h.includes('证券代码')) return j
    if (h === 'symbol' || h === 'code6' || h.includes('ts_code')) return j
  }
  return -1
}

function cellToStockCode6(cell: unknown, headerNorm: string): string {
  const raw = String(cell ?? '').trim()
  if (!raw) return ''
  if (headerNorm.includes('ts_code') || raw.includes('.')) {
    const pre = raw.split('.')[0]?.trim() ?? ''
    const dig = pre.replace(/\D/g, '')
    if (dig.length >= 6) return dig.slice(-6)
  }
  const digits = raw.replace(/\D/g, '')
  if (digits.length >= 6) return digits.slice(-6)
  if (digits.length > 0) return digits.padStart(6, '0')
  return raw
}

/** 浮点数展示保留两位；整数、代码、非数字原样返回 */
export function formatDecimalTwoPlaces(cell: unknown): string | null {
  if (cell == null) return null
  const raw = String(cell).trim()
  if (!raw) return ''
  // 含字母的代码/标签（如 600519.SH）不改
  if (/[a-zA-Z_%]/.test(raw)) return null
  // 仅处理带小数点或科学计数法的数值；纯整数保持原样
  if (!/^[-+]?(?:\d+\.\d+|\.\d+)(?:[eE][-+]?\d+)?$|^[-+]?\d+[eE][-+]?\d+$/.test(raw)) {
    return null
  }
  const n = Number(raw)
  if (!Number.isFinite(n)) return null
  return n.toFixed(2)
}

export function formatPreviewCell(header: string, cell: unknown, relPath: string): string {
  const h = normalizeHeaderCell(header)
  if (isTodayHighLowTable(relPath)) {
    if (h === 'symbol' || h === 'code6' || h.includes('ts_code')) {
      return cellToStockCode6(cell, h) || String(cell ?? '')
    }
    if (h === 'today_high' || h === 'today_low' || h === 'high_low_diff') {
      const n = parseFloat(String(cell))
      if (!Number.isNaN(n)) return n.toFixed(2)
    }
  }
  const rounded = formatDecimalTwoPlaces(cell)
  if (rounded != null) return rounded
  return cell == null ? '' : String(cell)
}

/** 整表复制：表头 + 行，制表符分隔（与旧版「复制全部」一致） */
export function tableRowsToCopyText(
  headers: string[],
  rows: Array<Array<string | number | null | undefined>>,
  relPath: string,
): string {
  const lines = [headers.join('\t')]
  for (const row of rows) {
    const cells = headers.map((h, i) => formatPreviewCell(h, row?.[i], relPath))
    lines.push(cells.join('\t'))
  }
  return lines.join('\n')
}

/** 仅股票代码列，每行一个 */
export function stockCodesToCopyText(
  headers: string[],
  rows: Array<Array<string | number | null | undefined>>,
): string | null {
  const col = findStockCodeColumnIndex(headers)
  if (col < 0) return null
  const hn = normalizeHeaderCell(headers[col])
  const lines: string[] = []
  for (const row of rows) {
    const code = cellToStockCode6(row?.[col], hn)
    if (code) lines.push(code)
  }
  return lines.join('\n')
}

export async function copyTextToClipboard(text: string): Promise<boolean> {
  if (!text) return false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    /* fallback below */
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(ta)
  return ok
}
