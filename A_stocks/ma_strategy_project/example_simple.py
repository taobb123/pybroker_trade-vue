#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单示例：快速使用均线策略
"""

from data.fetcher import DataFetcher
from strategies.moving_average import MovingAverageStrategy
from backtest.engine import BacktestEngine
from backtest.analyzer import PerformanceAnalyzer

# 1. 获取数据（使用模拟数据）
fetcher = DataFetcher()
data = fetcher.fetch_stock_data(
    code='000001',
    start_date='2023-01-01',
    end_date='2023-12-31',
    use_mock_if_fail=True
)

# 2. 创建策略
strategy = MovingAverageStrategy(short_window=5, long_window=20)

# 3. 运行回测
engine = BacktestEngine(strategy, initial_capital=100000)
results = engine.run(data)

# 4. 分析结果
analyzer = PerformanceAnalyzer()
analysis = analyzer.analyze(results)
analyzer.print_report(analysis)

# 5. 查看最新信号
latest_signal = strategy.get_latest_signal(data)
print(f"\n最新交易信号: {latest_signal['action']} @ {latest_signal['price']:.2f}")

