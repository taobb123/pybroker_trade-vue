<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/auth'
import { useQuotaStore } from '@/stores/quota'

const auth = useAuthStore()
const quota = useQuotaStore()
const router = useRouter()
const route = useRoute()
const mode = ref<'login' | 'register'>('login')
const busy = ref(false)
const error = ref('')

const form = reactive({
  email: 'demo@workflow.local',
  password: 'demo1234',
  nickname: '',
  phone: '',
})

const redirectTo = computed(() => {
  const q = route.query.redirect
  return typeof q === 'string' && q.startsWith('/') ? q : '/'
})

async function submit() {
  error.value = ''
  busy.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(form.email, form.password)
    } else {
      await auth.register({
        email: form.email,
        password: form.password,
        nickname: form.nickname || undefined,
        phone: form.phone || undefined,
      })
    }
    await quota.refresh()
    if (!auth.user?.onboardingDone) {
      // 不把默认「/」带进引导，完成引导后走推荐策略
      const q =
        redirectTo.value && redirectTo.value !== '/'
          ? { redirect: redirectTo.value }
          : undefined
      void router.replace({ path: '/onboarding', query: q })
      return
    }
    void router.replace(redirectTo.value)
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="flex min-h-svh items-center justify-center bg-background p-6">
    <Card class="w-full max-w-sm border-border/80 shadow-none">
      <CardHeader class="space-y-1">
        <CardTitle class="text-xl tracking-tight">
          {{ mode === 'login' ? '登录' : '注册' }}
        </CardTitle>
        <CardDescription>
          M3 引导 · 服务端用户/会员 · 演示 demo@workflow.local / demo1234
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-4">
        <form class="space-y-3" @submit.prevent="submit">
          <div class="space-y-1.5">
            <Label for="email">邮箱</Label>
            <Input
              id="email"
              v-model="form.email"
              type="email"
              autocomplete="username"
              required
            />
          </div>
          <div class="space-y-1.5">
            <Label for="password">密码</Label>
            <Input
              id="password"
              v-model="form.password"
              type="password"
              autocomplete="current-password"
              required
              minlength="6"
            />
          </div>
          <template v-if="mode === 'register'">
            <div class="space-y-1.5">
              <Label for="nickname">昵称（可选）</Label>
              <Input id="nickname" v-model="form.nickname" />
            </div>
            <div class="space-y-1.5">
              <Label for="phone">手机号（可选）</Label>
              <Input id="phone" v-model="form.phone" type="tel" />
            </div>
          </template>
          <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
          <Button type="submit" class="w-full" :disabled="busy">
            {{ busy ? '请稍候…' : mode === 'login' ? '登录' : '注册并登录' }}
          </Button>
        </form>

        <Button
          variant="ghost"
          class="w-full"
          type="button"
          @click="mode = mode === 'login' ? 'register' : 'login'"
        >
          {{ mode === 'login' ? '没有账号？注册' : '已有账号？登录' }}
        </Button>
      </CardContent>
    </Card>
  </div>
</template>
