<script setup lang="ts">
import { useRouter } from 'vue-router'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import StatusPill from '@/components/tremor/StatusPill.vue'
import { useWorkflowStore } from '@/stores/workflow'

const store = useWorkflowStore()
const router = useRouter()

function onOpenChange(open: boolean) {
  store.sheetOpen = open
}

function goReport() {
  store.sheetOpen = false
  void router.push('/reports')
}

function openOutputLink(out: { path?: string; label: string; glob?: string }) {
  if (store.activeStep && out.path) {
    store.openStepOutput(store.activeStep, out.path)
  }
  goReport()
}
</script>

<template>
  <Sheet :open="store.sheetOpen" @update:open="onOpenChange">
    <SheetContent side="right" class="flex w-full flex-col sm:max-w-xl">
      <SheetHeader>
        <SheetTitle>{{ store.activeStep?.title ?? '输出' }}</SheetTitle>
        <SheetDescription class="font-mono">
          {{ store.activeStep?.id ?? '选择 Workflow 后运行' }}
        </SheetDescription>
      </SheetHeader>

      <div class="flex items-center gap-2 px-4">
        <StatusPill :status="store.status" />
        <span
          v-if="store.lastResult"
          class="text-xs font-medium"
          :class="store.lastResult.exit_code === 0 ? 'text-emerald-700' : 'text-destructive'"
        >
          exit_code={{ store.lastResult.exit_code }}
        </span>
      </div>

      <div
        v-if="store.activeStep?.workspaceOutputs?.length && store.lastResult?.exit_code === 0"
        class="flex flex-wrap gap-2 px-4"
      >
        <button
          v-for="(out, idx) in store.activeStep.workspaceOutputs"
          :key="idx"
          type="button"
          class="text-xs font-medium text-emerald-700 hover:underline"
          @click="openOutputLink(out)"
        >
          查看 · {{ out.label }}
        </button>
      </div>

      <ScrollArea class="min-h-0 flex-1 px-4">
        <pre class="whitespace-pre-wrap break-words rounded-lg border bg-muted/40 p-4 font-mono text-xs leading-relaxed text-foreground">{{ store.lastResult?.merged_log || (store.busy ? '执行中…' : '点击「运行」后在此查看输出') }}</pre>
      </ScrollArea>

      <SheetFooter class="flex-row justify-end gap-2 sm:space-x-0">
        <Button variant="outline" @click="store.sheetOpen = false">关闭</Button>
        <Button
          v-if="store.lastResult?.exit_code === 0"
          variant="outline"
          @click="goReport"
        >
          查看报告
        </Button>
        <Button
          v-if="store.activeStep"
          :disabled="store.busy"
          @click="store.runStep(store.activeStep)"
        >
          重新运行
        </Button>
      </SheetFooter>
    </SheetContent>
  </Sheet>
</template>
