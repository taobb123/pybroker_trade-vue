# -*- coding: utf-8 -*-
"""经验分布、95% VaR/CVaR、Beta-Binomial 胜率后验。"""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np
import pandas as pd

_FPMIN = 1e-300
_EPS = 3e-14
_MAXIT = 200


def _betacf(a: float, b: float, x: float) -> float:
    """连分式，对应 Numerical Recipes 的 betacf。"""
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _FPMIN:
        d = _FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, _MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < _FPMIN:
            d = _FPMIN
        c = 1.0 + aa / c
        if abs(c) < _FPMIN:
            c = _FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < _EPS:
            break
    return h


def regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """正则化不完全贝塔 I_x(a, b)。"""
    if a <= 0 or b <= 0:
        raise ValueError("a、b 必须为正")
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    log_bt = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log(1.0 - x)
    )
    bt = math.exp(log_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def var_cvar_95(returns: Iterable[float]) -> tuple[float, float]:
    """历史 95% VaR 与 CVaR。

    升序后取最差 k 个样本，k = max(1, ceil(0.05 * n))。
    VaR 是这 k 个里最温和的那个（第 k 差），CVaR 是这 k 个的均值。
    两者都是收益率本身，亏损为负。
    """
    x = np.sort(np.asarray(list(returns), dtype=float))
    x = x[np.isfinite(x)]
    n = int(x.size)
    if n == 0:
        raise ValueError("收益样本为空")
    k = max(1, int(math.ceil(0.05 * n)))
    tail = x[:k]
    return float(tail[-1]), float(tail.mean())


def _normal_sf(z: float) -> float:
    """标准正态的右尾概率 P(Z > z)。"""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def beta_binomial_posterior(
    n_win: int,
    n_loss: int,
    *,
    alpha: float = 1.0,
    beta: float = 1.0,
) -> tuple[float, float]:
    """返回 (后验均值, P(p>0.5|数据))。大样本改用正态近似，避免不完全贝塔下溢。"""
    if n_win < 0 or n_loss < 0:
        raise ValueError("胜负次数不能为负")
    a = float(alpha) + int(n_win)
    b = float(beta) + int(n_loss)
    mean = a / (a + b)
    if a + b > 400:
        var = a * b / ((a + b) ** 2 * (a + b + 1.0))
        if var <= 0:
            prob_gt_half = 1.0 if mean > 0.5 else 0.0
        else:
            prob_gt_half = _normal_sf((0.5 - mean) / math.sqrt(var))
    else:
        prob_gt_half = 1.0 - regularized_incomplete_beta(0.5, a, b)
    return float(mean), float(min(1.0, max(0.0, prob_gt_half)))


def _moment_or_none(series: pd.Series, kind: str) -> float | None:
    if kind == "skew" and len(series) < 3:
        return None
    if kind == "kurt" and len(series) < 4:
        return None
    value = float(series.skew() if kind == "skew" else series.kurt())
    if value != value:
        return None
    return value


def histogram(returns: np.ndarray, bins: int = 12) -> list[dict[str, float | int]]:
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        return []
    if float(np.nanmax(x)) == float(np.nanmin(x)):
        point = float(x[0])
        return [{"left": point, "right": point, "count": int(x.size)}]
    counts, edges = np.histogram(x, bins=bins)
    out: list[dict[str, float | int]] = []
    for i, count in enumerate(counts):
        out.append(
            {
                "left": float(edges[i]),
                "right": float(edges[i + 1]),
                "count": int(count),
            }
        )
    return out
