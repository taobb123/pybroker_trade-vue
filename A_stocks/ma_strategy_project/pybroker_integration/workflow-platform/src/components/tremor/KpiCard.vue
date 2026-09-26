<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

defineProps<{
  label: string
  value: string
  delta?: string
  deltaTone?: 'up' | 'down' | 'neutral'
  hint?: string
  /** 功能名等长文本：换行，不用数字字号 */
  valueClass?: HTMLAttributes['class']
}>()
</script>

<template>
  <Card>
    <CardHeader class="pb-2">
      <CardDescription>{{ label }}</CardDescription>
      <CardTitle :class="cn('text-2xl tabular-nums', valueClass)">{{ value }}</CardTitle>
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
