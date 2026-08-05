import {
  averageScore,
  verdictFromScore,
  type PitchVerdict,
  type ScoreDimensionKey,
} from '@/config/opportunityRules'

export interface OpportunityScores {
  trend: number | null
  fundamental: number | null
  flow: number | null
  valuation: number | null
}

export interface Opportunity {
  id: string
  symbol: string
  name: string
  /** 分项；缺数据为 null */
  scores: OpportunityScores
  /** 一句上涨/等待逻辑 */
  thesis: string
  /** 一句风险 */
  risk: string
  /** 可选：跳转工作流 */
  stepId?: string
  /** 可选：现价 / 理想买入区（S2 观察池会用；S1 展示） */
  price?: number
  idealLow?: number
  idealHigh?: number
}

export interface ScoredOpportunity extends Opportunity {
  composite: number | null
  verdict: PitchVerdict
  dimensions: ScoreDimensionKey[]
}

export function scoreOpportunity(op: Opportunity): ScoredOpportunity {
  const dims: ScoreDimensionKey[] = ['trend', 'fundamental', 'flow', 'valuation']
  const composite = averageScore([
    op.scores.trend,
    op.scores.fundamental,
    op.scores.flow,
    op.scores.valuation,
  ])
  return {
    ...op,
    composite,
    verdict: verdictFromScore(composite),
    dimensions: dims,
  }
}
