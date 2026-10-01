# -*- coding: utf-8 -*-
"""V4：同一条等权日收益上，比较温度仓位和分数凯利。只做研究展示，不写实盘仓位。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from risk_return.correlation import SLEEVES, load_aligned
from risk_return.distribution import beta_binomial_posterior
from risk_return.monte_carlo import kelly_raw
from risk_return.regime import TEMPERATURE_CSV, attach_prior_temperature, load_temperature

SCHEMA_VERSION = "risk_budget_v4"
QUARTER = 0.25

NOTES = (
    "等权曲线只用来比较仓位预算，不产生新的选股分数。",
    "温度仓位用收益日之前已经知道的建议仓位。",
    "四分之一凯利用这整段等权日收益估计，是样本内对照，不是当时已经知道的仓位。",
    "取更小是每一天在温度仓位和四分之一凯利里留较小的那个。",
    "这里不改日常的半凯利，也不写实盘仓位文件。",
)

TOP_LEVEL_KEYS = (
    "schema_version",
    "sleeves",
    "n_days",
    "sample_start",
    "sample_end",
    "posterior_win_rate",
    "payoff_b",
    "kelly_raw",
    "quarter_position",
    "budgets",
    "notes",
    "created_at",
)

BUDGET_KEYS = (
    "name",
    "average_position",
    "terminal_wealth",
    "total_return",
    "max_drawdown",
)


def equal_weight_return(frame: pd.DataFrame) -> pd.Series:
    return frame[list(SLEEVES)].mean(axis=1)


def estimate_quarter_kelly(returns: np.ndarray) -> dict[str, float]:
    values = np.asarray(returns, dtype=float)
    values = values[np.isfinite(values)]
    if values.size == 0:
        raise ValueError("等权日收益为空")
    wins = values[values > 0]
    losses = values[values < 0]
    if wins.size == 0 or losses.size == 0:
        raise ValueError("等权日收益缺少盈利或亏损，无法估计凯利")
    posterior, _ = beta_binomial_posterior(int(wins.size), int(np.sum(values <= 0)))
    payoff = float(wins.mean() / abs(losses.mean()))
    raw = kelly_raw(posterior, payoff)
    if raw != raw:
        raise ValueError("凯利估计无效")
    quarter = QUARTER * max(0.0, raw)
    return {
        "posterior_win_rate": float(posterior),
        "payoff_b": payoff,
        "kelly_raw": float(raw),
        "quarter_position": float(quarter),
    }


def path_stats(name: str, positions: np.ndarray, returns: np.ndarray) -> dict[str, float | str]:
    wealth = 1.0
    peak = 1.0
    max_dd = 0.0
    for pos, ret in zip(positions, returns, strict=True):
        wealth = max(0.0, wealth * (1.0 + float(pos) * float(ret)))
        peak = max(peak, wealth)
        if peak > 0:
            max_dd = max(max_dd, 1.0 - wealth / peak)
    return {
        "name": name,
        "average_position": float(np.mean(positions)),
        "terminal_wealth": float(wealth),
        "total_return": float(wealth - 1.0),
        "max_drawdown": float(max_dd),
    }


def build_budget_report(aligned: pd.DataFrame, temperature: pd.DataFrame) -> dict:
    joined = attach_prior_temperature(aligned, temperature)
    if joined.empty:
        raise ValueError("温度档没有覆盖这些收益日")
    returns = equal_weight_return(joined).to_numpy(dtype=float)
    temperature_position = pd.to_numeric(joined["position_pct"], errors="coerce").to_numpy(dtype=float) / 100.0
    if not np.isfinite(temperature_position).all():
        raise ValueError("温度仓位有缺失")
    kelly = estimate_quarter_kelly(returns)
    quarter = np.full(returns.shape, kelly["quarter_position"], dtype=float)
    full = np.ones(returns.shape, dtype=float)
    tighter = np.minimum(temperature_position, quarter)
    budgets = [
        path_stats("始终满仓", full, returns),
        path_stats("温度仓位", temperature_position, returns),
        path_stats("四分之一凯利", quarter, returns),
        path_stats("取更小", tighter, returns),
    ]
    for row in budgets:
        missing = [key for key in BUDGET_KEYS if key not in row]
        if missing:
            raise RuntimeError(f"风险预算缺字段: {missing}")
    report = {
        "schema_version": SCHEMA_VERSION,
        "sleeves": list(SLEEVES),
        "n_days": int(len(joined)),
        "sample_start": pd.Timestamp(joined["date"].min()).strftime("%Y-%m-%d"),
        "sample_end": pd.Timestamp(joined["date"].max()).strftime("%Y-%m-%d"),
        "posterior_win_rate": kelly["posterior_win_rate"],
        "payoff_b": kelly["payoff_b"],
        "kelly_raw": kelly["kelly_raw"],
        "quarter_position": kelly["quarter_position"],
        "budgets": budgets,
        "notes": list(NOTES),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    missing = [key for key in TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(f"风险预算结果缺字段: {missing}")
    return report


def load_budget_inputs(
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_aligned(group_path, sleeve_path), load_temperature(temperature_path or TEMPERATURE_CSV)
