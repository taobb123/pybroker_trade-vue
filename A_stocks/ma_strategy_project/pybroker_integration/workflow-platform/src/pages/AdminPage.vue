<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuthStore, PLAN_LABEL, type PlanTier } from '@/stores/auth'
import {
  adminAddBonus,
  adminListOrders,
  adminListUsers,
  adminOrderAction,
  adminResetOnboarding,
  adminSetMembership,
  adminSetStatus,
  type AdminUserRow,
} from '@/api/admin'
import type { ServerPaymentOrder } from '@/api/payment'

const auth = useAuthStore()
const router = useRouter()
const users = ref<AdminUserRow[]>([])
const orders = ref<ServerPaymentOrder[]>([])
const orderFilter = ref<'all' | 'pending' | 'paid' | 'cancelled' | 'failed'>('all')
const busy = ref(false)
const message = ref('')
const error = ref('')

async function loadUsers() {
  users.value = await adminListUsers()
}

async function loadOrders() {
  const status = orderFilter.value === 'all' ? undefined : orderFilter.value
  orders.value = await adminListOrders(status)
}

async function refresh() {
  error.value = ''
  busy.value = true
  try {
    await Promise.all([loadUsers(), loadOrders()])
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  if (!auth.isAuthenticated) {
    void router.replace({ path: '/login', query: { redirect: '/admin' } })
    return
  }
  if (auth.user?.role !== 'admin') {
    void router.replace('/')
    return
  }
  await refresh()
})

async function run(label: string, fn: () => Promise<void>) {
  message.value = ''
  error.value = ''
  busy.value = true
  try {
    await fn()
    message.value = label
    await refresh()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}

function setPlan(u: AdminUserRow, plan: PlanTier) {
  void run(`已将 ${u.email} 设为 ${PLAN_LABEL[plan]}`, () =>
    adminSetMembership(u.id, plan, plan === 'pro' ? 30 : 0),
  )
}

function toggleStatus(u: AdminUserRow) {
  const next = u.status === 'active' ? 'disabled' : 'active'
  void run(`已${next === 'active' ? '启用' : '禁用'} ${u.email}`, () =>
    adminSetStatus(u.id, next),
  )
}

function addBonus(u: AdminUserRow) {
  void run(`已给 ${u.email} +3 当日额度`, () => adminAddBonus(u.id, 3).then(() => undefined))
}

function resetOnboarding(u: AdminUserRow) {
  void run(`已重置 ${u.email} 引导`, () => adminResetOnboarding(u.id))
}

function orderAct(o: ServerPaymentOrder, action: 'mark_paid' | 'cancel') {
  void run(`订单 ${o.id} 已处理`, () => adminOrderAction(o.id, action).then(() => undefined))
}

function setOrderFilter(f: 'all' | 'pending' | 'paid' | 'cancelled' | 'failed') {
  orderFilter.value = f
  void loadOrders()
}

function canCorrectOrder(status: string) {
  return status === 'pending' || status === 'failed'
}

function formatTime(iso: string | null) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return iso
  }
}
</script>

<template>
  <div class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold tracking-tight">管理后台</h2>
        <p class="text-xs text-muted-foreground">
          M5 薄 Admin · 查人 / 改会员 / 加额度 / 订单纯纠偏
        </p>
      </div>
      <Button size="sm" variant="outline" :disabled="busy" @click="refresh">刷新</Button>
    </div>

    <p v-if="message" class="text-xs text-muted-foreground">{{ message }}</p>
    <p v-if="error" class="text-xs text-destructive">{{ error }}</p>

    <Tabs defaultValue="users">
      <TabsList>
        <TabsTrigger value="users">用户</TabsTrigger>
        <TabsTrigger value="orders">订单</TabsTrigger>
      </TabsList>

      <TabsContent value="users" class="mt-4">
        <Card class="shadow-none">
          <CardHeader class="pb-2">
            <CardTitle class="text-sm">用户列表</CardTitle>
            <CardDescription>邮箱 · 档位 · 状态 · 今日用量</CardDescription>
          </CardHeader>
          <CardContent class="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>邮箱</TableHead>
                  <TableHead>档位</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>今日 used</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-for="u in users" :key="u.id">
                  <TableCell>
                    <div class="text-sm">{{ u.email }}</div>
                    <div class="text-[11px] text-muted-foreground">
                      {{ u.nickname }} · {{ u.role }}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant="secondary">{{ PLAN_LABEL[u.plan as PlanTier] || u.plan }}</Badge>
                    <div v-if="u.expire_at" class="mt-1 text-[11px] text-muted-foreground">
                      {{ formatTime(u.expire_at) }}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge :variant="u.status === 'active' ? 'secondary' : 'destructive'">
                      {{ u.status }}
                    </Badge>
                  </TableCell>
                  <TableCell class="font-mono text-xs">
                    {{ u.today_used }}
                    <span class="text-muted-foreground">
                      / {{ u.daily_limit < 0 ? '∞' : u.daily_limit + u.today_bonus }}
                    </span>
                    <div v-if="u.today_bonus" class="text-[11px] text-muted-foreground">
                      bonus +{{ u.today_bonus }}
                    </div>
                  </TableCell>
                  <TableCell>
                    <div class="flex max-w-xs flex-wrap gap-1">
                      <Button size="sm" variant="outline" :disabled="busy" @click="setPlan(u, 'free')">
                        Free
                      </Button>
                      <Button size="sm" variant="outline" :disabled="busy" @click="setPlan(u, 'pro')">
                        Pro30
                      </Button>
                      <Button size="sm" variant="outline" :disabled="busy" @click="setPlan(u, 'team')">
                        Team
                      </Button>
                      <Button size="sm" variant="outline" :disabled="busy" @click="addBonus(u)">
                        +3
                      </Button>
                      <Button
                        size="sm"
                        variant="outline"
                        :disabled="busy || u.role === 'admin'"
                        @click="toggleStatus(u)"
                      >
                        {{ u.status === 'active' ? '禁用' : '启用' }}
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        :disabled="busy"
                        @click="resetOnboarding(u)"
                      >
                        重置引导
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>

      <TabsContent value="orders" class="mt-4 space-y-3">
        <div class="flex flex-wrap gap-2">
          <Button
            v-for="f in (['all', 'pending', 'paid', 'failed', 'cancelled'] as const)"
            :key="f"
            size="sm"
            :variant="orderFilter === f ? 'default' : 'outline'"
            :disabled="busy"
            @click="setOrderFilter(f)"
          >
            {{ f === 'all' ? '全部' : f }}
          </Button>
        </div>
        <Card class="shadow-none">
          <CardHeader class="pb-2">
            <CardTitle class="text-sm">订单</CardTitle>
            <CardDescription>
              pending / failed 可手工 mark paid 或 cancel（渠道失败≠用户取消）
            </CardDescription>
          </CardHeader>
          <CardContent class="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>订单号</TableHead>
                  <TableHead>用户</TableHead>
                  <TableHead>套餐</TableHead>
                  <TableHead>金额</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead>时间</TableHead>
                  <TableHead>操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                <TableRow v-if="!orders.length">
                  <TableCell colspan="7" class="text-center text-sm text-muted-foreground">
                    暂无订单
                  </TableCell>
                </TableRow>
                <TableRow v-for="o in orders" :key="o.id">
                  <TableCell class="font-mono text-xs">{{ o.id }}</TableCell>
                  <TableCell class="font-mono text-[11px]">{{ o.user_id }}</TableCell>
                  <TableCell>{{ o.plan }}</TableCell>
                  <TableCell>¥{{ o.amount_yuan }}</TableCell>
                  <TableCell>
                    <Badge variant="secondary">{{ o.status }}</Badge>
                  </TableCell>
                  <TableCell class="text-xs text-muted-foreground">
                    {{ formatTime(o.paid_at || o.created_at) }}
                  </TableCell>
                  <TableCell>
                    <div class="flex flex-wrap gap-1">
                      <Button
                        v-if="canCorrectOrder(o.status)"
                        size="sm"
                        variant="outline"
                        :disabled="busy"
                        @click="orderAct(o, 'mark_paid')"
                      >
                        标记已付
                      </Button>
                      <Button
                        v-if="canCorrectOrder(o.status)"
                        size="sm"
                        variant="ghost"
                        :disabled="busy"
                        @click="orderAct(o, 'cancel')"
                      >
                        取消
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </TabsContent>
    </Tabs>
  </div>
</template>
