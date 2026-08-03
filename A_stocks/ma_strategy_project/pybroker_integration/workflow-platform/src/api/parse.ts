export type RankRow = {
  rank: number
  symbol: string
  name?: string
  roc_20?: number
  weight?: number
  [key: string]: string | number | undefined
}

export type ParsedReport = {
  rows: RankRow[]
  numericKeys: string[]
  chartKey: string | null
}

/** 从日志中提取最后一个 JSON 数组（对象行） */
export function extractJsonArray(log: string): unknown[] | null {
  const text = log.trim()
  if (!text) return null

  // 优先匹配独立 JSON 数组块
  const blocks = text.match(/\[[\s\S]*?\]/g)
  if (!blocks?.length) return null

  for (let i = blocks.length - 1; i >= 0; i--) {
    try {
      const parsed = JSON.parse(blocks[i]!) as unknown
      if (Array.isArray(parsed) && parsed.length && typeof parsed[0] === 'object' && parsed[0]) {
        return parsed
      }
    } catch {
      /* try previous block */
    }
  }
  return null
}

export function parseReportFromLog(log: string): ParsedReport {
  const arr = extractJsonArray(log)
  if (!arr) {
    return { rows: [], numericKeys: [], chartKey: null }
  }

  const rows: RankRow[] = arr.map((item, idx) => {
    const o = item as Record<string, unknown>
    const rank = Number(o.rank ?? idx + 1)
    const symbol = String(o.symbol ?? o.code ?? o.ticker ?? '')
    const name = o.name != null ? String(o.name) : undefined
    const row: RankRow = { rank, symbol, name }
    for (const [k, v] of Object.entries(o)) {
      if (k === 'rank' || k === 'symbol' || k === 'name' || k === 'code' || k === 'ticker') continue
      if (typeof v === 'number') row[k] = v
      else if (typeof v === 'string' && v.trim() !== '' && !Number.isNaN(Number(v))) row[k] = Number(v)
      else if (typeof v === 'string') row[k] = v
    }
    return row
  })

  const numericKeys = new Set<string>()
  for (const row of rows) {
    for (const [k, v] of Object.entries(row)) {
      if (k === 'rank' || k === 'symbol' || k === 'name') continue
      if (typeof v === 'number') numericKeys.add(k)
    }
  }

  const keys = [...numericKeys]
  const preferred = ['roc_20', 'weight', 'score', 'value', 'pct']
  const chartKey = preferred.find((k) => keys.includes(k)) ?? keys[0] ?? null

  return { rows, numericKeys: keys, chartKey }
}

export function formatTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

/** 耗时展示：≤60s 用秒；超过 60s 改用分钟（保留 1 位小数） */
export function formatDurationMs(ms: number): string {
  const sec = Math.max(0, Number(ms) || 0) / 1000
  if (sec > 60) return `${(sec / 60).toFixed(1)}m`
  return `${sec.toFixed(1)}s`
}
