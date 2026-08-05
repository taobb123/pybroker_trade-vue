import { parseReportFromLog, type RankRow } from '@/api/parse'
import { findStockCodeColumnIndex } from '@/api/tableCopy'
import { fetchWorkspaceTable, type TablePreview } from '@/api/workflow'
import type { RunRecord } from '@/api/history'
import type { Opportunity } from '@/domain/opportunity'
import { MOCK_MARKET_ENV, MOCK_OPPORTUNITIES } from '@/data/mockOpportunities'

export type OpportunitySourceKind = 'pattern_csv' | 'run_log' | 'workspace_csv' | 'demo'

export interface MarketEnvironmentView {
  label: string
  fearIndex: number | null
  hint: string
  /** 打消「情绪弱却重仓」等顾虑的说明 */
  reassure: string
  asOf: string
  positionPct: number | null
}

export interface OpportunityBundle {
  items: Opportunity[]
  source: OpportunitySourceKind
  label: string
  stepId: string
  asOf?: string
  market: MarketEnvironmentView
}

export const PATTERN_STEP_ID = 'fetch_pattern_entry'
export const PATTERN_SCAN_CSV = 'pattern_entry_scan.csv'
export const PATTERN_VALUATION_CSV = 'pattern_entry_valuation_rank.csv'
export const MARKET_TEMP_CSV = 'market_temperature_latest.csv'
export const ROC_STEP_ID = 'roc_20'
export const ROC_RANK_CSV = 'factor_investing_ranking_latest.csv'

const MAX_ROWS = 12

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
  for (let i = 0; i < n.length; i++) {
    const h = n[i] ?? ''
    if (candidates.some((c) => h.includes(normHeader(c)))) return i
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

function isTruthy(v: string): boolean {
  const s = v.trim().toLowerCase()
  return s === 'true' || s === '1' || s === 'yes' || s === 'y'
}

function code6(raw: string): string {
  const dig = raw.replace(/\D/g, '')
  if (dig.length >= 6) return dig.slice(-6)
  return raw.trim()
}

/** pattern score 常在个位数～30，需归一后再进好球阈值 */
export function patternToTrendScore(input: {
  score: number | null
  entry: boolean
  selectTag: string
  stateCode: string
}): number {
  const score = input.score ?? 0
  if (input.entry) return Math.min(99, Math.round(88 + Math.min(score, 20) * 0.4))
  if (input.selectTag === '建仓') return Math.min(99, Math.round(82 + Math.min(score, 30) * 0.4))
  if (input.selectTag === '待选' || input.stateCode === 'confirming') {
    // 22 → 86，16 → 77，6 → 63
    return Math.max(50, Math.min(96, Math.round(55 + score * 1.4)))
  }
  return Math.max(40, Math.min(72, Math.round(40 + score)))
}

export function valuationToScore(upside: number | null, undervalued: boolean): number | null {
  if (undervalued) return Math.min(95, Math.round(78 + Math.min(upside ?? 0.5, 2) * 8))
  if (upside == null) return null
  if (upside >= 0.3) return Math.min(90, Math.round(70 + upside * 20))
  if (upside >= 0) return Math.round(55 + upside * 40)
  return Math.max(30, Math.round(50 + upside * 40))
}

export function rocToTrendScore(roc: number): number {
  const n = Number(roc)
  if (!Number.isFinite(n)) return 50
  return Math.max(1, Math.min(99, Math.round(60 + n * 150)))
}

type ValRow = {
  upside: number | null
  fairPrice: number | null
  close: number | null
  undervalued: boolean
}

function parseValuationMap(table: TablePreview): Map<string, ValRow> {
  const map = new Map<string, ValRow>()
  if (!table.exists || !table.headers?.length || !table.rows?.length) return map
  const h = table.headers
  const rows = table.rows as unknown[][]
  const codeIdx = findStockCodeColumnIndex(h)
  if (codeIdx < 0) return map
  const upsideIdx = colIndex(h, ['upside', 'upside_raw'])
  const fairIdx = colIndex(h, ['fair_price', 'fairprice'])
  const closeIdx = colIndex(h, ['close', '收盘'])
  const underIdx = colIndex(h, ['undervalued'])
  for (const row of rows) {
    const sym = code6(cell(row, codeIdx))
    if (!sym) continue
    map.set(sym, {
      upside: cellNum(row, upsideIdx),
      fairPrice: cellNum(row, fairIdx),
      close: cellNum(row, closeIdx),
      undervalued: isTruthy(cell(row, underIdx)),
    })
  }
  return map
}

function patternRowsToOpportunities(
  table: TablePreview,
  valuation: Map<string, ValRow>,
): Opportunity[] {
  if (!table.exists || !table.headers?.length || !table.rows?.length) return []
  const h = table.headers
  const rows = table.rows as unknown[][]
  const codeIdx = findStockCodeColumnIndex(h)
  if (codeIdx < 0) return []

  const nameIdx = colIndex(h, ['stock_name', 'name', '股票名称'])
  const comboIdx = colIndex(h, ['combo_name', 'combo'])
  const stateIdx = colIndex(h, ['state'])
  const stateCodeIdx = colIndex(h, ['state_code'])
  const tagIdx = colIndex(h, ['select_tag'])
  const entryIdx = colIndex(h, ['entry'])
  const scoreIdx = colIndex(h, ['score'])
  const closeIdx = colIndex(h, ['close'])
  const notesIdx = colIndex(h, ['notes'])
  const dateIdx = colIndex(h, ['signal_date'])
  const platformIdx = colIndex(h, ['platform_level'])
  const breakoutHighIdx = colIndex(h, ['breakout_high'])
  const panicLowIdx = colIndex(h, ['panic_low'])

  const out: Opportunity[] = []
  for (const row of rows) {
    const symbol = code6(cell(row, codeIdx))
    if (!symbol) continue
    const selectTag = cell(row, tagIdx)
    const entry = isTruthy(cell(row, entryIdx))
    const stateCode = cell(row, stateCodeIdx)
    // 降噪：只保留待选/建仓或已触发 entry
    if (!entry && selectTag !== '待选' && selectTag !== '建仓') continue

    const score = cellNum(row, scoreIdx)
    const trend = patternToTrendScore({ score, entry, selectTag, stateCode })
    const name = cell(row, nameIdx) || symbol
    const combo = cell(row, comboIdx)
    const state = cell(row, stateIdx)
    const notes = cell(row, notesIdx)
    const signalDate = cell(row, dateIdx)
    const close = cellNum(row, closeIdx)
    const platform = cellNum(row, platformIdx)
    const breakoutHigh = cellNum(row, breakoutHighIdx)
    const panicLow = cellNum(row, panicLowIdx)
    const val = valuation.get(symbol)

    const valuationScore = val
      ? valuationToScore(val.upside, val.undervalued)
      : null

    let idealLow: number | undefined
    let idealHigh: number | undefined
    if (val?.fairPrice != null) {
      idealLow = Number((val.fairPrice * 0.85).toFixed(2))
      idealHigh = Number(val.fairPrice.toFixed(2))
    } else if (platform != null && breakoutHigh != null) {
      idealLow = platform
      idealHigh = breakoutHigh
    } else if (panicLow != null && close != null) {
      idealLow = panicLow
      idealHigh = close
    }

    const thesisParts = [combo, state, notes].filter(Boolean)
    const thesis =
      (thesisParts.join(' · ').slice(0, 120) || '形态规则扫描命中') +
      (signalDate ? `（信号日 ${signalDate}）` : '')

    out.push({
      id: `pattern-${symbol}-${signalDate || 'na'}`,
      symbol,
      name,
      scores: {
        trend,
        fundamental: null,
        flow: null,
        valuation: valuationScore,
      },
      thesis,
      risk: entry
        ? '已标建仓条件，仍须核对仓位与止损；形态失败则快速退出。'
        : '尚未触发 entry；适合观察池等待，勿因「待选」情绪化追高。',
      stepId: PATTERN_STEP_ID,
      price: close ?? val?.close ?? undefined,
      idealLow,
      idealHigh,
    })
  }

  // 好球优先：综合可排前的先展示（趋势+估值平均）
  out.sort((a, b) => {
    const sa = [a.scores.trend, a.scores.valuation].filter((n): n is number => n != null)
    const sb = [b.scores.trend, b.scores.valuation].filter((n): n is number => n != null)
    const avg = (xs: number[]) => (xs.length ? xs.reduce((p, c) => p + c, 0) / xs.length : 0)
    return avg(sb) - avg(sa)
  })

  return out.slice(0, MAX_ROWS)
}

function parseMarketEnv(table: TablePreview): MarketEnvironmentView | null {
  if (!table.exists || !table.headers?.length || !table.rows?.length) return null
  const h = table.headers
  const row = table.rows[0] as unknown[]
  const label = cell(row, colIndex(h, ['position_label', '仓位建议'])) || '市场环境'
  const total = cellNum(row, colIndex(h, ['total_score', '总分']))
  const positionPct = cellNum(row, colIndex(h, ['position_pct', '仓位']))
  const rawHint =
    cell(row, colIndex(h, ['诊断_一句话', '诊断一句'])) ||
    cell(row, colIndex(h, ['诊断_操作建议'])) ||
    '参考仓位温度，仍只打好球。'
  const asOf =
    cell(row, colIndex(h, ['report_time', 'trade_date', '交易日'])) || '工作区温度表'

  const score = total ?? 0
  const pct = positionPct ?? 0
  // 旧产物：情绪弱文案 + 校准重仓 → 前端纠偏展示
  const conflicting =
    score < 45 &&
    pct >= 55 &&
    /轻仓|观望|减少新开仓|空仓/.test(rawHint)

  const hint = conflicting
    ? `情绪偏弱（温度 ${Math.round(score)}），仓位按回测校准为约 ${Math.round(pct)}%：弱市中精选个股、保留参与空间。`
    : rawHint.slice(0, 160)

  const reassure =
    score < 45 && pct >= 55
      ? '说明：温度分看当下情绪，仓位来自「过往同类情绪 → 未来收益」回测校准；低分区间历史上随后约10日上行概率并不差，故可相对积极，但仍只打好球、不追涨杀跌。'
      : pct >= 55
        ? '仓位建议结合温度与历史回测；高仓≠满仓梭哈，仍以好球与做 T 档位约束出手。'
        : '仓位建议结合温度与历史回测；情绪偏弱时以等待好球为主。'

  return {
    label,
    fearIndex: total != null ? Math.round(total) : null,
    hint,
    reassure,
    asOf,
    positionPct,
  }
}

function demoMarket(): MarketEnvironmentView {
  return {
    label: MOCK_MARKET_ENV.label,
    fearIndex: MOCK_MARKET_ENV.fearIndex,
    hint: MOCK_MARKET_ENV.hint,
    reassure: '演示数据；正式环境将展示情绪与回测校准说明。',
    asOf: MOCK_MARKET_ENV.asOf,
    positionPct: null,
  }
}

function rankFallbackTrend(rank: number): number {
  return Math.max(55, Math.min(96, 96 - (Math.max(1, rank) - 1) * 4))
}

function pickNumeric(row: RankRow, keys: string[]): number | null {
  for (const k of keys) {
    const v = row[k]
    if (typeof v === 'number' && Number.isFinite(v)) return v
  }
  return null
}

export function rankRowsToOpportunities(rows: RankRow[], stepId: string): Opportunity[] {
  return rows
    .filter((r) => String(r.symbol || '').trim())
    .slice(0, MAX_ROWS)
    .map((r, idx) => {
      const rank = Number(r.rank) || idx + 1
      const roc = pickNumeric(r, ['roc_20', 'roc20', 'ROC20', 'roc', 'score', 'weight'])
      const trend = roc != null ? rocToTrendScore(roc) : rankFallbackTrend(rank)
      const name = (r.name && String(r.name)) || String(r.symbol)
      const rocPct = roc != null ? `${(roc * 100).toFixed(1)}%` : null
      return {
        id: `run-${stepId}-${r.symbol}`,
        symbol: String(r.symbol).replace(/\D/g, '').slice(-6) || String(r.symbol),
        name,
        scores: { trend, fundamental: null, flow: null, valuation: null },
        thesis: rocPct
          ? `20日 ROC 排名第 ${rank}（${rocPct}），趋势动量相对靠前。`
          : `20日 ROC 排序第 ${rank}，规则动量相对靠前。`,
        risk: '动量策略易回撤；缺基本面/估值维度时须自行补研究，勿单凭排序出手。',
        stepId,
      } satisfies Opportunity
    })
}

function tableToRankRows(headers: string[], rows: Array<Array<unknown>>): RankRow[] {
  const codeIdx = findStockCodeColumnIndex(headers)
  if (codeIdx < 0) return []
  const nameIdx = colIndex(headers, ['name', '股票名称', 'stock_name', '证券简称'])
  const rankIdx = colIndex(headers, ['rank', '排名', '名次'])
  const rocIdx = colIndex(headers, ['roc_20', 'roc20', 'ROC_20', 'roc', '综合评分', 'score', 'weight'])

  return rows.map((row, idx) => {
    const symbol = code6(cell(row, codeIdx))
    const name = nameIdx >= 0 ? cell(row, nameIdx) : undefined
    const rankRaw = cellNum(row, rankIdx)
    const out: RankRow = {
      rank: rankRaw != null ? rankRaw : idx + 1,
      symbol,
      name,
    }
    const roc = cellNum(row, rocIdx)
    if (roc != null) {
      // 综合评分若已是 0–100，勿当 ROC 比例
      out.roc_20 = roc > 1.5 ? roc / 100 : roc
    }
    return out
  })
}

function latestStepRun(runs: RunRecord[], stepId: string): RunRecord | null {
  for (const r of runs) {
    if (r.stepId !== stepId) continue
    if (r.status === 'success' || r.exitCode === 0) return r
  }
  return null
}

/**
 * 优先形态建仓 CSV（可并估值）→ roc_20 运行日志 → 因子排名 CSV → 演示
 * 市场环境：market_temperature_latest.csv，否则演示
 */
export async function loadOpportunityBundle(runs: RunRecord[]): Promise<OpportunityBundle> {
  const [scan, valuationTable, tempTable] = await Promise.all([
    fetchWorkspaceTable(PATTERN_SCAN_CSV, 200),
    fetchWorkspaceTable(PATTERN_VALUATION_CSV, 200),
    fetchWorkspaceTable(MARKET_TEMP_CSV, 5),
  ])
  const market = parseMarketEnv(tempTable) ?? demoMarket()
  const valuation = parseValuationMap(valuationTable)
  const patternItems = patternRowsToOpportunities(scan, valuation)
  if (patternItems.length) {
    const dateIdx = colIndex(scan.headers, ['signal_date'])
    const first = (scan.rows?.[0] as unknown[] | undefined) ?? []
    const asOf = dateIdx >= 0 ? cell(first, dateIdx) : ''
    return {
      items: patternItems,
      source: 'pattern_csv',
      label: `形态建仓表 ${PATTERN_SCAN_CSV}${valuation.size ? ' + 估值排名' : ''}`,
      stepId: PATTERN_STEP_ID,
      asOf: asOf || undefined,
      market,
    }
  }

  const rocRun = latestStepRun(runs, ROC_STEP_ID)
  if (rocRun) {
    const parsed = parseReportFromLog(rocRun.log)
    if (parsed.rows.length) {
      return {
        items: rankRowsToOpportunities(parsed.rows, ROC_STEP_ID),
        source: 'run_log',
        label: `来自工作流「${rocRun.stepTitle}」最近成功运行`,
        stepId: ROC_STEP_ID,
        asOf: rocRun.finishedAt,
        market,
      }
    }
  }

  const rankCsv = await fetchWorkspaceTable(ROC_RANK_CSV, 50)
  if (rankCsv.exists && rankCsv.headers?.length && rankCsv.rows?.length) {
    const rankRows = tableToRankRows(rankCsv.headers, rankCsv.rows as Array<Array<unknown>>)
    const items = rankRowsToOpportunities(rankRows, ROC_STEP_ID)
    if (items.length) {
      return {
        items,
        source: 'workspace_csv',
        label: `来自工作区表 ${ROC_RANK_CSV}`,
        stepId: ROC_STEP_ID,
        market,
      }
    }
  }

  return {
    items: MOCK_OPPORTUNITIES,
    source: 'demo',
    label: '演示规则数据（未找到形态/ROC 产物）',
    stepId: PATTERN_STEP_ID,
    market,
  }
}
