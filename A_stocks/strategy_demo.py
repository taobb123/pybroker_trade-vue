#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
量化交易策略示例
结合现有的manage_stocks.py系统实现自动化交易策略
"""

from manage_stocks import StockManager
import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class TradingStrategy:
    """交易策略基类"""
    
    def __init__(self, manager):
        self.manager = manager
    
    def calculate_signals(self, stock_code, lookback_days=60):
        """计算交易信号
        
        Args:
            stock_code: 股票代码
            lookback_days: 回溯天数
            
        Returns:
            signal: 1=买入, -1=卖出, 0=持有
        """
        # 获取历史数据
        data = self.get_stock_data(stock_code, lookback_days)
        
        if data is None or len(data) < 20:
            return 0
        
        # 这里实现具体的策略逻辑
        # 示例：简单均线策略
        return self._ma_strategy(data)
    
    def _ma_strategy(self, data):
        """双均线策略
        短期均线上穿长期均线：买入
        短期均线下穿长期均线：卖出
        """
        short_window = 5
        long_window = 20
        
        if len(data) < long_window:
            return 0
        
        # 计算均线
        ma_short = data['change_percent'].rolling(window=short_window).mean()
        ma_long = data['change_percent'].rolling(window=long_window).mean()
        
        # 信号生成
        if len(ma_short) >= 2:
            # 检查交叉
            if ma_short.iloc[-1] > ma_long.iloc[-1] and ma_short.iloc[-2] <= ma_long.iloc[-2]:
                return 1  # 买入信号
            elif ma_short.iloc[-1] < ma_long.iloc[-1] and ma_short.iloc[-2] >= ma_long.iloc[-2]:
                return -1  # 卖出信号
        
        return 0  # 持有
    
    def get_stock_data(self, stock_code, days):
        """从数据库获取股票历史数据"""
        try:
            # 获取该股票的历史数据
            # 注意：这里需要您添加历史数据存储功能
            # 暂时返回None
            return None
        except Exception as e:
            print(f"获取数据失败: {e}")
            return None


class SimpleStrategy:
    """简单策略：基于潜力股分析"""
    
    def __init__(self, manager):
        self.manager = manager
    
    def run_analysis_strategy(self, min_gain=1.5, max_loss=-3.0):
        """运行潜力股分析策略
        
        策略逻辑：
        1. 获取涨幅榜行业
        2. 选择数量最多的行业中的涨幅股
        3. 推荐买入
        """
        print("\n" + "="*70)
        print("运行潜力股分析策略")
        print("="*70)
        
        # 获取潜力股分析结果
        result = self.manager.get_potential_and_oversold_stocks(
            min_gain=min_gain, 
            max_loss=max_loss,
            reverse_mode=False
        )
        
        if not result:
            print("无法获取分析结果")
            return []
        
        # 提取潜力股
        potential_groups = result.get('potential_groups', {})
        buy_signals = []
        
        for industry, stocks in potential_groups.items():
            print(f"\n行业: {industry}")
            for stock in stocks[:5]:  # 每个行业取前5只
                if stock['change_percent'] >= min_gain:
                    signal = {
                        'code': stock['code'],
                        'name': stock['name'],
                        'industry': stock['industry'],
                        'price': stock['current_price'],
                        'change': stock['change_percent'],
                        'signal': 'BUY',
                        'reason': f"潜力股-{industry}行业领头"
                    }
                    buy_signals.append(signal)
                    print(f"  买入信号: {stock['name']} ({stock['code']}) "
                          f"涨幅:{stock['change_percent']:.2f}% 价格:{stock['current_price']:.2f}")
        
        return buy_signals
    
    def run_reverse_strategy(self, min_gain=1.5, max_loss=-3.0):
        """运行反向策略
        
        策略逻辑：
        1. 获取跌幅榜行业
        2. 排除数量最多的行业
        3. 选择其他行业中的超跌股（可能反弹）
        """
        print("\n" + "="*70)
        print("运行反向指标策略")
        print("="*70)
        
        # 使用反向指标
        result = self.manager.get_potential_and_oversold_stocks(
            min_gain=min_gain,
            max_loss=max_loss,
            reverse_mode=True  # 反向指标
        )
        
        if not result:
            print("无法获取分析结果")
            return []
        
        # 提取超跌股
        oversold_groups = result.get('oversold_groups', {})
        buy_signals = []
        
        for industry, stocks in oversold_groups.items():
            print(f"\ środowiska: {industry}")
            for stock in stocks[:3]:  # 每个行业取前3只
                if stock['change_percent'] <= max_loss:
                    signal = {
                        'code': stock['code'],
                        'name': stock['name'],
                        'industry': stock['industry'],
                        'price': stock['current_price'],
                        'change': stock['change_percent'],
                        'signal': 'BUY',
                        'reason': f"超跌反弹-{industry}行业"
                    }
                    buy_signals.append(signal)
                    print(f"  买入信号: {stock['name']} ({stock['code']}) "
                          f"跌幅:{stock['change_percent']:.2f}% 价格:{stock['current_price']:.2f}")
        
        return buy_signals


class RiskManager:
    """风险管理"""
    
    def __init__(self, max_position=10000, max_stocks=5):
        self.max_position = max_position  # 单只股票最大仓位
        self.max_stocks = max_stocks  # 最多持有股票数
    
    def check_position(self, signals):
        """检查仓位"""
        # 限制买入数量
        if len(signals) > self.max_stocks:
            # 按涨幅排序，选择前N只
            signals = sorted(signals, key=lambda x: x['change'], reverse=True)
            signals = signals[:self.max_stocks]
        
        return signals


class StrategyExecutor:
    """策略执行器"""
    
    def __init__(self, manager):
        self.manager = manager
        self.simple_strategy = SimpleStrategy(manager)
        self.risk_manager = RiskManager()
    
    def daily_trading_signals(self, strategy_type='normal'):
        """生成每日交易信号
        
        Args:
            strategy_type: 'normal' 或 'reverse'
        """
        print("\n" + "="*70)
        print(f"生成交易信号 - {strategy_type}策略")
        print("="*70)
        
        # 根据策略类型选择
        if strategy_type == 'reverse':
            signals = self.simple_strategy.run_reverse_strategy()
        else:
            signals = self.simple_strategy.run_analysis_strategy()
        
        # 风险管理
        signals = self.risk_manager.check_position(signals)
        
        return signals
    
    def print_signals(self, signals):
        """打印交易信号"""
        if not signals:
            print("\n暂无交易信号")
            return
        
        print("\n" + "="*70)
        print(f"交易信号汇总 (共{len(signals)}个)")
        print("="*70)
        
        for i, signal in enumerate(signals, 1):
            print(f"\n【信号 {i}】")
            print(f"  代码: {signal['code']}")
            print(f"  名称: {signal['name']}")
            print(f"  行业: {signal['industry']}")
            print(f"  操作: {signal['signal']}")
            print(f"  当前价: {signal['price']:.2f}")
            print(f"  涨跌幅: {signal['change']:.2f}%")
            print(f"  推荐理由: {signal['reason']}")
        
        print("="*70)


def main():
    """主函数"""
    # 连接数据库
    manager = StockManager()
    
    if not manager.connection:
        print("无法连接数据库")
        return
    
    print("✓ 数据库连接成功")
    
    # 创建执行器
    executor = StrategyExecutor(manager)
    
    # 策略选择
    print("\n请选择策略:")
    print("1. 正向指标策略（推荐）")
    print("2. 反向指标策略")
    print("3. 两种策略都运行")
    
    choice = input("\n请选择 (1/2/3): ").strip()
    
    signals_all = []
    
    if choice == '1':
        signals = executor.daily_trading_signals('normal')
        signals_all.extend(signals)
    elif choice == '2':
        signals = executor.daily_trading_signals('reverse')
        signals_all.extend(signals)
    elif choice == '3':
        signals1 = executor.daily_trading_signals('normal')
        signals2 = executor.daily_trading_signals('reverse')
        signals_all.extend(signals1)
        signals_all.extend(signals2)
    else:
        print("无效选择")
        return
    
    # 打印汇总
    executor.print_signals(signals_all)
    
    # 询问是否执行
    if signals_all:
        confirm = input("\n是否执行这些交易信号？(y/n): ").strip().lower()
        if confirm == 'y':
            print("\n注意：这里是模拟执行，实际交易需要连接到您的交易系统")
            for signal in signals_all:
                print(f"模拟执行: {signal['signal']} {signal['code']} {signal['name']}")
    
    # 关闭连接
    manager.close()
    print("\n✓ 完成")


if __name__ == '__main__':
    main()

