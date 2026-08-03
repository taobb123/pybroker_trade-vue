<script setup lang="ts">
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

defineProps<{
  label: string
  value: string
  delta?: string
  deltaTone?: 'up' | 'down' | 'neutral'
  hint?: string
}>()
</script>

<template>
  <Card>
    <CardHeader class="pb-2">
      <CardDescription>{{ label }}</CardDescription>
      <CardTitle class="text-2xl tabular-nums">{{ value }}</CardTitle>
    </CardHeader>
    <CardContent class="pt-0">
      <p
        v-if="delta"
        class="text-xs font-medium"
        :class="{
          'text-emerald-600': deltaTone === 'up',
          'text-destructive': deltaTone === 'down',
          'text-muted-foreground': !deltaTone || deltaTone === 'neutral',
        }"
      >
        {{ delta }}
      </p>
      <p v-if="hint" class="mt-1 text-xs text-muted-foreground">{{ hint }}</p>
    </CardContent>
  </Card>
</template>
