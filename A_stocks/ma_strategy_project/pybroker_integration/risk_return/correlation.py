# -*- coding: utf-8 -*-
"""V2：五个已有信号组的日收益相关，以及共同为负是否高于相互独立。只读现成收益表。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GROUP_RETURNS = PROJECT_ROOT / "output" / "h0_w23_w46" / "group_returns.csv"
SLEEVE_RETURNS = PROJECT_ROOT / "output" / "doc15_sleeves" / "sleeve_returns.csv"

SLEEVES = ("W2+W3", "W4+W6", "M+", "Q", "G")
GROUP_COLUMNS = ("W2+W3", "W4+W6")
SLEEVE_COLUMNS = ("M+", "Q", "G")

SCHEMA_VERSION = "sleeve_corr_v2"
DEFAULT_PATHS = 10_000
DEFAULT_HORIZON = 60
DEFAULT_SEED = 20261001

NOTES = (
    "W2+W3 是底部放量上涨与上涨缩量整理的并集：近 6 个交易日里，每只股票只留最新一次分类，落到 2 或 3 就进这一组，组内等权。",
    "W4+W6 是上涨放量突破与下跌放量的并集，规则相同，落到 4 或 6 就进这一组，组内等权。",
    "一只股票按最新分类只进其中一组，不是把两个组合的收益再按 50% 对半相加。",
    "M+、Q、G 用已有的因子多头日收益：M+ 按周取前 10%，Q 按月取前 10%，G 按月取增长分前 13。",
    "相关和共同为负只在五个信号组都有收益的交易日上计算。",
    "独立对照是各信号组单独有放回抽样。联合对照是同一天的五行一起抽样。",
    "等权曲线只用于比较回撤，不产生新的选股分数。",
)

TOP_LEVEL_KEYS = (
    "schema_version",
    "sleeves",
    "sources",
    "n_days",
    "sample_start",
    "sample_end",
    "small_sample",
    "means",
    "loss_rates",
    "correlation",
    "historical_all_negative",
    "historical_at_least_four_negative",
    "independent_all_negative",
    "joint_all_negative",
    "n_paths",
    "horizon_days",
    "seed",
    "joint_median_max_drawdown",
    "independent_median_max_drawdown",
    "joint_prob_dd_gt_20",
    "independent_prob_dd_gt_20",
    "notes",
    "created_at",
)


def load_aligned(
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
) -> pd.DataFrame:
    group_file = Path(group_path or GROUP_RETURNS)
    sleeve_file = Path(sleeve_path or SLEEVE_RETURNS)
    missing = [str(p) for p in (group_file, sleeve_file) if not p.is_file()]
    if missing:
        raise FileNotFoundError("缺少已有收益表: " + "；".join(missing))
    group = pd.read_csv(group_file)
    sleeve = pd.read_csv(sleeve_file)
    for frame, cols, path in (
        (group, GROUP_COLUMNS, group_file),
        (sleeve, SLEEVE_COLUMNS, sleeve_file),
    ):
        absent = [col for col in cols if col not in frame.columns]
        if absent or "date" not in frame.columns:
            raise ValueError(f"{path.name} 缺少列: {', '.join(absent or ['date'])}")
    group["date"] = pd.to_datetime(group["date"], errors="coerce").dt.normalize()
    sleeve["date"] = pd.to_datetime(sleeve["date"], errors="coerce").dt.normalize()
    merged = group[["date", *GROUP_COLUMNS]].merge(
        sleeve[["date", *SLEEVE_COLUMNS]],
        on="date",
        how="inner",
    )
    for col in SLEEVES:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")
    merged = merged.dropna(subset=list(SLEEVES)).sort_values("date")
    return merged.reset_index(drop=True)


def _drawdown_stats(portfolio: np.ndarray) -> tuple[float, float]:
    """portfolio 形状 (路径, 天数)，元素是日收益。"""
    n_paths, horizon = portfolio.shape
    wealth = np.empty((n_paths, horizon + 1), dtype=float)
    wealth[:, 0] = 1.0
    for t in range(horizon):
        wealth[:, t + 1] = np.maximum(wealth[:, t] * (1.0 + portfolio[:, t]), 0.0)
    peak = np.maximum.accumulate(wealth, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        drawdown = np.where(peak > 0, 1.0 - wealth / peak, 1.0)
    max_dd = drawdown.max(axis=1)
    return float(np.median(max_dd)), float(np.mean(max_dd > 0.20))


def build_correlation_report(
    aligned: pd.DataFrame,
    *,
    n_paths: int = DEFAULT_PATHS,
    horizon_days: int = DEFAULT_HORIZON,
    seed: int = DEFAULT_SEED,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
) -> dict:
    frame = aligned.dropna(subset=list(SLEEVES)).copy()
    values = frame[list(SLEEVES)].to_numpy(dtype=float)
    n_days = int(len(frame))
    if n_days < 5:
        raise ValueError(f"五个信号组重叠只有 {n_days} 天，无法估计相关")
    horizon = min(int(horizon_days), n_days)
    corr = frame[list(SLEEVES)].corr(method="pearson")
    matrix = [
        [None if pd.isna(corr.loc[row, col]) else float(corr.loc[row, col]) for col in SLEEVES]
        for row in SLEEVES
    ]
    all_negative = np.all(values < 0, axis=1)
    at_least_four = np.sum(values < 0, axis=1) >= 4
    rng = np.random.default_rng(int(seed))
    joint_idx = rng.integers(0, n_days, size=int(n_paths))
    indep_draws = np.column_stack(
        [values[rng.integers(0, n_days, size=int(n_paths)), i] for i in range(len(SLEEVES))]
    )
    joint_day = values[joint_idx]
    path_seed = np.random.default_rng(int(seed) + 1)
    joint_paths = values[path_seed.integers(0, n_days, size=(int(n_paths), horizon))]
    indep_paths = np.stack(
        [
            values[path_seed.integers(0, n_days, size=(int(n_paths), horizon)), i]
            for i in range(len(SLEEVES))
        ],
        axis=2,
    )
    joint_dd, joint_p20 = _drawdown_stats(joint_paths.mean(axis=2))
    indep_dd, indep_p20 = _drawdown_stats(indep_paths.mean(axis=2))
    group_file = Path(group_path or GROUP_RETURNS)
    sleeve_file = Path(sleeve_path or SLEEVE_RETURNS)

    def _rel(path: Path) -> str:
        try:
            return path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return path.name

    sources = [
        {"sleeve": "W2+W3", "file": _rel(group_file), "column": "W2+W3"},
        {"sleeve": "W4+W6", "file": _rel(group_file), "column": "W4+W6"},
        {"sleeve": "M+", "file": _rel(sleeve_file), "column": "M+"},
        {"sleeve": "Q", "file": _rel(sleeve_file), "column": "Q"},
        {"sleeve": "G", "file": _rel(sleeve_file), "column": "G"},
    ]
    report = {
        "schema_version": SCHEMA_VERSION,
        "sleeves": list(SLEEVES),
        "sources": sources,
        "n_days": n_days,
        "sample_start": pd.Timestamp(frame["date"].min()).strftime("%Y-%m-%d"),
        "sample_end": pd.Timestamp(frame["date"].max()).strftime("%Y-%m-%d"),
        "small_sample": n_days < 30,
        "means": {name: float(values[:, i].mean()) for i, name in enumerate(SLEEVES)},
        "loss_rates": {name: float(np.mean(values[:, i] < 0)) for i, name in enumerate(SLEEVES)},
        "correlation": matrix,
        "historical_all_negative": float(np.mean(all_negative)),
        "historical_at_least_four_negative": float(np.mean(at_least_four)),
        "independent_all_negative": float(np.mean(np.all(indep_draws < 0, axis=1))),
        "joint_all_negative": float(np.mean(np.all(joint_day < 0, axis=1))),
        "n_paths": int(n_paths),
        "horizon_days": int(horizon),
        "seed": int(seed),
        "joint_median_max_drawdown": joint_dd,
        "independent_median_max_drawdown": indep_dd,
        "joint_prob_dd_gt_20": joint_p20,
        "independent_prob_dd_gt_20": indep_p20,
        "notes": list(NOTES),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    missing = [key for key in TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(f"相关结果缺字段: {missing}")
    return report
