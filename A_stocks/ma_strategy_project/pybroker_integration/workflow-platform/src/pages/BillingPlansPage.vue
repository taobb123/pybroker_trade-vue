<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Check } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { useAuthStore } from '@/stores/auth'
import { PLAN_CATALOG, useBillingStore } from '@/stores/billing'
import {
  fetchPaymentChannels,
  type PaymentChannel,
  type PaymentChannelId,
} from '@/api/payment'
import { trackEvent } from '@/api/events'

const auth = useAuthStore()
const billing = useBillingStore()
const router = useRouter()
const message = ref('')
const busy = ref(false)
const payOpen = ref(false)
const channels = ref<PaymentChannel[]>([])
const selectedChannel = ref<PaymentChannelId>('mock')

const currentPlan = computed(() => auth.user?.plan ?? null)

onMounted(async () => {
  if (!auth.isAuthenticated) {
    void router.replace({ path: '/login', query: { redirect: '/billing/plans' } })
    return
  }
  channels.value = await fetchPaymentChannels()
  if (channels.value.length) {
    selectedChannel.value = channels.value[0]!.id
  }
})

async function choose(planId: (typeof PLAN_CATALOG)[number]['id'], purchasable: boolean) {
  message.value = ''
  if (!purchasable) {
    message.value = 'Team 档请联系客服开通（本期不提供自助购买）'
    return
  }
  if (!auth.user) {
    void router.push({ path: '/login', query: { redirect: '/billing/plans' } })
    return
  }
  if (currentPlan.value === planId) {
    message.value = '已是当前套餐'
    return
  }

  if (planId === 'free') {
    busy.value = true
    try {
      const res = await billing.switchToFree()
      message.value = res.ok ? '已切换为 Free' : res.reason || '操作失败'
    } finally {
      busy.value = false
    }
    return
  }

  if (planId === 'pro') {
    if (!channels.value.length) {
      channels.value = await fetchPaymentChannels()
    }
    trackEvent('click_upgrade', { plan: 'pro', source: 'billing_plans' })
    payOpen.value = true
  }
}

async function confirmPay() {
  message.value = ''
  busy.value = true
  try {
    const res = await billing.checkoutPro(selectedChannel.value)
    payOpen.value = false
    if (!res.ok) {
      message.value = res.reason || '支付失败'
      return
    }
    message.value = res.reason
      ? `支付完成（${res.reason}）`
      : '支付成功 · 已升级为 Pro，可在订单页查看'
  } finally {
    busy.value = false
  }
}

async function createPendingOnly() {
  message.value = ''
  busy.value = true
  try {
    const res = await billing.createProPending(selectedChannel.value)
    payOpen.value = false
    if (!res.ok) {
      message.value = res.reason || '下单失败'
      return
    }
    message.value = `已创建 pending 订单 ${res.orderId} · 可去管理后台「标记已付 / 取消」纠偏`
  } finally {
    busy.value = false
  }
}

async function simulateCallbackFail() {
  message.value = ''
  busy.value = true
  try {
    const res = await billing.createProThenFailCallback(selectedChannel.value)
    payOpen.value = false
    if (!res.ok) {
      message.value = res.reason || '模拟失败'
      return
    }
    message.value = res.reason || '已模拟回调失败'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div v-if="auth.user" class="space-y-5">
    <div class="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 class="text-base font-semibold tracking-tight">会员套餐</h2>
        <p class="text-xs text-muted-foreground">
          R5 支付闭环 · 渠道下单 / 回调生效 · 当前
          <span class="font-medium text-foreground">{{ auth.planLabel }}</span>
        </p>
      </div>
      <Button size="sm" variant="outline" @click="router.push('/billing/orders')">
        订单
      </Button>
    </div>

    <p v-if="message" class="text-xs text-muted-foreground">{{ message }}</p>

    <div class="grid gap-3 md:grid-cols-3">
      <Card
        v-for="plan in PLAN_CATALOG"
        :key="plan.id"
        class="shadow-none"
        :class="currentPlan === plan.id ? 'border-primary' : ''"
      >
        <CardHeader class="space-y-1">
          <div class="flex items-center justify-between gap-2">
            <CardTitle class="text-base">{{ plan.name }}</CardTitle>
            <Badge v-if="currentPlan === plan.id" variant="secondary">当前</Badge>
          </div>
          <CardDescription class="text-lg font-semibold text-foreground">
            {{ plan.priceLabel }}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul class="space-y-2 text-sm text-muted-foreground">
            <li v-for="f in plan.features" :key="f" class="flex items-start gap-2">
              <Check class="mt-0.5 size-3.5 shrink-0 text-foreground" />
              <span>{{ f }}</span>
            </li>
          </ul>
        </CardContent>
        <CardFooter>
          <Button
            class="w-full"
            :variant="plan.purchasable ? (currentPlan === plan.id ? 'outline' : 'default') : 'secondary'"
            :disabled="busy || currentPlan === plan.id"
            @click="choose(plan.id, plan.purchasable)"
          >
            {{ currentPlan === plan.id ? '当前方案' : plan.cta }}
          </Button>
        </CardFooter>
      </Card>
    </div>

    <p class="text-xs text-muted-foreground">
      微信 / 支付宝已接「下单→回调」形状；未配置商户密钥时为模拟确认。Stripe 预留。
    </p>

    <Sheet :open="payOpen" @update:open="payOpen = $event">
      <SheetContent class="sm:max-w-md">
        <SheetHeader>
          <SheetTitle>选择支付方式</SheetTitle>
          <SheetDescription>
            Pro ¥{{ PLAN_CATALOG.find((p) => p.id === 'pro')?.amountYuan ?? 39 }} / 30 天 ·
            确认后写入服务端订单并由回调生效权益
          </SheetDescription>
        </SheetHeader>

        <div class="space-y-2 px-4 py-2">
          <button
            v-for="ch in channels"
            :key="ch.id"
            type="button"
            class="flex w-full flex-col items-start gap-0.5 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors"
            :class="selectedChannel === ch.id ? 'border-primary bg-muted/40' : 'hover:bg-muted/30'"
            @click="selectedChannel = ch.id"
          >
            <span class="font-medium">{{ ch.label }}</span>
            <span class="text-xs text-muted-foreground">{{ ch.hint }}</span>
          </button>
        </div>

        <SheetFooter class="flex-col gap-2 sm:flex-col">
          <Button class="w-full" :disabled="busy" @click="confirmPay">
            {{ busy ? '处理中…' : '确认支付（模拟成功）' }}
          </Button>
          <Button class="w-full" variant="secondary" :disabled="busy" @click="createPendingOnly">
            仅下单（留 pending）
          </Button>
          <Button class="w-full" variant="outline" :disabled="busy" @click="simulateCallbackFail">
            模拟回调失败（→ failed）
          </Button>
          <Button class="w-full" variant="ghost" :disabled="busy" @click="payOpen = false">
            关闭
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  </div>
</template>
