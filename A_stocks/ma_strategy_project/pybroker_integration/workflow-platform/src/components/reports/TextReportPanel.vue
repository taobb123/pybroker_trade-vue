<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { fetchWorkspaceFile } from '@/api/workflow'
import { copyTextToClipboard } from '@/api/tableCopy'
import { trackEvent } from '@/api/events'
import { useQuotaStore } from '@/stores/quota'

const props = defineProps<{
  path: string
}>()

const quota = useQuotaStore()
const router = useRouter()
const loading = ref(false)
const exists = ref(false)
const raw = ref('')
const error = ref('')
const copyFlash = ref('')
let copyFlashTimer: ReturnType<typeof setTimeout> | null = null

const lineCount = computed(() => (raw.value ? raw.value.split(/\r?\n/).length : 0))
const nonEmptyLineCount = computed(() =>
  raw.value
    ? raw.value.split(/\r?\n/).filter((l) => l.trim()).length
    : 0,
)

async function load(path: string) {
  if (!path) {
    exists.value = false
    raw.value = ''
    error.value = ''
    return
  }
  loading.value = true
  error.value = ''
  const file = await fetchWorkspaceFile(path)
  loading.value = false
  exists.value = file.exists
  raw.value = file.exists ? file.content : ''
  if (!file.exists) error.value = '文件尚未生成或不存在，请先运行对应 Workflow。'
}

async function onCopy() {
  const gate = quota.assertCanExport()
  if (!gate.ok) {
    alert(gate.reason)
    void router.push('/billing/plans')
    return
  }
  if (!raw.value.trim()) {
    alert('文本无内容可复制。')
    return
  }
  const ok = await copyTextToClipboard(raw.value)
  if (!ok) {
    alert('复制失败，请手动选中文本复制。')
    return
  }
  trackEvent('export_report', { kind: 'text_copy', path: props.path })
  copyFlash.value = '已复制'
  if (copyFlashTimer) clearTimeout(copyFlashTimer)
  copyFlashTimer = setTimeout(() => {
    copyFlash.value = ''
  }, 1600)
}

watch(
  () => props.path,
  (p) => {
    void load(p)
  },
  { immediate: true },
)
</script>

<template>
  <div class="space-y-2">
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p class="font-mono text-[11px] text-muted-foreground">{{ path || '未选择文本' }}</p>
      <Button
        v-if="exists && raw && !quota.canExportReports()"
        size="sm"
        variant="outline"
        @click="router.push('/billing/plans')"
      >
        导出需 Pro
      </Button>
      <Button
        v-else-if="exists && raw"
        size="sm"
        variant="outline"
        class="border-rose-300 text-rose-700 hover:bg-rose-50"
        @click="onCopy"
      >
        {{ copyFlash || '复制全文' }}
      </Button>
    </div>
    <p v-if="loading" class="py-8 text-center text-sm text-muted-foreground">加载中…</p>
    <template v-else-if="error && !exists">
      <p class="py-8 text-center text-sm text-muted-foreground">{{ error }}</p>
    </template>
    <template v-else-if="exists">
      <p class="text-[11px] text-muted-foreground">
        文本预览 · {{ lineCount }} 行
        <template v-if="nonEmptyLineCount !== lineCount">
          （非空 {{ nonEmptyLineCount }}）
        </template>
        <template v-if="!quota.canExportReports()"> · 复制需 Pro</template>
      </p>
      <pre
        class="max-h-[min(70vh,720px)] overflow-auto whitespace-pre-wrap break-words rounded-lg border bg-muted/30 p-4 font-mono text-xs leading-relaxed"
      >{{ raw || '（空文件）' }}</pre>
    </template>
    <p v-else class="py-8 text-center text-sm text-muted-foreground">请选择上方文本输出。</p>
  </div>
</template>
