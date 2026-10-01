# -*- coding: utf-8 -*-
"""V5：训练期估计分数凯利，测试期才记真实结果，并把分数轻轻挪开。不写实盘仓位。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from risk_return.budget import equal_weight_return, estimate_quarter_kelly, path_stats
from risk_return.correlation import SLEEVES, load_aligned
from risk_return.regime import TEMPERATURE_CSV, attach_prior_temperature, load_temperature

SCHEMA_VERSION = "walkforward_v5"
TRAIN_DAYS = 60
TEST_DAYS = 20
STEP_DAYS = 20
FRACTIONS = (0.15, 0.25, 0.35)
BASE_FRACTION = 0.25

NOTES = (
    "等权曲线只用于这次滚动检验，不产生新的选股分数。",
    "每一轮用过去 60 个交易日估计凯利，后面 20 个交易日才用这个仓位。测试期开始前仓位已经定下。",
    "扰动把凯利分数从 0.25 挪到 0.15 和 0.35，看测试期累计收益和回撤变多少。",
    "这里不改日常的半凯利，也不写实盘仓位文件。",
)

TOP_LEVEL_KEYS = (
    "schema_version",
    "sleeves",
    "train_days",
    "test_days",
    "step_days",
    "n_folds",
    "oos_start",
    "oos_end",
    "folds",
    "perturbations",
    "boundary",
    "notes",
    "created_at",
)

FOLD_KEYS = (
    "train_start",
    "train_end",
    "test_start",
    "test_end",
    "posterior_win_rate",
    "kelly_raw",
    "position",
    "predicted_loss_prob",
    "realized_loss_rate",
    "test_return",
    "test_max_drawdown",
    "temperature_return",
    "temperature_max_drawdown",
)

PERTURB_KEYS = (
    "fraction",
    "terminal_wealth",
    "total_return",
    "max_drawdown",
    "worst_fold_return",
)


def _windows(n_days: int, train_days: int, test_days: int, step_days: int):
    start = 0
    while start + train_days + test_days <= n_days:
        train_end = start + train_days
        test_end = train_end + test_days
        yield start, train_end, test_end
        start += step_days


def _position_from_train(train_returns: np.ndarray, fraction: float) -> dict[str, float] | None:
    try:
        est = estimate_quarter_kelly(train_returns)
    except ValueError:
        return None
    raw = max(0.0, float(est["kelly_raw"]))
    return {
        "posterior_win_rate": float(est["posterior_win_rate"]),
        "kelly_raw": float(est["kelly_raw"]),
        "position": float(fraction) * raw,
    }


def _boundary(rows: list[dict], folds: list[dict]) -> str:
    returns = [float(row["total_return"]) for row in rows]
    temps = [float(fold["temperature_return"]) for fold in folds]
    return (
        f"凯利分数在 0.15 到 0.35 之间挪动时，测试期累计只从 {min(returns) * 100:.1f}% 变到 {max(returns) * 100:.1f}%；"
        f"同一批测试段上，温度仓位收益从 {min(temps) * 100:.1f}% 摆到 {max(temps) * 100:.1f}%。"
    )


def build_walkforward_report(
    aligned: pd.DataFrame,
    temperature: pd.DataFrame,
    *,
    train_days: int = TRAIN_DAYS,
    test_days: int = TEST_DAYS,
    step_days: int = STEP_DAYS,
    fractions: tuple[float, ...] = FRACTIONS,
) -> dict:
    if train_days < 4 or test_days < 1 or step_days < 1:
        raise ValueError("训练期至少 4 天，测试期和步长必须为正")
    if BASE_FRACTION not in fractions:
        raise ValueError("扰动里需要包含 0.25")
    joined = attach_prior_temperature(aligned, temperature)
    if joined.empty:
        raise ValueError("温度档没有覆盖这些收益日")
    returns = equal_weight_return(joined).to_numpy(dtype=float)
    temperature_position = pd.to_numeric(joined["position_pct"], errors="coerce").to_numpy(dtype=float) / 100.0
    dates = pd.to_datetime(joined["date"])
    spans = list(_windows(len(returns), train_days, test_days, step_days))
    if not spans:
        raise ValueError(f"样本只有 {len(returns)} 天，不够一轮 {train_days}+{test_days} 的滚动检验")

    folds: list[dict] = []
    pieces: dict[float, list[tuple[np.ndarray, np.ndarray]]] = {fraction: [] for fraction in fractions}
    for train_start, train_end, test_end in spans:
        train = returns[train_start:train_end]
        test = returns[train_end:test_end]
        temp_pos = temperature_position[train_end:test_end]
        base = _position_from_train(train, BASE_FRACTION)
        if base is None:
            base = {"posterior_win_rate": None, "kelly_raw": None, "position": 0.0}
        held = np.full(test.shape, float(base["position"]))
        held_stats = path_stats("测试", held, test)
        temp_stats = path_stats("温度", temp_pos, test)
        posterior = base["posterior_win_rate"]
        fold = {
            "train_start": pd.Timestamp(dates.iloc[train_start]).strftime("%Y-%m-%d"),
            "train_end": pd.Timestamp(dates.iloc[train_end - 1]).strftime("%Y-%m-%d"),
            "test_start": pd.Timestamp(dates.iloc[train_end]).strftime("%Y-%m-%d"),
            "test_end": pd.Timestamp(dates.iloc[test_end - 1]).strftime("%Y-%m-%d"),
            "posterior_win_rate": posterior,
            "kelly_raw": base["kelly_raw"],
            "position": float(base["position"]),
            "predicted_loss_prob": None if posterior is None else float(1.0 - posterior),
            "realized_loss_rate": float(np.mean(test <= 0)),
            "test_return": float(held_stats["total_return"]),
            "test_max_drawdown": float(held_stats["max_drawdown"]),
            "temperature_return": float(temp_stats["total_return"]),
            "temperature_max_drawdown": float(temp_stats["max_drawdown"]),
        }
        missing = [key for key in FOLD_KEYS if key not in fold]
        if missing:
            raise RuntimeError(f"滚动检验缺字段: {missing}")
        folds.append(fold)
        for fraction in fractions:
            est = _position_from_train(train, fraction)
            position = 0.0 if est is None else float(est["position"])
            pieces[fraction].append((np.full(test.shape, position), test))

    perturbations = []
    for fraction in fractions:
        positions = np.concatenate([item[0] for item in pieces[fraction]])
        test_returns = np.concatenate([item[1] for item in pieces[fraction]])
        stats = path_stats(f"{fraction:.2f}", positions, test_returns)
        fold_returns = []
        for pos, ret in pieces[fraction]:
            fold_returns.append(float(path_stats("段", pos, ret)["total_return"]))
        row = {
            "fraction": float(fraction),
            "terminal_wealth": float(stats["terminal_wealth"]),
            "total_return": float(stats["total_return"]),
            "max_drawdown": float(stats["max_drawdown"]),
            "worst_fold_return": float(min(fold_returns)),
        }
        missing = [key for key in PERTURB_KEYS if key not in row]
        if missing:
            raise RuntimeError(f"扰动结果缺字段: {missing}")
        perturbations.append(row)

    report = {
        "schema_version": SCHEMA_VERSION,
        "sleeves": list(SLEEVES),
        "train_days": int(train_days),
        "test_days": int(test_days),
        "step_days": int(step_days),
        "n_folds": int(len(folds)),
        "oos_start": folds[0]["test_start"],
        "oos_end": folds[-1]["test_end"],
        "folds": folds,
        "perturbations": perturbations,
        "boundary": _boundary(perturbations, folds),
        "notes": list(NOTES),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    missing = [key for key in TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(f"滚动检验结果缺字段: {missing}")
    return report


def load_walkforward_inputs(
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_aligned(group_path, sleeve_path), load_temperature(temperature_path or TEMPERATURE_CSV)
