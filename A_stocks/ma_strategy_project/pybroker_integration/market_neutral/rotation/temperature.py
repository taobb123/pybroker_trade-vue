# -*- coding: utf-8 -*-
"""加载市场温度计仓位序列，供多空总敞口缩放。"""
from __future__ import annotations

import os
from typing import Optional

import pandas as pd

from market_neutral.rotation.spec import RotationSpec


def load_temperature_series(spec: Optional[RotationSpec] = None) -> pd.DataFrame:
    """
    返回列: date, total_score, position_pct, position_scale, temp_bucket
    position_scale = position_pct / 100，缺省 1.0
    """
    from market_neutral.rotation.spec import temp_bucket

    spec = spec or RotationSpec()
    frames = []
    for path in (spec.temp_history_csv, spec.temp_latest_csv):
        if not path or not os.path.isfile(path):
            continue
        try:
            df = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            continue
        if df is None or df.empty:
            continue
        d = df.copy()
        # trade_date 可能是 YYYYMMDD 或带时间的 report
        if "trade_date" in d.columns:
            td = d["trade_date"].astype(str).str.replace(r"\.0$", "", regex=True)
            d["date"] = pd.to_datetime(td, format="%Y%m%d", errors="coerce")
            miss = d["date"].isna()
            if miss.any():
                d.loc[miss, "date"] = pd.to_datetime(td[miss], errors="coerce")
        elif "date" in d.columns:
            d["date"] = pd.to_datetime(d["date"], errors="coerce")
        else:
            continue
        if "position_pct" not in d.columns:
            continue
        d["position_pct"] = pd.to_numeric(d["position_pct"], errors="coerce")
        if "total_score" in d.columns:
            d["total_score"] = pd.to_numeric(d["total_score"], errors="coerce")
        else:
            d["total_score"] = float("nan")
        d = d.dropna(subset=["date", "position_pct"])
        d["date"] = d["date"].dt.normalize()
        frames.append(d[["date", "total_score", "position_pct"]])

    if not frames:
        return pd.DataFrame(
            columns=["date", "total_score", "position_pct", "position_scale", "temp_bucket"]
        )

    out = pd.concat(frames, ignore_index=True)
    out = out.sort_values("date").drop_duplicates("date", keep="last")
    out["position_scale"] = (out["position_pct"] / 100.0).clip(0.0, 1.0)
    out["temp_bucket"] = out["position_pct"].map(temp_bucket)
    return out.reset_index(drop=True)


def position_scale_asof(
    temp_df: pd.DataFrame,
    dt: pd.Timestamp,
    *,
    default: float = 1.0,
) -> float:
    if temp_df is None or temp_df.empty:
        return float(default)
    dt = pd.Timestamp(dt).normalize()
    sub = temp_df[temp_df["date"] <= dt]
    if sub.empty:
        return float(default)
    return float(sub.iloc[-1]["position_scale"])


def temp_row_asof(temp_df: pd.DataFrame, dt: pd.Timestamp) -> dict:
    if temp_df is None or temp_df.empty:
        return {
            "position_pct": 100.0,
            "position_scale": 1.0,
            "temp_bucket": "mid",
            "total_score": float("nan"),
        }
    dt = pd.Timestamp(dt).normalize()
    sub = temp_df[temp_df["date"] <= dt]
    if sub.empty:
        return {
            "position_pct": 100.0,
            "position_scale": 1.0,
            "temp_bucket": "mid",
            "total_score": float("nan"),
        }
    r = sub.iloc[-1]
    return {
        "position_pct": float(r["position_pct"]),
        "position_scale": float(r["position_scale"]),
        "temp_bucket": str(r["temp_bucket"]),
        "total_score": float(r["total_score"]) if pd.notna(r.get("total_score")) else float("nan"),
    }
