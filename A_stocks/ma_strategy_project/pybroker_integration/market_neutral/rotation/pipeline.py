# -*- coding: utf-8 -*-
"""等权合成 EQ + 轮动合成 ROT（软权重 × 温度仓位缩放）。"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from market_neutral.backtest.engine import compute_metrics
from market_neutral.config import MNConfig
from market_neutral.rotation.features import build_feature_panel, weekly_factor_returns
from market_neutral.rotation.spec import ROTATION_FACTORS, RotationSpec
from market_neutral.rotation.temperature import load_temperature_series
from market_neutral.rotation.weights import (
    compute_weight_schedule,
    equal_weights,
)


def _day_ret_matrix(
    results: dict,
    calendar: Sequence[pd.Timestamp],
    factors: Sequence[str],
) -> pd.DataFrame:
    cal = [pd.Timestamp(d).normalize() for d in calendar]
    base = pd.DataFrame({"date": cal})
    for v in factors:
        pack = results.get(v)
        if not pack or pack.get("equity") is None or pack["equity"].empty:
            base[v] = 0.0
            continue
        eq = pack["equity"].copy()
        eq["date"] = pd.to_datetime(eq["date"]).dt.normalize()
        eq["day_return"] = pd.to_numeric(eq["day_return"], errors="coerce").fillna(0.0)
        m = base.merge(eq[["date", "day_return"]], on="date", how="left")
        base[v] = m["day_return"].fillna(0.0)
    return base


def _weights_on_calendar(
    weight_sched: pd.DataFrame,
    calendar: Sequence[pd.Timestamp],
    factors: Sequence[str],
    *,
    equal: bool = False,
) -> pd.DataFrame:
    cal = [pd.Timestamp(d).normalize() for d in calendar]
    out = pd.DataFrame({"date": cal})
    if equal or weight_sched is None or weight_sched.empty:
        eqw = equal_weights(factors)
        for f in factors:
            out[f"w_{f}"] = eqw[f]
        out["position_scale"] = 1.0
        return out

    ws = weight_sched.copy()
    ws["date"] = pd.to_datetime(ws["date"]).dt.normalize()
    ws = ws.sort_values("date")
    # asof merge
    out = pd.merge_asof(
        out.sort_values("date"),
        ws.sort_values("date"),
        on="date",
        direction="backward",
    )
    for f in factors:
        col = f"w_{f}"
        if col not in out.columns:
            out[col] = 1.0 / len(factors)
        out[col] = out[col].fillna(1.0 / len(factors))
    if "position_scale" not in out.columns:
        out["position_scale"] = 1.0
    out["position_scale"] = out["position_scale"].fillna(1.0)
    return out


def _simulate_blend(
    day_mat: pd.DataFrame,
    wcal: pd.DataFrame,
    factors: Sequence[str],
    *,
    variant_name: str,
    initial_cash: float,
    apply_temp_scale: bool,
) -> Tuple[pd.DataFrame, dict]:
    merged = day_mat.merge(wcal, on="date", how="left", suffixes=("", "_w"))
    for f in factors:
        col = f"w_{f}"
        if col not in merged.columns:
            merged[col] = 1.0 / len(factors)
        merged[col] = merged[col].fillna(1.0 / len(factors))
    if "position_scale" not in merged.columns:
        merged["position_scale"] = 1.0
    merged["position_scale"] = merged["position_scale"].fillna(1.0)

    equity = float(initial_cash)
    rows: List[dict] = []
    for _, r in merged.iterrows():
        raw = 0.0
        for f in factors:
            raw += float(r.get(f, 0.0) or 0.0) * float(r.get(f"w_{f}", 0.0) or 0.0)
        scale = float(r["position_scale"]) if apply_temp_scale else 1.0
        day_ret = scale * raw
        equity *= 1.0 + day_ret
        rows.append(
            {
                "date": pd.Timestamp(r["date"]).strftime("%Y-%m-%d"),
                "variant": variant_name,
                "equity": equity,
                "day_return": day_ret,
                "n_long": 0,
                "n_short": 0,
                "position_scale": scale,
            }
        )
    eq_df = pd.DataFrame(rows)
    met = compute_metrics(eq_df, initial_cash)
    met["variant"] = variant_name
    return eq_df, met


def run_rotation_overlay(
    results: dict,
    *,
    calendar: Sequence[pd.Timestamp],
    rebal_dates: Sequence[pd.Timestamp],
    cfg: MNConfig,
    spec: Optional[RotationSpec] = None,
) -> Tuple[dict, pd.DataFrame, pd.DataFrame]:
    """
    在已有单因子回测结果上叠加 EQ / ROT。
    返回 (extra_results, weight_schedule, feature_panel)
    """
    spec = spec or RotationSpec()
    factors = [f for f in spec.factors if f in results]
    if len(factors) < 2:
        return {}, pd.DataFrame(), pd.DataFrame()

    temp_df = load_temperature_series(spec)
    print(
        f"  [rotation] 温度序列 {len(temp_df)} 行 · 因子 {factors}",
        flush=True,
    )

    period_ret = weekly_factor_returns(results, rebal_dates, factors=factors)
    feat = build_feature_panel(period_ret, spec=spec)
    # 轮动调权日：与默认周频一致
    weight_sched = compute_weight_schedule(
        feat, rebal_dates, temp_df, spec=spec
    )
    print(
        f"  [rotation] 特征 {len(feat)} · 权重日程 {len(weight_sched)} "
        f"(GBM周数={int(weight_sched['used_gbm'].sum()) if not weight_sched.empty and 'used_gbm' in weight_sched.columns else 0})",
        flush=True,
    )

    day_mat = _day_ret_matrix(results, calendar, factors)
    w_eq = _weights_on_calendar(weight_sched, calendar, factors, equal=True)
    w_rot = _weights_on_calendar(weight_sched, calendar, factors, equal=False)

    eq_eq, met_eq = _simulate_blend(
        day_mat,
        w_eq,
        factors,
        variant_name="EQ",
        initial_cash=cfg.initial_cash,
        apply_temp_scale=False,
    )
    eq_rot, met_rot = _simulate_blend(
        day_mat,
        w_rot,
        factors,
        variant_name="ROT",
        initial_cash=cfg.initial_cash,
        apply_temp_scale=True,
    )
    met_eq["rebalance_freq"] = cfg.rebalance
    met_rot["rebalance_freq"] = f"{cfg.rebalance}+temp"
    met_eq["rank_ic"] = float("nan")
    met_eq["icir"] = float("nan")
    met_eq["ic_count"] = 0
    met_rot["rank_ic"] = float("nan")
    met_rot["icir"] = float("nan")
    met_rot["ic_count"] = 0

    # 合成组合的「门禁」：成分因子 Rank IC 的加权平均（用末日权重）
    if not weight_sched.empty:
        last = weight_sched.iloc[-1]
        wsum = 0.0
        ic_acc = 0.0
        icir_acc = 0.0
        for f in factors:
            wi = float(last.get(f"w_{f}", 0.0) or 0.0)
            m = (results.get(f) or {}).get("metrics") or {}
            ic_acc += wi * float(m.get("rank_ic", 0) or 0)
            icir_acc += wi * float(m.get("icir", 0) or 0)
            wsum += wi
        if wsum > 0:
            met_rot["rank_ic"] = ic_acc / wsum
            met_rot["icir"] = icir_acc / wsum
            met_rot["ic_count"] = int(
                np.nanmean([float((results.get(f) or {}).get("metrics", {}).get("ic_count", 0) or 0) for f in factors])
            )
            # EQ：等权平均 IC
            met_eq["rank_ic"] = float(
                np.nanmean([float((results.get(f) or {}).get("metrics", {}).get("rank_ic", 0) or 0) for f in factors])
            )
            met_eq["icir"] = float(
                np.nanmean([float((results.get(f) or {}).get("metrics", {}).get("icir", 0) or 0) for f in factors])
            )
            met_eq["ic_count"] = met_rot["ic_count"]

    extra = {
        "EQ": {
            "equity": eq_eq,
            "rebalance": pd.DataFrame(),
            "holdings": pd.DataFrame(),
            "metrics": met_eq,
            "factor": None,
        },
        "ROT": {
            "equity": eq_rot,
            "rebalance": weight_sched,
            "holdings": weight_sched.tail(1).copy() if not weight_sched.empty else pd.DataFrame(),
            "metrics": met_rot,
            "factor": feat,
        },
    }
    return extra, weight_sched, feat
