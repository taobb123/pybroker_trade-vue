# -*- coding: utf-8 -*-
"""温度分档 × 滚动 ICIR 规则权重；可选轻量 GBM 增量。"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from market_neutral.rotation.spec import (
    TEMP_BIAS,
    ROTATION_FACTORS,
    RotationSpec,
)
from market_neutral.rotation.temperature import temp_row_asof


def _clip_renorm(
    w: Dict[str, float],
    *,
    factors: Sequence[str],
    max_w: float,
    min_w: float,
) -> Dict[str, float]:
    out = {f: float(w.get(f, 0.0) or 0.0) for f in factors}
    for f in factors:
        out[f] = float(np.clip(out[f], min_w, max_w))
    s = sum(out.values())
    if s <= 1e-12:
        n = len(factors)
        return {f: 1.0 / n for f in factors}
    return {f: out[f] / s for f in factors}


def rule_weights_for_date(
    feat_day: pd.DataFrame,
    *,
    temp_info: dict,
    spec: RotationSpec,
    lookback: int = 8,
) -> Dict[str, float]:
    """
    score_f = max(icir_8w, 0) * 0.5 + max(icir_4w,0)*0.3 + max(icir_12w,0)*0.2
            再乘温度偏置，归一化并裁剪。
    """
    factors = spec.factors
    scores: Dict[str, float] = {}
    bucket = str(temp_info.get("temp_bucket") or "mid")
    bias = TEMP_BIAS.get(bucket, TEMP_BIAS["mid"])
    ic_cols = [f"icir_{lb}w" for lb in (4, 8, 12)]
    weights_ic = {4: 0.30, 8: 0.50, 12: 0.20}

    by_v = {}
    if feat_day is not None and not feat_day.empty:
        for _, r in feat_day.iterrows():
            by_v[str(r["variant"])] = r

    for f in factors:
        r = by_v.get(f)
        s = 0.0
        if r is not None:
            for lb, wt in weights_ic.items():
                col = f"icir_{lb}w"
                val = float(r[col]) if col in r.index and pd.notna(r[col]) else 0.0
                s += wt * max(val, spec.icir_floor)
        # 无历史时给均等底分
        if s <= 1e-12:
            s = 1e-3
        scores[f] = s * float(bias.get(f, 1.0))

    raw = {f: scores[f] for f in factors}
    total = sum(raw.values())
    w = {f: raw[f] / total for f in factors}
    return _clip_renorm(
        w, factors=factors, max_w=spec.max_weight, min_w=spec.min_weight
    )


def equal_weights(factors: Sequence[str] = ROTATION_FACTORS) -> Dict[str, float]:
    n = max(1, len(factors))
    return {f: 1.0 / n for f in factors}


def ema_smooth(
    prev: Optional[Dict[str, float]],
    curr: Dict[str, float],
    *,
    alpha: float,
    factors: Sequence[str],
) -> Dict[str, float]:
    if not prev:
        return {f: float(curr.get(f, 0.0)) for f in factors}
    a = float(np.clip(alpha, 0.05, 1.0))
    out = {
        f: a * float(curr.get(f, 0.0)) + (1.0 - a) * float(prev.get(f, 0.0))
        for f in factors
    }
    s = sum(out.values())
    if s <= 1e-12:
        return equal_weights(factors)
    return {f: out[f] / s for f in factors}


def _try_gbm_weights(
    feat: pd.DataFrame,
    asof: pd.Timestamp,
    *,
    spec: RotationSpec,
) -> Optional[Dict[str, float]]:
    """
    扩展窗口：用历史特征预测下期 period_return，按预测收益 softmax。
    样本不足或依赖缺失则返回 None。
    """
    if not spec.use_gbm or feat is None or feat.empty:
        return None
    f = feat.copy()
    f["date"] = pd.to_datetime(f["date"]).dt.normalize()
    asof = pd.Timestamp(asof).normalize()
    # 标签 = 当期 period_return；训练用 date < asof
    train = f[f["date"] < asof].dropna(subset=["period_return"])
    # 每个 date 需要齐套特征
    feat_cols = [c for c in f.columns if c.startswith("icir_") or c.startswith("ret_")]
    if len(feat_cols) < 3:
        return None
    train = train.dropna(subset=feat_cols)
    n_dates = train["date"].nunique()
    if n_dates < spec.gbm_min_samples:
        return None

    try:
        from sklearn.ensemble import GradientBoostingRegressor
    except Exception:
        return None

    X = train[feat_cols].values
    y = train["period_return"].values
    model = GradientBoostingRegressor(
        n_estimators=80,
        max_depth=2,
        learning_rate=0.05,
        subsample=0.9,
        random_state=42,
    )
    try:
        model.fit(X, y)
    except Exception:
        return None

    day = f[f["date"] == asof]
    if day.empty:
        return None
    preds: Dict[str, float] = {}
    for _, r in day.iterrows():
        v = str(r["variant"])
        if v not in spec.factors:
            continue
        x = r[feat_cols].astype(float).fillna(0.0).values.reshape(1, -1)
        try:
            preds[v] = float(model.predict(x)[0])
        except Exception:
            preds[v] = 0.0
    if len(preds) < 2:
        return None
    # softmax on clipped preds
    arr = np.array([preds.get(f, 0.0) for f in spec.factors], dtype=float)
    arr = arr - np.nanmax(arr)
    ex = np.exp(np.clip(arr, -8, 8))
    ex = np.where(np.isfinite(ex), ex, 0.0)
    if ex.sum() <= 1e-12:
        return None
    w = {f: float(ex[i] / ex.sum()) for i, f in enumerate(spec.factors)}
    return _clip_renorm(
        w, factors=spec.factors, max_w=spec.max_weight, min_w=spec.min_weight
    )


def blend_rule_gbm(
    rule_w: Dict[str, float],
    gbm_w: Optional[Dict[str, float]],
    *,
    spec: RotationSpec,
) -> Dict[str, float]:
    if not gbm_w:
        return rule_w
    b = float(np.clip(spec.gbm_blend, 0.0, 1.0))
    out = {
        f: (1.0 - b) * float(rule_w.get(f, 0.0)) + b * float(gbm_w.get(f, 0.0))
        for f in spec.factors
    }
    s = sum(out.values())
    if s <= 1e-12:
        return rule_w
    out = {f: out[f] / s for f in spec.factors}
    return _clip_renorm(
        out, factors=spec.factors, max_w=spec.max_weight, min_w=spec.min_weight
    )


def compute_weight_schedule(
    feat: pd.DataFrame,
    rebal_dates: Sequence[pd.Timestamp],
    temp_df: pd.DataFrame,
    *,
    spec: Optional[RotationSpec] = None,
) -> pd.DataFrame:
    """返回每个调仓日的因子权重表。"""
    spec = spec or RotationSpec()
    factors = list(spec.factors)
    prev = None
    rows: List[dict] = []
    rebal = sorted({pd.Timestamp(d).normalize() for d in rebal_dates})
    for dt in rebal:
        day_feat = (
            feat[feat["date"] == dt] if feat is not None and not feat.empty else pd.DataFrame()
        )
        tinfo = temp_row_asof(temp_df, dt)
        rule_w = rule_weights_for_date(day_feat, temp_info=tinfo, spec=spec)
        gbm_w = _try_gbm_weights(feat, dt, spec=spec)
        mixed = blend_rule_gbm(rule_w, gbm_w, spec=spec)
        smoothed = ema_smooth(prev, mixed, alpha=spec.ema_alpha, factors=factors)
        prev = smoothed
        row = {
            "date": dt.strftime("%Y-%m-%d"),
            "position_pct": tinfo["position_pct"],
            "position_scale": tinfo["position_scale"],
            "temp_bucket": tinfo["temp_bucket"],
            "used_gbm": bool(gbm_w),
        }
        for f in factors:
            row[f"w_{f}"] = smoothed[f]
        rows.append(row)
    return pd.DataFrame(rows)
