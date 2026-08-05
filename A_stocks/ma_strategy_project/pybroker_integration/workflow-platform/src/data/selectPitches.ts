/**
 * 选球：市场中性多头净值 Top2 因子 × 各因子排名 Top2 股
 */
import { findStockCodeColumnIndex } from '@/api/tableCopy'
import { fetchWorkspaceTable, type TablePreview } from '@/api/workflow'
import type { Opportunity } from '@/domain/opportunity'
import {
  patternToTrendScore,
  valuationToScore,
} from '@/data/loadOpportunities'

export type NeutralFactorId = 'A' | 'B' | 'Q' | 'M+' | 'M-'

export const FACTOR_META: Record<
  NeutralFactorId,
  { label: string; rankCsv: string; scoreCol: string }
> = {
  A: { label: '形态', rankCsv: 'pattern_entry_scan.csv', scoreCol: 'score' },
  B: { label: '相对PE', rankCsv: 'pattern_entry_valuation_rank.csv', scoreCol: 'upside' },
  Q: { label: '公司估值Q', rankCsv: 'pattern_entry_q_rank.csv', scoreCol: 'company_q' },
  'M+': { label: '动量MUD', rankCsv: 'pattern_entry_mplus_rank.csv', scoreCol: 'mud_plus' },
  'M-': { label: '反转MUD', rankCsv: 'pattern_entry_mminus_rank.csv', scoreCol: 'mud_minus' },
}

const METRICS_CSV = 'market_neutral/output/latest/metrics.csv'
const TOP_FACTORS = 2
const TOP_STOCKS_PER_FACTOR = 2

export interface FactorPick {
  factorId: NeutralFactorId
  label: string
  longNav: number
  variant: string
}

export interface PitchCandidate {
  opportunity: Opportunity
  factorId: NeutralFactorId
  factorLabel: string
  factorRank: number
  longNav: number
}

export interface PitchSelectBundle {
  factors: FactorPick[]
  pitches: PitchCandidate[]
  label: string
}

function normHeader(h: unknown): string {
  return String(h ?? '')
    .trim()
    .replace(/\s/g, '')
    .toLowerCase()
}

function colIndex(headers: string[], candidates: string[]): number {
  const n = headers.map(normHeader)
  for (const c of candidates) {
    const t = normHeader(c)
    const i = n.indexOf(t)
    if (i >= 0) return i
  }
  return -1
}

function cell(row: unknown[], idx: number): string {
  if (idx < 0) return ''
  return String(row[idx] ?? '').trim()
}

function cellNum(row: unknown[], idx: number): number | null {
  if (idx < 0) return null
  const n = Number(row[idx])
  return Number.isFinite(n) ? n : null
}

function code6(raw: string): string {
  const dig = raw.replace(/\D/g, '')
  if (dig.length >= 6) return dig.slice(-6)
  return raw.trim()
}

function isTruthy(v: string): boolean {
  const s = v.trim().toLowerCase()
  return s === 'true' || s === '1' || s === 'yes'
}

/** 从 metrics 按多头累计收益取前 N 个因子（优先 *_L，否则用主组 long_total_return） */
export function pickTopFactorsByLongNav(table: TablePreview, topN = TOP_FACTORS): FactorPick[] {
  if (!table.exists || !table.headers?.length || !table.rows?.length) return []
  const h = table.headers
  const variantIdx = colIndex(h, ['variant'])
  const longIdx = colIndex(h, ['long_total_return'])
  if (variantIdx < 0 || longIdx < 0) return []

  const byFactor = new Map<NeutralFactorId, FactorPick>()

  for (const row of table.rows as unknown[][]) {
    const variant = cell(row, variantIdx)
    const longNav = cellNum(row, longIdx)
    if (longNav == null) continue

    let factorId: NeutralFactorId | null = null
    if (variant === 'A' || variant === 'A_L') factorId = 'A'
    else if (variant === 'B' || variant === 'B_L') factorId = 'B'
    else if (variant === 'Q' || variant === 'Q_L') factorId = 'Q'
    else if (variant === 'M+' || variant === 'M+_L') factorId = 'M+'
    else if (variant === 'M-' || variant === 'M-_L') factorId = 'M-'
    if (!factorId) continue

    const preferL = variant.endsWith('_L')
    const prev = byFactor.get(factorId)
    if (!prev) {
      byFactor.set(factorId, {
        factorId,
        label: FACTOR_META[factorId].label,
        longNav,
        variant,
      })
      continue
    }
    // 同因子：优先保留 *_L；同类型则取更高多头净值
    const prevL = prev.variant.endsWith('_L')
    if (preferL && !prevL) {
      byFactor.set(factorId, {
        factorId,
        label: FACTOR_META[factorId].label,
        longNav,
        variant,
      })
    } else if (preferL === prevL && longNav > prev.longNav) {
      byFactor.set(factorId, {
        factorId,
        label: FACTOR_META[factorId].label,
        longNav,
        variant,
      })
    }
  }

  return [...byFactor.values()]
    .sort((a, b) => b.longNav - a.longNav)
    .slice(0, topN)
}

type RankRow = {
  symbol: string
  name: string
  rank: number
  close: number | null
  rawScore: number | null
  fairPrice: number | null
  upside: number | null
  undervalued: boolean
  thesisExtra: string
}

function parseRankTable(factorId: NeutralFactorId, table: TablePreview): RankRow[] {
  if (!table.exists || !table.headers?.length || !table.rows?.length) return []
  const h = table.headers
  const codeIdx = findStockCodeColumnIndex(h)
  if (codeIdx < 0) return []
  const nameIdx = colIndex(h, ['stock_name', 'name', '股票名称'])
  const rankIdx = colIndex(h, ['rank', '排名'])
  const closeIdx = colIndex(h, ['close', '收盘'])
  const scoreIdx = colIndex(h, [
    FACTOR_META[factorId].scoreCol,
    'score',
    'upside',
    'company_q',
    'mud_plus',
    'mud_minus',
  ])
  const fairIdx = colIndex(h, ['fair_price'])
  const upsideIdx = colIndex(h, ['upside'])
  const underIdx = colIndex(h, ['undervalued'])
  const tagIdx = colIndex(h, ['select_tag'])
  const entryIdx = colIndex(h, ['entry'])
  const comboIdx = colIndex(h, ['combo_name', 'state', 'notes'])

  const rows: RankRow[] = []
  for (let i = 0; i < (table.rows as unknown[][]).length; i++) {
    const row = (table.rows as unknown[][])[i]!
    const symbol = code6(cell(row, codeIdx))
    if (!symbol) continue

    if (factorId === 'A') {
      const tag = cell(row, tagIdx)
      const entry = isTruthy(cell(row, entryIdx))
      if (!entry && tag !== '待选' && tag !== '建仓') continue
    }

    const rank = cellNum(row, rankIdx) ?? i + 1
    rows.push({
      symbol,
      name: cell(row, nameIdx) || symbol,
      rank,
      close: cellNum(row, closeIdx),
      rawScore: cellNum(row, scoreIdx),
      fairPrice: cellNum(row, fairIdx),
      upside: cellNum(row, upsideIdx),
      undervalued: isTruthy(cell(row, underIdx)),
      thesisExtra: cell(row, comboIdx),
    })
  }

  if (factorId === 'A') {
    rows.sort((a, b) => (b.rawScore ?? 0) - (a.rawScore ?? 0))
    return rows.map((r, idx) => ({ ...r, rank: idx + 1 }))
  }

  rows.sort((a, b) => a.rank - b.rank)
  return rows
}

function rankRowToOpportunity(
  factorId: NeutralFactorId,
  row: RankRow,
  factorRank: number,
): Opportunity {
  const meta = FACTOR_META[factorId]
  let trend: number | null = null
  let valuation: number | null = null
  let fundamental: number | null = null
  let flow: number | null = null

  if (factorId === 'A') {
    trend = patternToTrendScore({
      score: row.rawScore,
      entry: false,
      selectTag: '待选',
      stateCode: 'confirming',
    })
  } else if (factorId === 'B') {
    valuation = valuationToScore(row.upside ?? row.rawScore, row.undervalued)
    trend = valuation != null ? Math.min(90, valuation - 2) : 72
  } else if (factorId === 'Q') {
    const q = row.rawScore
    fundamental = q != null ? Math.max(50, Math.min(96, Math.round(q * 100))) : null
    trend = fundamental
  } else if (factorId === 'M+') {
    const m = row.rawScore
    flow = m != null ? Math.max(50, Math.min(96, Math.round(m * 100))) : null
    trend = flow
  } else {
    const m = row.rawScore
    flow = m != null ? Math.max(50, Math.min(96, Math.round(m * 100))) : null
    trend = flow != null ? Math.max(55, flow - 5) : 70
  }

  if (row.upside != null || row.undervalued) {
    valuation = valuation ?? valuationToScore(row.upside, row.undervalued)
  }

  let idealLow: number | undefined
  let idealHigh: number | undefined
  if (row.fairPrice != null) {
    idealLow = Number((row.fairPrice * 0.85).toFixed(2))
    idealHigh = Number(row.fairPrice.toFixed(2))
  }

  return {
    id: `pitch-${factorId}-${row.symbol}`,
    symbol: row.symbol,
    name: row.name,
    scores: { trend, fundamental, flow, valuation },
    thesis: `市场中性「${meta.label}」多头净值优选 · 因子内排名第 ${factorRank}${
      row.thesisExtra ? ` · ${row.thesisExtra.slice(0, 60)}` : ''
    }`,
    risk: '来自因子横截面排名，须结合做 T 档位与预测 K 线再决定是否出手。',
    stepId: 'market_neutral',
    price: row.close ?? undefined,
    idealLow,
    idealHigh,
  }
}

/**
 * 加载选球包：无 metrics 或无排名则返回 null（雷达回退旧路径）
 */
export async function loadPitchSelectBundle(): Promise<PitchSelectBundle | null> {
  const metrics = await fetchWorkspaceTable(METRICS_CSV, 50)
  const factors = pickTopFactorsByLongNav(metrics)
  if (factors.length < 1) return null

  const rankTables = await Promise.all(
    factors.map((f) => fetchWorkspaceTable(FACTOR_META[f.factorId].rankCsv, 80)),
  )

  const pitches: PitchCandidate[] = []
  const seen = new Set<string>()

  factors.forEach((f, fi) => {
    const ranks = parseRankTable(f.factorId, rankTables[fi]!)
    const top = ranks.slice(0, TOP_STOCKS_PER_FACTOR)
    top.forEach((row, si) => {
      if (seen.has(row.symbol)) return
      seen.add(row.symbol)
      pitches.push({
        opportunity: rankRowToOpportunity(f.factorId, row, si + 1),
        factorId: f.factorId,
        factorLabel: f.label,
        factorRank: si + 1,
        longNav: f.longNav,
      })
    })
  })

  if (!pitches.length) return null

  const factorDesc = factors
    .map((f) => `${f.label}(${(f.longNav * 100).toFixed(1)}%)`)
    .join('、')

  return {
    factors,
    pitches,
    label: `市场中性多头净值 Top${factors.length}：${factorDesc} → 各取前 ${TOP_STOCKS_PER_FACTOR} 股`,
  }
}
