<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, RouterLink, RouterView } from 'vue-router'
import {
  LayoutDashboard,
  Workflow,
  History,
  FileBarChart2,
} from '@lucide/vue'
import {
  Sidebar,
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarInset,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarProvider,
  SidebarRail,
  SidebarTrigger,
} from '@/components/ui/sidebar'
import { Separator } from '@/components/ui/separator'
import BackToTop from '@/components/BackToTop.vue'

const route = useRoute()
const mainScroll = ref<HTMLElement | null>(null)

const nav = [
  { to: '/', label: '总览', icon: LayoutDashboard },
  { to: '/workflows', label: '工作流', icon: Workflow },
  { to: '/runs', label: '运行记录', icon: History },
  { to: '/reports', label: '报告', icon: FileBarChart2 },
] as const

const pageTitle = computed(() => {
  const hit = nav.find((n) => n.to === route.path)
  return hit?.label ?? '工作流平台'
})
</script>

<template>
  <SidebarProvider class="h-svh max-h-svh overflow-hidden">
    <Sidebar collapsible="icon" variant="inset">
      <SidebarHeader class="px-3 py-3">
        <div class="flex items-center gap-2">
          <div class="flex size-8 items-center justify-center rounded-md bg-sidebar-primary text-xs font-bold text-sidebar-primary-foreground">
            国
          </div>
          <div class="min-w-0 group-data-[collapsible=icon]:hidden">
            <p class="truncate text-sm font-semibold">流控制台</p>
            <p class="truncate text-xs text-muted-foreground">Shadcn · Sheet</p>
          </div>
        </div>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>导航</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem v-for="item in nav" :key="item.to">
                <SidebarMenuButton
                  as-child
                  :tooltip="item.label"
                  :is-active="route.path === item.to"
                >
                  <RouterLink :to="item.to">
                    <component :is="item.icon" />
                    <span>{{ item.label }}</span>
                  </RouterLink>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>
      <SidebarRail />
    </Sidebar>

    <SidebarInset class="min-h-0 min-w-0 overflow-hidden md:max-h-[calc(100svh-1rem)]">
      <header class="flex h-14 shrink-0 items-center gap-2 border-b px-4">
        <SidebarTrigger class="-ml-1" />
        <Separator orientation="vertical" class="mr-2 h-4" />
        <div class="min-w-0">
          <h1 class="truncate text-sm font-semibold">{{ pageTitle }}</h1>
          <p class="truncate text-xs text-muted-foreground">对接 workflow_server · 旧台并存</p>
        </div>
      </header>
      <div
        ref="mainScroll"
        class="min-h-0 min-w-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain p-4 md:p-5"
      >
        <div class="mx-auto w-full max-w-4xl min-w-0">
          <RouterView />
        </div>
      </div>
      <BackToTop :target="mainScroll" />
    </SidebarInset>
  </SidebarProvider>
</template>
