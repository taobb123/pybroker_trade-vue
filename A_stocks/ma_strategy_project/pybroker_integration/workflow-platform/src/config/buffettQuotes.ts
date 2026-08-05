/**
 * 巴菲特（及格雷厄姆）经典表述——用于机会雷达价值传达，非投资建议。
 */

export type BuffettPrinciple = 'competence' | 'margin' | 'pitch' | 'temperament'

export const PRINCIPLE_LABEL: Record<BuffettPrinciple, string> = {
  competence: '能力圈',
  margin: '安全边际',
  pitch: '等待好球',
  temperament: '情绪纪律',
}

export interface BuffettQuote {
  id: string
  text: string
  attribution: string
  principle: BuffettPrinciple
  /** 一句话落在本产品上的含义 */
  productHint: string
}

export const BUFFETT_QUOTES: BuffettQuote[] = [
  {
    id: 'pitch-1',
    text: '股市是没有好球必打的棒球场——好球才挥棒，坏球可以放过。',
    attribution: '沃伦·巴菲特',
    principle: 'pitch',
    productHint: '所以我们问「今天有没有好球？」而不是「今天该买什么」。',
  },
  {
    id: 'greed-1',
    text: '别人贪婪时我恐惧，别人恐惧时我贪婪。',
    attribution: '沃伦·巴菲特',
    principle: 'temperament',
    productHint: '观察池帮你把冲动先「挂起」，等规则与价格都到位再行动。',
  },
  {
    id: 'competence-1',
    text: '风险来自你不知道自己在做什么。',
    attribution: '沃伦·巴菲特',
    principle: 'competence',
    productHint: '只展示平台能覆盖、可解释的机会，不装全能行情站。',
  },
  {
    id: 'margin-1',
    text: '安全边际是投资中的核心概念——价格显著低于价值时才买。',
    attribution: '本杰明·格雷厄姆 / 巴菲特传承',
    principle: 'margin',
    productHint: '理想买入区未到，状态就是「等待」，不是勉强出手。',
  },
  {
    id: 'pitch-2',
    text: '我们不必对每一个球挥棒；错过机会不可怕，做错才可怕。',
    attribution: '沃伦·巴菲特（意译）',
    principle: 'pitch',
    productHint: '「今日无好球」是功能：允许你合法地不交易。',
  },
  {
    id: 'temperament-2',
    text: '投资成功不需要天才智商，需要的是 temperament——情绪稳定的性情。',
    attribution: '沃伦·巴菲特',
    principle: 'temperament',
    productHint: '用规则评分替代盘感，减少被涨跌牵着走。',
  },
]

/** 按日期轮换，同一天内稳定 */
export function quoteOfDay(date = new Date()): BuffettQuote {
  const start = new Date(date.getFullYear(), 0, 0)
  const day = Math.floor((date.getTime() - start.getTime()) / 86_400_000)
  return BUFFETT_QUOTES[day % BUFFETT_QUOTES.length]!
}
