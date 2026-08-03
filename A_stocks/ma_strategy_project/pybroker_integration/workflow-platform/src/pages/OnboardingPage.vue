<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Check } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  ONBOARDING_BONUS_RUNS,
  ONBOARDING_PERSONAS,
  ONBOARDING_RECOMMENDED_STEP_ID,
  ONBOARDING_RECOMMENDED_TITLE,
  resolveOnboardingLanding,
  type OnboardingPersonaId,
} from '@/config/businessRules'
import { completeOnboarding } from '@/api/onboarding'
import { useAuthStore } from '@/stores/auth'
import { useQuotaStore } from '@/stores/quota'

const auth = useAuthStore()
const quota = useQuotaStore()
const router = useRouter()
const route = useRoute()

const step = ref(1)
const persona = ref<OnboardingPersonaId | null>(null)
const skippedPersona = ref(false)
const busy = ref(false)
const error = ref('')

const redirectAfter = computed(() => resolveOnboardingLanding(route.query.redirect))

function selectPersona(id: OnboardingPersonaId) {
  persona.value = id
  skippedPersona.value = false
}

function skipPersona() {
  persona.value = null
  skippedPersona.value = true
  error.value = ''
  step.value = 2
}

function nextFromPersona() {
  if (!persona.value && !skippedPersona.value) {
    error.value = '请选择身份，或点击跳过'
    return
  }
  error.value = ''
  step.value = 2
}

async function finish() {
  error.value = ''
  busy.value = true
  try {
    const res = await completeOnboarding({
      persona: skippedPersona.value ? null : persona.value,
      skipPersona: skippedPersona.value,
    })
    auth.applyServerUser(res.user)
    quota.applyServerQuota(res.quota)
    void router.replace(redirectAfter.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex min-h-svh items-center justify-center bg-background p-6">
    <Card class="w-full max-w-md border-border/80 shadow-none">
      <CardHeader class="space-y-1">
        <p class="text-xs text-muted-foreground">首次引导 · {{ step }} / 3</p>
        <CardTitle class="text-xl tracking-tight">
          <template v-if="step === 1">你主要想用平台做什么？</template>
          <template v-else-if="step === 2">推荐一条基础策略</template>
          <template v-else>领取体验次数</template>
        </CardTitle>
        <CardDescription>
          <template v-if="step === 1">选一个身份，便于后续推荐；也可跳过</template>
          <template v-else-if="step === 2">约 1 分钟跑通第一次价值</template>
          <template v-else>完成后进入工作台，可立即运行推荐策略</template>
        </CardDescription>
      </CardHeader>

      <CardContent class="space-y-4">
        <!-- Step 1 -->
        <div v-if="step === 1" class="space-y-2">
          <button
            v-for="p in ONBOARDING_PERSONAS"
            :key="p.id"
            type="button"
            class="flex w-full flex-col items-start gap-0.5 rounded-lg border px-3 py-2.5 text-left text-sm transition-colors"
            :class="persona === p.id ? 'border-primary bg-muted/40' : 'hover:bg-muted/30'"
            @click="selectPersona(p.id)"
          >
            <span class="font-medium">{{ p.label }}</span>
            <span class="text-xs text-muted-foreground">{{ p.hint }}</span>
          </button>
          <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
          <div class="flex gap-2 pt-2">
            <Button variant="ghost" class="flex-1" type="button" @click="skipPersona">跳过</Button>
            <Button class="flex-1" type="button" @click="nextFromPersona">下一步</Button>
          </div>
        </div>

        <!-- Step 2 -->
        <div v-else-if="step === 2" class="space-y-3">
          <div class="rounded-lg border px-3 py-3">
            <p class="text-sm font-medium">{{ ONBOARDING_RECOMMENDED_TITLE }}</p>
            <p class="mt-1 text-xs text-muted-foreground">
              步骤 ID：{{ ONBOARDING_RECOMMENDED_STEP_ID }} · 基础策略 · Free 可用
            </p>
          </div>
          <ul class="space-y-1.5 text-sm text-muted-foreground">
            <li class="flex items-start gap-2">
              <Check class="mt-0.5 size-3.5 shrink-0 text-foreground" />
              完成后会跳到该工作流卡片
            </li>
            <li class="flex items-start gap-2">
              <Check class="mt-0.5 size-3.5 shrink-0 text-foreground" />
              发起运行会计入今日配额
            </li>
          </ul>
          <div class="flex gap-2 pt-1">
            <Button variant="outline" class="flex-1" type="button" @click="step = 1">上一步</Button>
            <Button class="flex-1" type="button" @click="step = 3">下一步</Button>
          </div>
        </div>

        <!-- Step 3 -->
        <div v-else class="space-y-3">
          <div class="rounded-lg border bg-muted/30 px-3 py-3 text-sm">
            <p>
              今日额外赠送
              <span class="font-semibold text-foreground">+{{ ONBOARDING_BONUS_RUNS }}</span>
              次运行（仅首次引导）
            </p>
            <p class="mt-1 text-xs text-muted-foreground">与 Free 每日 10 次叠加，当日有效</p>
          </div>
          <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
          <div class="flex gap-2">
            <Button variant="outline" class="flex-1" type="button" :disabled="busy" @click="step = 2">
              上一步
            </Button>
            <Button class="flex-1" type="button" :disabled="busy" @click="finish">
              {{ busy ? '处理中…' : '完成并进入工作台' }}
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
