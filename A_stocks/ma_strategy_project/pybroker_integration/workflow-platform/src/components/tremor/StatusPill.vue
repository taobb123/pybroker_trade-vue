<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const props = defineProps<{
  status: 'idle' | 'running' | 'success' | 'error'
}>()

const label: Record<string, string> = {
  idle: '待命',
  running: '运行中',
  success: '成功',
  error: '失败',
}

const variant = computed(() => {
  if (props.status === 'error') return 'destructive' as const
  if (props.status === 'running') return 'default' as const
  return 'secondary' as const
})

const extraClass = computed(() =>
  cn(
    props.status === 'success' && 'border-transparent bg-emerald-50 text-emerald-700',
    props.status === 'running' && 'bg-sky-600 text-white',
  ),
)
</script>

<template>
  <Badge :variant="variant" :class="extraClass">
    {{ label[status] }}
  </Badge>
</template>
