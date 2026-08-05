<script setup lang="ts">
import { computed } from 'vue'
import { Badge } from '@/components/ui/badge'
import {
  PRINCIPLE_LABEL,
  quoteOfDay,
  type BuffettQuote,
} from '@/config/buffettQuotes'

const props = defineProps<{
  /** 不传则按日轮换 */
  quote?: BuffettQuote
}>()

const current = computed(() => props.quote ?? quoteOfDay())
</script>

<template>
  <aside
    class="rounded-xl border border-amber-200/60 bg-gradient-to-br from-amber-50/80 to-background px-4 py-3.5 dark:border-amber-900/40 dark:from-amber-950/30"
  >
    <div class="flex flex-wrap items-center gap-2">
      <Badge variant="outline" class="border-amber-300/80 text-amber-900 dark:text-amber-100">
        {{ PRINCIPLE_LABEL[current.principle] }}
      </Badge>
      <span class="text-[11px] text-muted-foreground">理解本站价值</span>
    </div>
    <blockquote class="mt-2 text-sm leading-relaxed text-foreground/90 sm:text-[15px]">
      「{{ current.text }}」
    </blockquote>
    <p class="mt-1.5 text-xs text-muted-foreground">—— {{ current.attribution }}</p>
    <p class="mt-2 text-xs leading-relaxed text-amber-950/70 dark:text-amber-100/70">
      {{ current.productHint }}
    </p>
  </aside>
</template>
