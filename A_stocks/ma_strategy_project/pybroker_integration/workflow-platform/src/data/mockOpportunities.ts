import type { Opportunity } from '@/domain/opportunity'

/** S1 mock；S4 再接真实产物。用 URL ?empty=1 验收空态。 */
export const MOCK_OPPORTUNITIES: Opportunity[] = [
  {
    id: 'mock-002460',
    symbol: '002460',
    name: '赣锋锂业',
    scores: { trend: 86, fundamental: 78, flow: 82, valuation: 84 },
    thesis: '锂价企稳后的趋势修复，量价与资金同步改善。',
    risk: '商品价格波动仍大，若再度破位需重新评估。',
    stepId: 'roc_20',
    price: 38.6,
    idealLow: 35,
    idealHigh: 39,
  },
  {
    id: 'mock-000063',
    symbol: '000063',
    name: '中兴通讯',
    scores: { trend: 88, fundamental: 85, flow: 80, valuation: 79 },
    thesis: '通信设备景气回升，技术趋势与基本面同向。',
    risk: '估值已不便宜，追高空间有限。',
    stepId: 'roc_20',
    price: 32.1,
    idealLow: 28,
    idealHigh: 31,
  },
  {
    id: 'mock-600519',
    symbol: '600519',
    name: '贵州茅台',
    scores: { trend: 62, fundamental: 92, flow: 55, valuation: 48 },
    thesis: '质量很高，但价格未进入理想区，继续等待。',
    risk: '情绪与政策扰动可能延长等待期。',
    price: 1480,
    idealLow: 1200,
    idealHigh: 1350,
  },
]

/** 半静态市场环境（Q2）；不阻塞 S1 */
export const MOCK_MARKET_ENV = {
  label: '机会区域',
  fearIndex: 38,
  hint: '波动回落，适合提高关注，仍只打好球。',
  asOf: '演示数据',
}
