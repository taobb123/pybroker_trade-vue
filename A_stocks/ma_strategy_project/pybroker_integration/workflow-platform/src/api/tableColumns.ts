/** 工作流预览表：研究向列映射（无映射则回退原 headers） */

export type ColumnSpec = {
  key: string
  label: string
  /** 默认隐藏（「显示全部列」时可见） */
  hideByDefault?: boolean
}

/** 文件名（basename）→ 列配置；未列出的列默认隐藏 */
const TABLE_COLUMN_MAPS: Record<string, ColumnSpec[]> = {
  'vp_six_combo_scan.csv': [
    { key: 'symbol', label: '股票' },
    { key: 'stock_name', label: '名称' },
    { key: 'signal_date', label: '信号日' },
    { key: 'combo_name', label: '组合' },
    { key: 'position_stage', label: '阶段' },
    { key: 'action_hint', label: '建议' },
    { key: 'meaning', label: '含义' },
    { key: 'combo_id', label: '组合ID', hideByDefault: true },
    { key: 'phase', label: 'phase', hideByDefault: true },
    { key: 'match_exact', label: '精确匹配', hideByDefault: true },
    { key: 'resonance_score', label: '共振分', hideByDefault: true },
  ],
  'dc_concept_ma5_scan.csv': [
    { key: 'concept_name', label: '概念' },
    { key: 'concept_code', label: '代码' },
    { key: 'signal_date', label: '信号日' },
    { key: 'score_total', label: '综合分' },
    { key: 'score_capital', label: '资金分' },
    { key: 'score_low', label: '低位分' },
    { key: 'signal_low', label: '低位通过', hideByDefault: true },
    { key: 'capital_ok', label: '资金标注', hideByDefault: true },
  ],
  'dc_concept_ma5_members.csv': [
    { key: 'con_code', label: '成分代码' },
    { key: 'con_name', label: '成分名称' },
    { key: 'concept_name', label: '概念' },
    { key: 'trade_date', label: '日期' },
    { key: 'concept_code', label: '概念代码', hideByDefault: true },
  ],
  'ma5_trend_scan.csv': [
    { key: 'symbol', label: '股票' },
    { key: 'stock_name', label: '名称' },
    { key: 'signal_date', label: '信号日' },
    { key: 'close', label: '收盘' },
    { key: 'ma5', label: 'MA5' },
    { key: 'ma10', label: 'MA10' },
    { key: 'ma20', label: 'MA20' },
  ],
  'market_temperature_latest.csv': [
    { key: 'trade_date', label: '交易日' },
    { key: 'total_score', label: '总分' },
    { key: 'position_pct', label: '仓位%' },
    { key: 'position_label', label: '仓位建议' },
    { key: 'risk_penalty', label: '风险扣分' },
    { key: 'risk_signal_count', label: '风险信号数' },
    { key: 'report_time', label: '报告时间' },
    { key: 'model_version', label: '版本', hideByDefault: true },
  ],
  'vp_combo_watch_4.csv': [
    { key: 'symbol', label: '股票' },
    { key: 'stock_name', label: '名称' },
    { key: 'signal_date', label: '信号日' },
    { key: 'combo_name', label: '组合' },
    { key: 'action_hint', label: '建议' },
  ],
  'vp_combo_watch_6.csv': [
    { key: 'symbol', label: '股票' },
    { key: 'stock_name', label: '名称' },
    { key: 'signal_date', label: '信号日' },
    { key: 'combo_name', label: '组合' },
    { key: 'action_hint', label: '建议' },
  ],
}

export function tableBasename(path: string): string {
  const p = String(path || '').replace(/\\/g, '/')
  const i = p.lastIndexOf('/')
  return i >= 0 ? p.slice(i + 1) : p
}

export type ResolvedColumn = {
  key: string
  label: string
  index: number
  hidden: boolean
}

/**
 * 根据 CSV 路径与 headers 解析展示列。
 * showAll=true 时显示全部原始列（有映射则用中文名）。
 */
export function resolveTableColumns(
  path: string,
  headers: string[],
  showAll = false,
): ResolvedColumn[] {
  const base = tableBasename(path).toLowerCase()
  const specs = TABLE_COLUMN_MAPS[base]
  const indexOf = (key: string) =>
    headers.findIndex((h) => h.trim().toLowerCase() === key.toLowerCase())

  if (!specs?.length) {
    return headers.map((h, index) => ({
      key: h,
      label: h,
      index,
      hidden: false,
    }))
  }

  const used = new Set<number>()
  const mapped: ResolvedColumn[] = []
  for (const spec of specs) {
    const index = indexOf(spec.key)
    if (index < 0) continue
    used.add(index)
    mapped.push({
      key: spec.key,
      label: spec.label,
      index,
      hidden: Boolean(spec.hideByDefault) && !showAll,
    })
  }

  if (showAll) {
    headers.forEach((h, index) => {
      if (used.has(index)) return
      mapped.push({ key: h, label: h, index, hidden: false })
    })
  }

  return mapped.filter((c) => !c.hidden)
}

export function hasColumnMap(path: string): boolean {
  return Boolean(TABLE_COLUMN_MAPS[tableBasename(path).toLowerCase()])
}
