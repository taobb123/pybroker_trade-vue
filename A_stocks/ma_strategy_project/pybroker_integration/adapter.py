#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PyBroker 适配器
将现有策略转换为 PyBroker 格式
"""

try:
    import pybroker as pb  # type: ignore
except ImportError:
    pb = None  # type: ignore
import os
import sys
import pandas as pd
import numpy as np
from typing import Dict, Optional, Callable

# 添加项目根目录到路径，以便导入 strategies 和 utils
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from strategies.base import BaseStrategy
    from strategies.moving_average import MovingAverageStrategy
    from strategies.mean_reversion import MeanReversionStrategy
    from utils.logger import logger
except ImportError:
    # 如果导入失败，设置为 None（适配器可能不会被使用）
    BaseStrategy = None
    MovingAverageStrategy = None
    MeanReversionStrategy = None
    logger = None


class PyBrokerAdapter:
    """PyBroker 适配器类，用于将现有策略转换为 PyBroker 格式"""
    
    def __init__(self, strategy: BaseStrategy, initial_cash: float = 100000, 
                 commission: float = 0.001):
        """
        初始化适配器
        
        Args:
            strategy: 策略对象（MovingAverageStrategy 或 MeanReversionStrategy）
            initial_cash: 初始资金
            commission: 手续费率
        """
        if pb is None:
            raise ImportError("PyBroker 未安装，请运行: pip install -U lib-pybroker")
        
        if BaseStrategy is None or MovingAverageStrategy is None or MeanReversionStrategy is None:
            raise ImportError(
                "无法导入策略模块。请确保项目根目录的 strategies 模块可用。\n"
                "如果不需要使用适配器，可以直接使用 PyBroker 策略。"
            )
        
        self.strategy = strategy
        self.initial_cash = initial_cash
        self.commission = commission
        self.pybroker_strategy = None
        
        # 根据策略类型创建 PyBroker 策略函数
        if isinstance(strategy, MovingAverageStrategy):
            self.pybroker_strategy = self._create_ma_strategy()
        elif isinstance(strategy, MeanReversionStrategy):
            self.pybroker_strategy = self._create_mr_strategy()
        else:
            raise ValueError(f"不支持的策略类型: {type(strategy)}")
    
    def _create_ma_strategy(self) -> Callable:
        """创建移动平均策略的 PyBroker 版本"""
        strategy = self.strategy
        
        def ma_strategy(ctx):
            """
            PyBroker 移动平均策略
            
            Args:
                ctx: PyBroker 执行上下文对象
            """
            # 计算移动平均线（使用 PyBroker 的内置函数）
            short_window = strategy.short_window
            long_window = strategy.long_window
            
            # 使用 PyBroker 的指标函数计算均线
            # ctx.sma() 或 ctx.indicators 可能可用，这里使用通用方法
            try:
                # 尝试使用 PyBroker 的内置函数
                ma_short = ctx.sma('close', short_window)
                ma_long = ctx.sma('close', long_window)
            except AttributeError:
                # 如果不可用，使用数据计算
                data = ctx.data
                if len(data) < long_window:
                    return
                ma_short_series = data['close'].rolling(window=short_window, min_periods=1).mean()
                ma_long_series = data['close'].rolling(window=long_window, min_periods=1).mean()
                ma_short = ma_short_series.iloc[-1]
                ma_long = ma_long_series.iloc[-2] if len(data) >= 2 else ma_long_series.iloc[-1]
                prev_ma_short = ma_short_series.iloc[-2] if len(data) >= 2 else ma_short
                prev_ma_long = ma_long_series.iloc[-2] if len(data) >= 2 else ma_long
            else:
                # 获取前一个值（需要访问历史数据）
                data = ctx.data
                if len(data) < 2:
                    return
                prev_ma_short_series = data['close'].rolling(window=short_window, min_periods=1).mean()
                prev_ma_long_series = data['close'].rolling(window=long_window, min_periods=1).mean()
                prev_ma_short = prev_ma_short_series.iloc[-2] if len(data) >= 2 else ma_short
                prev_ma_long = prev_ma_long_series.iloc[-2] if len(data) >= 2 else ma_long
            
            # 判断交叉
            cross_up = (prev_ma_short <= prev_ma_long) and (ma_short > ma_long)
            cross_down = (prev_ma_short >= prev_ma_long) and (ma_short < ma_long)
            
            # 生成信号
            if strategy.reverse_signals:
                # 反转模式：上穿买入，下穿卖出
                if cross_up and ctx.long_positions() == 0:
                    # 计算买入股数（全仓）
                    shares = int(ctx.cash / ctx.close)
                    if shares > 0:
                        ctx.buy_shares = shares
                elif cross_down and ctx.long_positions() > 0:
                    ctx.sell_all_shares()  # 全部卖出
            else:
                # 默认模式：下穿买入（超跌买入），上穿卖出（超涨卖出）
                if cross_down and ctx.long_positions() == 0:
                    # 计算买入股数（全仓）
                    shares = int(ctx.cash / ctx.close)
                    if shares > 0:
                        ctx.buy_shares = shares
                elif cross_up and ctx.long_positions() > 0:
                    ctx.sell_all_shares()  # 全部卖出
        
        return ma_strategy
    
    def _create_mr_strategy(self) -> Callable:
        """创建均值回归策略的 PyBroker 版本"""
        strategy = self.strategy
        
        def mr_strategy(ctx: pb.ExecContext):
            """
            PyBroker 均值回归策略
            
            Args:
                ctx: PyBroker 执行上下文对象
            """
            # 获取历史数据
            data = ctx.data
            
            # 获取策略参数
            window = strategy.window
            entry_z = strategy.entry_z
            exit_z = strategy.exit_z
            
            # 确保有足够的数据
            if len(data) < window:
                return
            
            # 计算均值和标准差
            mean = data['close'].rolling(window=window, min_periods=1).mean().iloc[-1]
            std = data['close'].rolling(window=window, min_periods=1).std().iloc[-1]
            
            if std == 0:
                return
            
            # 计算 Z-score
            current_price = ctx.close
            z_score = (current_price - mean) / std
            
            # 生成信号
            # 超跌买入（z_score < -entry_z）
            if z_score < -entry_z and ctx.long_positions() == 0:
                # 计算买入股数（全仓）
                shares = int(ctx.cash / ctx.close)
                if shares > 0:
                    ctx.buy_shares = shares
            # 超涨卖出（z_score > exit_z）
            elif z_score > exit_z and ctx.long_positions() > 0:
                ctx.sell_all_shares()  # 全部卖出
        
        return mr_strategy
    
    def run_backtest(self, data: pd.DataFrame, start_date: str, end_date: str,
                     symbol: str = 'STOCK') -> Dict:
        """
        运行 PyBroker 回测
        
        Args:
            data: 包含 OHLCV 数据的 DataFrame
            start_date: 开始日期
            end_date: 结束日期
            symbol: 股票代码
        
        Returns:
            dict: 回测结果
        """
        try:
            # 准备数据格式（PyBroker 需要 date, open, high, low, close, volume）
            pybroker_data = data.copy()
            
            # 确保日期列为 datetime 类型
            if 'date' in pybroker_data.columns:
                pybroker_data['date'] = pd.to_datetime(pybroker_data['date'])
                pybroker_data = pybroker_data.set_index('date')
            
            # 重命名列以匹配 PyBroker 格式（如果需要）
            # PyBroker 通常使用 date 作为索引，列名为 open, high, low, close, volume
            
            # 配置策略
            config = pb.StrategyConfig(
                strategy=self.pybroker_strategy,
                symbols=[symbol],
                start_date=start_date,
                end_date=end_date,
                initial_cash=self.initial_cash,
                commission=self.commission,
            )
            
            # 注册自定义数据源
            @pb.data_source(symbols=[symbol])
            def custom_data_source(symbol: str, start_date: str, end_date: str):
                """自定义数据源"""
                # 过滤数据到指定日期范围
                filtered_data = pybroker_data[
                    (pybroker_data.index >= pd.to_datetime(start_date)) &
                    (pybroker_data.index <= pd.to_datetime(end_date))
                ]
                return filtered_data
            
            # 运行回测
            result = pb.run_backtest(config)
            
            logger.info(f"PyBroker 回测完成: 策略={self.strategy.name}")
            
            return {
                'result': result,
                'config': config,
            }
            
        except Exception as e:
            logger.error(f"PyBroker 回测失败: {e}")
            raise


def convert_strategy_to_pybroker(strategy: BaseStrategy, 
                                 initial_cash: float = 100000,
                                 commission: float = 0.001) -> PyBrokerAdapter:
    """
    将现有策略转换为 PyBroker 适配器
    
    Args:
        strategy: 策略对象
        initial_cash: 初始资金
        commission: 手续费率
    
    Returns:
        PyBrokerAdapter: PyBroker 适配器对象
    """
    return PyBrokerAdapter(strategy, initial_cash, commission)

