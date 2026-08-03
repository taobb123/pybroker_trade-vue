import { computed } from 'vue'
import { defineStore } from 'pinia'
import { loadRunHistory } from '@/api/history'

export interface UsageKpi {
  todayVisits: number
  yesterdayVisits: number
  todayDeltaPct: number
  onlineUsers: number
  workflowRuns: number
}

export interface TrendPoint {
  date: string
  visits: number
}

export interface TopItem {
  name: string
  value: number
}

function dayKey(d: Date) {
  return d.toISOString().slice(0, 10)
}

/** 稳定假数据：按日期种子，刷新不变 */
function seededVisits(dateStr: string, base = 800) {
  let h = 0
  for (let i = 0; i < dateStr.length; i++) h = (h * 31 + dateStr.charCodeAt(i)) >>> 0
  return base + (h % 420)
}

function buildTrend(days = 30): TrendPoint[] {
  const out: TrendPoint[] = []
  const now = new Date()
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(now)
    d.setHours(12, 0, 0, 0)
    d.setDate(d.getDate() - i)
    const key = dayKey(d)
    out.push({ date: key, visits: seededVisits(key) })
  }
  return out
}

function countBy<T>(rows: T[], keyFn: (r: T) => string): TopItem[] {
  const map = new Map<string, number>()
  for (const r of rows) {
    const k = keyFn(r) || '—'
    map.set(k, (map.get(k) || 0) + 1)
  }
  return [...map.entries()]
    .map(([name, value]) => ({ name, value }))
    .sort((a, b) => b.value - a.value)
    .slice(0, 5)
}

export const useUsageStore = defineStore('usage', () => {
  const trend = computed(() => buildTrend(30))

  const kpi = computed<UsageKpi>(() => {
    const points = trend.value
    const today = points[points.length - 1]?.visits ?? 0
    const yesterday = points[points.length - 2]?.visits ?? 0
    const delta = yesterday ? Math.round(((today - yesterday) / yesterday) * 100) : 0
    const runs = loadRunHistory()
    return {
      todayVisits: today,
      yesterdayVisits: yesterday,
      todayDeltaPct: delta,
      onlineUsers: 8 + (today % 12),
      workflowRuns: runs.length,
    }
  })

  const topWorkflows = computed(() => {
    const runs = loadRunHistory()
    const real = countBy(runs, (r) => r.stepId)
    if (real.length) return real
    return [
      { name: 'market_temperature', value: 12 },
      { name: 'pattern_entry', value: 9 },
      { name: 'vp_six_combo', value: 7 },
    ]
  })

  const topStrategies = computed(() => {
    const runs = loadRunHistory().filter((r) => r.status === 'success')
    const real = countBy(runs, (r) => r.stepId)
    if (real.length) return real
    return [
      { name: 'ROC20', value: 6 },
      { name: '形态建仓', value: 5 },
      { name: '市场温度', value: 4 },
    ]
  })

  const topApis = computed<TopItem[]>(() => [
    { name: 'POST /api/workflow/run', value: Math.max(kpi.value.workflowRuns, 18) },
    { name: 'GET /api/workflow/steps', value: 42 },
    { name: 'GET /api/workspace/table', value: 31 },
    { name: 'GET /api/workspace/file', value: 19 },
  ])

  const topUsers = computed<TopItem[]>(() => [
    { name: 'demo@workflow.local', value: Math.max(kpi.value.workflowRuns, 11) },
    { name: 'research@local', value: 8 },
    { name: 'guest', value: 5 },
  ])

  return {
    kpi,
    trend,
    topWorkflows,
    topStrategies,
    topApis,
    topUsers,
  }
})
