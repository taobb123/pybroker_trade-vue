# -*- coding: utf-8 -*-
"""滚动特征：各因子周收益、ICIR 代理。"""
from __future__ import annotations

from typing import List, Sequence

import numpy as np
import pandas as pd

from market_neutral.rotation.spec import ROTATION_FACTORS, RotationSpec


def _equity_day_returns(pack: dict) -> pd.DataFrame:
    eq = pack.get("equity")
    if eq is None or eq.empty:
        return pd.DataFrame(columns=["date", "day_return"])
    d = eq.copy()
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    d["day_return"] = pd.to_numeric(d["day_return"], errors="coerce").fillna(0.0)
    return d[["date", "day_return"]].sort_values("date")


def weekly_factor_returns(
    results: dict,
    rebal_dates: Sequence[pd.Timestamp],
    factors: Sequence[str] = ROTATION_FACTORS,
) -> pd.DataFrame:
    """
    每个调仓区间：因子从该调仓日到下一调仓日前的累计收益。
    列: date(调仓日), variant, period_return
    """
    rebal = sorted({pd.Timestamp(d).normalize() for d in rebal_dates})
    rows: List[dict] = []
    for i, dt in enumerate(rebal):
        end = rebal[i + 1] if i + 1 < len(rebal) else None
        for v in factors:
            pack = results.get(v) or results.get(str(v))
            if not pack:
                continue
            eq = _equity_day_returns(pack)
            if eq.empty:
                continue
            if end is not None:
                sub = eq.loc[(eq["date"] > dt) & (eq["date"] <= end), "day_return"]
            else:
                sub = eq.loc[eq["date"] > dt, "day_return"]
            if sub.empty and end is not None:
                sub = eq.loc[(eq["date"] >= dt) & (eq["date"] < end), "day_return"]
            pret = float((1.0 + sub).prod() - 1.0) if len(sub) else float("nan")
            rows.append({"date": dt, "variant": v, "period_return": pret})
    return pd.DataFrame(rows)


def build_feature_panel(
    period_ret: pd.DataFrame,
    *,
    spec: RotationSpec,
) -> pd.DataFrame:
    """
    每个调仓日 × 因子：滚动 lookback 周收益均值/波动 → icir_proxy。
    特征仅用 ≤ 当日已实现的历史（不含当期标签）。
    """
    if period_ret is None or period_ret.empty:
        return pd.DataFrame()
    pr = period_ret.copy()
    pr["date"] = pd.to_datetime(pr["date"]).dt.normalize()
    pr = pr.sort_values(["variant", "date"])
    rows: List[dict] = []
    for v, g in pr.groupby("variant"):
        g = g.sort_values("date").reset_index(drop=True)
        rets = pd.to_numeric(g["period_return"], errors="coerce")
        for i in range(len(g)):
            hist = rets.iloc[:i]
            row = {
                "date": g.loc[i, "date"],
                "variant": v,
                "period_return": float(rets.iloc[i]) if rets.iloc[i] == rets.iloc[i] else np.nan,
            }
            for lb in spec.lookback_weeks:
                h = hist.iloc[-lb:] if len(hist) else hist
                if len(h) < max(2, lb // 2):
                    row[f"ret_{lb}w"] = np.nan
                    row[f"icir_{lb}w"] = np.nan
                    row[f"vol_{lb}w"] = np.nan
                else:
                    mu = float(h.mean())
                    sd = float(h.std(ddof=0))
                    row[f"ret_{lb}w"] = float(h.sum())
                    row[f"vol_{lb}w"] = sd
                    row[f"icir_{lb}w"] = mu / sd if sd > 1e-12 else 0.0
            rows.append(row)
    return pd.DataFrame(rows)


def pivot_icir_scores(
    feat: pd.DataFrame,
    *,
    lookback: int = 8,
    factors: Sequence[str] = ROTATION_FACTORS,
) -> pd.DataFrame:
    """宽表：date + 各因子 icir_{lookback}w。"""
    col = f"icir_{lookback}w"
    if feat is None or feat.empty or col not in feat.columns:
        return pd.DataFrame(columns=["date"] + list(factors))
    wide = feat.pivot_table(index="date", columns="variant", values=col, aggfunc="last")
    for f in factors:
        if f not in wide.columns:
            wide[f] = np.nan
    wide = wide[list(factors)].reset_index()
    return wide
