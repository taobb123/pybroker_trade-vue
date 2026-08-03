<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { workspaceMediaUrl } from '@/api/workspacePreview'

const props = defineProps<{
  path: string
}>()

const loading = ref(false)
const error = ref('')
const objectUrl = ref('')
const note = ref('')

function revoke() {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
}

async function load(path: string) {
  revoke()
  error.value = ''
  note.value = ''
  if (!path) return

  loading.value = true
  try {
    const res = await fetch(workspaceMediaUrl(path))
    if (!res.ok) {
      let detail = `HTTP ${res.status}`
      try {
        const j = (await res.json()) as { detail?: unknown }
        if (typeof j.detail === 'string') detail = j.detail
      } catch {
        /* ignore */
      }
      error.value = `无法加载图片：${detail}。若尚未生成，请先运行对应 Workflow。`
      return
    }
    const blob = await res.blob()
    objectUrl.value = URL.createObjectURL(blob)
    note.value = '图形预览加载中…'
  } catch (e) {
    error.value = String(e)
  } finally {
    loading.value = false
  }
}

function onImgLoad(ev: Event) {
  const img = ev.target as HTMLImageElement
  note.value = `图形预览 · ${img.naturalWidth || '?'}×${img.naturalHeight || '?'}px。可右键另存。`
}

function onImgError() {
  error.value = '图片解码失败。'
  revoke()
}

watch(
  () => props.path,
  (p) => {
    void load(p)
  },
  { immediate: true },
)

onBeforeUnmount(revoke)
</script>

<template>
  <div class="space-y-2">
    <p class="font-mono text-[11px] text-muted-foreground">{{ path || '未选择图形' }}</p>
    <p v-if="loading" class="py-8 text-center text-sm text-muted-foreground">加载中…</p>
    <p v-else-if="error" class="py-8 text-center text-sm text-amber-800">{{ error }}</p>
    <template v-else-if="objectUrl">
      <p class="text-[11px] text-muted-foreground">{{ note }}</p>
      <div class="flex max-h-[min(95vh,2880px)] justify-center overflow-auto rounded-lg border bg-muted/20 p-3">
        <img
          :src="objectUrl"
          :alt="path"
          class="h-auto w-full max-w-none object-contain"
          @load="onImgLoad"
          @error="onImgError"
        />
      </div>
    </template>
    <p v-else class="py-8 text-center text-sm text-muted-foreground">请选择上方图片输出。</p>
  </div>
</template>
