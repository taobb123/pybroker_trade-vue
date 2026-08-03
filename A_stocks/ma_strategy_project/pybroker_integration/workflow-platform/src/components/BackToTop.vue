<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowUp } from '@lucide/vue'
import { Button } from '@/components/ui/button'

const props = withDefaults(
  defineProps<{
    /** 主内容滚动容器 */
    target?: HTMLElement | null
    /** 滚过该像素后显示 */
    minPixels?: number
    /** 滚动进度超过该比例后显示（0–1） */
    progressThreshold?: number
  }>(),
  {
    target: null,
    minPixels: 160,
    progressThreshold: 0.12,
  },
)

const route = useRoute()
const visible = ref(false)
const sheetBlocking = ref(false)
const listeners: Array<() => void> = []
let sheetObserver: MutationObserver | null = null

function isSheetOpen(): boolean {
  const nodes = document.querySelectorAll(
    '[data-slot="sheet-content"], [data-slot="sheet-overlay"]',
  )
  for (const el of nodes) {
    const state = el.getAttribute('data-state')
    if (state === 'closed') continue
    // open / 无 state（已挂载即表示打开）
    if (state === 'open' || state == null) return true
  }
  return false
}

function syncSheetBlocking() {
  sheetBlocking.value = isSheetOpen()
}

function metrics() {
  const el = props.target
  if (el) {
    const max = Math.max(1, el.scrollHeight - el.clientHeight)
    return { top: el.scrollTop, progress: el.scrollTop / max, canScroll: max > 8 }
  }
  const doc = document.documentElement
  const max = Math.max(1, doc.scrollHeight - window.innerHeight)
  const top = window.scrollY || doc.scrollTop || 0
  return { top, progress: top / max, canScroll: max > 8 }
}

function onScroll() {
  syncSheetBlocking()
  const { top, progress, canScroll } = metrics()
  if (!canScroll || sheetBlocking.value) {
    visible.value = false
    return
  }
  visible.value = top >= props.minPixels || progress >= props.progressThreshold
}

function scrollToTop() {
  const el = props.target
  if (el && el.scrollTop > 0) {
    el.scrollTo({ top: 0, behavior: 'smooth' })
  }
  if ((window.scrollY || document.documentElement.scrollTop) > 0) {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }
}

function bind() {
  unbind()
  const el = props.target
  if (el) {
    el.addEventListener('scroll', onScroll, { passive: true })
    listeners.push(() => el.removeEventListener('scroll', onScroll))
  }
  window.addEventListener('scroll', onScroll, { passive: true })
  listeners.push(() => window.removeEventListener('scroll', onScroll))
  document.addEventListener('scroll', onScroll, { passive: true, capture: true })
  listeners.push(() => document.removeEventListener('scroll', onScroll, true))
  onScroll()
}

function unbind() {
  while (listeners.length) listeners.pop()?.()
}

onMounted(async () => {
  await nextTick()
  bind()
  sheetObserver = new MutationObserver(() => {
    syncSheetBlocking()
    onScroll()
  })
  sheetObserver.observe(document.body, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ['data-state'],
  })
  syncSheetBlocking()
})
onBeforeUnmount(() => {
  unbind()
  sheetObserver?.disconnect()
  sheetObserver = null
})

watch(
  () => props.target,
  async () => {
    await nextTick()
    bind()
  },
)

watch(
  () => route.fullPath,
  async () => {
    visible.value = false
    await nextTick()
    requestAnimationFrame(onScroll)
  },
)
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition duration-200 ease-out"
      enter-from-class="translate-y-2 opacity-0"
      enter-to-class="translate-y-0 opacity-100"
      leave-active-class="transition duration-150 ease-in"
      leave-from-class="translate-y-0 opacity-100"
      leave-to-class="translate-y-2 opacity-0"
    >
      <Button
        v-if="visible"
        type="button"
        size="icon"
        class="fixed bottom-6 right-6 z-40 size-11 rounded-full border bg-background text-foreground shadow-lg hover:bg-accent"
        aria-label="回到顶部"
        title="回到顶部"
        @click="scrollToTop"
      >
        <ArrowUp class="size-4" />
      </Button>
    </Transition>
  </Teleport>
</template>
