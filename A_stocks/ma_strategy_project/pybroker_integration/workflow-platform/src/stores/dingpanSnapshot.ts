import type { DingpanItem } from '@/api/dingpan'

const STORAGE_KEY = 'workflow-platform:dingpan-snapshot:v1'

function loadAll(): Record<string, DingpanItem> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, DingpanItem>
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeAll(items: Record<string, DingpanItem>) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items))
}

export function dingpanSnapshots(symbols: string[]): DingpanItem[] {
  const saved = loadAll()
  return symbols.map((symbol) => saved[symbol]).filter((item): item is DingpanItem => Boolean(item))
}

export function saveDingpanSnapshots(items: DingpanItem[]) {
  const saved = loadAll()
  for (const item of items) {
    if (!item.symbol) continue
    saved[item.symbol] = item
  }
  writeAll(saved)
}

export function dropDingpanSnapshot(symbol: string) {
  const saved = loadAll()
  if (!saved[symbol]) return
  delete saved[symbol]
  writeAll(saved)
}
