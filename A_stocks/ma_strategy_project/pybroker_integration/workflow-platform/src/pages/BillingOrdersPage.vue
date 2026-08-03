<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { PLAN_LABEL, useAuthStore } from '@/stores/auth'
import { useBillingStore, type OrderStatus } from '@/stores/billing'

const auth = useAuthStore()
const billing = useBillingStore()
const router = useRouter()

onMounted(async () => {
  if (!auth.isAuthenticated) {
    void router.replace({ path: '/login', query: { redirect: '/billing/orders' } })
    return
  }
  await billing.refreshOrders()
})

function formatTime(iso: string) {
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}

function statusLabel(s: OrderStatus) {
  if (s === 'paid') return '已支付'
  if (s === 'pending') return '待支付'
  if (s === 'failed') return '支付失败'
  return '已取消'
}

function statusVariant(s: OrderStatus): 'secondary' | 'outline' | 'destructive' {
  if (s === 'paid') return 'secondary'
  if (s === 'cancelled' || s === 'failed') return 'destructive'
  return 'outline'
}
</script>

<template>
  <div v-if="auth.user" class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold tracking-tight">订单</h2>
        <p class="text-xs text-muted-foreground">
          服务端订单 · 支付成功写入会员 · 发票下载下期
        </p>
      </div>
      <Button size="sm" variant="outline" @click="router.push('/billing/plans')">
        套餐
      </Button>
    </div>

    <div v-if="!billing.sortedOrders.length" class="rounded-lg border border-dashed p-8 text-center">
      <p class="text-sm text-muted-foreground">暂无订单</p>
      <Button class="mt-3" size="sm" @click="router.push('/billing/plans')">
        去选择套餐
      </Button>
    </div>

    <div v-else class="overflow-x-auto rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>订单号</TableHead>
            <TableHead>套餐</TableHead>
            <TableHead>渠道</TableHead>
            <TableHead>金额</TableHead>
            <TableHead>状态</TableHead>
            <TableHead>支付时间</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-for="o in billing.sortedOrders" :key="o.id">
            <TableCell class="font-mono text-xs">{{ o.id }}</TableCell>
            <TableCell>{{ PLAN_LABEL[o.plan] }}</TableCell>
            <TableCell class="text-xs text-muted-foreground">{{ o.channel }}</TableCell>
            <TableCell>¥{{ o.amountYuan }}</TableCell>
            <TableCell>
              <Badge :variant="statusVariant(o.status)">{{ statusLabel(o.status) }}</Badge>
            </TableCell>
            <TableCell class="text-xs text-muted-foreground">{{ formatTime(o.paidAt) }}</TableCell>
          </TableRow>
        </TableBody>
      </Table>
    </div>
  </div>
</template>
