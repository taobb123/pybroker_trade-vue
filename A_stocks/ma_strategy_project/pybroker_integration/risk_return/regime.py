# -*- coding: utf-8 -*-
"""V3：用收益日之前已经知道的市场温度仓位档，拆开五个信号组的日收益。不做状态转移。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from risk_return.correlation import GROUP_RETURNS, SLEEVES, SLEEVE_RETURNS, load_aligned

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPERATURE_CSV = PROJECT_ROOT / "market_temperature_backtest.csv"

STATE_ORDER = ("空仓", "轻仓 20%", "中仓 40%", "重仓 70%", "满仓 100%")
SCHEMA_VERSION = "temp_regime_v3"
SMALL_N = 30

NOTES = (
    "市场状态用现成的温度计仓位档，不另造牛市、震荡、熊市。",
    "收益日只用严格早于该日的温度总分和仓位档。",
    "每一档给出五个信号组的日收益均值，以及五组同日为负的比例。",
    "仓位档沿用温度回测表里已经记下的建议仓位。分数高不一定对应更重的仓。",
    "天数少于 30 的档只作对照，不单独下结论。",
)

TOP_LEVEL_KEYS = (
    "schema_version",
    "sleeves",
    "temperature_file",
    "n_days",
    "sample_start",
    "sample_end",
    "states",
    "notes",
    "created_at",
)

STATE_KEYS = (
    "label",
    "position_pct",
    "n_days",
    "small_sample",
    "mean_score",
    "means",
    "loss_rates",
    "all_negative",
)


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return path.name


def load_temperature(path: Path | None = None) -> pd.DataFrame:
    dest = Path(path or TEMPERATURE_CSV)
    if not dest.is_file():
        raise FileNotFoundError(f"缺少市场温度回测表: {dest}")
    frame = pd.read_csv(dest)
    if "trade_date" not in frame.columns or "position_label" not in frame.columns:
        raise ValueError(f"{dest.name} 缺少 trade_date 或 position_label")
    out = pd.DataFrame()
    out["temp_date"] = pd.to_datetime(frame["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    out["position_label"] = frame["position_label"].astype(str)
    out["position_pct"] = pd.to_numeric(frame.get("position_pct"), errors="coerce")
    out["total_score"] = pd.to_numeric(frame.get("total_score"), errors="coerce")
    out = out.dropna(subset=["temp_date", "position_label"])
    out = out[out["position_label"].str.len() > 0]
    return out.sort_values("temp_date").drop_duplicates("temp_date", keep="last")


def attach_prior_temperature(returns: pd.DataFrame, temperature: pd.DataFrame) -> pd.DataFrame:
    """收益日 t 只匹配 temp_date < t 的最近一档。"""
    left = returns.copy()
    left["date"] = pd.to_datetime(left["date"]).dt.normalize()
    left["asof"] = left["date"] - pd.Timedelta(days=1)
    right = temperature.sort_values("temp_date")
    merged = pd.merge_asof(
        left.sort_values("asof"),
        right,
        left_on="asof",
        right_on="temp_date",
        direction="backward",
    )
    merged = merged[merged["temp_date"].notna()]
    merged = merged[merged["temp_date"] < merged["date"]]
    return merged.sort_values("date").reset_index(drop=True)


def _state_row(label: str, block: pd.DataFrame) -> dict:
    values = block[list(SLEEVES)].to_numpy(dtype=float)
    n_days = int(len(block))
    pct = pd.to_numeric(block["position_pct"], errors="coerce").dropna()
    score = pd.to_numeric(block["total_score"], errors="coerce").dropna()
    return {
        "label": label,
        "position_pct": None if pct.empty else float(pct.iloc[-1]),
        "n_days": n_days,
        "small_sample": n_days < SMALL_N,
        "mean_score": None if score.empty else float(score.mean()),
        "means": {name: float(values[:, i].mean()) for i, name in enumerate(SLEEVES)},
        "loss_rates": {name: float(np.mean(values[:, i] < 0)) for i, name in enumerate(SLEEVES)},
        "all_negative": float(np.mean(np.all(values < 0, axis=1))) if n_days else None,
    }


def build_regime_report(
    aligned: pd.DataFrame,
    temperature: pd.DataFrame,
    *,
    temperature_path: Path | None = None,
) -> dict:
    joined = attach_prior_temperature(aligned, temperature)
    if joined.empty:
        raise ValueError("温度档没有覆盖这些收益日")
    order = {name: i for i, name in enumerate(STATE_ORDER)}
    labels = sorted(joined["position_label"].unique(), key=lambda name: (order.get(name, 99), name))
    states = [_state_row(label, joined[joined["position_label"] == label]) for label in labels]
    for row in states:
        missing = [key for key in STATE_KEYS if key not in row]
        if missing:
            raise RuntimeError(f"温度档缺字段: {missing}")
    report = {
        "schema_version": SCHEMA_VERSION,
        "sleeves": list(SLEEVES),
        "temperature_file": _rel(Path(temperature_path or TEMPERATURE_CSV)),
        "n_days": int(len(joined)),
        "sample_start": pd.Timestamp(joined["date"].min()).strftime("%Y-%m-%d"),
        "sample_end": pd.Timestamp(joined["date"].max()).strftime("%Y-%m-%d"),
        "states": states,
        "notes": list(NOTES),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    missing = [key for key in TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(f"温度档结果缺字段: {missing}")
    return report


def load_regime_inputs(
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    aligned = load_aligned(group_path or GROUP_RETURNS, sleeve_path or SLEEVE_RETURNS)
    temperature = load_temperature(temperature_path)
    return aligned, temperature
