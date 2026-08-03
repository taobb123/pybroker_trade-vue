# -*- coding: utf-8 -*-
"""MUD 因子：动量 M+ / 反转 M-。"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


def _close_vol_asof(df: pd.DataFrame, dt: pd.Timestamp):
    sub = df[df["date"] <= pd.Timestamp(dt)]
    if sub.empty:
        return None
    return sub


def compute_mud_panel(
    bars_by_symbol: Dict[str, pd.DataFrame],
    rebal_dates: Sequence[pd.Timestamp],
    *,
    mom_bars: int = 60,
    rev_bars: int = 20,
    vol_ma: int = 20,
    name_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    每个调仓日截面：
      mud_plus  = 波动调整动量 R60/σ20 + 0.3*量比分位（越高=涨得多且放量）
      mud_minus = -R20（越高=跌得越多，反转多头候选）
    """
    nm = name_map or {}
    rows: List[dict] = []
    need = max(mom_bars, rev_bars) + vol_ma + 5
    for dt in rebal_dates:
        dt = pd.Timestamp(dt).normalize()
        day_rows = []
        for sym, df in bars_by_symbol.items():
            if df is None or df.empty:
                continue
            sub = _close_vol_asof(df, dt)
            if sub is None or len(sub) < need:
                continue
            close = pd.to_numeric(sub["close"], errors="coerce")
            vol = pd.to_numeric(sub["volume"], errors="coerce")
            c0 = float(close.iloc[-1])
            if not (c0 == c0 and c0 > 0):
                continue
            c_m = float(close.iloc[-1 - mom_bars]) if len(close) > mom_bars else np.nan
            c_r = float(close.iloc[-1 - rev_bars]) if len(close) > rev_bars else np.nan
            r60 = c0 / c_m - 1.0 if c_m == c_m and c_m > 0 else np.nan
            r20 = c0 / c_r - 1.0 if c_r == c_r and c_r > 0 else np.nan
            ret20 = close.pct_change().iloc[-vol_ma:]
            sigma = float(ret20.std(ddof=0)) if len(ret20) >= 5 else np.nan
            mom_adj = r60 / sigma if (r60 == r60 and sigma == sigma and sigma > 1e-8) else r60
            v_today = float(vol.iloc[-1]) if len(vol) else np.nan
            v_ma = float(vol.iloc[-vol_ma - 1 : -1].mean()) if len(vol) > vol_ma else np.nan
            vol_ratio = v_today / v_ma if (v_today == v_today and v_ma == v_ma and v_ma > 0) else np.nan
            day_rows.append(
                {
                    "date": dt,
                    "symbol": str(sym).zfill(6),
                    "stock_name": nm.get(str(sym).zfill(6), ""),
                    "r60": r60,
                    "r20": r20,
                    "mom_adj": mom_adj,
                    "vol_ratio": vol_ratio,
                    "mud_minus_raw": -r20 if r20 == r20 else np.nan,
                    "close": c0,
                }
            )
        if not day_rows:
            continue
        g = pd.DataFrame(day_rows)
        # 截面合成 M+：0.7*mom_adj 分位 + 0.3*vol_ratio 分位
        g["mom_pct"] = g["mom_adj"].rank(method="average", pct=True)
        g["vol_pct"] = g["vol_ratio"].rank(method="average", pct=True)
        g["mud_plus"] = np.where(
            g["mom_adj"].notna(),
            0.7 * g["mom_pct"].fillna(0.5) + 0.3 * g["vol_pct"].fillna(0.5),
            np.nan,
        )
        g["mud_minus"] = g["mud_minus_raw"].rank(method="average", pct=True)
        rows.append(g)
    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "stock_name",
                "mud_plus",
                "mud_minus",
                "r60",
                "r20",
                "vol_ratio",
                "close",
            ]
        )
    out = pd.concat(rows, ignore_index=True)
    return out
