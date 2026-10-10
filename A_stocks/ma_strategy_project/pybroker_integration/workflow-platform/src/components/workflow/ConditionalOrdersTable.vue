<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { copyTextToClipboard } from '@/api/tableCopy'
import { trackEvent } from '@/api/events'
import { useQuotaStore } from '@/stores/quota'
import {
  CONDITIONAL_ORDER_HEADERS,
  buildConditionalOrders,
  conditionalOrdersToCopyText,
  conditionalOrdersToCsv,
} from '@/data/conditionalOrders'

const props = defineProps<{
  headers: string[]
  rows: string[][]
  truncated?: boolean
}>()

const quota = useQuotaStore()
const router = useRouter()
const copyFlash = ref('')
let copyFlashTimer: ReturnType<typeof setTimeout> | null = null

const built = computed(() => buildConditionalOrders(props.headers, props.rows))

function flashCopied() {
  copyFlash.value = '已复制'
  if (copyFlashTimer) clearTimeout(copyFlashTimer)
  copyFlashTimer = setTimeout(() => {
    copyFlash.value = ''
  }, 1600)
}

function gateExport(): boolean {
  const gate = quota.assertCanExport()
  if (!gate.ok) {
    alert(gate.reason)
    void router.push('/billing/plans')
    return false
  }
  return true
}

async function onCopy() {
  if (!gateExport()) return
  const text = conditionalOrdersToCopyText(built.value.orders)
  if (!text.trim()) {
    alert('条件单无内容可复制。')
    return
  }
  const ok = await copyTextToClipboard(text)
  if (!ok) {
    alert('复制失败，请手动选中表格复制。')
    return
  }
  trackEvent('export_report', { kind: 'conditional_orders_copy' })
  flashCopied()
}

function onDownload() {
  if (!gateExport()) return
  const csv = conditionalOrdersToCsv(built.value.orders)
  const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'today_conditional_orders.csv'
  a.click()
  URL.revokeObjectURL(url)
  trackEvent('export_report', { kind: 'conditional_orders_csv' })
}
</script>

<template>
  <section class="space-y-2 border-t border-border/60 pt-3">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <div class="min-w-0">
        <p class="text-xs font-medium text-foreground">条件单</p>
        <p class="text-[11px] text-muted-foreground">
          反弹买入、回落卖出；幅度 0.3%。价格保留到分。
          <template v-if="built.skippedZeroDiff">
            高低价差为 0 的 {{ built.skippedZeroDiff }} 只未生成。
          </template>
          <template v-if="truncated">高低价表已截断，条件单只覆盖已加载行。</template>
        </p>
      </div>
      <div v-if="built.orders.length" class="flex flex-wrap items-center gap-2">
        <Button
          v-if="!quota.canExportReports()"
          size="sm"
          variant="outline"
          @click="router.push('/billing/plans')"
        >
          导出需 Pro
        </Button>
        <template v-else>
          <Button
            size="sm"
            variant="outline"
            class="border-rose-300 text-rose-700 hover:bg-rose-50"
            @click="onCopy"
          >
            {{ copyFlash || '复制全部' }}
          </Button>
          <Button size="sm" variant="outline" @click="onDownload">下载 CSV</Button>
        </template>
      </div>
    </div>

    <p v-if="!built.ready" class="text-xs text-amber-700">高低价表缺少档位列，无法生成条件单。</p>
    <p v-else-if="!built.orders.length" class="text-xs text-muted-foreground">
      高低价差为 0，未生成条件单。
    </p>
    <template v-else>
      <p class="font-mono text-[11px] text-muted-foreground">today_conditional_orders.csv</p>
      <p class="text-[11px] text-muted-foreground">
        共 {{ built.orders.length }} 行。可选中表格单元格复制，或使用上方「复制全部」。
      </p>
      <div class="max-h-[min(420px,50vh)] overflow-auto rounded-lg border">
        <Table>
          <TableHeader class="sticky top-0 z-[1] bg-muted/95 backdrop-blur">
            <TableRow>
              <TableHead
                v-for="h in CONDITIONAL_ORDER_HEADERS"
                :key="h"
                class="whitespace-nowrap bg-muted/95"
              >
                {{ h }}
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableRow v-for="(row, ri) in built.orders" :key="ri">
              <TableCell
                v-for="h in CONDITIONAL_ORDER_HEADERS"
                :key="h"
                class="whitespace-nowrap font-mono text-xs"
              >
                {{ row[h] }}
              </TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </template>
  </section>
</template>
