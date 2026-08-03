# -*- coding: utf-8 -*-
"""Rank IC / ICIR。"""
from __future__ import annotations

from typing import Dict, List, Sequence

import numpy as np
import pandas as pd


def _fwd_ret(
    bars: Dict[str, pd.DataFrame],
    symbol: str,
    dt: pd.Timestamp,
    forward_days: int,
) -> float:
    df = bars.get(symbol)
    if df is None or df.empty:
        return float("nan")
    d = df[df["date"] >= pd.Timestamp(dt)].sort_values("date")
    if len(d) <= forward_days:
        return float("nan")
    # 调仓日收盘为起点：取当日或之后第一根，再向后 forward_days 根
    # 简化：date==dt 的 close 到 date 后第 N 个交易日 close
    all_dates = df[df["date"] >= pd.Timestamp(dt)].sort_values("date")
    if all_dates.empty:
        return float("nan")
    # 找到 dt 或其后第一根
    base = all_dates.iloc[0]
    # 在全序列中定位
    full = df.sort_values("date").reset_index(drop=True)
    idx = full.index[full["date"] == base["date"]]
    if len(idx) == 0:
        return float("nan")
    i0 = int(idx[0])
    i1 = i0 + int(forward_days)
    if i1 >= len(full):
        return float("nan")
    c0 = float(full.loc[i0, "close"])
    c1 = float(full.loc[i1, "close"])
    if c0 <= 0 or c0 != c0 or c1 != c1:
        return float("nan")
    return c1 / c0 - 1.0


def compute_rank_ic(
    factor_panel: pd.DataFrame,
    bars_by_symbol: Dict[str, pd.DataFrame],
    *,
    factor_col: str,
    rebal_dates: Sequence[pd.Timestamp],
    forward_days: int = 5,
) -> dict:
    """
    每个调仓日：因子值与未来 N 日收益的 Spearman Rank IC。
    返回 mean_ic, icir, ic_series 摘要。
    """
    if factor_panel is None or factor_panel.empty or factor_col not in factor_panel.columns:
        return {
            "rank_ic": 0.0,
            "icir": 0.0,
            "ic_count": 0,
            "forward_days": int(forward_days),
            "factor_col": factor_col,
        }
    panel = factor_panel.copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel["symbol"] = panel["symbol"].astype(str).str.zfill(6)
    ics: List[float] = []
    for dt in rebal_dates:
        dt = pd.Timestamp(dt).normalize()
        day = panel[panel["date"] == dt][["symbol", factor_col]].copy()
        day[factor_col] = pd.to_numeric(day[factor_col], errors="coerce")
        day = day.dropna(subset=[factor_col])
        if len(day) < 5:
            continue
        rets = []
        for sym in day["symbol"]:
            rets.append(_fwd_ret(bars_by_symbol, sym, dt, forward_days))
        day = day.copy()
        day["fwd"] = rets
        day = day.dropna(subset=["fwd"])
        if len(day) < 5:
            continue
        ic = day[factor_col].corr(day["fwd"], method="spearman")
        if ic == ic:
            ics.append(float(ic))
    if not ics:
        return {
            "rank_ic": 0.0,
            "icir": 0.0,
            "ic_count": 0,
            "forward_days": int(forward_days),
            "factor_col": factor_col,
        }
    arr = np.array(ics, dtype=float)
    mean_ic = float(arr.mean())
    std = float(arr.std(ddof=0))
    icir = mean_ic / std if std > 1e-12 else 0.0
    return {
        "rank_ic": mean_ic,
        "icir": icir,
        "ic_count": int(len(ics)),
        "forward_days": int(forward_days),
        "factor_col": factor_col,
    }
