# -*- coding: utf-8 -*-
"""用现有 mud_plus 构造 M+ 十分位的 T+3 收益样本。只读行情，不写日常链文件。"""
from __future__ import annotations

from typing import Dict, Mapping

import numpy as np
import pandas as pd

from market_neutral.factors.mud import compute_mud_panel
from risk_return.contract import HOLD_TRADING_DAYS, SAMPLE_STEP_TRADING_DAYS


def _traded_on(df: pd.DataFrame | None, dt: pd.Timestamp) -> bool:
    if df is None or df.empty or "date" not in df.columns:
        return False
    dates = pd.to_datetime(df["date"]).dt.normalize()
    return bool((dates == pd.Timestamp(dt).normalize()).any())


def forward_return_exact(df: pd.DataFrame | None, dt: pd.Timestamp, hold_days: int) -> float:
    """信号日当天必须有 K 线。收益 = close[i+hold]/close[i] - 1，i 为信号日。"""
    if df is None or df.empty or hold_days <= 0:
        return float("nan")
    full = df.sort_values("date").reset_index(drop=True)
    full["date"] = pd.to_datetime(full["date"]).dt.normalize()
    dt = pd.Timestamp(dt).normalize()
    hit = full.index[full["date"] == dt]
    if len(hit) == 0:
        return float("nan")
    i0 = int(hit[0])
    i1 = i0 + int(hold_days)
    if i1 >= len(full):
        return float("nan")
    c0 = float(full.loc[i0, "close"])
    c1 = float(full.loc[i1, "close"])
    if not (c0 == c0 and c1 == c1 and c0 > 0 and c1 > 0):
        return float("nan")
    return c1 / c0 - 1.0


def signal_dates(bars_by_symbol: Mapping[str, pd.DataFrame], step: int) -> list[pd.Timestamp]:
    """合并各标的交易日，从第一天起每 step 日取一个信号日。"""
    found: set[pd.Timestamp] = set()
    for df in bars_by_symbol.values():
        if df is None or df.empty or "date" not in df.columns:
            continue
        for raw in pd.to_datetime(df["date"]).dt.normalize():
            found.add(pd.Timestamp(raw))
    ordered = sorted(found)
    if step <= 0:
        raise ValueError("sample step 必须为正")
    return ordered[::step]


def assign_deciles(panel: pd.DataFrame) -> pd.DataFrame:
    """每个信号日按 mud_plus 截面分位，1 为最低，10 为最高。"""
    if panel.empty:
        out = panel.copy()
        out["decile"] = pd.Series(dtype=int)
        return out
    parts: list[pd.DataFrame] = []
    for _, day in panel.groupby("date", sort=True):
        g = day.copy()
        score = pd.to_numeric(g["mud_plus"], errors="coerce")
        pct = score.rank(method="average", pct=True)
        g["decile"] = np.ceil(pct * 10).clip(1, 10)
        g.loc[score.isna(), "decile"] = np.nan
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def build_mplus_t3_samples(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    hold_days: int = HOLD_TRADING_DAYS,
    sample_step: int = SAMPLE_STEP_TRADING_DAYS,
) -> pd.DataFrame:
    """返回列：date, symbol, mud_plus, decile, fwd_ret。"""
    columns = ["date", "symbol", "mud_plus", "decile", "fwd_ret"]
    dates = signal_dates(bars_by_symbol, sample_step)
    if not dates:
        return pd.DataFrame(columns=columns)
    prepared: Dict[str, pd.DataFrame] = {}
    for sym, df in bars_by_symbol.items():
        if df is None or df.empty:
            continue
        d = df.copy()
        d["date"] = pd.to_datetime(d["date"]).dt.normalize()
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
        d = d.dropna(subset=["date", "close"])
        d = d[d["close"] > 0]
        if d.empty:
            continue
        code = "".join(ch for ch in str(sym) if ch.isdigit()).zfill(6)
        prepared[code] = d.sort_values("date").drop_duplicates("date", keep="last")
    panel = compute_mud_panel(prepared, dates)
    if panel.empty or "mud_plus" not in panel.columns:
        return pd.DataFrame(columns=columns)
    panel = panel.dropna(subset=["mud_plus"]).copy()
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    panel["symbol"] = panel["symbol"].astype(str).str.zfill(6)
    traded = [
        _traded_on(prepared.get(str(row.symbol)), row.date)
        for row in panel.itertuples(index=False)
    ]
    panel = panel.loc[traded].copy()
    if panel.empty:
        return pd.DataFrame(columns=columns)
    panel = assign_deciles(panel)
    fwd: list[float] = []
    for row in panel.itertuples(index=False):
        fwd.append(forward_return_exact(prepared.get(str(row.symbol)), row.date, hold_days))
    panel["fwd_ret"] = fwd
    panel = panel.dropna(subset=["decile", "fwd_ret"])
    if panel.empty:
        return pd.DataFrame(columns=columns)
    panel["decile"] = panel["decile"].astype(int)
    return panel[columns].reset_index(drop=True)
