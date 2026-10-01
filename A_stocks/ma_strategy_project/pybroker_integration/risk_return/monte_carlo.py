# -*- coding: utf-8 -*-
"""从经验收益里有放回抽样，生成分数 Kelly 下的资金路径摘要。"""
from __future__ import annotations

from typing import Iterable

import numpy as np

from risk_return.contract import KELLY_FRACTIONS, SCENARIO_KEYS


def kelly_raw(p: float, b: float) -> float:
    """f* = p - (1-p)/b。无效输入返回 nan。不设上限。"""
    if not (0.0 <= p <= 1.0) or not (b > 0) or p != p or b != b:
        return float("nan")
    return float(p - (1.0 - p) / b)


def simulate_wealth(
    returns: Iterable[float],
    position: float,
    *,
    n_paths: int,
    n_trades: int,
    seed: int,
) -> dict[str, float]:
    """初始资金为 1。每笔组合收益 = position × 抽出的个股收益，其余视为现金。"""
    sample = np.asarray(list(returns), dtype=float)
    sample = sample[np.isfinite(sample)]
    if sample.size == 0:
        raise ValueError("蒙特卡洛样本为空")
    if n_paths <= 0 or n_trades <= 0:
        raise ValueError("路径数和笔数必须为正")
    rng = np.random.default_rng(int(seed))
    draws = rng.choice(sample, size=(int(n_paths), int(n_trades)), replace=True)
    wealth = np.empty((int(n_paths), int(n_trades) + 1), dtype=float)
    wealth[:, 0] = 1.0
    step = 1.0 + float(position) * draws
    for t in range(int(n_trades)):
        wealth[:, t + 1] = np.maximum(wealth[:, t] * step[:, t], 0.0)
    peak = np.maximum.accumulate(wealth, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = np.where(peak > 0, 1.0 - wealth / peak, 1.0)
    max_dd = drawdown.max(axis=1)
    terminal = wealth[:, -1]
    return {
        "median_terminal_wealth": float(np.median(terminal)),
        "p05_terminal_wealth": float(np.quantile(terminal, 0.05)),
        "p25_terminal_wealth": float(np.quantile(terminal, 0.25)),
        "p75_terminal_wealth": float(np.quantile(terminal, 0.75)),
        "p95_terminal_wealth": float(np.quantile(terminal, 0.95)),
        "median_max_drawdown": float(np.median(max_dd)),
        "prob_dd_gt_20": float(np.mean(max_dd > 0.20)),
        "prob_dd_gt_30": float(np.mean(max_dd > 0.30)),
    }


def kelly_scenarios(
    returns: np.ndarray,
    kelly_full: float,
    *,
    n_paths: int,
    n_trades: int,
    seed: int,
) -> list[dict[str, float | str]]:
    rows: list[dict[str, float | str]] = []
    for fraction, name in KELLY_FRACTIONS:
        position = max(0.0, float(fraction) * float(kelly_full))
        stats = simulate_wealth(
            returns,
            position,
            n_paths=n_paths,
            n_trades=n_trades,
            seed=seed,
        )
        row: dict[str, float | str] = {
            "name": name,
            "fraction_of_kelly": float(fraction),
            "position": float(position),
        }
        row.update(stats)
        missing = [key for key in SCENARIO_KEYS if key not in row]
        if missing:
            raise RuntimeError(f"情景缺字段: {missing}")
        rows.append(row)
    return rows
