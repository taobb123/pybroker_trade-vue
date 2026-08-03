# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd


def winsorize_upside(
    upside: pd.Series,
    *,
    q_low: float = 0.05,
    q_high: float = 0.95,
    clip_low: float = -0.80,
    clip_high: float = 1.50,
) -> pd.Series:
    """单截面 upside：先分位截断，再硬裁剪。"""
    s = pd.to_numeric(upside, errors="coerce")
    valid = s.dropna()
    if len(valid) >= 5:
        lo = float(valid.quantile(float(q_low)))
        hi = float(valid.quantile(float(q_high)))
        if hi < lo:
            lo, hi = hi, lo
        s = s.clip(lower=lo, upper=hi)
    return s.clip(lower=float(clip_low), upper=float(clip_high))


def build_valuation_panel(
    basic: pd.DataFrame,
    industry_map: Dict[str, str],
    *,
    winsor_q_low: float = 0.05,
    winsor_q_high: float = 0.95,
    clip_low: float = -0.80,
    clip_high: float = 1.50,
) -> pd.DataFrame:
    """
    索普式简化定价：
      fair ≈ close * (PE_ref / PE_ttm)
      upside = PE_ref / PE_ttm - 1
    PE_ref = 同日同行业（观察池内）pe_ttm 中位数；行业样本 <3 则用全池中位数。
    upside 按日做分位 winsorize + 硬裁剪，抑制极端低估/高估。
    """
    cols = [
        "date",
        "symbol",
        "pe_ttm",
        "pb",
        "close",
        "industry",
        "pe_ref",
        "fair_price",
        "upside_raw",
        "upside",
        "undervalued",
    ]
    if basic is None or basic.empty:
        return pd.DataFrame(columns=cols)

    df = basic.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    df["industry"] = df["symbol"].map(lambda s: industry_map.get(s, "未知"))
    df["pe_ttm"] = pd.to_numeric(df["pe_ttm"], errors="coerce")
    df["pb"] = pd.to_numeric(df.get("pb"), errors="coerce")
    df["close"] = pd.to_numeric(df["close"], errors="coerce")

    pe_refs = []
    for _dt, g in df.groupby("date"):
        pe = g["pe_ttm"]
        ok = pe.notna() & (pe > 0)
        pool_med = float(pe[ok].median()) if ok.any() else np.nan
        ref_map = {}
        for ind, sub in g.groupby("industry"):
            sub_ok = sub["pe_ttm"].notna() & (sub["pe_ttm"] > 0)
            if int(sub_ok.sum()) >= 3:
                ref_map[ind] = float(sub.loc[sub_ok, "pe_ttm"].median())
            else:
                ref_map[ind] = pool_med
        for idx, row in g.iterrows():
            pe_refs.append((idx, ref_map.get(row["industry"], pool_med)))

    ref_series = pd.Series({i: r for i, r in pe_refs})
    df["pe_ref"] = ref_series.reindex(df.index)
    valid = df["pe_ttm"].notna() & (df["pe_ttm"] > 0) & df["close"].notna() & (df["close"] > 0)
    df["fair_price"] = np.where(
        valid & df["pe_ref"].notna() & (df["pe_ref"] > 0),
        df["close"] * (df["pe_ref"] / df["pe_ttm"]),
        np.nan,
    )
    df["upside_raw"] = np.where(
        valid & df["pe_ref"].notna() & (df["pe_ref"] > 0),
        df["pe_ref"] / df["pe_ttm"] - 1.0,
        np.nan,
    )
    parts = []
    for _dt, g in df.groupby("date"):
        gg = g.copy()
        gg["upside"] = winsorize_upside(
            gg["upside_raw"],
            q_low=winsor_q_low,
            q_high=winsor_q_high,
            clip_low=clip_low,
            clip_high=clip_high,
        )
        parts.append(gg)
    df = pd.concat(parts, ignore_index=False).sort_index()
    df["undervalued"] = df["upside"] > 0
    return df[cols]
