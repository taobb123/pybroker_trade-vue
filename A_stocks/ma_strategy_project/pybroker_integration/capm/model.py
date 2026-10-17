# -*- coding: utf-8 -*-
"""单因子市场模型。无风险利率按 0，与现有信号组 Alpha 报告同一口径。"""
from __future__ import annotations

from typing import Mapping

import numpy as np
import pandas as pd

MIN_OBS = 60
PRIMARY_WINDOW = 250
ALT_WINDOW = 120
ANN_FACTOR = 252.0
T_NEAR_ZERO = 1.0
BETA_SPLIT = 1.0

NOTES = (
    "无风险利率按 0。回归是日收益对沪深300日收益，含截距。",
    "区间超额是同一窗口里累计收益减去沪深300累计收益，不是年化 Alpha。",
    "年化 Alpha 是日截距乘 252。窗口短时这个数会被放大，天数不足时优先看区间超额。",
    "主列用最近 250 个重叠交易日，旁列用最近 120 日。重叠少于 60 日不估计。",
    "情形按主列划分。Alpha 的 t 统计量绝对值小于 1 时，视为接近零。",
    "象限也按主列；主列空着时用 120 日。高 α 要年化 α 为正且 t(α) ≥ 1。高 β 是 β > 1。",
    "优先跟踪是高 α / 低 β。高 α / 高 β 先看超额是否持续。象限不写入观察池，也不改变仓位。",
)

QUADRANT_INSUFFICIENT = {
    "id": "insufficient",
    "title": "样本不足",
    "action": "暂不归类",
    "hint": "250 日和 120 日窗口都空着。",
}


def align_returns(asset: pd.Series, market: pd.Series) -> pd.DataFrame:
    both = pd.concat({"asset": asset, "market": market}, axis=1, join="inner")
    both = both.replace([np.inf, -np.inf], np.nan).dropna()
    both = both.sort_index()
    return both


def classify_quadrant(window: Mapping | None) -> dict[str, str]:
    """用同一窗口的 β 和 t(α) 放进四格。窗口空着时不硬塞。"""
    if not window:
        return dict(QUADRANT_INSUFFICIENT)
    beta = window.get("beta")
    t_alpha = window.get("t_alpha")
    alpha_ann = window.get("alpha_ann")
    if not _finite_number(beta) or not _finite_number(t_alpha) or not _finite_number(alpha_ann):
        return dict(QUADRANT_INSUFFICIENT)
    high_alpha = float(alpha_ann) > 0 and float(t_alpha) >= T_NEAR_ZERO
    high_beta = float(beta) > BETA_SPLIT
    if high_alpha and high_beta:
        return {
            "id": "high_alpha_high_beta",
            "title": "高 α / 高 β",
            "action": "待验证",
            "hint": "有超额收益，但市场暴露也高。先看这段超额是否持续。",
        }
    if high_alpha:
        return {
            "id": "high_alpha_low_beta",
            "title": "高 α / 低 β",
            "action": "优先跟踪",
            "hint": "超额还在，市场暴露相对低。",
        }
    if high_beta:
        return {
            "id": "low_alpha_high_beta",
            "title": "低 α / 高 β",
            "action": "审查",
            "hint": "承担了更高的市场风险，却没有对应补偿。",
        }
    return {
        "id": "low_alpha_low_beta",
        "title": "低 α / 低 β",
        "action": "观察",
        "hint": "对市场不敏感。还要看收益够不够覆盖交易成本。",
    }


def _finite_number(value: object) -> bool:
    if isinstance(value, (bool, str)):
        return False
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(number))


def scenario_label(total: float, t_alpha: float) -> str:
    near = abs(t_alpha) < T_NEAR_ZERO
    up = total > 0
    if up and t_alpha >= T_NEAR_ZERO:
        return "跑赢市场风险基准"
    if up and near:
        return "收益基本可由市场风险解释"
    if (not up) and t_alpha >= T_NEAR_ZERO:
        return "跌幅小于模型预期"
    if up and t_alpha <= -T_NEAR_ZERO:
        return "涨幅低于模型预期"
    if (not up) and t_alpha <= -T_NEAR_ZERO:
        return "跌幅大于模型预期"
    if not up and near:
        return "跌幅与市场风险大体相符"
    return "样本不足以判断"


def fit_window(both: pd.DataFrame, window: int) -> dict | None:
    """取对齐序列的最后 window 行。行数不够则留空，不用更短样本顶替。"""
    if window < MIN_OBS or len(both) < window:
        return None
    part = both.iloc[-int(window) :]
    return _fit(part["asset"].to_numpy(dtype=float), part["market"].to_numpy(dtype=float), part.index)


def attribute_frame(both: pd.DataFrame) -> dict:
    primary = fit_window(both, PRIMARY_WINDOW)
    alt = fit_window(both, ALT_WINDOW)
    source = primary or alt
    label_window = PRIMARY_WINDOW if primary else (ALT_WINDOW if alt else None)
    label = scenario_label(source["total"], source["t_alpha"]) if source else "样本不足"
    quadrant = classify_quadrant(source)
    if primary is None and alt is None:
        if len(both) < MIN_OBS:
            reason = f"与沪深300重叠 {len(both)} 个交易日，少于 {MIN_OBS} 日"
        else:
            reason = f"重叠 {len(both)} 日，不足 {ALT_WINDOW} 日窗口"
    elif primary is None:
        reason = f"重叠 {len(both)} 日，{PRIMARY_WINDOW} 日窗口留空"
    else:
        reason = ""
    return {
        "n_overlap": int(len(both)),
        "label": label,
        "label_window": label_window,
        "quadrant": quadrant,
        "reason": reason,
        "w250": primary,
        "w120": alt,
    }


def _fit(asset: np.ndarray, market: np.ndarray, index: pd.Index) -> dict | None:
    n = int(len(asset))
    if n < MIN_OBS:
        return None
    design = np.column_stack([np.ones(n), market])
    gram = design.T @ design
    det = float(np.linalg.det(gram))
    if not np.isfinite(det) or abs(det) < 1e-18:
        return None
    coef, _, _, _ = np.linalg.lstsq(design, asset, rcond=None)
    alpha = float(coef[0])
    beta = float(coef[1])
    fitted = design @ coef
    resid = asset - fitted
    ss_res = float(np.sum(resid ** 2))
    centered = asset - float(np.mean(asset))
    ss_tot = float(np.sum(centered ** 2))
    r2 = None if ss_tot <= 0 else float(1.0 - ss_res / ss_tot)
    dof = n - 2
    sigma2 = ss_res / dof if dof > 0 else float("nan")
    try:
        cov = sigma2 * np.linalg.inv(gram)
        se_alpha = float(np.sqrt(cov[0, 0]))
        se_beta = float(np.sqrt(cov[1, 1]))
    except np.linalg.LinAlgError:
        se_alpha = float("nan")
        se_beta = float("nan")
    if not np.isfinite(se_alpha) or se_alpha <= 1e-15:
        t_alpha = 0.0 if abs(alpha) < 1e-15 else float(np.copysign(1e6, alpha))
    else:
        t_alpha = alpha / se_alpha
    total = _compound(asset)
    benchmark = _compound(market)
    start = pd.Timestamp(index[0]).date().isoformat()
    end = pd.Timestamp(index[-1]).date().isoformat()
    resid_vol = None
    if np.isfinite(sigma2) and sigma2 >= 0:
        resid_vol = float(np.sqrt(sigma2) * np.sqrt(ANN_FACTOR))
    return {
        "n": n,
        "start": start,
        "end": end,
        "total": total,
        "benchmark": benchmark,
        "excess": None if total is None or benchmark is None else float(total - benchmark),
        "beta": beta,
        "beta_se": None if not np.isfinite(se_beta) else se_beta,
        "alpha_ann": alpha * ANN_FACTOR,
        "t_alpha": float(t_alpha),
        "r2": r2,
        "resid_vol_ann": resid_vol,
    }


def _compound(returns: np.ndarray) -> float | None:
    if len(returns) == 0 or not np.isfinite(returns).all():
        return None
    return float(np.prod(1.0 + returns) - 1.0)


def as_jsonable(value: Mapping | None) -> dict | None:
    if value is None:
        return None
    out: dict = {}
    for key, item in value.items():
        if isinstance(item, (float, np.floating)):
            number = float(item)
            out[key] = number if np.isfinite(number) else None
        elif isinstance(item, (int, np.integer)):
            out[key] = int(item)
        else:
            out[key] = item
    return out
