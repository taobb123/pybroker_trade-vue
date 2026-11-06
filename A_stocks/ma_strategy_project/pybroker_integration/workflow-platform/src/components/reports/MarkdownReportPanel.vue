<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { fetchWorkspaceFile } from '@/api/workflow'
import { isDailyBriefMarkdown, renderMarkdownToHtml } from '@/api/workspacePreview'

const props = defineProps<{
  path: string
  compact?: boolean
}>()

const loading = ref(false)
const exists = ref(false)
const raw = ref('')
const error = ref('')

const html = computed(() => (raw.value ? renderMarkdownToHtml(raw.value) : ''))
const lineCount = computed(() => (raw.value ? raw.value.split(/\r?\n/).length : 0))
const dailyBrief = computed(() => isDailyBriefMarkdown(raw.value))

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
    <p v-if="!compact" class="font-mono text-[11px] text-muted-foreground">{{ path || '未选择文档' }}</p>
    <p v-if="loading" class="py-8 text-center text-sm text-muted-foreground">加载中…</p>
    <template v-else-if="error && !exists">
      <p class="py-8 text-center text-sm text-muted-foreground">{{ error }}</p>
    </template>
    <template v-else-if="exists">
      <p v-if="!compact" class="text-[11px] text-muted-foreground">Markdown 预览 · {{ lineCount }} 行</p>
      <div
        class="md-report rounded-lg border bg-background text-sm"
        :class="
          dailyBrief
            ? 'brief-fit px-3 py-2'
            : 'max-h-[min(70vh,720px)] overflow-auto px-4 py-3 leading-relaxed'
        "
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
.md-report.brief-fit {
  overflow: visible;
  max-height: none;
}
.md-report :deep(.brief-board) {
  font-size: 0.9375rem;
  line-height: 1.45;
}
.md-report :deep(.brief-head) {
  margin-bottom: 0.85rem;
}
.md-report :deep(.brief-head h1) {
  margin: 0;
  font-size: 1.3rem;
}
.md-report :deep(.brief-head p) {
  margin: 0.2rem 0 0;
  color: var(--muted-foreground);
}
.md-report :deep(.brief-panel) {
  min-width: 0;
  border: 1px solid var(--border);
  border-radius: 0.75rem;
  background: color-mix(in oklch, var(--muted) 35%, transparent);
  padding: 0.85rem 1rem 1rem;
}
.md-report :deep(.brief-panel h2) {
  margin: 0 0 0.75rem;
  padding: 0;
  border: none;
  font-size: 0.95rem;
}
.md-report :deep(.brief-panel p) {
  margin: 0 0 0.65rem;
  color: var(--muted-foreground);
  font-size: 0.8rem;
}
.md-report :deep(.brief-kpis) {
  margin-bottom: 0.85rem;
}
.md-report :deep(.brief-kpi-row) {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 0.75rem;
}
.md-report :deep(.brief-kpis .brief-indices) {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem 0.9rem;
  margin: 0 0 0.85rem;
  color: var(--foreground);
  font-size: 0.875rem;
}
.md-report :deep(.brief-index) {
  display: inline-flex;
  align-items: baseline;
  gap: 0.35rem;
}
.md-report :deep(.brief-index b) {
  color: oklch(0.5 0.18 28);
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.md-report :deep(.brief-kpi-value.brief-down),
.md-report :deep(.brief-index b.brief-down) {
  color: oklch(0.55 0.16 145);
}
.md-report :deep(.brief-kpis ol) {
  margin: 0.85rem 0 0;
}
.md-report :deep(.brief-logic) {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 0.15rem;
  margin: 0;
  padding: 0.45rem 0;
  border-bottom: 1px solid var(--border);
}
.md-report :deep(.brief-logic-title) {
  color: var(--muted-foreground);
  font-size: 0.8rem;
  font-weight: 450;
  line-height: 1.45;
}
.md-report :deep(.brief-kpi-tile) {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  border-radius: 0.65rem;
  background: var(--background);
  padding: 0.7rem 0.85rem;
}
.md-report :deep(.brief-kpi) {
  color: var(--muted-foreground);
  font-size: 0.8rem;
  font-weight: 550;
}
.md-report :deep(.brief-kpi-value) {
  color: oklch(0.5 0.18 28);
  font-size: 1.25rem;
  font-weight: 650;
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}
.md-report :deep(.brief-split) {
  display: grid;
  grid-template-columns: minmax(0, 1.45fr) minmax(16rem, 0.85fr);
  gap: 0.85rem;
  align-items: start;
}
.md-report :deep(.brief-side) {
  display: flex;
  flex-direction: column;
  gap: 0.85rem;
}
.md-report :deep(.brief-board-tier) {
  display: flex;
  align-items: baseline;
  gap: 0.45rem;
  margin: 0.85rem 0 0.4rem;
  font-size: 1rem;
  font-weight: 650;
}
.md-report :deep(.brief-count),
.md-report :deep(.brief-num) {
  color: oklch(0.5 0.18 28);
  font-size: 0.8125rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.md-report :deep(.brief-board-tier .brief-count) {
  border-radius: 999px;
  background: oklch(0.96 0.02 28);
  padding: 0.05rem 0.45rem;
  font-weight: 600;
}
.md-report :deep(.brief-ladder ul) {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin: 0;
  padding: 0;
  list-style: none;
}
.md-report :deep(.brief-chip) {
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
  margin: 0;
  border: 1px solid var(--border);
  border-radius: 999px;
  background: var(--background);
  padding: 0.28rem 0.45rem 0.28rem 0.65rem;
}
.md-report :deep(.brief-stock) {
  color: var(--foreground);
  font-size: 0.875rem;
  font-weight: 500;
}
.md-report :deep(.brief-rhythm) {
  color: var(--muted-foreground);
  font-size: 0.75rem;
}
.md-report :deep(.brief-theme) {
  border-radius: 999px;
  background: oklch(0.95 0.03 250);
  color: oklch(0.42 0.14 250);
  padding: 0.05rem 0.45rem;
  font-size: 0.75rem;
  font-weight: 650;
}
.md-report :deep(.brief-theme-row) {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
  margin: 0;
  padding: 0.5rem 0;
  border-bottom: 1px solid var(--border);
}
.md-report :deep(.brief-theme-row .brief-theme) {
  background: transparent;
  padding: 0;
  font-size: 0.875rem;
  font-weight: 500;
}
.md-report :deep(.brief-panel ol) {
  margin: 0;
  padding: 0;
  list-style: none;
}
.md-report :deep(.brief-lhb) {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}
.md-report :deep(.brief-lhb-line) {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem 0.7rem;
}
.md-report :deep(.brief-figure) {
  color: oklch(0.5 0.18 28);
  font-size: 0.8125rem;
  font-weight: 650;
  font-variant-numeric: tabular-nums;
}
.md-report :deep(.brief-lhb-seat) {
  margin-top: 0.15rem;
  color: var(--muted-foreground);
  font-size: 0.78rem;
  line-height: 1.4;
  overflow-wrap: anywhere;
}
.md-report :deep(.brief-foot) {
  margin-top: 0.85rem;
  color: var(--muted-foreground);
  font-size: 0.8rem;
}
.md-report :deep(.brief-foot p) {
  margin: 0.15rem 0 0;
}
@media (max-width: 860px) {
  .md-report :deep(.brief-kpi-row) {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .md-report :deep(.brief-split) {
    grid-template-columns: 1fr;
  }
}
</style>
