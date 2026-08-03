# -*- coding: utf-8 -*-
"""个股多空：因子横截面前 q% 做多、后 q% 做空（资金中性）。"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np
import pandas as pd

# 形态状态序（越高越偏「建仓/确认」）
_STATE_ORD = {
    "entry": 5.0,
    "confirming": 4.0,
    "trial": 3.0,
    "candidate": 2.0,
    "watch": 1.0,
    "invalid": 0.0,
}


def merge_factor_snapshot(
    pattern: pd.DataFrame,
    valuation: pd.DataFrame,
) -> pd.DataFrame:
    """调仓日截面：形态 + 估值（兼容旧接口）。"""
    if pattern is None or pattern.empty:
        base = valuation.copy() if valuation is not None else pd.DataFrame()
        if not base.empty:
            base["pattern_ok"] = False
            base["state_code"] = ""
            base["state"] = ""
            base["score"] = 0.0
            base["entry"] = False
            base["stock_name"] = base.get("stock_name", "")
        return base
    p = pattern.copy()
    p["date"] = pd.to_datetime(p["date"]).dt.normalize()
    p["symbol"] = p["symbol"].astype(str).str.zfill(6)
    if valuation is None or valuation.empty:
        p["upside"] = pd.NA
        p["undervalued"] = False
        p["fair_price"] = pd.NA
        p["pe_ttm"] = pd.NA
        p["pe_ref"] = pd.NA
        p["industry"] = ""
        return p
    v = valuation.copy()
    v["date"] = pd.to_datetime(v["date"]).dt.normalize()
    v["symbol"] = v["symbol"].astype(str).str.zfill(6)
    cols = [
        c
        for c in (
            "date",
            "symbol",
            "pe_ttm",
            "pb",
            "fair_price",
            "upside",
            "upside_raw",
            "undervalued",
            "pe_ref",
            "industry",
        )
        if c in v.columns
    ]
    out = p.merge(v[cols], on=["date", "symbol"], how="outer")
    out["pattern_ok"] = out.get("pattern_ok", False)
    out["pattern_ok"] = out["pattern_ok"].where(out["pattern_ok"].notna(), False).map(bool)
    out["undervalued"] = out.get("undervalued", False)
    out["undervalued"] = out["undervalued"].where(out["undervalued"].notna(), False).map(bool)
    out["state_code"] = out["state_code"].fillna("") if "state_code" in out.columns else ""
    out["state"] = out["state"].fillna("") if "state" in out.columns else ""
    out["score"] = pd.to_numeric(out.get("score"), errors="coerce").fillna(0.0)
    out["stock_name"] = out.get("stock_name", pd.Series(dtype=str)).fillna("")
    return out


def pattern_factor_score(df: pd.DataFrame) -> pd.Series:
    """形态连续因子：状态序 ×1000 + 模型 score。"""
    sc = df.get("state_code", pd.Series("", index=df.index)).astype(str)
    ord_ = sc.map(lambda x: _STATE_ORD.get(x, 0.0)).astype(float)
    raw = pd.to_numeric(df.get("score"), errors="coerce").fillna(0.0)
    return ord_ * 1000.0 + raw


def _quantile_legs(
    ranked: pd.DataFrame,
    *,
    quantile: float = 0.10,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """按已降序排列的截面取前/后 quantile。"""
    if ranked is None or ranked.empty:
        return pd.DataFrame(), pd.DataFrame()
    n = len(ranked)
    q = float(quantile)
    if q <= 0 or q >= 0.5:
        q = 0.10
    k = max(1, int(np.floor(n * q)))
    if 2 * k > n:
        k = max(1, n // 2)
    longs = ranked.iloc[:k].copy()
    shorts = ranked.iloc[-k:].copy()
    # 避免重叠（极小样本）
    long_set = set(longs["symbol"].astype(str))
    shorts = shorts[~shorts["symbol"].astype(str).isin(long_set)].copy()
    if shorts.empty and n >= 2:
        shorts = ranked.iloc[-k:].copy()
        shorts = shorts[~shorts["symbol"].astype(str).isin(long_set)].copy()
    if longs.empty or shorts.empty:
        return pd.DataFrame(), pd.DataFrame()
    longs["weight"] = 1.0 / len(longs)
    shorts["weight"] = -1.0 / len(shorts)
    longs["side"] = "long"
    shorts["side"] = "short"
    return longs, shorts


def select_long_short(
    snap: pd.DataFrame,
    variant: str,
    *,
    quantile: float = 0.10,
) -> Tuple[pd.DataFrame, pd.DataFrame, str]:
    """
    A: 形态  B: 相对PE upside  C: 形态+PE分位合成
    Q: 轻量公司估值  M+/MPLUS: 动量MUD  M-/MMINUS: 反转MUD
    """
    if snap is None or snap.empty:
        return pd.DataFrame(), pd.DataFrame(), ""
    df = snap.copy()
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    v = str(variant).upper().replace("＋", "+").replace("－", "-")
    if v in ("MPLUS", "M_PLUS", "MUD+", "MUD_PLUS"):
        v = "M+"
    if v in ("MMINUS", "M_MINUS", "MUD-", "MUD_MINUS"):
        v = "M-"

    if v == "A":
        df["factor"] = pattern_factor_score(df)
        note = "pattern_score"
        ranked = df.sort_values(["factor", "symbol"], ascending=[False, True])
    elif v == "B":
        df["factor"] = pd.to_numeric(df.get("upside"), errors="coerce")
        df = df[df["factor"].notna()].copy()
        note = "upside"
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), note
        ranked = df.sort_values(["factor", "symbol"], ascending=[False, True])
    elif v == "Q":
        df["factor"] = pd.to_numeric(df.get("company_q"), errors="coerce")
        df = df[df["factor"].notna()].copy()
        note = "company_q"
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), note
        ranked = df.sort_values(["factor", "symbol"], ascending=[False, True])
    elif v == "M+":
        df["factor"] = pd.to_numeric(df.get("mud_plus"), errors="coerce")
        df = df[df["factor"].notna()].copy()
        note = "mud_plus"
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), note
        ranked = df.sort_values(["factor", "symbol"], ascending=[False, True])
    elif v == "M-":
        df["factor"] = pd.to_numeric(df.get("mud_minus"), errors="coerce")
        df = df[df["factor"].notna()].copy()
        note = "mud_minus"
        if df.empty:
            return pd.DataFrame(), pd.DataFrame(), note
        ranked = df.sort_values(["factor", "symbol"], ascending=[False, True])
    else:  # C：分位合成
        df["pattern_f"] = pattern_factor_score(df)
        df["value_f"] = pd.to_numeric(df.get("upside"), errors="coerce")
        df["p_pct"] = df["pattern_f"].rank(method="average", pct=True)
        df["v_pct"] = df["value_f"].rank(method="average", pct=True)
        df["factor"] = np.where(
            df["value_f"].notna(),
            0.5 * df["p_pct"] + 0.5 * df["v_pct"],
            df["p_pct"],
        )
        note = "avg_rank(pattern,upside)"
        ranked = df.sort_values(["factor", "symbol"], ascending=[False, True])

    longs, shorts = _quantile_legs(ranked, quantile=quantile)
    if not longs.empty:
        longs["variant"] = v
        longs["factor_name"] = note
    if not shorts.empty:
        shorts["variant"] = v
        shorts["factor_name"] = note
    return longs, shorts, note


def build_target_weights(
    longs: pd.DataFrame,
    shorts: pd.DataFrame,
) -> List[dict]:
    """多头权重和为 +1，空头权重和为 -1。"""
    rows: List[dict] = []

    def _row(r, side: str, w: float) -> dict:
        return {
            "symbol": str(r["symbol"]).zfill(6),
            "name": str(r.get("stock_name") or ""),
            "weight": float(w),
            "side": side,
            "state": str(r.get("state") or ""),
            "state_code": str(r.get("state_code") or ""),
            "upside": float(r["upside"]) if "upside" in r and pd.notna(r.get("upside")) else None,
            "fair_price": float(r["fair_price"])
            if "fair_price" in r and pd.notna(r.get("fair_price"))
            else None,
            "close": float(r["close"]) if "close" in r and pd.notna(r.get("close")) else None,
            "factor": float(r["factor"]) if "factor" in r and pd.notna(r.get("factor")) else None,
        }

    if longs is not None and not longs.empty:
        for _, r in longs.iterrows():
            rows.append(_row(r, "long", float(r.get("weight") or 0.0)))
    if shorts is not None and not shorts.empty:
        for _, r in shorts.iterrows():
            rows.append(_row(r, "short", float(r.get("weight") or 0.0)))
    return rows


# 兼容旧名
def select_longs(*args, **kwargs):
    longs, _shorts, _ = select_long_short(*args, **kwargs)
    return longs
