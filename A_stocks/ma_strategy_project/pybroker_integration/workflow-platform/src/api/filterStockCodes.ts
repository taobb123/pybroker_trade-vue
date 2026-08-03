/** 与旧版 stock_pool_workflow.html filterStockCodes 对齐 */

const EXCLUDED_CODE_PREFIXES = ['300', '301', '688', '920']

/** 量价六组合自定义列表路径 */
export const VP_SIX_COMBO_SYMBOLS_PATH = 'config/fetch_vp_six_combo_symbols.txt'
export const DC_CONCEPT_MEMBERS_CSV = 'dc_concept_ma5_members.csv'

export function parsePureSixDigitCodes(text: string): string[] {
  return String(text || '')
    .split(/[\s,;，；\r\n\t]+/)
    .map((t) => t.trim())
    .filter((s) => /^\d{6}$/.test(s))
}

/** 东财成分代码 → 6 位（与 fetch_dc_concept_ma5._con_code_to_symbol 一致） */
export function conCodeToSymbol6(conCode: string): string {
  const s = String(conCode || '')
    .trim()
    .toUpperCase()
  if (!s) return ''
  const pre = s.split('.')[0] ?? ''
  const digits = pre.replace(/\D/g, '')
  if (digits.length < 6) return ''
  return digits.slice(-6).padStart(6, '0')
}

/** 从 dc_concept_ma5_members.csv 文本提取 6 位代码（读 con_code 列） */
export function extractSymbolsFromMembersCsv(csvText: string): string[] {
  const lines = String(csvText || '')
    .replace(/^\uFEFF/, '')
    .split(/\r?\n/)
    .filter((l) => l.trim())
  if (lines.length < 2) return []

  const headers = splitCsvLine(lines[0]!).map((h) => h.trim().toLowerCase())
  let col = headers.indexOf('con_code')
  if (col < 0) col = headers.findIndex((h) => h.includes('con_code') || h === 'symbol' || h === 'ts_code')
  if (col < 0) return []

  const out: string[] = []
  const seen = new Set<string>()
  for (let i = 1; i < lines.length; i++) {
    const cells = splitCsvLine(lines[i]!)
    const sym = conCodeToSymbol6(cells[col] ?? '')
    if (!sym || seen.has(sym)) continue
    seen.add(sym)
    out.push(sym)
  }
  return out
}

function splitCsvLine(line: string): string[] {
  const cells: string[] = []
  let cur = ''
  let inQ = false
  for (let i = 0; i < line.length; i++) {
    const ch = line[i]!
    if (ch === '"') {
      if (inQ && line[i + 1] === '"') {
        cur += '"'
        i += 1
      } else {
        inQ = !inQ
      }
      continue
    }
    if (ch === ',' && !inQ) {
      cells.push(cur)
      cur = ''
      continue
    }
    cur += ch
  }
  cells.push(cur)
  return cells
}

export type FilterStockCodesResult = {
  codes: string[]
  inputCount: number
  dupSkipped: number
  prefixSkipped: number
  outputCount: number
}

export function filterStockCodes(text: string): FilterStockCodesResult {
  const tokens = parsePureSixDigitCodes(text)
  const seen = new Set<string>()
  const codes: string[] = []
  let dupSkipped = 0
  let prefixSkipped = 0

  for (const code of tokens) {
    if (seen.has(code)) {
      dupSkipped += 1
      continue
    }
    seen.add(code)
    const prefix = code.slice(0, 3)
    if (EXCLUDED_CODE_PREFIXES.includes(prefix)) {
      prefixSkipped += 1
      continue
    }
    codes.push(code)
  }

  return {
    codes,
    inputCount: tokens.length,
    dupSkipped,
    prefixSkipped,
    outputCount: codes.length,
  }
}

/** 东财成分表 → 清洗 → 写入量价六组合 symbols 文本 */
export function buildVpSixComboSymbolsFile(codes: string[]): string {
  const header = [
    '# 由 fetch_dc_concept_ma5 → 股票代码清洗 自动生成',
    '# 供 fetch_vp_six_combo 作为自定义股票列表',
    '',
  ].join('\n')
  return header + codes.join('\n') + (codes.length ? '\n' : '')
}
