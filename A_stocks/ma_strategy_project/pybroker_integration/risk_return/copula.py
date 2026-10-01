# -*- coding: utf-8 -*-
"""V6：五个信号组的同日亏损，对照正态相关和互相独立。不产生新的选股分数。"""
from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from risk_return.correlation import SLEEVES, load_aligned

SCHEMA_VERSION = "gaussian_copula_v6"
DEFAULT_PATHS = 10_000
DEFAULT_SEED = 20261001
TAIL_Q = 0.10

NOTES = (
    "正态相关保留每个信号组自己的历史盈亏分布，只把它们按正态方式绑在一起。",
    "互相独立是各信号组单独抽取，同一天不再绑在一起。",
    "底部 10% 是每个信号组自己最差的一成日子。",
    "这里不产生新的选股分数，也不改日常链路。",
)

TOP_LEVEL_KEYS = (
    "schema_version",
    "sleeves",
    "n_days",
    "sample_start",
    "sample_end",
    "n_paths",
    "seed",
    "tail_q",
    "historical_all_negative",
    "gaussian_all_negative",
    "independent_all_negative",
    "pairs",
    "boundary",
    "notes",
    "created_at",
)

PAIR_KEYS = ("left", "right", "historical", "gaussian")

# Peter Acklam 的正态分位近似。
_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)


def norm_ppf(probability: np.ndarray) -> np.ndarray:
    p = np.clip(np.asarray(probability, dtype=float), 1e-12, 1.0 - 1e-12)
    plow = 0.02425
    low = p < plow
    high = p > 1.0 - plow
    mid = ~(low | high)
    out = np.empty(p.shape, dtype=float)
    if np.any(low):
        q = np.sqrt(-2.0 * np.log(p[low]))
        num = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
        den = ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
        out[low] = num / den
    if np.any(high):
        q = np.sqrt(-2.0 * np.log(1.0 - p[high]))
        num = (((((_C[0] * q + _C[1]) * q + _C[2]) * q + _C[3]) * q + _C[4]) * q + _C[5])
        den = ((((_D[0] * q + _D[1]) * q + _D[2]) * q + _D[3]) * q + 1.0)
        out[high] = -(num / den)
    q = p[mid] - 0.5
    r = q * q
    num = (((((_A[0] * r + _A[1]) * r + _A[2]) * r + _A[3]) * r + _A[4]) * r + _A[5]) * q
    den = (((((_B[0] * r + _B[1]) * r + _B[2]) * r + _B[3]) * r + _B[4]) * r + 1.0)
    out[mid] = num / den
    return out


def norm_cdf(score: np.ndarray) -> np.ndarray:
    values = np.asarray(score, dtype=float)
    erfc = np.vectorize(math.erfc, otypes=[float])
    return 0.5 * erfc(-values / math.sqrt(2.0))


def _correlation(scores: np.ndarray) -> np.ndarray:
    corr = np.corrcoef(scores, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    np.fill_diagonal(corr, 1.0)
    values, vectors = np.linalg.eigh(corr)
    values = np.clip(values, 1e-8, None)
    rebuilt = vectors @ np.diag(values) @ vectors.T
    scale = np.sqrt(np.clip(np.diag(rebuilt), 1e-12, None))
    rebuilt = rebuilt / np.outer(scale, scale)
    np.fill_diagonal(rebuilt, 1.0)
    return rebuilt


def _uniforms(values: np.ndarray) -> np.ndarray:
    ranked = pd.DataFrame(values).rank(method="average").to_numpy(dtype=float)
    return ranked / (len(values) + 1.0)


def _empirical_quantile(samples: np.ndarray, probability: np.ndarray) -> np.ndarray:
    ordered = np.sort(np.asarray(samples, dtype=float))
    index = np.floor(np.asarray(probability, dtype=float) * len(ordered)).astype(int)
    index = np.clip(index, 0, len(ordered) - 1)
    return ordered[index]


def simulate_gaussian(values: np.ndarray, n_paths: int, seed: int) -> np.ndarray:
    uniforms = _uniforms(values)
    scores = norm_ppf(uniforms)
    factor = np.linalg.cholesky(_correlation(scores))
    rng = np.random.default_rng(int(seed))
    draws = rng.standard_normal((int(n_paths), values.shape[1])) @ factor.T
    simulated_u = norm_cdf(draws)
    return np.column_stack(
        [_empirical_quantile(values[:, i], simulated_u[:, i]) for i in range(values.shape[1])]
    )


def _boundary(historical: float, gaussian: float, independent: float, top_pair: dict) -> str:
    return (
        f"五组同日为负，历史 {historical * 100:.1f}%，正态相关 {gaussian * 100:.1f}%，互相独立 {independent * 100:.1f}%；"
        f"底部同时落到超出正态相关最多的是 {top_pair['left']} 与 {top_pair['right']}，"
        f"历史 {top_pair['historical'] * 100:.1f}%，正态相关 {top_pair['gaussian'] * 100:.1f}%。"
    )


def build_copula_report(
    aligned: pd.DataFrame,
    *,
    n_paths: int = DEFAULT_PATHS,
    seed: int = DEFAULT_SEED,
    tail_q: float = TAIL_Q,
) -> dict:
    frame = aligned.dropna(subset=list(SLEEVES)).copy()
    values = frame[list(SLEEVES)].to_numpy(dtype=float)
    n_days = int(len(frame))
    if n_days < 30:
        raise ValueError(f"五个信号组重叠只有 {n_days} 天，无法比较正态相关")
    simulated = simulate_gaussian(values, n_paths, seed)
    historical_all = float(np.mean(np.all(values < 0, axis=1)))
    gaussian_all = float(np.mean(np.all(simulated < 0, axis=1)))
    independent_all = float(np.prod(np.mean(values < 0, axis=0)))
    thresholds = np.quantile(values, tail_q, axis=0)
    pairs = []
    for i, left in enumerate(SLEEVES):
        for j, right in enumerate(SLEEVES):
            if j <= i:
                continue
            historical = float(np.mean((values[:, i] <= thresholds[i]) & (values[:, j] <= thresholds[j])))
            gaussian = float(np.mean((simulated[:, i] <= thresholds[i]) & (simulated[:, j] <= thresholds[j])))
            row = {"left": left, "right": right, "historical": historical, "gaussian": gaussian}
            missing = [key for key in PAIR_KEYS if key not in row]
            if missing:
                raise RuntimeError(f"配对缺字段: {missing}")
            pairs.append(row)
    pairs.sort(key=lambda row: row["historical"] - row["gaussian"], reverse=True)
    report = {
        "schema_version": SCHEMA_VERSION,
        "sleeves": list(SLEEVES),
        "n_days": n_days,
        "sample_start": pd.Timestamp(frame["date"].min()).strftime("%Y-%m-%d"),
        "sample_end": pd.Timestamp(frame["date"].max()).strftime("%Y-%m-%d"),
        "n_paths": int(n_paths),
        "seed": int(seed),
        "tail_q": float(tail_q),
        "historical_all_negative": historical_all,
        "gaussian_all_negative": gaussian_all,
        "independent_all_negative": independent_all,
        "pairs": pairs,
        "boundary": _boundary(historical_all, gaussian_all, independent_all, pairs[0]),
        "notes": list(NOTES),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    missing = [key for key in TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(f"正态相关结果缺字段: {missing}")
    return report
