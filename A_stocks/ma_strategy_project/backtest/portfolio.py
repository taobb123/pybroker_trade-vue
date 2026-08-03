#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多股票组合回测（等权分配，基础版）
"""

from __future__ import annotations

from typing import List, Dict

import pandas as pd

try:
    from ..data.fetcher import DataFetcher
    from ..strategies.moving_average import MovingAverageStrategy
    from ..backtest.engine import BacktestEngine
except Exception:
    from data.fetcher import DataFetcher
    from strategies.moving_average import MovingAverageStrategy
    from backtest.engine import BacktestEngine


def run_portfolio_backtest(
    codes: List[str],
    start_date: str,
    end_date: str,
    initial_capital: float,
    commission: float,
    short_window: int,
    long_window: int,
) -> Dict:
    per_capital = initial_capital / max(len(codes), 1)
    results: List[Dict] = []
    final_total = 0.0

    with DataFetcher() as fetcher:
        for code in codes:
            try:
                # 不使用模拟数据，如果数据为空则跳过该股票
                data = fetcher.fetch_stock_data(code, start_date, end_date, use_mock_if_fail=False)
                if data is None or data.empty:
                    results.append({
                        'code': code,
                        'final_value': 0.0,
                        'total_return': 0.0,
                        'num_trades': 0,
                        'error': '数据不可用'
                    })
                    continue
                
                strategy = MovingAverageStrategy(short_window=short_window, long_window=long_window)
                engine = BacktestEngine(strategy=strategy, initial_capital=per_capital, commission=commission)
                r = engine.run(data)
                results.append({
                    'code': code,
                    'final_value': r['final_value'],
                    'total_return': r['total_return'],
                    'num_trades': r['num_trades'],
                })
                final_total += r['final_value']
            except Exception as e:
                results.append({
                    'code': code,
                    'final_value': 0.0,
                    'total_return': 0.0,
                    'num_trades': 0,
                    'error': str(e)
                })

    portfolio_return = (final_total / initial_capital - 1) * 100

    return {
        'per_code': results,
        'final_value': final_total,
        'total_return': portfolio_return,
    }


