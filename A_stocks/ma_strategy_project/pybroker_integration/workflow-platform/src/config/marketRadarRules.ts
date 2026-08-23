/**
 * 盘中市场雷达灯号阈值 —— 与 pybroker_integration/market_radar.py 对齐。
 */

export const RS_STRONG_INDEX = 0.5
export const RS_WEAK_INDEX = -1.0
export const VOLUME_SURGE = 0.3
export const LAG_SECTOR = -2.0
export const INDEX_LAMP_BAND = 0.3

export const POLL_MS = 60_000
export const MAX_RADAR_SYMBOLS = 40

export type RadarLamp = 'strong' | 'watch' | 'weak' | 'unknown'
export type RadarSession = 'open' | 'closed'

export const LAMP_LABEL: Record<RadarLamp, string> = {
  strong: '强',
  watch: '观察',
  weak: '弱',
  unknown: '—',
}
