<script setup lang="ts">
import { onMounted, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Separator } from '@/components/ui/separator'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const form = reactive({
  nickname: '',
  email: '',
  phone: '',
})

function syncForm() {
  if (!auth.user) return
  form.nickname = auth.user.nickname
  form.email = auth.user.email
  form.phone = auth.user.phone
}

onMounted(() => {
  if (!auth.isAuthenticated) {
    void router.replace({ path: '/login', query: { redirect: '/account' } })
    return
  }
  syncForm()
})

watch(
  () => auth.user,
  () => syncForm(),
)

function save() {
  auth.updateProfile({
    nickname: form.nickname,
    email: form.email,
    phone: form.phone,
  })
}
</script>

<template>
  <div v-if="auth.user" class="space-y-5">
    <div>
      <h2 class="text-base font-semibold tracking-tight">用户中心</h2>
      <p class="text-xs text-muted-foreground">
        仅保留产品允许字段 · 头像 / 昵称 / 邮箱 / 手机 / 会员等级 / 邀请码
      </p>
    </div>

    <Card class="shadow-none">
      <CardHeader class="flex flex-row items-center gap-3 space-y-0">
        <div
          class="flex size-12 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground"
        >
          {{ auth.user.avatarText }}
        </div>
        <div class="min-w-0 flex-1">
          <CardTitle class="truncate text-base">{{ auth.user.nickname }}</CardTitle>
          <CardDescription class="truncate">{{ auth.user.email }}</CardDescription>
        </div>
        <Badge variant="secondary">{{ auth.planLabel }}</Badge>
      </CardHeader>
      <CardContent class="space-y-4">
        <div class="grid gap-3">
          <div class="space-y-1.5">
            <Label for="nickname">昵称</Label>
            <Input id="nickname" v-model="form.nickname" />
          </div>
          <div class="space-y-1.5">
            <Label for="acc-email">邮箱</Label>
            <Input id="acc-email" v-model="form.email" type="email" />
          </div>
          <div class="space-y-1.5">
            <Label for="acc-phone">手机号</Label>
            <Input id="acc-phone" v-model="form.phone" type="tel" />
          </div>
        </div>

        <Separator />

        <div class="grid gap-2 text-sm">
          <div class="flex items-center justify-between gap-3">
            <span class="text-muted-foreground">会员等级</span>
            <span class="font-medium">{{ auth.planLabel }}</span>
          </div>
          <div class="flex items-center justify-between gap-3">
            <span class="text-muted-foreground">邀请码</span>
            <span class="font-mono text-xs">{{ auth.user.inviteCode }}</span>
          </div>
        </div>

        <div class="flex flex-wrap gap-2 pt-1">
          <Button type="button" @click="save">保存</Button>
          <Button type="button" variant="outline" @click="router.push('/billing/plans')">
            会员套餐
          </Button>
          <Button type="button" variant="outline" @click="router.push('/billing/orders')">
            订单
          </Button>
        </div>
      </CardContent>
    </Card>
  </div>
</template>
