<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ChevronsUpDown, CreditCard, LogOut, Settings, Shield, UserRound } from '@lucide/vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const { isMobile, setOpenMobile } = useSidebar()

function go(path: string) {
  if (isMobile.value) setOpenMobile(false)
  void router.push(path)
}

function logout() {
  auth.logout()
  if (isMobile.value) setOpenMobile(false)
  void router.push('/login')
}
</script>

<template>
  <SidebarMenu>
    <SidebarMenuItem>
      <template v-if="auth.user">
        <DropdownMenu>
          <DropdownMenuTrigger as-child>
            <SidebarMenuButton
              size="lg"
              class="data-[state=open]:bg-sidebar-accent data-[state=open]:text-sidebar-accent-foreground"
            >
              <div
                class="flex size-8 items-center justify-center rounded-lg bg-sidebar-primary text-xs font-semibold text-sidebar-primary-foreground"
              >
                {{ auth.user.avatarText }}
              </div>
              <div class="grid min-w-0 flex-1 text-left text-sm leading-tight">
                <span class="truncate font-medium">{{ auth.user.nickname }}</span>
                <span class="truncate text-xs text-muted-foreground">{{ auth.user.email }}</span>
              </div>
              <ChevronsUpDown class="ml-auto size-4" />
            </SidebarMenuButton>
          </DropdownMenuTrigger>
          <DropdownMenuContent
            class="w-(--reka-dropdown-menu-trigger-width) min-w-56 rounded-lg"
            side="top"
            align="start"
            :side-offset="4"
          >
            <DropdownMenuLabel class="p-0 font-normal">
              <div class="flex items-center gap-2 px-1 py-1.5 text-left text-sm">
                <div
                  class="flex size-8 items-center justify-center rounded-lg bg-primary text-xs font-semibold text-primary-foreground"
                >
                  {{ auth.user.avatarText }}
                </div>
                <div class="grid min-w-0 flex-1 text-left text-sm leading-tight">
                  <span class="truncate font-medium">{{ auth.user.nickname }}</span>
                  <span class="truncate text-xs text-muted-foreground">
                    {{ auth.planLabel }} · {{ auth.user.email }}
                  </span>
                </div>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem @click="go('/account')">
              <Settings />
              用户中心
            </DropdownMenuItem>
            <DropdownMenuItem @click="go('/billing/plans')">
              <CreditCard />
              会员 / 账单
            </DropdownMenuItem>
            <DropdownMenuItem v-if="auth.user.role === 'admin'" @click="go('/admin')">
              <Shield />
              管理后台
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem variant="destructive" @click="logout">
              <LogOut />
              退出登录
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </template>

      <SidebarMenuButton v-else size="lg" @click="go('/login')">
        <div
          class="flex size-8 items-center justify-center rounded-lg border border-dashed text-muted-foreground"
        >
          <UserRound class="size-4" />
        </div>
        <div class="grid min-w-0 flex-1 text-left text-sm leading-tight">
          <span class="truncate font-medium">未登录</span>
          <span class="truncate text-xs text-muted-foreground">登录 / 注册</span>
        </div>
      </SidebarMenuButton>
    </SidebarMenuItem>
  </SidebarMenu>
</template>
