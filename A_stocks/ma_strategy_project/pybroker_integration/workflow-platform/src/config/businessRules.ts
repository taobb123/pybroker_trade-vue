/**
 * 业务闭环规则配置源（与 AI全栈工程师/业务闭环-产品规则设计-v1.md 保持一致）
 * 改数字只改此处，UI / 门控 / 后续 API 共用。
 */
import type { PlanTier } from '@/stores/auth'

export type CapabilityKey =
  | 'workflow.basic'
  | 'workflow.advanced'
  | 'report.export'
  | 'workspace.cloud_save'
  | 'team.seats'

export interface PlanRule {
  id: PlanTier
  name: string
  /** 展示价（分档文案）；Team 可为 0 + 联系客服 */
  priceYuanPerMonth: number
  priceLabel: string
  /** 自然日运行配额；-1 = 不限 */
  dailyRunQuota: number
  periodDays: number
  purchasable: boolean
  capabilities: Record<CapabilityKey, boolean>
  features: string[]
  cta: string
}

/** 未登录是否允许发起 run（收费验证期可改为 true） */
export const ENFORCE_AUTH_FOR_RUN = true

/** 配额：发起一次 run 计 1 次（含失败/中止） */
export const QUOTA_COUNTS_FAILED_RUNS = true

/** M6：每用户滑动窗口内最大发起次数（与后端 MVP_RUN_RATE_LIMIT 对齐） */
export const RUN_RATE_LIMIT_PER_MINUTE = 10
export const RUN_RATE_WINDOW_SEC = 60

/**
 * 显式高级步骤 ID（YAML 未写 tier 时的兜底）。
 * 规则：无标记默认 basic；core 高亮默认 advanced；也可写在此表。
 */
export const ADVANCED_STEP_IDS = new Set<string>([
  'market_temperature',
  'fetch_pattern_entry',
  'factor_Investing_strategy_pro',
  'risk-based_strategy',
])

export function resolveStepTier(input: {
  id: string
  tier?: unknown
  highlight?: unknown
}): 'basic' | 'advanced' {
  const raw = String(input.tier ?? '').toLowerCase()
  if (raw === 'advanced' || raw === 'basic') return raw
  if (ADVANCED_STEP_IDS.has(String(input.id))) return 'advanced'
  if (String(input.highlight ?? '') === 'core') return 'advanced'
  return 'basic'
}

export function isAdvancedStep(step: { id: string; tier?: string }): boolean {
  return (step.tier ?? resolveStepTier({ id: step.id })) === 'advanced'
}

export const PLAN_RULES: Record<PlanTier, PlanRule> = {
  free: {
    id: 'free',
    name: 'Free',
    priceYuanPerMonth: 0,
    priceLabel: '¥0',
    dailyRunQuota: 10,
    periodDays: 0,
    purchasable: true,
    capabilities: {
      'workflow.basic': true,
      'workflow.advanced': false,
      'report.export': false,
      'workspace.cloud_save': false,
      'team.seats': false,
    },
    features: [
      '每日好球预览（限 1 条）',
      '观察池 5 只',
      '基础工作流',
      '每天 10 次运行',
    ],
    cta: '使用 Free',
  },
  pro: {
    id: 'pro',
    name: 'Pro',
    priceYuanPerMonth: 99,
    priceLabel: '¥99 / 月',
    dailyRunQuota: 100,
    periodDays: 30,
    purchasable: true,
    capabilities: {
      'workflow.basic': true,
      'workflow.advanced': true,
      'report.export': true,
      'workspace.cloud_save': true,
      'team.seats': false,
    },
    features: [
      '完整好球雷达',
      '观察池 40 只',
      '每天 100 次运行',
      '高级策略',
      '报告导出',
    ],
    cta: '解锁完整好球与观察纪律',
  },
  team: {
    id: 'team',
    name: 'Team',
    priceYuanPerMonth: 0,
    priceLabel: '联系客服',
    dailyRunQuota: -1,
    periodDays: 0,
    purchasable: false,
    capabilities: {
      'workflow.basic': true,
      'workflow.advanced': true,
      'report.export': true,
      'workspace.cloud_save': true,
      'team.seats': true,
    },
    features: ['完整好球与观察池', '不限运行次数', '席位协作', '优先支持'],
    cta: '联系客服',
  },
}

export function planRule(plan: PlanTier): PlanRule {
  return PLAN_RULES[plan]
}

export function hasCapability(plan: PlanTier, key: CapabilityKey): boolean {
  return PLAN_RULES[plan].capabilities[key]
}

export function dailyQuotaLabel(plan: PlanTier): string {
  const q = PLAN_RULES[plan].dailyRunQuota
  return q < 0 ? '不限' : `每天 ${q} 次`
}

/** M3 Onboarding：推荐基础策略 + 当日体验次数 */
export const ONBOARDING_RECOMMENDED_STEP_ID = 'roc_20'
export const ONBOARDING_RECOMMENDED_TITLE = '20日 ROC 排序'
export const ONBOARDING_BONUS_RUNS = 3

export type OnboardingPersonaId = 'investor' | 'researcher' | 'explorer'

export const ONBOARDING_PERSONAS: {
  id: OnboardingPersonaId
  label: string
  hint: string
}[] = [
  { id: 'investor', label: '个人投资者', hint: '想快速筛选与跟踪标的' },
  { id: 'researcher', label: '研究 / 分析', hint: '偏因子与回测链路' },
  { id: 'explorer', label: '先随便看看', hint: '先熟悉平台再定方向' },
]

/** 引导完成后的落地页；默认机会雷达（价值 MVP） */
export function resolveOnboardingLanding(redirect?: unknown): string {
  const radar = '/'
  if (typeof redirect !== 'string' || !redirect.startsWith('/')) return radar
  if (redirect.startsWith('/onboarding')) return radar
  if (redirect === '/' || redirect === '') return radar
  return redirect
}

