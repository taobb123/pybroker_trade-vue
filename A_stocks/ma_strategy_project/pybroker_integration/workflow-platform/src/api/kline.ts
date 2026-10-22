export type PredictionSignal = {
  stock_name?: string
  real_sequence?: string
  pred_sequence?: string
  same_count?: number
  t1_pred_direction?: string
  t1_pred_direction_label?: string
  predicted_direction?: string
  predicted_direction_label?: string
  regime?: string
  regime_label?: string
}

export type PredictionChart = {
  symbol: string
  symbol_name?: string
  history_days?: number
  future_days?: number
  dates: string[]
  opens: number[]
  highs: number[]
  lows: number[]
  closes: number[]
  /** 当天实际最高。未来预测日为空，影线不使用。 */
  actual_highs?: Array<number | null>
  /** 当天实际最低。未来预测日为空，影线不使用。 */
  actual_lows?: Array<number | null>
  is_future?: boolean[]
  model_label?: string
  pred_dir?: string
  signal?: PredictionSignal | string
}

export type PredictionKlinePayload = {
  chart_count?: number
  history_days?: number
  model_label?: string
  generated_at?: string
  charts: PredictionChart[]
}

const COLOR_UP = '#f85149'
const COLOR_DOWN = '#3fb950'

export function isPredictionKlinePath(path: string): boolean {
  const p = path.replace(/\\/g, '/').toLowerCase()
  return p.endsWith('prediction_kline_compare.json') || /prediction_kline.*\.json$/.test(p)
}

export function parsePredictionKlineJson(content: string): PredictionKlinePayload | null {
  try {
    const data = JSON.parse(content) as PredictionKlinePayload
    if (!data || !Array.isArray(data.charts) || !data.charts.length) return null
    return data
  } catch {
    return null
  }
}

export function getChartSignal(chart: PredictionChart): PredictionSignal | null {
  if (!chart.signal || typeof chart.signal === 'string') return null
  return chart.signal
}

function num(v: unknown, fallback = NaN): number {
  const n = Number(v)
  return Number.isFinite(n) ? n : fallback
}

function round2(n: number): number {
  return Math.round(n * 100) / 100
}

function actualAt(list: Array<number | null> | undefined, index: number): number | null {
  if (!list || index < 0 || index >= list.length) return null
  const raw = list[index]
  if (raw == null || raw === '') return null
  const n = num(raw)
  return Number.isFinite(n) ? n : null
}

/**
 * 实体是预测高低。上影线尖端是实际高，下影线尖端是实际低。
 * 实际高不高于预测高时没有上影；实际低不低于预测低时没有下影。
 * 比较先保留两位，与近三日表一致。
 */
function wickHigh(predHi: number, actualHi: number | null, future: boolean): number {
  if (future || actualHi == null) return predHi
  return round2(actualHi) > round2(predHi) ? actualHi : predHi
}

function wickLow(predLo: number, actualLo: number | null, future: boolean): number {
  if (future || actualLo == null) return predLo
  return round2(actualLo) < round2(predLo) ? actualLo : predLo
}

/**
 * 与旧版一致：综合高低模型 open≈low、close≈high，不能用 open/close 判断涨跌。
 * 用 (high+low)/2 相对前一根 mid：升=红，降=绿。
 */
export function toCandlestickOption(chart: PredictionChart) {
  const n = chart.dates?.length ?? 0
  const categories = (chart.dates ?? []).map((d, i) => {
    const s = String(d)
    const short = s.length >= 10 ? s.slice(5) : s
    return chart.is_future?.[i] ? `${short}*` : short
  })

  const values: Array<{
    value: number[]
    itemStyle: {
      color: string
      color0: string
      borderColor: string
      borderColor0: string
      opacity?: number
    }
  }> = []

  let prevMid: number | null = null
  for (let i = 0; i < n; i++) {
    const o = num(chart.opens[i])
    const c = num(chart.closes[i])
    const l = num(chart.lows[i], Number.isFinite(o) ? o : c)
    const h = num(chart.highs[i], Number.isFinite(c) ? c : o)
    const lo = Number.isFinite(l) ? l : Math.min(o, c)
    const hi = Number.isFinite(h) ? h : Math.max(o, c)
    const mid = (hi + lo) / 2
    const up = prevMid == null ? true : mid >= prevMid
    const color = up ? COLOR_UP : COLOR_DOWN
    const future = Boolean(chart.is_future?.[i])
    const top = wickHigh(hi, actualAt(chart.actual_highs, i), future)
    const bot = wickLow(lo, actualAt(chart.actual_lows, i), future)
    values.push({
      // ECharts: [open, close, low, high]。实体是预测高低，上影到实际高，下影到实际低。
      value: [lo, hi, bot, top],
      itemStyle: {
        color,
        color0: color,
        borderColor: color,
        borderColor0: color,
        opacity: future ? 0.55 : 0.9,
      },
    })
    if (Number.isFinite(mid)) prevMid = mid
  }

  return {
    animation: false,
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params]
        const p = list[0] as { dataIndex?: number; name?: string } | undefined
        const idx = p?.dataIndex ?? 0
        const h = num(chart.highs[idx])
        const l = num(chart.lows[idx])
        const future = Boolean(chart.is_future?.[idx])
        const ah = actualAt(chart.actual_highs, idx)
        const al = actualAt(chart.actual_lows, idx)
        const lines = [
          `${chart.dates[idx] || p?.name || ''}${future ? '（预测日）' : ''}`,
          `预测高: ${Number.isFinite(h) ? h.toFixed(2) : '-'}`,
          `预测低: ${Number.isFinite(l) ? l.toFixed(2) : '-'}`,
        ]
        if (!future && ah != null && al != null && Number.isFinite(h) && Number.isFinite(l)) {
          const highDelta = round2(round2(h) - round2(ah))
          const lowDelta = round2(round2(al) - round2(l))
          lines.push(
            `实际高: ${ah.toFixed(2)}`,
            `高点差值: ${highDelta.toFixed(2)}${highDelta < 0 ? '（实际高更高）' : ''}`,
            `实际低: ${al.toFixed(2)}`,
            `低点差值: ${lowDelta.toFixed(2)}${lowDelta > 0 ? '（实际低更高）' : ''}`,
          )
        }
        return lines.join('<br/>')
      },
    },
    grid: { left: 52, right: 16, top: 16, bottom: 36, containLabel: false },
    xAxis: {
      type: 'category',
      data: categories,
      boundaryGap: true,
      axisLine: { lineStyle: { color: '#e4e4e7' } },
      axisLabel: {
        color: '#71717a',
        fontSize: 10,
        hideOverlap: true,
        formatter: (v: string) => {
          const s = String(v)
          return s.endsWith('*') ? `{fut|${s}}` : s
        },
        rich: {
          fut: { color: '#d97706', fontWeight: 700, fontSize: 10 },
        },
      },
    },
    yAxis: {
      type: 'value',
      scale: true,
      axisLabel: { color: '#71717a', fontSize: 10 },
      splitLine: { lineStyle: { color: '#f4f4f5' } },
    },
    series: [
      {
        type: 'candlestick',
        name: 'kline',
        data: values,
        barMaxWidth: 12,
      },
    ],
  }
}

export function chartBlockTitle(chart: PredictionChart, historyDays: number): string {
  const sig = getChartSignal(chart)
  const name = sig?.stock_name || chart.symbol_name || chart.symbol || ''
  let title = `${name} · ${historyDays}+1 根`
  if (sig) {
    title += `（真实${sig.real_sequence || '?'} vs 预测${sig.pred_sequence || '?'} · 相同 ${sig.same_count ?? '?'}）`
  }
  return title
}

/** 报告页精简：仅名称 */
export function chartStockName(chart: PredictionChart): string {
  const sig = getChartSignal(chart)
  return sig?.stock_name || chart.symbol_name || chart.symbol || ''
}

/** 报告页精简：涨/跌文案 */
export function chartRiseFallLabel(chart: PredictionChart): string {
  const sig = getChartSignal(chart)
  const label = sig?.predicted_direction_label || ''
  if (label === '涨' || label === '跌') return label
  const dir = sig?.predicted_direction
  if (dir === 'up') return '涨'
  if (dir === 'down') return '跌'
  if (chart.pred_dir === 'up') return '涨'
  if (chart.pred_dir === 'down') return '跌'
  return label || '—'
}
