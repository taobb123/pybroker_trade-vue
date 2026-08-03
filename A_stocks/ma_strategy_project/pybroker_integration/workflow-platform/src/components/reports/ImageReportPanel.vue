<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { workspaceMediaUrl } from '@/api/workspacePreview'
import { trackEvent } from '@/api/events'
import { useQuotaStore } from '@/stores/quota'

const props = defineProps<{
  path: string
}>()

const quota = useQuotaStore()
const router = useRouter()
const loading = ref(false)
const error = ref('')
const objectUrl = ref('')
const note = ref('')
const blobRef = ref<Blob | null>(null)

function revoke() {
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
  blobRef.value = null
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
    blobRef.value = blob
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
  note.value = `图形预览 · ${img.naturalWidth || '?'}×${img.naturalHeight || '?'}px`
}

function onImgError() {
  error.value = '图片解码失败。'
  revoke()
}

function onDownload() {
  const gate = quota.assertCanExport()
  if (!gate.ok) {
    alert(gate.reason)
    void router.push('/billing/plans')
    return
  }
  if (!blobRef.value) return
  const url = URL.createObjectURL(blobRef.value)
  const a = document.createElement('a')
  a.href = url
  a.download = props.path.split(/[/\\]/).pop() || 'chart.png'
  a.click()
  URL.revokeObjectURL(url)
  trackEvent('export_report', { kind: 'image_download', path: props.path })
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
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="font-mono text-[11px] text-muted-foreground">{{ path || '未选择图形' }}</p>
      <Button
        v-if="objectUrl && !quota.canExportReports()"
        size="sm"
        variant="outline"
        @click="router.push('/billing/plans')"
      >
        下载需 Pro
      </Button>
      <Button
        v-else-if="objectUrl"
        size="sm"
        variant="outline"
        @click="onDownload"
      >
        下载图片
      </Button>
    </div>
    <p v-if="loading" class="py-8 text-center text-sm text-muted-foreground">加载中…</p>
    <p v-else-if="error" class="py-8 text-center text-sm text-amber-800">{{ error }}</p>
    <template v-else-if="objectUrl">
      <p class="text-[11px] text-muted-foreground">
        {{ note }}
        <template v-if="!quota.canExportReports()"> · 下载需 Pro</template>
      </p>
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
