/**
 * 好球规则（无 AI）——与协作纪要 007 默认假设对齐。
 * 缺字段的维度记为 null，不参与综合分（降权省略）。
 */

export type ScoreDimensionKey = 'trend' | 'fundamental' | 'flow' | 'valuation'

export const SCORE_DIMENSION_LABELS: Record<ScoreDimensionKey, string> = {
  trend: '技术趋势',
  fundamental: '基本面',
  flow: '资金',
  valuation: '估值/安全边际',
}

/** 综合分 ≥ 该阈值 →「好球」；否则「等待」 */
export const GOOD_PITCH_THRESHOLD = 80

export type PitchVerdict = 'good' | 'wait'

export function averageScore(scores: Array<number | null | undefined>): number | null {
  const nums = scores.filter((n): n is number => typeof n === 'number' && Number.isFinite(n))
  if (!nums.length) return null
  return Math.round(nums.reduce((a, b) => a + b, 0) / nums.length)
}

export function verdictFromScore(score: number | null): PitchVerdict {
  if (score == null) return 'wait'
  return score >= GOOD_PITCH_THRESHOLD ? 'good' : 'wait'
}

export const VERDICT_LABEL: Record<PitchVerdict, string> = {
  good: '好球',
  wait: '等待',
}

export const DISCLAIMER =
  '本页为规则化研究辅助工具，不构成投资建议。请独立判断并自行承担风险。'
