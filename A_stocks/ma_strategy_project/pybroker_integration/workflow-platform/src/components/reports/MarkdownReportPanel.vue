<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchWorkspaceFile } from '@/api/workflow'
import { renderMarkdownToHtml } from '@/api/workspacePreview'

const props = defineProps<{
  path: string
}>()

const loading = ref(false)
const exists = ref(false)
const raw = ref('')
const error = ref('')

const html = computed(() => (raw.value ? renderMarkdownToHtml(raw.value) : ''))
const lineCount = computed(() => (raw.value ? raw.value.split(/\r?\n/).length : 0))

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
    <p class="font-mono text-[11px] text-muted-foreground">{{ path || '未选择文档' }}</p>
    <p v-if="loading" class="py-8 text-center text-sm text-muted-foreground">加载中…</p>
    <template v-else-if="error && !exists">
      <p class="py-8 text-center text-sm text-muted-foreground">{{ error }}</p>
    </template>
    <template v-else-if="exists">
      <p class="text-[11px] text-muted-foreground">Markdown 预览 · {{ lineCount }} 行</p>
      <div
        class="md-report max-h-[min(70vh,720px)] overflow-auto rounded-lg border bg-background px-4 py-3 text-sm leading-relaxed"
        v-html="html"
      />
    </template>
    <p v-else class="py-8 text-center text-sm text-muted-foreground">请选择上方 Markdown 输出。</p>
  </div>
</template>

<style scoped>
.md-report :deep(h1) {
  margin: 0.75rem 0 0.5rem;
  font-size: 1.25rem;
  font-weight: 600;
}
.md-report :deep(h2) {
  margin: 0.7rem 0 0.4rem;
  font-size: 1.1rem;
  font-weight: 600;
}
.md-report :deep(h3) {
  margin: 0.6rem 0 0.35rem;
  font-size: 1rem;
  font-weight: 600;
}
.md-report :deep(p) {
  margin: 0.35rem 0;
}
.md-report :deep(ul),
.md-report :deep(ol) {
  margin: 0.35rem 0;
  padding-left: 1.25rem;
}
.md-report :deep(li) {
  margin: 0.15rem 0;
}
.md-report :deep(hr) {
  margin: 0.75rem 0;
  border: none;
  border-top: 1px solid var(--border);
}
.md-report :deep(code) {
  border-radius: 0.25rem;
  background: oklch(0.97 0 0);
  padding: 0.1rem 0.3rem;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 0.85em;
}
.md-report :deep(pre) {
  margin: 0.5rem 0;
  overflow: auto;
  border-radius: 0.5rem;
  background: oklch(0.97 0 0);
  padding: 0.75rem 1rem;
}
.md-report :deep(pre code) {
  background: transparent;
  padding: 0;
}
.md-report :deep(table) {
  width: 100%;
  margin: 0.5rem 0;
  border-collapse: collapse;
  font-size: 0.8rem;
}
.md-report :deep(th),
.md-report :deep(td) {
  border: 1px solid var(--border);
  padding: 0.35rem 0.5rem;
  text-align: left;
  font-variant-numeric: tabular-nums;
}
.md-report :deep(th) {
  background: oklch(0.97 0 0);
  font-weight: 600;
}
.md-report :deep(a) {
  color: oklch(0.45 0.12 250);
  text-decoration: underline;
}
</style>
