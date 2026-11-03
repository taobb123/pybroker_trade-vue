<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { copyTextToClipboard, stockCodesToCopyText } from '@/api/tableCopy'
import { fetchThemeCatalog, runThemeReview, type ThemeReviewReport } from '@/api/themeReview'

const themes = ref('')
const loading = ref(false)
const error = ref('')
const message = ref('')
const report = ref<ThemeReviewReport | null>(null)
const copyFlash = ref('')
const catalog = ref<string[]>([])
const catalogDate = ref('')
const catalogError = ref('')
const catalogLoading = ref(false)
const filterText = ref('')

const tracked = computed(() => report.value?.rows ?? [])
const selectedNames = computed(() => splitThemeNames(themes.value))
const selectedSet = computed(() => new Set(selectedNames.value))
const visibleNames = computed(() => {
  const query = filterText.value.trim()
  if (!query) return catalog.value
  return catalog.value.filter((name) => name.includes(query))
})

function splitThemeNames(text: string): string[] {
  const seen = new Set<string>()
  const names: string[] = []
  for (const part of text.split(/[\s,，;；、]+/)) {
    const name = part.trim()
    if (!name || seen.has(name)) continue
    seen.add(name)
    names.push(name)
  }
  return names
}

async function run() {
  loading.value = true
  error.value = ''
  message.value = ''
  try {
    const payload = await runThemeReview(themes.value)
    report.value = payload.report
    if (!payload.ok) error.value = payload.error || payload.message || '题材复盘没有完成。'
    else message.value = payload.message || ''
  } catch (exc) {
    report.value = null
    error.value = exc instanceof Error ? exc.message : '题材复盘没有完成。'
  } finally {
    loading.value = false
  }
}

function toggleTheme(name: string) {
  if (loading.value) return
  const names = splitThemeNames(themes.value)
  const index = names.indexOf(name)
  if (index >= 0) names.splice(index, 1)
  else names.push(name)
  themes.value = names.join('\n')
}

async function loadCatalog() {
  catalogLoading.value = true
  catalogError.value = ''
  try {
    const payload = await fetchThemeCatalog()
    catalog.value = payload.names
    catalogDate.value = payload.tradeDate
    if (!payload.ok) catalogError.value = payload.error || payload.message || '没有取到东财概念列表。'
    else if (!payload.names.length) catalogError.value = payload.message || '没有取到东财概念列表。'
  } catch (exc) {
    catalog.value = []
    catalogError.value = exc instanceof Error ? exc.message : '没有取到东财概念列表。'
  } finally {
    catalogLoading.value = false
  }
}

onMounted(loadCatalog)

async function copyCodes() {
  const text = stockCodesToCopyText(
    ['代码'],
    tracked.value.map((row) => [row.symbol]),
  )
  if (!text) return
  const ok = await copyTextToClipboard(text)
  copyFlash.value = ok ? '已复制' : '复制失败'
  window.setTimeout(() => {
    copyFlash.value = ''
  }, 1500)
}
</script>

<template>
  <div class="space-y-3">
    <Card>
      <CardHeader>
        <CardTitle>题材复盘</CardTitle>
        <CardDescription>
          点选一个或多个东财概念标签，或在下面手填概念名。系统拉全部成分，先去重并剔除 300/301/688/920 开头，再对剩下的股票拉日线，留下百亚启动段相似度达到 0.52 的股票，再标上量价六组合。只在本页展示，不写入观察池。
        </CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <div class="space-y-2">
          <div class="flex flex-wrap items-center gap-2">
            <Input
              v-model="filterText"
              class="h-8 max-w-xs text-sm"
              placeholder="在概念里查找"
            />
            <span class="text-xs text-muted-foreground">
              {{ catalogLoading ? '正在读取东财概念…' : `东财概念 ${catalog.length} 个` }}
              <template v-if="catalogDate"> · {{ catalogDate }}</template>
              <template v-if="filterText.trim()"> · 显示 {{ visibleNames.length }} 个</template>
              · 已选 {{ selectedNames.length }} 个
            </span>
          </div>
          <p v-if="catalogError" class="text-xs text-destructive">{{ catalogError }}</p>
          <div v-else class="max-h-80 overflow-y-auto rounded-md border p-2">
            <div class="flex flex-wrap gap-1.5">
              <Button
                v-for="name in visibleNames"
                :key="name"
                size="sm"
                class="h-7 px-2 text-xs"
                :variant="selectedSet.has(name) ? 'default' : 'outline'"
                :disabled="loading"
                @click="toggleTheme(name)"
              >
                {{ name }}
              </Button>
            </div>
            <p v-if="!catalogLoading && !visibleNames.length" class="text-xs text-muted-foreground">没有符合的概念。</p>
          </div>
        </div>
        <Textarea
          v-model="themes"
          class="min-h-24 text-sm"
          placeholder="每行一个东财概念名，例如：脑机接口"
        />
        <div class="flex flex-wrap gap-2">
          <Button size="sm" :disabled="loading || !themes.trim()" @click="run">
            {{ loading ? '对照中' : '生成跟踪名单' }}
          </Button>
          <Button size="sm" variant="outline" :disabled="!tracked.length" @click="copyCodes">
            {{ copyFlash || `复制代码（${tracked.length}）` }}
          </Button>
        </div>
        <p v-if="loading" class="text-xs text-muted-foreground">
          正在拉成分、清洗代码、对照百亚启动段，并给跟踪股票标注六组合。成分多时会多等一会儿。
        </p>
        <p v-if="error" class="text-xs text-destructive">{{ error }}</p>
        <p v-else-if="message" class="text-xs text-muted-foreground">{{ message }}</p>
        <p v-if="report" class="text-xs text-muted-foreground">
          成分日期 {{ report.tradeDate || '—' }}。成分 {{ report.memberCount }} 只，去重 {{ report.dupSkipped }}，剔除前缀 {{ report.prefixSkipped }}，进入对照 {{ report.poolCount }} 只，跟踪 {{ report.trackedCount }} 只。
          <template v-for="theme in report.themes" :key="theme.name">
            {{ theme.name }} {{ theme.matched ? `${theme.memberCount} 只` : '未匹配' }}。
          </template>
        </p>
      </CardContent>
    </Card>

    <Card>
      <CardHeader>
        <CardTitle>跟踪股票</CardTitle>
        <CardDescription>按相似度从高到低。六组合只说明当前形态，不从名单里剔除。</CardDescription>
      </CardHeader>
      <CardContent class="space-y-3">
        <div v-if="tracked.length" class="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>题材</TableHead>
                <TableHead>代码</TableHead>
                <TableHead>名称</TableHead>
                <TableHead class="text-right">相似度</TableHead>
                <TableHead>六组合</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              <TableRow v-for="row in tracked" :key="row.symbol">
                <TableCell>{{ row.themes }}</TableCell>
                <TableCell class="font-medium tabular-nums">{{ row.symbol }}</TableCell>
                <TableCell>{{ row.stockName || '—' }}</TableCell>
                <TableCell class="text-right tabular-nums">{{ row.similarity.toFixed(2) }}</TableCell>
                <TableCell>
                  <Badge v-if="row.comboName" variant="secondary">{{ row.comboName }}</Badge>
                  <span v-else class="text-muted-foreground">—</span>
                  <p v-if="row.comboNote" class="mt-1 text-xs text-muted-foreground">{{ row.comboNote }}</p>
                  <p v-if="row.reason" class="mt-1 max-w-xl text-xs text-muted-foreground">{{ row.reason }}</p>
                </TableCell>
              </TableRow>
            </TableBody>
          </Table>
        </div>
        <p v-else-if="report && report.memberCount > 0 && report.poolCount === 0" class="text-xs text-muted-foreground">清洗后没有剩余代码。</p>
        <p v-else-if="report && report.poolCount > 0" class="text-xs text-muted-foreground">这次没有达到 0.52 的股票。</p>
        <ul v-if="report?.notes.length" class="space-y-1 text-xs text-muted-foreground">
          <li v-for="note in report.notes" :key="note">{{ note }}</li>
        </ul>
      </CardContent>
    </Card>
  </div>
</template>
