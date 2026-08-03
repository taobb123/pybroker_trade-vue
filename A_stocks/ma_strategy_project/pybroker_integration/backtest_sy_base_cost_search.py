#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在固定区间上，对阈值回测中的 base_cost 做离散爬山搜索。

股票池：同目录 stocks_pool.txt（一行一只，空行与 # 注释忽略）。
爬山起点：脚本运行当日——用该股前复权日线「最新一根 K 线」上的 MA20（收盘 rolling 20）
         作为 default_base_cost，再按原算法 1% 步长三点爬山（与原先语义一致）。

回测区间、初始资金：仍继承 backtest_sy_002028_threshold 中的 START_DATE / END_DATE / INITIAL_CASH。
不再从该模块继承 SYMBOL / BASE_COST。

策略（高效）：
1) 每只标的回测区间只拉取一次 OHLC，传入每次 hill 内的回测。
2) 步长 = 当前起点 default_base_cost 的 1%（算术值，新基准再 round 到 2 位小数）。
3) 每一步只在 c 与 c±step 三点比较收益率；局部峰则停；否则移向最优邻居。

每次处理完一只标的即将最优 base_cost upsert 到 optimal_base_cost.csv（按代码覆盖旧行）。
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Dict, List, Tuple

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backtest_sy_002028_threshold import (  # noqa: E402
    END_DATE,
    INITIAL_CASH,
    START_DATE,
    backtest_threshold_strategy,
    fetch_ohlc_qfq,
    fetch_stock_name,
)
from optimal_base_cost_store import DEFAULT_OPTIMAL_BASE_CSV, upsert_optimal_base  # noqa: E402

DEFAULT_POOL_TXT = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
# 为计算「运行日」MA20 向前多取的日历天数（含节假日缓冲）
MA20_LOOKBACK_DAYS = 120


def load_symbols_from_pool_file(pool_path: str) -> List[str]:
    """从文本文件加载股票代码：一行一只，忽略空行与 # 注释。"""
    if not os.path.isfile(pool_path):
        raise FileNotFoundError(f"股票池文件不存在: {pool_path}")
    symbols: List[str] = []
    with open(pool_path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            symbols.append(s)
    return symbols


def _round_base(x: float) -> float:
    return round(float(x), 2)


def ma20_asof_run_date(
    symbol: str,
    *,
    asof: date | None = None,
) -> float:
    """
    脚本运行「当天」口径：取 asof 日（默认今天）之前能拉到的最新一根日线，
    用该段行情最后一根 bar 上的 MA20（含该 bar 收盘的 rolling(20)）作为标量。
    """
    d0 = asof if asof is not None else date.today()
    end_s = d0.strftime("%Y-%m-%d")
    start_s = (d0 - timedelta(days=MA20_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    df = fetch_ohlc_qfq(symbol, start_s, end_s)
    if df is None or df.empty:
        raise RuntimeError(f"{symbol}: 无法获取用于 MA20 的行情")
    d = df.copy()
    d["date"] = pd.to_datetime(d["date"])
    d = d.sort_values("date").reset_index(drop=True)
    d["close"] = pd.to_numeric(d["close"], errors="coerce")
    d = d.dropna(subset=["close"])
    if len(d) < 20:
        raise RuntimeError(f"{symbol}: K 线不足 20 根，无法计算 MA20")
    ma = d["close"].rolling(20).mean()
    val = float(ma.iloc[-1])
    if val != val or val <= 0:  # nan
        mv = ma.dropna()
        if mv.empty:
            raise RuntimeError(f"{symbol}: MA20 无有效值")
        val = float(mv.iloc[-1])
    return _round_base(val)


def hill_climb_base_cost(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_cash: float,
    default_base_cost: float,
    *,
    min_base: float = 0.01,
    max_iterations: int = 10_000,
) -> Tuple[float, Dict, List[Tuple[float, float]], Dict[float, float]]:
    """
    :return: (最优 base_cost, 该点完整回测结果, 搜索路径 [(c, return_pct), ...], 各点收益率缓存)
    """
    step = float(default_base_cost) * 0.01
    if step <= 0:
        raise ValueError("default_base_cost 必须为正，且步长 = 其 1%")

    df = fetch_ohlc_qfq(symbol, start_date, end_date)
    cache_rp: Dict[float, float] = {}
    cache_full: Dict[float, Dict] = {}

    def return_pct(bc: float) -> float:
        k = _round_base(bc)
        if k not in cache_rp:
            r = backtest_threshold_strategy(
                symbol,
                start_date,
                end_date,
                initial_cash=initial_cash,
                base_cost=k,
                df=df,
            )
            cache_rp[k] = float(r["return_pct"])
            cache_full[k] = r
        return cache_rp[k]

    c = _round_base(default_base_cost)
    return_pct(c)  # 确保起点在缓存中

    trace: List[Tuple[float, float]] = [(c, cache_rp[c])]
    it = 0
    while it < max_iterations:
        it += 1
        candidates: List[float] = [c]
        cp = _round_base(c + step)
        if cp != c:
            candidates.append(cp)
        cm = _round_base(c - step)
        if cm >= min_base and cm != c:
            candidates.append(cm)

        scored = [(x, return_pct(x)) for x in candidates]
        best_x, best_r = max(scored, key=lambda t: t[1])

        if best_x == c:
            return c, cache_full[c], trace, cache_rp

        c = best_x
        trace.append((c, cache_rp[c]))

    raise RuntimeError(f"未在 max_iterations={max_iterations} 内收敛，最后 base_cost={c}")


def main() -> None:
    pool_path = DEFAULT_POOL_TXT
    symbols = load_symbols_from_pool_file(pool_path)
    if not symbols:
        raise SystemExit(f"股票池为空: {pool_path}")

    run_day = date.today()
    print("BASE_COST 爬山搜索（起点 = 运行日 MA20）")
    print(f"股票池: {pool_path}  共 {len(symbols)} 只")
    print(f"运行日: {run_day.isoformat()}  （MA20 取该日前已收盘的最新日线）")
    print(f"回测区间: {START_DATE} ~ {END_DATE}  （继承 backtest_sy_002028_threshold）")
    print(f"初始资金: {INITIAL_CASH:,.2f}")
    print("算法: 每标的单 OHLC + 缓存；步长 = MA20 起点 × 1%；三点取优爬山")
    print("=" * 72)

    ok = 0
    for sym in symbols:
        sn = fetch_stock_name(sym)
        label = f"{sym}" + (f" {sn}" if sn else "")
        try:
            ma20_bc = ma20_asof_run_date(sym, asof=run_day)
        except Exception as e:
            print(f"[跳过] {label}  MA20 失败: {e}")
            continue

        step = ma20_bc * 0.01
        print(f"\n--- {label}  MA20 起点={ma20_bc}  步长≈{step:.6g} ---")

        try:
            best_c, result, trace, cache = hill_climb_base_cost(
                sym,
                START_DATE,
                END_DATE,
                float(INITIAL_CASH),
                ma20_bc,
            )
        except Exception as e:
            print(f"[失败] {label}  爬山/回测: {e}")
            continue

        print(
            f"收敛: optimal_base_cost={best_c}  return_pct={result['return_pct']:.4f}%  "
            f"回测唯一点={len(cache)}  路径长={len(trace)}"
        )

        upsert_optimal_base(
            sym,
            float(best_c),
            START_DATE,
            END_DATE,
            float(result["return_pct"]),
            stock_name=sn,
        )
        ok += 1

    print("=" * 72)
    print(f"完成: 成功 {ok}/{len(symbols)}  已 upsert 至 {DEFAULT_OPTIMAL_BASE_CSV}")


if __name__ == "__main__":
    main()
