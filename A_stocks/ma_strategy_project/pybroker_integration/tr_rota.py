#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
独立运行：趋势轮动策略（TrendRotationStrategy）

用法：
    在项目根目录下运行：

        python ma_strategy_project/pybroker_integration/tr_rota.py
"""

import os
import sys
from typing import Dict

import numpy as np
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext

# 获取当前文件所在目录（pybroker_integration 目录）
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录（ma_strategy_project 目录）
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

# 添加项目根目录到路径（这样可以导入 config, data, utils 等顶层模块）
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 添加 pybroker_integration 目录到路径（这样可以导入 src 等子模块）
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

from pybroker_integration.custom_data_source import create_custom_data_source
from src.modules.indicators import ROC_20_INDICATOR


def rank_stocks(ctxs: Dict[str, ExecContext]):
    """
    使用 20 日 ROC 对所有股票进行排名，选出收益率最高的前 N 名。
    逻辑与原趋势轮动策略一致，但这里只用于选择轮动标的。
    """
    roc_scores = {}

    for symbol, ctx in ctxs.items():
        try:
            roc = ctx.indicator('roc_20')[-1]
            if not np.isnan(roc):
                roc_scores[symbol] = roc
            else:
                roc_scores[symbol] = -999.0
        except (IndexError, KeyError, ValueError):
            roc_scores[symbol] = -999.0
            continue

    threshold = pyb.param('rank_threshold')
    # 简单按分数排序取前 N 名
    valid_scores = {
        s: sc for s, sc in roc_scores.items()
        if sc is not None and not np.isnan(sc)
    }
    top_symbols = sorted(
        valid_scores.keys(),
        key=lambda s: valid_scores[s],
        reverse=True
    )[:threshold]

    pyb.param('top_symbols', top_symbols)
    pyb.param('roc_scores', roc_scores)


def execute_trailing_rotation(ctx: ExecContext):
    """
    使用 PyBroker 内置的移动止损功能，替代 MACD/RSI/成交量的趋势轮动执行逻辑。

    规则：
    - 股票池由 20 日 ROC 排名前 N 名决定（轮动逻辑保留）。
    - 当股票在前 rank_threshold（前5名）中且当前无持仓时建仓。
    - 使用 PyBroker 内置的 stop_trailing_pct 来管理风险（移动止损）。
    - 如果股票不再位于前 rank_threshold 名中，则清盘该股票。
    """
    top_symbols = pyb.param('top_symbols')
    if not top_symbols:
        return

    # 参数
    max_positions = pyb.param('max_positions')
    rank_threshold = pyb.param('rank_threshold')
    target_size = pyb.param('target_size')  # 每个持仓资金比例
    trail_pct = pyb.param('trail_pct', 30)  # 移动止损百分比（PyBroker 使用百分比数值，如 20 表示 20%）

    # 前 rank_threshold 名（用于买入和判断是否清盘）
    top_rank_symbols = top_symbols[:rank_threshold]

    if ctx.long_pos():
        # 已有持仓：检查是否还在前 rank_threshold 名中
        # 如果股票不再位于前 rank_threshold 名的 20 天涨幅（ROC）中，则清盘该股票
        if ctx.symbol not in top_rank_symbols:
            ctx.sell_all_shares()
    else:
        # 未持仓：如果股票在前 rank_threshold 名中，则考虑建仓
        # 买入标准：前5名中的任意股票（与 rotation_trade.py 一致）
        if ctx.symbol in top_rank_symbols:
            # 这里不再依赖 MACD/RSI/成交量信号，只要在轮动池中就建仓
            ctx.buy_shares = ctx.calc_target_shares(target_size)
            
            # 使用 PyBroker 内置的移动止损功能：从最高市场价格下跌指定百分比时自动卖出
            ctx.stop_trailing_pct = trail_pct
            
            # 使用 ROC 分数作为排序权重（便于回测报告中查看）
            roc_scores = pyb.param('roc_scores', {})
            ctx.score = roc_scores.get(ctx.symbol, 0.0)


def main():
    """单独运行：基于移动止损的趋势轮动策略。"""

    # 股票池（与文档示例一致）
    symbols = [
        '600570',
        '603194',
        '603019',
        '002352',
        '301626',
        '603501',
        '301626',
        '600085',
        '603596',
        '600085'
    ]

    # 回测参数
    start_date = '20240501'
    end_date = '20251128'

    print("=" * 70)
    print("单独运行：趋势轮动策略（使用 20 日 ROC + 移动止损，替代 MACD/RSI/成交量信号）")
    print("=" * 70)

    # 策略配置：持仓数与资金
    config = StrategyConfig(
        max_long_positions=2,
        initial_cash=50000,
    )

    # 全局参数
    pyb.param('target_size', 0.5)       # 每个持仓 50% 资金
    pyb.param('rank_threshold', 5)       # 从前 5 名中轮动（用于判断是否清盘）
    pyb.param('max_positions', 2)       # 同时持有 2 只
    pyb.param('trail_pct', 20)           # 20% 移动止损（PyBroker 使用百分比数值）

    # 创建数据源
    data_source = create_custom_data_source()

    # 构建 PyBroker 策略
    strategy = Strategy(
        data_source,
        start_date=start_date,
        end_date=end_date,
        config=config,
    )

    # 每个交易日开盘前先做一次 ROC 排名
    strategy.set_before_exec(rank_stocks)

    # 仅需要 ROC 指标用于排名
    strategy.add_execution(
        execute_trailing_rotation,
        symbols,
        indicators=[ROC_20_INDICATOR],
    )

    # 运行回测
    result = strategy.backtest(warmup=20)

    # 保存交易明细到 CSV
    trades_csv_name = 'trend_rotation_result_single.csv'
    result_dir = os.path.join(CURRENT_DIR, 'data', 'processed')
    os.makedirs(result_dir, exist_ok=True)
    trades_path = os.path.join(result_dir, trades_csv_name)
    trades_df = result.trades
    trades_df.to_csv(trades_path, index=False, encoding='utf-8-sig')

    print("\n回测完成！")
    print(f"总交易数: {len(result.trades)}")
    print(f"交易明细已保存到: {trades_path}")

    if len(result.trades) > 0 and not result.metrics_df.empty:
        # 尝试获取总收益（列名可能因 PyBroker 版本不同而变化）
        return_col = None
        for col in ['total_return', 'return', 'return_pct', 'total_return_pct', 'total_pnl']:
            if col in result.metrics_df.columns:
                return_col = col
                break
        if return_col:
            print(f"总收益: {result.metrics_df[return_col].iloc[0]:.2%}")

        # 尝试获取夏普比率
        sharpe_col = None
        for col in ['sharpe', 'sharpe_ratio']:
            if col in result.metrics_df.columns:
                sharpe_col = col
                break
        if sharpe_col:
            print(f"夏普比率: {result.metrics_df[sharpe_col].iloc[0]:.4f}")


if __name__ == '__main__':
    main()


