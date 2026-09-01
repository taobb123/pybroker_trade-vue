<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Bookmark, Crosshair, RefreshCw } from '@lucide/vue'
import { Button } from '@/components/ui/button'
import BuffettQuoteCard from '@/components/radar/BuffettQuoteCard.vue'
import MarketRadarPanel from '@/components/radar/MarketRadarPanel.vue'
import OpportunityCard from '@/components/radar/OpportunityCard.vue'
import PitchSelectCard from '@/components/radar/PitchSelectCard.vue'
import { DISCLAIMER, GOOD_PITCH_THRESHOLD } from '@/config/opportunityRules'
import { radarLimit, UPGRADE_VALUE_CTA } from '@/config/radarLimits'
import {
  TEMPERATURE_RUN_MODES,
  TEMPERATURE_STEP_ID,
} from '@/config/temperatureRunModes'
import {
  loadOpportunityBundle,
  type OpportunityBundle,
} from '@/data/loadOpportunities'
import {
  loadPitchSelectBundle,
  type PitchSelectBundle,
} from '@/data/selectPitches'
import { loadTLevelsByName, type TLevels } from '@/data/tLevels'
import { parsePredictionKlineJson, type PredictionKlinePayload } from '@/api/kline'
import { fetchWorkspaceFile } from '@/api/workflow'
import { formatTime } from '@/api/parse'
import { trackEvent } from '@/api/events'
import { scoreOpportunity, type ScoredOpportunity } from '@/domain/opportunity'
import { useAuthStore } from '@/stores/auth'
import { useWatchlistStore } from '@/stores/watchlist'
import { useWorkflowStore } from '@/stores/workflow'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const watchlist = useWatchlistStore()
const workflow = useWorkflowStore()

const loading = ref(true)
const radarTick = ref(0)
const radarBooted = ref(false)
const pitchBundle = ref<PitchSelectBundle | null>(null)
const fallbackBundle = ref<OpportunityBundle | null>(null)
const tLevels = ref<Map<string, TLevels>>(new Map())
const klinePayload = ref<PredictionKlinePayload | null>(null)

const forceEmpty = computed(() => String(route.query.empty ?? '') === '1')
const usePitchMode = computed(() => Boolean(pitchBundle.value?.pitches.length) && !forceEmpty.value)

const plan = computed(() => auth.user?.plan ?? 'free')
const limits = computed(() => radarLimit(plan.value))

const visiblePitches = computed(() => {
  const list = pitchBundle.value?.pitches ?? []
  const max = limits.value.maxGoodPitches
  if (max < 0) return list
  return list.slice(0, max)
})

const hiddenPitchCount = computed(() =>
  Math.max(0, (pitchBundle.value?.pitches.length ?? 0) - visiblePitches.value.length),
)

const scored = computed(() => (fallbackBundle.value?.items ?? []).map(scoreOpportunity))

const allGood = computed(() => {
  if (forceEmpty.value || usePitchMode.value) return [] as ScoredOpportunity[]
  return scored.value.filter((o) => o.verdict === 'good')
})

const goodPitches = computed(() => {
  const max = limits.value.maxGoodPitches
  if (max < 0) return allGood.value
  return allGood.value.slice(0, max)
})

const hiddenGoodCount = computed(() => Math.max(0, allGood.value.length - goodPitches.value.length))

const waitingNearby = computed(() => {
  if (forceEmpty.value || usePitchMode.value) return [] as ScoredOpportunity[]
  return scored.value.filter((o) => o.verdict === 'wait')
})

const hasGood = computed(() => goodPitches.value.length > 0)

const sourceHint = computed(() => {
  if (pitchBundle.value) return pitchBundle.value.label
  if (!fallbackBundle.value) return ''
  const t = fallbackBundle.value.asOf ? ` · ${formatTime(fallbackBundle.value.asOf)}` : ''
  return `${fallbackBundle.value.label}${t}`
})

const market = computed(() => fallbackBundle.value?.market)

function levelsFor(name: string): TLevels | null {
  return tLevels.value.get(name) || tLevels.value.get(name.replace(/\s/g, '')) || null
}

async function refresh() {
  loading.value = true
  try {
    const [pitches, fallback, levels, klineFile] = await Promise.all([
      loadPitchSelectBundle(),
      loadOpportunityBundle(workflow.runs),
      loadTLevelsByName(),
      fetchWorkspaceFile('prediction_kline_compare.json'),
    ])
    pitchBundle.value = pitches
    fallbackBundle.value = fallback
    tLevels.value = levels
    klinePayload.value =
      klineFile.exists && klineFile.content
        ? parsePredictionKlineJson(klineFile.content)
        : null
    if (radarBooted.value) radarTick.value += 1
    radarBooted.value = true
  } finally {
    loading.value = false
  }
}

function goUpgrade() {
  trackEvent('click_upgrade', { from: 'radar_good_pitch_limit' })
  void router.push('/billing/plans')
}

function openTemperature(modeId?: string) {
  void router.push({
    path: '/workflows',
    query: {
      step: TEMPERATURE_STEP_ID,
      ...(modeId ? { mode: modeId } : {}),
    },
  })
}

onMounted(() => {
  void refresh()
})
</script>

<template>
  <div class="space-y-6">
    <section class="space-y-2">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            机会雷达 · 选球
          </p>
          <h2 class="text-xl font-semibold tracking-tight sm:text-2xl">
            今天有没有好球？
          </h2>
          <p class="mt-1 max-w-xl text-sm text-muted-foreground">
            市场中性多头净值 Top2 因子 × 各取前 2 股；选球卡内嵌预测 K 线，右侧为做 T 买一/买二等档位。
            综合分 ≥ {{ GOOD_PITCH_THRESHOLD }} 标为好球。下方盘中雷达盯成长因子 M加 / Q / 量能 各前 5。
          </p>
          <p v-if="sourceHint" class="mt-1 text-[11px] text-muted-foreground">
            数据源：{{ sourceHint }}
          </p>
        </div>
        <div class="flex flex-wrap gap-2">
          <Button size="sm" variant="outline" :disabled="loading" @click="refresh">
            <RefreshCw class="size-3.5" :class="loading && 'animate-spin'" />
            刷新
          </Button>
          <Button size="sm" variant="outline" @click="router.push('/watchlist')">
            <Bookmark class="size-3.5" />
            观察池
            <span v-if="watchlist.count" class="tabular-nums text-muted-foreground">
              ({{ watchlist.count }})
            </span>
          </Button>
          <Button size="sm" variant="outline" @click="router.push('/workflows')">
            工作流执行台
          </Button>
        </div>
      </div>
      <p class="text-[11px] leading-relaxed text-muted-foreground">
        {{ DISCLAIMER }}
      </p>
    </section>

    <BuffettQuoteCard />

    <section class="space-y-3 rounded-xl border bg-muted/20 p-4">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div class="min-w-0 flex-1">
          <p class="text-xs text-muted-foreground">市场环境</p>
          <p class="text-base font-semibold">{{ market?.label ?? (usePitchMode ? '选球模式' : '加载中') }}</p>
          <p class="mt-0.5 text-sm text-muted-foreground">
            {{
              market?.hint ??
                (usePitchMode
                  ? '已按市场中性多头净值筛选因子与个股。'
                  : '优先市场中性选球；无产物时回退形态/演示。')
            }}
          </p>
          <p
            v-if="market?.reassure"
            class="mt-2 max-w-2xl rounded-md border border-amber-200/70 bg-amber-50/60 px-2.5 py-1.5 text-[11px] leading-relaxed text-amber-950/80 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-100/80"
          >
            {{ market.reassure }}
          </p>
          <p class="mt-2 text-[11px] text-muted-foreground">
            对应工作流：
            <button
              type="button"
              class="font-medium text-foreground underline-offset-2 hover:underline"
              @click="openTemperature()"
            >
              市场温度计 - 每日仓位报告
            </button>
          </p>
        </div>
        <div class="shrink-0 text-right">
          <p class="text-[11px] text-muted-foreground">
            {{ market?.fearIndex != null ? '温度总分' : '模式' }}
          </p>
          <p class="text-2xl font-semibold tabular-nums">
            <template v-if="market?.fearIndex != null">{{ market.fearIndex }}</template>
            <template v-else-if="loading">…</template>
            <template v-else>{{ usePitchMode ? '中性选球' : '回退' }}</template>
          </p>
          <p class="text-[11px] text-muted-foreground">{{ market?.asOf }}</p>
          <Button size="sm" variant="outline" class="mt-2" @click="openTemperature('daily')">
            打开温度计
          </Button>
        </div>
      </div>

      <div class="border-t border-border/60 pt-3">
        <p class="text-xs font-medium text-foreground">运行时三种选择</p>
        <p class="mt-0.5 text-[11px] text-muted-foreground">
          进入工作流后，在「运行模式」里任选其一；日常看盘选每日报告即可。
        </p>
        <ul class="mt-3 grid gap-2 sm:grid-cols-3">
          <li
            v-for="m in TEMPERATURE_RUN_MODES"
            :key="m.id"
            class="flex flex-col rounded-lg border bg-background/80 p-3"
          >
            <p class="text-sm font-semibold">{{ m.label }}</p>
            <p class="mt-1 flex-1 text-[11px] leading-relaxed text-muted-foreground">
              {{ m.summary }}
            </p>
            <Button
              size="sm"
              variant="outline"
              class="mt-2 h-7 self-start text-xs"
              @click="openTemperature(m.id)"
            >
              用此模式打开
            </Button>
          </li>
        </ul>
      </div>
    </section>

    <MarketRadarPanel :tick="radarTick" />

    <!-- 选球卡（主路径） -->
    <section v-if="usePitchMode" class="space-y-3">
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-base font-semibold">选球卡</h3>
        <span class="text-xs text-muted-foreground">
          {{ visiblePitches.length }} 只 · K线+做T档位
          <template v-if="hiddenPitchCount"> · 另有 {{ hiddenPitchCount }} 只需升级</template>
        </span>
      </div>
      <div class="space-y-3">
        <PitchSelectCard
          v-for="p in visiblePitches"
          :key="p.opportunity.id"
          :pitch="p"
          :levels="levelsFor(p.opportunity.name)"
          :kline-payload="klinePayload"
        />
      </div>
      <div
        v-if="hiddenPitchCount"
        class="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-dashed px-4 py-3"
      >
        <p class="text-sm text-muted-foreground">
          Free 预览仅显示 {{ limits.maxGoodPitches }} 张选球卡。{{ UPGRADE_VALUE_CTA }}。
        </p>
        <Button size="sm" @click="goUpgrade">升级 Pro</Button>
      </div>
    </section>

    <!-- 回退：旧好球列表 -->
    <section v-else class="space-y-3">
      <div class="flex items-center justify-between gap-2">
        <h3 class="text-base font-semibold">今日好球</h3>
        <span class="text-xs text-muted-foreground">
          <template v-if="loading">加载中…</template>
          <template v-else>
            {{ hasGood ? `${goodPitches.length} 条 · 规则评分` : '0 条' }}
            <template v-if="hiddenGoodCount"> · 另有 {{ hiddenGoodCount }} 条需升级可见</template>
          </template>
        </span>
      </div>

      <div
        v-if="loading"
        class="rounded-xl border border-dashed bg-muted/20 px-6 py-10 text-center text-sm text-muted-foreground"
      >
        正在读取市场中性 / 形态产物…
      </div>

      <div
        v-else-if="!hasGood"
        class="flex flex-col items-center gap-3 rounded-xl border border-dashed bg-muted/20 px-6 py-12 text-center"
      >
        <div class="flex size-12 items-center justify-center rounded-full bg-muted">
          <Crosshair class="size-6 text-muted-foreground" />
        </div>
        <div class="space-y-1">
          <p class="text-base font-semibold">今日无好球</p>
          <p class="max-w-sm text-sm text-muted-foreground">
            请先运行「市场中性 · 形态/PE/Q/MUD」生成 metrics；再运行「做 T」生成 K 线与买一买二。
          </p>
        </div>
        <div class="flex flex-wrap justify-center gap-2">
          <Button
            size="sm"
            variant="outline"
            @click="router.push({ path: '/workflows', query: { step: 'market_neutral' } })"
          >
            运行市场中性
          </Button>
          <Button
            size="sm"
            variant="outline"
            @click="router.push({ path: '/workflows', query: { step: 'compute_today' } })"
          >
            做 T 止盈止损
          </Button>
        </div>
        <p v-if="forceEmpty" class="text-[11px] text-muted-foreground">
          验收空态：已启用 ?empty=1
        </p>
      </div>

      <div v-else class="space-y-3">
        <OpportunityCard v-for="item in goodPitches" :key="item.id" :item="item" />
      </div>
    </section>

    <section v-if="!loading && !usePitchMode && waitingNearby.length" class="space-y-3">
      <div>
        <h3 class="text-base font-semibold">接近但需等待</h3>
        <p class="text-xs text-muted-foreground">未过阈值，不构成出手建议</p>
      </div>
      <OpportunityCard v-for="item in waitingNearby" :key="item.id" :item="item" />
    </section>
  </div>
</template>
