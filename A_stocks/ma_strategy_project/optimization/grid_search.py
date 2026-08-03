#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双均线参数网格搜索（简单版）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import pandas as pd

try:
    from ..strategies.moving_average import MovingAverageStrategy  # type: ignore
    from ..backtest.engine import BacktestEngine  # type: ignore
except Exception:  # 兼容直接脚本运行
    from strategies.moving_average import MovingAverageStrategy  # type: ignore
    from backtest.engine import BacktestEngine  # type: ignore


@dataclass
class SearchResult:
    short_window: int
    long_window: int
    total_return: float


def grid_search_ma(data: pd.DataFrame, short_choices: List[int], long_choices: List[int],
                   initial_capital: float, commission: float) -> Tuple[SearchResult, List[SearchResult]]:
    results: List[SearchResult] = []
    best: SearchResult | None = None

    for s in short_choices:
        for l in long_choices:
            if s >= l:
                continue
            strategy = MovingAverageStrategy(short_window=s, long_window=l)
            engine = BacktestEngine(strategy=strategy, initial_capital=initial_capital, commission=commission)
            r = engine.run(data)
            sr = SearchResult(short_window=s, long_window=l, total_return=float(r['total_return']))
            results.append(sr)
            if best is None or sr.total_return > best.total_return:
                best = sr

    assert best is not None
    return best, results


