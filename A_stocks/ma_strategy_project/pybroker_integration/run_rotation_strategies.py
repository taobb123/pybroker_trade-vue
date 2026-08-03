#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
轮动策略主执行文件
运行趋势轮动策略和均值回归轮动策略
"""

import os
import sys

# 获取当前文件所在目录（pybroker_integration目录）
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
# 获取项目根目录（ma_strategy_project目录）
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

# 添加项目根目录到路径（这样可以从项目根目录导入 strategies, utils 等）
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 添加pybroker_integration目录到路径（这样可以从 pybroker_integration 导入模块）
if CURRENT_DIR not in sys.path:
    sys.path.insert(0, CURRENT_DIR)

# 直接导入策略类
# 注意：这里使用直接导入，策略文件中的路径设置应该已经处理好了
from src.strategies.trend_rotation_strategy import TrendRotationStrategy
from src.strategies.mean_reversion_rotation_strategy import MeanReversionRotationStrategy


def main():
    """主函数：运行两个轮动策略"""
    
    # 股票池
    symbols = [
        '600570',
        '600690',
        '000738',
        '601360',
        '601939',
        '002463',
        '603501',
        '600435',
        '603392',
        '600085'
    ]
    
    # 回测参数
    start_date = '20240501'
    end_date = '20251128'
    
    print("=" * 70)
    print("轮动策略回测")
    print("=" * 70)
    
    # ========== 策略1：趋势轮动策略 ==========
    print("\n" + "=" * 70)
    print("策略1：趋势行情轮动策略（MACD + RSI + 成交量）")
    print("=" * 70)
    
    trend_strategy = TrendRotationStrategy(
        max_positions=2,
        rank_threshold=5,
        initial_cash=50000
    )
    
    trend_result = trend_strategy.run_backtest(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        warmup=26,
        result_filename='trend_rotation_result.csv'
    )
    
    print(f"\n趋势策略回测结果:")
    print(f"  总交易数: {len(trend_result.trades)}")
    if len(trend_result.trades) > 0 and not trend_result.metrics_df.empty:
        # 尝试获取总收益（可能的列名：total_return, return, return_pct）
        return_col = None
        for col in ['total_return', 'return', 'return_pct', 'total_return_pct']:
            if col in trend_result.metrics_df.columns:
                return_col = col
                break
        
        if return_col:
            print(f"  总收益: {trend_result.metrics_df[return_col].iloc[0]:.2%}")
        
        # 尝试获取夏普比率（可能的列名：sharpe, sharpe_ratio）
        sharpe_col = None
        for col in ['sharpe', 'sharpe_ratio']:
            if col in trend_result.metrics_df.columns:
                sharpe_col = col
                break
        
        if sharpe_col:
            print(f"  夏普比率: {trend_result.metrics_df[sharpe_col].iloc[0]:.4f}")
        
        # 尝试获取最大回撤（可能的列名：max_dd, max_drawdown, drawdown）
        dd_col = None
        for col in ['max_dd', 'max_drawdown', 'drawdown']:
            if col in trend_result.metrics_df.columns:
                dd_col = col
                break
        
        if dd_col:
            print(f"  最大回撤: {trend_result.metrics_df[dd_col].iloc[0]:.2%}")
        
        # 如果所有指标都找不到，打印可用列（用于调试）
        if not (return_col or sharpe_col or dd_col):
            print(f"  警告: 无法找到标准指标列")
            print(f"  可用指标列: {list(trend_result.metrics_df.columns)}")
    
    # ========== 策略2：均值回归轮动策略 ==========
    print("\n" + "=" * 70)
    print("策略2：震荡行情轮动策略（均值回归）")
    print("=" * 70)
    
    mr_strategy = MeanReversionRotationStrategy(
        max_positions=2,
        rank_threshold=5,
        initial_cash=50000,
        zscore_weight=0.6,
        bollinger_weight=0.4
    )
    
    mr_result = mr_strategy.run_backtest(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        warmup=20,
        result_filename='mean_reversion_rotation_result.csv'
    )
    
    print(f"\n均值回归策略回测结果:")
    print(f"  总交易数: {len(mr_result.trades)}")
    if len(mr_result.trades) > 0 and not mr_result.metrics_df.empty:
        # 尝试获取总收益（可能的列名：total_return, return, return_pct）
        return_col = None
        for col in ['total_return', 'return', 'return_pct', 'total_return_pct']:
            if col in mr_result.metrics_df.columns:
                return_col = col
                break
        
        if return_col:
            print(f"  总收益: {mr_result.metrics_df[return_col].iloc[0]:.2%}")
        
        # 尝试获取夏普比率（可能的列名：sharpe, sharpe_ratio）
        sharpe_col = None
        for col in ['sharpe', 'sharpe_ratio']:
            if col in mr_result.metrics_df.columns:
                sharpe_col = col
                break
        
        if sharpe_col:
            print(f"  夏普比率: {mr_result.metrics_df[sharpe_col].iloc[0]:.4f}")
        
        # 尝试获取最大回撤（可能的列名：max_dd, max_drawdown, drawdown）
        dd_col = None
        for col in ['max_dd', 'max_drawdown', 'drawdown']:
            if col in mr_result.metrics_df.columns:
                dd_col = col
                break
        
        if dd_col:
            print(f"  最大回撤: {mr_result.metrics_df[dd_col].iloc[0]:.2%}")
        
        # 如果所有指标都找不到，打印可用列（用于调试）
        if not (return_col or sharpe_col or dd_col):
            print(f"  警告: 无法找到标准指标列")
            print(f"  可用指标列: {list(mr_result.metrics_df.columns)}")
    
    # ========== 策略对比 ==========
    print("\n" + "=" * 70)
    print("策略对比")
    print("=" * 70)
    
    if (len(trend_result.trades) > 0 and len(mr_result.trades) > 0 and
        not trend_result.metrics_df.empty and not mr_result.metrics_df.empty):
        
        # 获取总收益列名
        trend_return_col = None
        mr_return_col = None
        for col in ['total_return', 'return', 'return_pct', 'total_return_pct']:
            if col in trend_result.metrics_df.columns:
                trend_return_col = col
            if col in mr_result.metrics_df.columns:
                mr_return_col = col
            if trend_return_col and mr_return_col:
                break
        
        if trend_return_col and mr_return_col:
            trend_return = trend_result.metrics_df[trend_return_col].iloc[0]
            mr_return = mr_result.metrics_df[mr_return_col].iloc[0]
            
            print(f"\n总收益对比:")
            print(f"  趋势策略: {trend_return:.2%}")
            print(f"  均值回归策略: {mr_return:.2%}")
            print(f"  差异: {abs(trend_return - mr_return):.2%}")
            
            if trend_return > mr_return:
                print(f"\n✓ 趋势策略表现更好（适合趋势行情）")
            else:
                print(f"\n✓ 均值回归策略表现更好（适合震荡行情）")
        else:
            print(f"\n无法对比总收益（指标列名不匹配）")
    
    print("\n" + "=" * 70)
    print("回测完成！")
    print("=" * 70)
    print("\n结果文件已保存到 data/processed/ 目录")


if __name__ == '__main__':
    main()

