<script setup lang="ts">
import { Play } from '@lucide/vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { WorkflowStep } from '@/api/workflow'

defineProps<{
  step: WorkflowStep
  busy?: boolean
}>()

const emit = defineEmits<{
  run: []
  open: []
}>()
</script>

<template>
  <div
    class="group flex items-center gap-4 border-b px-4 py-3 last:border-b-0 hover:bg-muted/50"
  >
    <button type="button" class="min-w-0 flex-1 text-left" @click="emit('open')">
      <p class="font-mono text-[11px] text-muted-foreground">{{ step.id }}</p>
      <p class="truncate text-sm font-medium">{{ step.title }}</p>
      <p v-if="step.description" class="mt-0.5 line-clamp-1 text-xs text-muted-foreground">
        {{ step.description }}
      </p>
      <div v-if="step.tags?.length" class="mt-1.5 flex flex-wrap gap-1">
        <Badge v-for="tag in step.tags" :key="tag" variant="secondary">{{ tag }}</Badge>
      </div>
    </button>
    <Button size="sm" :disabled="busy" @click.stop="emit('run')">
      <Play class="size-3.5" />
      运行
    </Button>
  </div>
</template>
