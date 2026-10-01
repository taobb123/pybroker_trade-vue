# -*- coding: utf-8 -*-
"""把 M+ 十分位样本收成一份研究 JSON。不写日常链文件。"""
from __future__ import annotations

from datetime import datetime
from typing import Mapping

import numpy as np
import pandas as pd

from risk_return.contract import (
    DECILE_KEYS,
    DEFAULT_N_PATHS,
    DEFAULT_N_TRADES,
    DEFAULT_SEED,
    FACTOR,
    FACTOR_FIELD,
    FACTOR_NOTE,
    HISTOGRAM_BINS,
    HOLD_TRADING_DAYS,
    NOTES,
    PRIOR_ALPHA,
    PRIOR_BETA,
    SAMPLE_STEP_TRADING_DAYS,
    SCHEMA_VERSION,
    SEED_RULE,
    SMALL_SAMPLE_N,
    TOP_LEVEL_KEYS,
    WEALTH_START,
)
from risk_return.distribution import (
    beta_binomial_posterior,
    histogram,
    var_cvar_95,
)
from risk_return.monte_carlo import kelly_raw, kelly_scenarios
from risk_return.samples import build_mplus_t3_samples


def _none_if_nan(value: float | None) -> float | None:
    if value is None:
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _empty_decile(decile: int) -> dict:
    row = {key: None for key in DECILE_KEYS}
    row["decile"] = decile
    row["label"] = f"Q{decile}"
    row["n"] = 0
    row["small_sample"] = True
    row["histogram"] = []
    row["scenarios"] = []
    row["note"] = None
    return row


def summarize_decile(
    returns: np.ndarray,
    decile: int,
    *,
    n_paths: int,
    n_trades: int,
    seed: int,
    prior_alpha: float,
    prior_beta: float,
    small_n: int,
) -> dict:
    row = _empty_decile(decile)
    x = np.asarray(returns, dtype=float)
    x = x[np.isfinite(x)]
    n = int(x.size)
    row["n"] = n
    row["small_sample"] = n < int(small_n)
    if n == 0:
        return row
    wins = int(np.sum(x > 0))
    losses = n - wins
    posterior, prob_gt = beta_binomial_posterior(
        wins, losses, alpha=prior_alpha, beta=prior_beta
    )
    var_95, cvar_95 = var_cvar_95(x)
    series = pd.Series(x)
    positive = x[x > 0]
    negative = x[x < 0]
    payoff = None
    note = None
    raw = None
    full = 0.0
    if positive.size > 0 and negative.size > 0:
        payoff = float(positive.mean() / abs(float(negative.mean())))
        raw = kelly_raw(posterior, payoff)
        full = 0.0 if raw != raw else max(0.0, float(raw))
    else:
        note = "盈亏比无法估计，对照仓位为 0"
    row.update(
        {
            "mean": float(x.mean()),
            "median": float(np.median(x)),
            "win_rate": wins / n,
            "posterior_win_rate": posterior,
            "prob_win_rate_gt_half": prob_gt,
            "prob_loss": losses / n,
            "std": float(series.std(ddof=1)) if n >= 2 else None,
            "skew": _none_if_nan(float(series.skew())) if n >= 3 else None,
            "excess_kurtosis": _none_if_nan(float(series.kurt())) if n >= 4 else None,
            "var_95": var_95,
            "cvar_95": cvar_95,
            "payoff_b": payoff,
            "kelly_raw": _none_if_nan(raw) if raw is not None else None,
            "kelly_full": full,
            "histogram": histogram(x, HISTOGRAM_BINS),
            "scenarios": kelly_scenarios(
                x,
                full,
                n_paths=n_paths,
                n_trades=n_trades,
                seed=int(seed) + int(decile),
            ),
            "note": note,
        }
    )
    return row


def report_from_samples(
    samples: pd.DataFrame,
    *,
    n_paths: int = DEFAULT_N_PATHS,
    n_trades: int = DEFAULT_N_TRADES,
    seed: int = DEFAULT_SEED,
    sample_step: int | None = SAMPLE_STEP_TRADING_DAYS,
    sample_source: str = "",
) -> dict:
    deciles = []
    if samples is None or samples.empty:
        grouped: dict[int, np.ndarray] = {}
        sample_end = None
        n_rows = 0
        n_dates = 0
    else:
        frame = samples.copy()
        frame["decile"] = pd.to_numeric(frame["decile"], errors="coerce")
        frame["fwd_ret"] = pd.to_numeric(frame["fwd_ret"], errors="coerce")
        frame = frame.dropna(subset=["decile", "fwd_ret"])
        frame["date"] = pd.to_datetime(frame["date"]).dt.normalize()
        grouped = {
            int(decile): grp["fwd_ret"].to_numpy(dtype=float)
            for decile, grp in frame.groupby("decile")
        }
        sample_end = frame["date"].max().strftime("%Y-%m-%d") if not frame.empty else None
        n_rows = int(len(frame))
        n_dates = int(frame["date"].nunique()) if n_rows else 0
    for decile in range(1, 11):
        deciles.append(
            summarize_decile(
                grouped.get(decile, np.array([], dtype=float)),
                decile,
                n_paths=n_paths,
                n_trades=n_trades,
                seed=seed,
                prior_alpha=PRIOR_ALPHA,
                prior_beta=PRIOR_BETA,
                small_n=SMALL_SAMPLE_N,
            )
        )
    report = {
        "schema_version": SCHEMA_VERSION,
        "factor": FACTOR,
        "factor_field": FACTOR_FIELD,
        "factor_note": FACTOR_NOTE,
        "hold_trading_days": HOLD_TRADING_DAYS,
        "sample_step_trading_days": sample_step,
        "sample_source": sample_source,
        "sample_end": sample_end,
        "n_rows": n_rows,
        "n_signal_dates": n_dates,
        "n_paths": int(n_paths),
        "n_trades": int(n_trades),
        "seed": int(seed),
        "seed_rule": SEED_RULE,
        "prior_alpha": PRIOR_ALPHA,
        "prior_beta": PRIOR_BETA,
        "small_sample_n": SMALL_SAMPLE_N,
        "wealth_start": WEALTH_START,
        "deciles": deciles,
        "notes": list(NOTES),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    missing = [key for key in TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(f"结果缺字段: {missing}")
    return report


def run_mplus_t3(
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    n_paths: int = DEFAULT_N_PATHS,
    n_trades: int = DEFAULT_N_TRADES,
    seed: int = DEFAULT_SEED,
) -> dict:
    samples = build_mplus_t3_samples(bars_by_symbol)
    return report_from_samples(
        samples,
        n_paths=n_paths,
        n_trades=n_trades,
        seed=seed,
    )
