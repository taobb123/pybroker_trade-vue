/**
 * 市场温度计工作流运行模式（与 workflow_runner.yaml run_modes 对齐）
 */
export const TEMPERATURE_STEP_ID = 'market_temperature'

export interface TemperatureRunMode {
  id: string
  label: string
  /** 运行时选择说明 */
  summary: string
}

export const TEMPERATURE_RUN_MODES: TemperatureRunMode[] = [
  {
    id: 'daily',
    label: '每日报告',
    summary: '计算当日温度分与建议仓位，写入每日仓位报告。日常看盘用这个。',
  },
  {
    id: 'backtest_fast',
    label: '快速回测',
    summary: '用历史数据验证「温度分 vs 未来收益」，不改仓位映射。用于检验模型是否靠谱。',
  },
  {
    id: 'backtest_calibrate',
    label: '回测并校准',
    summary: '回测后按历史收益重写仓位阶梯（校准 JSON）。会改变之后「每日报告」的仓位建议。',
  },
]
