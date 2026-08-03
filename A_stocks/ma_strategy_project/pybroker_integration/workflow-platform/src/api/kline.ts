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
    values.push({
      // ECharts: [open, close, low, high] — 用区间两端画实体，颜色由 itemStyle 强制
      value: [lo, hi, lo, hi],
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
        const o = num(chart.opens[idx])
        const c = num(chart.closes[idx])
        const h = num(chart.highs[idx])
        const l = num(chart.lows[idx])
        const fut = chart.is_future?.[idx] ? '（预测日）' : ''
        return [
          `${chart.dates[idx] || p?.name || ''}${fut}`,
          `高: ${Number.isFinite(h) ? h.toFixed(2) : '-'}`,
          `低: ${Number.isFinite(l) ? l.toFixed(2) : '-'}`,
          `开: ${Number.isFinite(o) ? o.toFixed(2) : '-'}`,
          `收: ${Number.isFinite(c) ? c.toFixed(2) : '-'}`,
        ].join('<br/>')
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
