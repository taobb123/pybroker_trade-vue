<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Check } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { useAuthStore } from '@/stores/auth'
import { PLAN_CATALOG, useBillingStore } from '@/stores/billing'

const auth = useAuthStore()
const billing = useBillingStore()
const router = useRouter()
const message = ref('')
const busy = ref(false)

const currentPlan = computed(() => auth.user?.plan ?? null)

onMounted(() => {
  if (!auth.isAuthenticated) {
    void router.replace({ path: '/login', query: { redirect: '/billing/plans' } })
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

  busy.value = true
  try {
    const res = billing.mockCheckout(planId)
    if (!res.ok) {
      message.value = res.reason || '操作失败'
      return
    }
    message.value =
      planId === 'free'
        ? '已切换为 Free（演示）'
        : 'Mock 支付成功 · 已升级为 Pro，可在订单页查看'
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
          拼装式商业壳 · 支付为 Mock · 当前
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
      微信 / 支付宝 / Stripe 真通道 · 下期接入官方 SDK
    </p>
  </div>
</template>
