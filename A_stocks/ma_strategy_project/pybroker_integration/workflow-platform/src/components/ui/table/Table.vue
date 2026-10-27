<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

const props = defineProps<{
  class?: HTMLAttributes['class']
  /** 外层自己滚动，表格不再包一层横向滚动 */
  bare?: boolean
}>()
</script>

<template>
  <table
    v-if="bare"
    data-slot="table"
    :class="cn('w-full caption-bottom text-sm', props.class)"
  >
    <slot />
  </table>
  <div v-else data-slot="table-container" class="relative w-full overflow-x-auto">
    <table data-slot="table" :class="cn('w-full caption-bottom text-sm', props.class)">
      <slot />
    </table>
  </div>
</template>
