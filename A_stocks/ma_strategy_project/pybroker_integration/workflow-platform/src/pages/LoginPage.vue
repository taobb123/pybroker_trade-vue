<script setup lang="ts">
import { computed, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const form = reactive({
  email: 'demo@workflow.local',
  phone: '',
})

const redirectTo = computed(() => {
  const q = route.query.redirect
  return typeof q === 'string' && q.startsWith('/') ? q : '/'
})

function submit() {
  auth.mockLogin({
    email: form.email,
    phone: form.phone,
  })
  void router.replace(redirectTo.value)
}

function oneClickDemo() {
  auth.mockLogin({
    email: 'demo@workflow.local',
    phone: '13800000000',
    nickname: '演示用户',
  })
  void router.replace(redirectTo.value)
}
</script>

<template>
  <div class="flex min-h-svh items-center justify-center bg-background p-6">
    <Card class="w-full max-w-sm border-border/80 shadow-none">
      <CardHeader class="space-y-1">
        <CardTitle class="text-xl tracking-tight">登录</CardTitle>
        <CardDescription>
          样板模块 · Mock 登录（不接真实 Auth 内核）
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
              placeholder="name@example.com"
            />
          </div>
          <div class="space-y-1.5">
            <Label for="phone">手机号（可选）</Label>
            <Input
              id="phone"
              v-model="form.phone"
              type="tel"
              autocomplete="tel"
              placeholder="国内主路径预留"
            />
          </div>
          <Button type="submit" class="w-full">
            继续
          </Button>
        </form>

        <div class="relative py-1">
          <div class="absolute inset-0 flex items-center">
            <span class="w-full border-t" />
          </div>
          <div class="relative flex justify-center text-xs uppercase">
            <span class="bg-card px-2 text-muted-foreground">或</span>
          </div>
        </div>

        <Button variant="outline" class="w-full" type="button" @click="oneClickDemo">
          一键演示登录
        </Button>

        <p class="text-center text-xs text-muted-foreground">
          微信 / Google / GitHub 登录 · 下期对接托管 Auth
        </p>
      </CardContent>
    </Card>
  </div>
</template>
