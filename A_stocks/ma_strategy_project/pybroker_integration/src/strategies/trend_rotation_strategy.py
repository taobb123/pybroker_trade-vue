#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
趋势行情轮动策略
使用MACD、RSI、成交量指标，适用于趋势行情
"""

import os
import sys
import numpy as np
import pybroker as pyb
from pybroker import Strategy, StrategyConfig, ExecContext
from typing import Dict

# 添加项目根目录到路径（ma_strategy_project）
PROJECT_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(
            os.path.dirname(os.path.abspath(__file__))
        )
    )
)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 添加 pybroker_integration 目录到路径（放在项目根之后，避免覆盖顶层 config 包）
PYBROKER_ROOT = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)
if PYBROKER_ROOT not in sys.path:
    # 使用 append 保持 PROJECT_ROOT 在前
    sys.path.append(PYBROKER_ROOT)

from pybroker_integration.custom_data_source import create_custom_data_source
from src.modules.indicators import (
    MACD_INDICATOR,
    MACD_SIGNAL_INDICATOR,
    MACD_HIST_INDICATOR,
    RSI_INDICATOR,
    VOLUME_RATIO_INDICATOR,
    ROC_20_INDICATOR,
    TREND_INDICATORS
)
from src.modules.signals import (
    check_trend_buy_signal,
    check_trend_sell_signal,
    rank_stocks_by_score
)


class TrendRotationStrategy:
    """
    趋势行情轮动策略
    
    策略逻辑：
    1. 使用MACD、RSI、成交量计算每只股票的综合评分
    2. 选择评分最高的N只股票进行轮动
    3. 如果持有的股票不在前N名中，则卖出
    4. 如果股票在前N名中且未持有，则买入
    """
    
    def __init__(
        self,
        max_positions: int = 2,
        rank_threshold: int = 5,
        initial_cash: float = 50000
    ):
        """
        初始化策略
        
        Args:
            max_positions: 最大持仓数量
            rank_threshold: 排名阈值（从前N名中选择）
            initial_cash: 初始资金
        """
        self.max_positions = max_positions
        self.rank_threshold = rank_threshold
        self.initial_cash = initial_cash
        
        # 设置策略配置
        self.config = StrategyConfig(
            max_long_positions=max_positions,
            initial_cash=initial_cash
        )
        
        # 设置参数
        pyb.param('target_size', 0.5)  # 每个持仓分配50%资金
        pyb.param('rank_threshold', rank_threshold)
        pyb.param('max_positions', max_positions)
    
    def rank_stocks(self, ctxs: Dict[str, ExecContext]):
        """
        对所有股票进行排名（基于过去20天的收益率ROC）
        
        Args:
            ctxs: 所有股票的执行上下文字典
        """
        roc_scores = {}
        
        for symbol, ctx in ctxs.items():
            try:
                # 获取ROC（20天收益率）作为排名依据
                roc = ctx.indicator('roc_20')[-1]
                
                # 如果ROC有效，保存
                if not np.isnan(roc):
                    roc_scores[symbol] = roc
                else:
                    roc_scores[symbol] = -999.0  # 无效值设为很小的数
                    
            except (IndexError, KeyError, ValueError) as e:
                # 如果指标计算失败，设为很小的值
                roc_scores[symbol] = -999.0
                continue
        
        # 根据ROC排名，获取前N名（收益率最高的）
        threshold = pyb.param('rank_threshold')
        top_symbols = rank_stocks_by_score(roc_scores, top_n=threshold)
        
        # 保存排名结果
        pyb.param('top_symbols', top_symbols)
        pyb.param('roc_scores', roc_scores)
    
    def execute_rotation(self, ctx: ExecContext):
        """
        执行轮动交易
        使用指标判断买卖点，使用ROC排名选择股票池
        
        Args:
            ctx: 当前股票的执行上下文
        """
        top_symbols = pyb.param('top_symbols')
        if top_symbols is None:
            return
        
        # 获取指标值用于判断买卖点
        try:
            macd = ctx.indicator('macd_12_26_9')[-1]
            macd_signal = ctx.indicator('macd_signal_12_26_9')[-1]
            macd_hist = ctx.indicator('macd_hist_12_26_9')[-1]
            rsi = ctx.indicator('rsi_14')[-1]
            volume_ratio = ctx.indicator('volume_ratio_20')[-1]
            cmma_20 = ctx.indicator('cmma_20')[-1]
        except (IndexError, KeyError, ValueError):
            # 如果指标获取失败，不执行交易
            return
        
        if ctx.long_pos():
            # 如果持有股票
            # 条件1：不在前5名中，则卖出
            if ctx.symbol not in top_symbols:
                ctx.sell_all_shares()
            # 条件2：在前5名中，但指标显示卖出信号，则卖出
            elif check_trend_sell_signal(macd, macd_signal, macd_hist, rsi):
                ctx.sell_all_shares()
        else:
            # 如果未持有股票
            # 条件1：在前2名中（分配资金的前2名）
            max_positions = pyb.param('max_positions')
            top_2_symbols = top_symbols[:max_positions]
            
            if ctx.symbol in top_2_symbols:
                # 条件2：指标显示买入信号，且CMMA < 0（价格低于20日均线）
                if check_trend_buy_signal(macd, macd_signal, macd_hist, rsi, volume_ratio) and cmma_20 < 0:
                    target_size = pyb.param('target_size')  # 0.5 (50%)
                    ctx.buy_shares = ctx.calc_target_shares(target_size)
                    
                    # 设置ROC评分（用于排序）
                    roc_scores = pyb.param('roc_scores', {})
                    ctx.score = roc_scores.get(ctx.symbol, 0.0)
    
    def run_backtest(
        self,
        symbols: list,
        start_date: str,
        end_date: str,
        warmup: int = 26,
        save_result: bool = True,
        result_filename: str = 'trend_rotation_result.csv'
    ):
        """
        运行回测
        
        Args:
            symbols: 股票代码列表
            start_date: 开始日期（格式：YYYYMMDD）
            end_date: 结束日期（格式：YYYYMMDD）
            warmup: 预热期（Bar数量），默认26（确保MACD等指标有足够数据）
            save_result: 是否保存结果，默认True
            result_filename: 结果文件名，默认'trend_rotation_result.csv'
        
        Returns:
            pybroker.BacktestResult: 回测结果
        """
        # 创建数据源
        data_source = create_custom_data_source()
        
        # 创建策略
        strategy = Strategy(
            data_source,
            start_date=start_date,
            end_date=end_date,
            config=self.config
        )
        
        # 设置排名函数（在执行前运行）
        strategy.set_before_exec(self.rank_stocks)
        
        # 添加执行函数和指标（包括ROC指标用于排名）
        all_indicators = TREND_INDICATORS + [ROC_20_INDICATOR]
        strategy.add_execution(
            self.execute_rotation,
            symbols,
            indicators=all_indicators
        )
        
        # 运行回测
        result = strategy.backtest(warmup=warmup)
        
        # 保存结果
        if save_result:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            result_dir = os.path.join(script_dir, '../../data/processed')
            os.makedirs(result_dir, exist_ok=True)
            csv_file = os.path.join(result_dir, result_filename)
            trades_df = result.trades
            trades_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
            print(f"回测结果已保存到: {csv_file}")
        
        return result


if __name__ == '__main__':
    # 示例：运行趋势轮动策略
    strategy = TrendRotationStrategy(
        max_positions=2,
        rank_threshold=5,
        initial_cash=50000
    )
    
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
    
    result = strategy.run_backtest(
        symbols=symbols,
        start_date='20240501',
        end_date='20251128',
        warmup=26
    )
    
    print("\n回测完成！")
    print(f"总交易数: {len(result.trades)}")
    if len(result.trades) > 0 and not result.metrics_df.empty:
        # 尝试获取总收益
        return_col = None
        for col in ['total_pnl ', 'initial_market_value ', 'end_market_value ', 'total_return_pct']:
            if col in result.metrics_df.columns:
                return_col = col
                break
        if return_col:
            print(f"总收益: {result.metrics_df[return_col].iloc[0]:.2%}")
        
        # 尝试获取夏普比率
        sharpe_col = None
        for col in ['sharpe', 'sortino']:
            if col in result.metrics_df.columns:
                sharpe_col = col
                break
        if sharpe_col:
            print(f"夏普比率: {result.metrics_df[sharpe_col].iloc[0]:.4f}")

