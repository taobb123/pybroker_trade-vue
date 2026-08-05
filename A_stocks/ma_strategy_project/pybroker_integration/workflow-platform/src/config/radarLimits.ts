/**
 * 机会雷达 / 观察池 价值层配额（与套餐对齐，无 AI）
 */
import type { PlanTier } from '@/stores/auth'

export interface RadarPlanLimit {
  /** 今日好球可见条数；-1 = 不限 */
  maxGoodPitches: number
  /** 观察池容量；-1 = 不限（仍受本地硬顶） */
  maxWatchlist: number
  /** 选球卡内 K 线 + 做 T 档位是否清晰可见 */
  clearPitchKlineLevels: boolean
}

export const RADAR_PLAN_LIMITS: Record<PlanTier, RadarPlanLimit> = {
  free: { maxGoodPitches: 1, maxWatchlist: 5, clearPitchKlineLevels: false },
  pro: { maxGoodPitches: -1, maxWatchlist: 40, clearPitchKlineLevels: true },
  team: { maxGoodPitches: -1, maxWatchlist: 40, clearPitchKlineLevels: true },
}

export function radarLimit(plan: PlanTier): RadarPlanLimit {
  return RADAR_PLAN_LIMITS[plan] ?? RADAR_PLAN_LIMITS.free
}

export function canSeePitchKlineLevels(plan: PlanTier): boolean {
  return radarLimit(plan).clearPitchKlineLevels
}

export const UPGRADE_VALUE_CTA = '解锁完整好球与观察纪律'
export const UPGRADE_KLINE_LEVELS_CTA = 'K 线与做 T 档位为 Pro 权限'