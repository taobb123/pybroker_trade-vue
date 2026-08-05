<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import WorkflowStudioBlock from '@/components/workflow/WorkflowStudioBlock.vue'
import OutputSheet from '@/components/workflow/OutputSheet.vue'
import { useWorkflowStore } from '@/stores/workflow'
import { useQuotaStore } from '@/stores/quota'

const store = useWorkflowStore()
const quota = useQuotaStore()
const route = useRoute()
const router = useRouter()
const query = ref('')
const category = ref<'all' | 'daily' | 'biweekly' | 'core' | 'chain'>('all')
const focusStepId = ref('')
const expandAdvancedFor = ref('')

const quotaTone = computed(() => {
  if (quota.isUnlimited) return 'text-muted-foreground'
  if (quota.remainingToday <= 0) return 'text-destructive'
  if (quota.remainingToday <= 2) return 'text-amber-600'
  return 'text-muted-foreground'
})

const filters = [
  ['all', '全部'],
  ['core', '核心'],
  ['daily', '每日'],
  ['chain', '链路'],
  ['biweekly', '双周'],
] as const

/** 平台侧去掉「每周」与其它工具类；前端小工具（如代码清洗）仍展示 */
const visibleSteps = computed(() =>
  store.steps.filter((s) => {
    if (s.type === 'frontend_tool') return true
    return s.category !== 'weekly' && s.category !== 'tool'
  }),
)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  return visibleSteps.value.filter((s) => {
    if (category.value !== 'all' && s.category !== category.value) return false
    if (!q) return true
    return (
      s.id.toLowerCase().includes(q) ||
      s.title.toLowerCase().includes(q) ||
      (s.description ?? '').toLowerCase().includes(q)
    )
  })
})

async function focusStepFromRoute() {
  const stepId = String(route.query.step ?? '').trim()
  const runId = String(route.query.run ?? '').trim()
  const modeId = String(route.query.mode ?? '').trim()
  if (!stepId) {
    focusStepId.value = ''
    expandAdvancedFor.value = ''
    return
  }
  if (runId) store.selectRun(runId)
  category.value = 'all'
  query.value = ''
  focusStepId.value = stepId
  // 最近运行进入：展开「高级/输入」
  expandAdvancedFor.value = stepId

  const step = store.steps.find((s) => s.id === stepId)
  if (step && modeId && step.runModes?.some((m) => m.id === modeId)) {
    const draft = store.ensureDraft(step)
    draft.runMode = modeId
  }

  await nextTick()
  const el = document.getElementById(`wf-card-${stepId}`)
  el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

onMounted(async () => {
  await store.loadSteps()
  void quota.refresh()
  await focusStepFromRoute()
})

watch(
  () => [route.query.step, route.query.run, route.query.mode, store.steps.length] as const,
  () => {
    void focusStepFromRoute()
  },
)
</script>

<template>
  <div class="w-full min-w-0 max-w-full space-y-6 overflow-x-hidden">
    <div
      class="flex flex-wrap items-center justify-between gap-2 rounded-lg border px-3 py-2 text-xs"
      :class="quota.remainingToday <= 0 && !quota.isUnlimited ? 'border-destructive/40 bg-destructive/5' : 'bg-muted/30'"
    >
      <div class="space-y-0.5">
        <p :class="['font-medium', quotaTone]">{{ quota.summaryLabel }}</p>
        <p class="text-muted-foreground">
          档位规则：{{ quota.planQuotaHint }} · 发起即计次 · 每分钟最多 10 次
        </p>
      </div>
      <Button
        v-if="!quota.isUnlimited && quota.remainingToday <= 0"
        size="sm"
        @click="router.push('/billing/plans')"
      >
        升级会员
      </Button>
    </div>

    <div
      v-if="quota.blockMessage"
      class="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive"
    >
      {{ quota.blockMessage }}
    </div>

    <div class="flex flex-wrap items-center gap-2">
      <Input
        v-model="query"
        type="search"
        placeholder="搜索 Workflow…"
        class="h-8 w-64"
      />
      <div class="flex flex-wrap gap-1">
        <Button
          v-for="c in filters"
          :key="c[0]"
          size="sm"
          :variant="category === c[0] ? 'default' : 'outline'"
          @click="category = c[0]"
        >
          {{ c[1] }}
        </Button>
      </div>
      <p class="ml-auto text-xs text-muted-foreground">
        {{ filtered.length }} 项 · 统一区域布局
      </p>
    </div>

    <div class="w-full min-w-0 space-y-8">
      <WorkflowStudioBlock
        v-for="step in filtered"
        :key="step.id"
        :step="step"
        :busy="store.busy"
        :focused="focusStepId === step.id"
        :expand-advanced="expandAdvancedFor === step.id"
      />
      <p v-if="!filtered.length" class="py-10 text-center text-sm text-muted-foreground">
        无匹配 Workflow
      </p>
    </div>

    <OutputSheet />
  </div>
</template>
