#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import pandas as pd
import numpy as np
import sys
from pathlib import Path

# 将工程根目录加入 sys.path，确保 "ma_strategy_project" 可被导入
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ma_strategy_project.strategies.moving_average import MovingAverageStrategy
from ma_strategy_project.backtest.analyzer import PerformanceAnalyzer


def make_df(n=10, start=1.0, step=1.0):
    dates = pd.date_range('2020-01-01', periods=n, freq='D')
    close = np.array([start + i * step for i in range(n)], dtype=float)
    df = pd.DataFrame({
        'date': dates,
        'open': close,
        'high': close,
        'low': close,
        'close': close,
        'volume': np.ones(n)
    })
    return df


def test_moving_average_signals_vectorized():
    df = make_df(20)
    strategy = MovingAverageStrategy(short_window=3, long_window=7)
    out = strategy.generate_signals(df)

    # 基本列存在
    assert {'ma_short', 'ma_long', 'signal', 'positions'} <= set(out.columns)
    # 由于价格单调上升，应至少出现一次上穿（在反向策略为卖出 -1）
    assert (out['signal'] == -1).sum() >= 1
    # positions 为 signal 的差分，应该非全零
    assert out['positions'].abs().sum() > 0


def test_performance_analyzer_outputs():
    # 构造一个简单的等比增长的账户曲线
    n = 30
    dates = pd.date_range('2020-01-01', periods=n, freq='D')
    total = pd.Series(np.linspace(1000, 1100, n), index=dates)
    returns = total.pct_change().fillna(0)
    data = pd.DataFrame({'total': total, 'returns': returns})

    results = {
        'data': data,
        'initial_capital': 1000.0,
        'final_value': float(total.iloc[-1]),
        'total_return': (total.iloc[-1] / total.iloc[0] - 1) * 100,
        'num_trades': 0,
        'trades': []
    }

    analysis = PerformanceAnalyzer.analyze(results)

    # 核心指标应存在且为数值
    required_keys = {
        'initial_capital', 'final_value', 'total_return', 'annual_return',
        'sharpe_ratio', 'max_drawdown', 'max_drawdown_pct', 'num_trades'
    }
    assert required_keys <= set(analysis.keys())
    assert isinstance(analysis['total_return'], float)
    assert isinstance(analysis['sharpe_ratio'], float)

    if __name__ == "__main__":
        test_moving_average_signals_vectorized()
        test_performance_analyzer_outputs()
        print("All tests passed.")


