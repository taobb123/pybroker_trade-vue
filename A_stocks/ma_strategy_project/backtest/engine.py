#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测引擎
模拟交易执行，计算回测结果
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional
from strategies.base import BaseStrategy
from config.settings import BACKTEST_CONFIG
from utils.logger import logger


class BacktestEngine:
    """回测引擎"""
    
    def __init__(self, strategy: BaseStrategy, 
                 initial_capital: float = None,
                 commission: float = None):
        """
        初始化回测引擎
        
        Args:
            strategy: 策略对象
            initial_capital: 初始资金（默认从配置读取）
            commission: 手续费率（默认从配置读取）
        """
        self.strategy = strategy
        self.initial_capital = initial_capital or BACKTEST_CONFIG['initial_capital']
        self.commission = commission or BACKTEST_CONFIG['commission']
        
        logger.info(f"初始化回测引擎: 初始资金={self.initial_capital}, 手续费率={self.commission}")
    
    def run(self, data: pd.DataFrame, 
            initial_capital: float = None,
            commission: float = None) -> Dict:
        """
        运行回测
        
        Args:
            data: 包含OHLC数据的DataFrame
            initial_capital: 初始资金（可选，覆盖默认值）
            commission: 手续费率（可选，覆盖默认值）
        
        Returns:
            dict: 回测结果字典，包含：
                - data: 包含回测结果的DataFrame
                - trades: 交易记录列表
                - final_value: 最终资产
                - total_return: 总收益率
                - sharpe_ratio: 夏普比率
                - max_drawdown: 最大回撤
        """
        # 使用传入参数或默认值
        capital = initial_capital or self.initial_capital
        comm = commission or self.commission
        
        logger.info(f"开始回测: 策略={self.strategy.name}, 数据量={len(data)}")
        
        # 生成交易信号
        data_with_signals = self.strategy.generate_signals(data)
        
        # 检查是否有信号
        if 'signal' not in data_with_signals.columns:
            raise ValueError("策略未生成signal列")
        
        # 初始化持仓和资金记录
        positions = pd.DataFrame(index=data_with_signals.index)
        positions['date'] = data_with_signals['date']
        positions['cash'] = capital
        positions['stock'] = 0  # 持有股票数量
        positions['holdings'] = 0.0  # 持仓市值
        positions['total'] = capital  # 总资产
        
        # 交易记录
        trades = []
        current_position = 0  # 当前持仓数量
        entry_price = 0.0  # 买入价格
        
        # 遍历每一天，模拟交易
        for i in range(len(data_with_signals)):
            current_row = data_with_signals.iloc[i]
            current_price = current_row['close']
            current_date = current_row['date']
            
            # 获取持仓信息（前一天）
            if i > 0:
                cash = positions.iloc[i-1]['cash']
                stock = positions.iloc[i-1]['stock']
            else:
                cash = capital
                stock = 0
            
            # 检查是否有交易信号
            signal = current_row.get('signal', 0)
            positions_change = current_row.get('positions', 0)
            
            # 买入信号（开仓或加仓）
            if positions_change > 0 and stock == 0:  # 买入
                # 计算可买入数量（考虑手续费）
                available_cash = cash * (1 - comm)  # 预留手续费
                shares = int(available_cash / current_price)
                
                if shares > 0:
                    # 计算实际成本（含手续费）
                    cost = shares * current_price * (1 + comm)
                    
                    if cost <= cash:
                        stock = shares
                        cash = cash - cost
                        entry_price = current_price
                        
                        # 记录交易
                        trades.append({
                            'date': current_date,
                            'type': 'BUY',
                            'price': current_price,
                            'shares': shares,
                            'cost': cost,
                            'cash_after': cash
                        })
                        
                        logger.debug(f"{current_date}: 买入 {shares}股 @ {current_price:.2f}")
            
            # 卖出信号（平仓）
            elif positions_change < 0 and stock > 0:  # 卖出
                # 计算卖出收入（扣除手续费）
                proceeds = stock * current_price * (1 - comm)
                cash = cash + proceeds
                
                # 记录交易
                trades.append({
                    'date': current_date,
                    'type': 'SELL',
                    'price': current_price,
                    'shares': stock,
                    'proceeds': proceeds,
                    'pnl': proceeds - stock * entry_price,  # 盈亏
                    'cash_after': cash
                })
                
                logger.debug(f"{current_date}: 卖出 {stock}股 @ {current_price:.2f}")
                stock = 0
                entry_price = 0.0
            
            # 更新持仓记录
            holdings_value = stock * current_price
            total_value = cash + holdings_value
            
            positions.iloc[i, positions.columns.get_loc('cash')] = cash
            positions.iloc[i, positions.columns.get_loc('stock')] = stock
            positions.iloc[i, positions.columns.get_loc('holdings')] = holdings_value
            positions.iloc[i, positions.columns.get_loc('total')] = total_value
        
        # 合并数据
        result_data = data_with_signals.copy()
        result_data['cash'] = positions['cash'].values
        result_data['holdings'] = positions['holdings'].values
        result_data['total'] = positions['total'].values
        
        # 计算收益率
        result_data['returns'] = result_data['total'].pct_change().fillna(0)
        
        # 计算最终结果
        final_value = result_data['total'].iloc[-1]
        total_return = (final_value / capital - 1) * 100
        
        logger.info(f"回测完成: 初始资金={capital:.2f}, 最终资产={final_value:.2f}, 总收益率={total_return:.2f}%")
        
        return {
            'data': result_data,
            'trades': trades,
            'initial_capital': capital,
            'final_value': final_value,
            'total_return': total_return,
            'num_trades': len(trades),
        }





