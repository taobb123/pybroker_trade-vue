<script setup lang="ts">
defineProps<{
  items: Array<{ name: string; value: number; href?: string }>
}>()

const maxValue = (items: Array<{ value: number }>) =>
  items.reduce((m, i) => Math.max(m, i.value), 0)

function widthPct(value: number, max: number) {
  if (!max) return '0%'
  return `${Math.max(4, Math.round((value / max) * 100))}%`
}
</script>

<template>
  <ul class="space-y-2">
    <li v-for="item in items" :key="item.name" class="space-y-1">
      <div class="flex items-center justify-between text-sm">
        <span class="truncate text-foreground">{{ item.name }}</span>
        <span class="font-mono text-xs tabular-nums text-muted-foreground">{{ item.value }}</span>
      </div>
      <div class="h-1.5 overflow-hidden rounded-full bg-muted">
        <div
          class="h-full rounded-full bg-primary"
          :style="{ width: widthPct(item.value, maxValue(items)) }"
        />
      </div>
    </li>
  </ul>
</template>
