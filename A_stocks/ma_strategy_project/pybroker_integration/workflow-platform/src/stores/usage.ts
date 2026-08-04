import { computed } from 'vue'
import { defineStore } from 'pinia'
import { loadRunHistory } from '@/api/history'

export interface UsageKpi {
  workflowRuns: number
}

export interface TopItem {
  name: string
  value: number
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
  const kpi = computed<UsageKpi>(() => ({
    workflowRuns: loadRunHistory().length,
  }))

  const topWorkflows = computed(() => {
    const runs = loadRunHistory()
    return countBy(runs, (r) => r.stepId)
  })

  const topStrategies = computed(() => {
    const runs = loadRunHistory().filter((r) => r.status === 'success')
    return countBy(runs, (r) => r.stepId)
  })

  return {
    kpi,
    topWorkflows,
    topStrategies,
  }
})
