#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测结果分析模块
计算各种性能指标
"""

import pandas as pd
import numpy as np
from typing import Dict
try:
    from ..utils.logger import logger  # type: ignore
except Exception:  # pragma: no cover
    from utils.logger import logger  # type: ignore


class PerformanceAnalyzer:
    """性能分析器"""
    
    @staticmethod
    def calculate_sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.03, 
                               periods_per_year: int = 252) -> float:
        """
        计算夏普比率
        
        Args:
            returns: 收益率序列
            risk_free_rate: 无风险利率（年化，默认3%）
            periods_per_year: 每年交易周期数（默认252个交易日）
        
        Returns:
            float: 夏普比率
        """
        if returns.empty or returns.std() == 0:
            return 0.0
        
        # 年化收益率
        annual_return = returns.mean() * periods_per_year
        
        # 年化波动率
        annual_volatility = returns.std() * np.sqrt(periods_per_year)
        
        if annual_volatility == 0:
            return 0.0
        
        # 夏普比率
        sharpe = (annual_return - risk_free_rate) / annual_volatility
        
        return sharpe
    
    @staticmethod
    def calculate_max_drawdown(total_value: pd.Series) -> Dict:
        """
        计算最大回撤
        
        Args:
            total_value: 总资产序列
        
        Returns:
            dict: 包含max_drawdown, max_drawdown_pct, drawdown_period等信息
        """
        if total_value.empty:
            return {
                'max_drawdown': 0.0,
                'max_drawdown_pct': 0.0,
                'drawdown_days': 0
            }
        
        # 计算累积最高值
        cumulative_max = total_value.expanding().max()
        
        # 计算回撤
        drawdown = cumulative_max - total_value
        drawdown_pct = (drawdown / cumulative_max) * 100
        
        # 最大回撤
        max_dd = drawdown.max()
        max_dd_pct = drawdown_pct.max()
        
        # 找到最大回撤的期间
        max_dd_idx = drawdown.idxmax()
        if pd.notna(max_dd_idx):
            # 找到回撤开始点（最高点）
            # 检查切片是否为空，避免空序列错误
            peak_slice = cumulative_max[:max_dd_idx]
            if not peak_slice.empty:
                peak_idx = peak_slice.idxmax()
                if pd.notna(peak_idx):
                    try:
                        drawdown_days = (max_dd_idx - peak_idx).days if hasattr(max_dd_idx - peak_idx, 'days') else 0
                    except (AttributeError, TypeError):
                        # 如果不是日期类型，尝试计算索引差
                        try:
                            drawdown_days = (peak_slice.index.get_loc(max_dd_idx) - peak_slice.index.get_loc(peak_idx)) if peak_idx in peak_slice.index else 0
                        except (KeyError, ValueError):
                            drawdown_days = 0
                else:
                    drawdown_days = 0
            else:
                drawdown_days = 0
        else:
            drawdown_days = 0
        
        return {
            'max_drawdown': float(max_dd),
            'max_drawdown_pct': float(max_dd_pct),
            'drawdown_days': drawdown_days
        }
    
    @staticmethod
    def calculate_annual_return(total_return: float, periods: int, periods_per_year: int = 252) -> float:
        """
        计算年化收益率
        
        Args:
            total_return: 总收益率（小数形式，如0.1表示10%）
            periods: 总周期数
            periods_per_year: 每年周期数
        
        Returns:
            float: 年化收益率（百分比）
        """
        if periods == 0:
            return 0.0
        
        years = periods / periods_per_year
        if years <= 0:
            return 0.0
        
        # 年化收益率
        annual_return = ((1 + total_return / 100) ** (1 / years) - 1) * 100
        
        return annual_return
    
    @staticmethod
    def analyze(results: Dict) -> Dict:
        """
        全面分析回测结果
        
        Args:
            results: 回测结果字典（BacktestEngine.run()的返回值）
        
        Returns:
            dict: 包含所有性能指标的字典
        """
        data = results['data']
        
        if data.empty:
            logger.warning("数据为空，无法分析")
            return {}
        
        # 基础指标
        initial_capital = results['initial_capital']
        final_value = results['final_value']
        total_return = results['total_return']
        num_trades = results['num_trades']
        
        # 计算收益率序列
        returns = data['returns']
        
        # 夏普比率
        sharpe_ratio = PerformanceAnalyzer.calculate_sharpe_ratio(returns)
        
        # 最大回撤
        drawdown_info = PerformanceAnalyzer.calculate_max_drawdown(data['total'])
        
        # 年化收益率
        periods = len(data)
        annual_return = PerformanceAnalyzer.calculate_annual_return(
            total_return, periods
        )
        
        # 胜率（如果有多笔交易）
        win_rate = 0.0
        if num_trades > 0 and 'trades' in results:
            trades = results['trades']
            buy_trades = [t for t in trades if t['type'] == 'BUY']
            sell_trades = [t for t in trades if t['type'] == 'SELL']
            
            if len(sell_trades) > 0:
                profitable_trades = sum(1 for t in sell_trades if t.get('pnl', 0) > 0)
                win_rate = (profitable_trades / len(sell_trades)) * 100
        
        # 平均盈亏（仅考虑卖出的交易）
        avg_profit = 0.0
        if num_trades > 0 and 'trades' in results:
            sell_trades = [t for t in results['trades'] if t['type'] == 'SELL' and 'pnl' in t]
            if len(sell_trades) > 0:
                avg_profit = np.mean([t['pnl'] for t in sell_trades])
        
        # 整理分析结果
        analysis = {
            'initial_capital': float(initial_capital),
            'final_value': float(final_value),
            'total_return': float(total_return),
            'annual_return': float(annual_return),
            'sharpe_ratio': float(sharpe_ratio),
            'max_drawdown': drawdown_info['max_drawdown'],
            'max_drawdown_pct': drawdown_info['max_drawdown_pct'],
            'drawdown_days': drawdown_info['drawdown_days'],
            'num_trades': num_trades,
            'win_rate': float(win_rate),
            'avg_profit': float(avg_profit),
            'periods': periods
        }
        
        logger.info(f"性能分析完成: 总收益率={total_return:.2f}%, 夏普比率={sharpe_ratio:.2f}")
        
        return analysis
    
    @staticmethod
    def print_report(analysis: Dict):
        """
        打印回测报告
        
        Args:
            analysis: 分析结果字典
        """
        print("\n" + "="*70)
        print("回测结果报告")
        print("="*70)
        print(f"\n【资金情况】")
        print(f"  初始资金: {analysis['initial_capital']:,.2f} 元")
        print(f"  最终资产: {analysis['final_value']:,.2f} 元")
        print(f"  总收益率: {analysis['total_return']:+.2f}%")
        print(f"  年化收益率: {analysis['annual_return']:+.2f}%")
        
        print(f"\n【风险指标】")
        print(f"  夏普比率: {analysis['sharpe_ratio']:.2f}")
        print(f"  最大回撤: {analysis['max_drawdown']:,.2f} 元 ({analysis['max_drawdown_pct']:.2f}%)")
        if analysis['drawdown_days'] > 0:
            print(f"  回撤持续天数: {analysis['drawdown_days']} 天")
        
        print(f"\n【交易统计】")
        print(f"  交易次数: {analysis['num_trades']} 笔")
        if analysis['num_trades'] > 0:
            print(f"  胜率: {analysis['win_rate']:.2f}%")
            print(f"  平均盈亏: {analysis['avg_profit']:+.2f} 元")
        
        print(f"\n【数据信息】")
        print(f"  回测周期: {analysis['periods']} 个交易日")
        print("="*70 + "\n")





