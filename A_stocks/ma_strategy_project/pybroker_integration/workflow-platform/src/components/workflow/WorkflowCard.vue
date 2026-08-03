<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Play } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardFooter, CardHeader } from '@/components/ui/card'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import FileEditDialog from '@/components/workflow/FileEditDialog.vue'
import type { WorkflowStep } from '@/api/types'
import { isPathOutput } from '@/api/types'
import { useWorkflowStore } from '@/stores/workflow'

const props = defineProps<{
  step: WorkflowStep
  busy?: boolean
  focused?: boolean
}>()

const store = useWorkflowStore()
const router = useRouter()
const draft = computed(() => store.ensureDraft(props.step))

const editOpen = ref(false)
const editPath = ref('')
const editLabel = ref('')

const accent = computed(() => {
  const c = props.step.category
  if (c === 'core') return 'border-l-amber-500'
  if (c === 'chain') return 'border-l-blue-500'
  if (c === 'daily') return 'border-l-emerald-500'
  if (c === 'biweekly' || c === 'weekly') return 'border-l-violet-500'
  return 'border-l-zinc-400'
})

function openEdit(path: string, label: string) {
  editPath.value = path
  editLabel.value = label
  editOpen.value = true
}

function openOutput(path: string) {
  store.openStepOutput(props.step, path)
  void router.push('/reports')
}

async function onRun() {
  const result = await store.runStep(props.step)
  if (result && 'blocked' in result && result.blocked) {
    alert(result.reason)
  }
}
</script>

<template>
  <Card
    :id="`wf-card-${step.id}`"
    :class="[
      'overflow-hidden border-l-4 py-0 scroll-mt-4 transition-shadow',
      accent,
      focused ? 'ring-2 ring-amber-400 shadow-md' : '',
    ]"
  >
    <CardHeader class="space-y-2 border-b px-4 py-3">
      <div class="flex items-start justify-between gap-3">
        <div class="min-w-0">
          <p class="font-mono text-[11px] text-muted-foreground">{{ step.id }}</p>
          <h3 class="text-base font-semibold leading-snug">{{ step.title }}</h3>
        </div>
        <Button
          v-if="step.runnable"
          size="sm"
          :disabled="busy"
          @click="onRun"
        >
          <Play class="size-3.5" />
          运行
        </Button>
      </div>
      <div v-if="step.tags?.length" class="flex flex-wrap gap-1">
        <Badge v-for="tag in step.tags" :key="tag" variant="secondary">{{ tag }}</Badge>
      </div>
      <p v-if="step.description" class="rounded-md bg-muted/50 px-2.5 py-2 text-xs leading-relaxed text-muted-foreground">
        {{ step.description }}
      </p>
    </CardHeader>

    <CardContent class="space-y-3 px-4 py-3">
      <div v-if="step.runModes?.length" class="space-y-1">
        <p class="text-xs text-muted-foreground">运行模式</p>
        <Select
          :model-value="draft.runMode"
          @update:model-value="(v) => v && (draft.runMode = String(v))"
        >
          <SelectTrigger class="h-8 w-full max-w-xs">
            <SelectValue placeholder="选择模式" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="m in step.runModes" :key="m.id" :value="m.id">
              {{ m.label }}
            </SelectItem>
          </SelectContent>
        </Select>
      </div>

      <div v-if="step.poolPresets?.length" class="space-y-1">
        <p class="text-xs text-muted-foreground">股票池</p>
        <Select
          :model-value="draft.poolPath"
          @update:model-value="(v) => v && (draft.poolPath = String(v))"
        >
          <SelectTrigger class="h-8 w-full max-w-xs">
            <SelectValue placeholder="选择股票池" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem v-for="p in step.poolPresets" :key="p.path" :value="p.path">
              {{ p.label }}
            </SelectItem>
            <SelectItem value="__custom__">自定义路径</SelectItem>
          </SelectContent>
        </Select>
        <input
          v-if="draft.poolPath === '__custom__'"
          v-model="draft.poolCustom"
          class="h-8 w-full max-w-md rounded-md border px-2 text-xs"
          placeholder="相对项目根的池文件路径"
        />
      </div>

      <div v-if="step.symbolsPaste" class="space-y-1.5">
        <p class="text-xs text-muted-foreground">
          {{ step.symbolsPasteHint || '可选粘贴股票代码' }}
        </p>
        <textarea
          v-model="draft.symbolsText"
          class="min-h-20 w-full rounded-md border bg-background px-2.5 py-2 font-mono text-xs leading-relaxed outline-none focus:border-ring"
          placeholder="600519&#10;000001&#10;002821 或逗号分隔"
          spellcheck="false"
        />
        <div v-if="step.symbolsPasteComboOptions?.length" class="space-y-1">
          <p class="text-xs text-muted-foreground">形态 ID（粘贴列表时必选）</p>
          <Select
            :model-value="draft.comboId || undefined"
            @update:model-value="(v) => (draft.comboId = v ? String(v) : '')"
          >
            <SelectTrigger class="h-8 w-full max-w-xs">
              <SelectValue placeholder="—— 请选择 ——" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem v-for="c in step.symbolsPasteComboOptions" :key="c.id" :value="c.id">
                {{ c.label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
        <p class="text-[11px] text-muted-foreground">
          {{
            draft.symbolsText.trim()
              ? '已粘贴 → 运行时传入 --symbols'
              : step.symbolsPasteEmptyHint || '未粘贴 → 使用默认上游逻辑'
          }}
        </p>
      </div>

      <div v-if="step.workspaceInputs?.length" class="flex flex-wrap gap-1.5">
        <Button
          v-for="inp in step.workspaceInputs"
          :key="inp.path"
          size="sm"
          variant="outline"
          @click="openEdit(inp.path, inp.label)"
        >
          编辑 · {{ inp.label }}
        </Button>
      </div>
    </CardContent>

    <CardFooter
      v-if="step.workspaceOutputs?.length"
      class="flex flex-wrap gap-x-3 gap-y-1 border-t px-4 py-3"
    >
      <template v-for="(out, idx) in step.workspaceOutputs" :key="idx">
        <button
          v-if="isPathOutput(out)"
          type="button"
          class="text-xs font-medium text-emerald-700 hover:underline"
          @click="openOutput(out.path)"
        >
          查看 · {{ out.label }}
        </button>
        <span v-else class="text-xs text-muted-foreground">查看 · {{ out.label }}（glob）</span>
      </template>
    </CardFooter>

    <FileEditDialog
      v-model:open="editOpen"
      :path="editPath"
      :label="editLabel"
    />
  </Card>
</template>
