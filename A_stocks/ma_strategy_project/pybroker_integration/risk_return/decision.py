# -*- coding: utf-8 -*-
"""决策中心：市场数据 → 温度档 → 估计器 → 一个仓位 → 当日结果 → 下一档状态。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from risk_return.budget import equal_weight_return, estimate_quarter_kelly, path_stats
from risk_return.copula import simulate_gaussian
from risk_return.correlation import SLEEVES, load_aligned
from risk_return.distribution import beta_binomial_posterior, var_cvar_95
from risk_return.regime import (
    SMALL_N,
    STATE_ORDER,
    TEMPERATURE_CSV,
    attach_prior_temperature,
    load_temperature,
)

SCHEMA_VERSION = "decision_center_v2"
LAMBDA_TAIL = 1.0
HORIZON_DAYS = 20
DEFAULT_PATHS = 4_000
DEFAULT_SEED = 20261001
CANDIDATE_ORDER = ("空仓", "四分之一凯利", "温度档")

NOTES = (
    "状态是严格早于收益日的温度仓位档。分数高不自动加重仓。",
    "五个信号组的权重按同一温度档里已经看到的后验、条件均值和协方差轮动。条件均值为负的组权重为 0，后验用来缩小仍为正的组。",
    "总仓位仍在空仓、轮动组合上的四分之一凯利、温度计仓位里选。温度档只缩放总敞口，不把权重改回等权。",
    "候选只有空仓、当时同档样本上的四分之一凯利、温度计自己的仓位。",
    "估计器给出同档后验、等权收益分布、五组相关，以及正态相关下的同亏。",
    "蒙特卡洛有两条路径：按历史同一天抽取，以及按正态相关重新绑定。候选效用取两条里更差的那条。",
    "效用等于持有 20 个交易日的终值收益均值，减去终值收益 95% CVaR 的亏损幅度。路径里不切换状态。",
    "收益日 t 的仓位只用 t 之前、同一温度档上的五组日收益。当日收益写回同档样本，供下一次后验使用。",
    "下一日状态直接读最新温度档，不做状态转移。",
    "同一温度档在 t 之前少于 30 天时，动作记为空仓。",
    "效用相同则取仓位更小的；仓位也相同则按空仓、四分之一凯利、温度档的顺序取更靠前的。",
    "这里用的后验来自等权日收益，不读 M+ 的 T+3 后验。不写实盘仓位，也不改观察池。",
)

TOP_LEVEL_KEYS = (
    "schema_version",
    "sleeves",
    "n_days",
    "sample_start",
    "sample_end",
    "lambda_tail",
    "horizon_days",
    "n_paths",
    "min_prior",
    "seed",
    "next_action",
    "states",
    "ledger",
    "terminal_wealth",
    "total_return",
    "max_drawdown",
    "boundary",
    "notes",
    "created_at",
)

NEXT_KEYS = (
    "as_of",
    "state",
    "score",
    "temperature_position",
    "action",
    "position",
    "n_prior",
    "estimate",
    "candidates",
    "feedback",
)

CANDIDATE_KEYS = (
    "name",
    "position",
    "expected_return",
    "cvar_95",
    "utility",
    "chosen",
)

STATE_KEYS = (
    "label",
    "n_days",
    "mean_position",
    "mean_realized",
    "last_action",
    "last_date",
)

LEDGER_KEYS = (
    "date",
    "state",
    "score",
    "action",
    "position",
    "realized",
    "n_prior",
)


def _finite_score(value: object) -> float | None:
    number = pd.to_numeric(value, errors="coerce")
    if number != number:
        return None
    return float(number)


def _candidate_row(
    name: str,
    position: float,
    terminal: np.ndarray | None,
    *,
    chosen: bool,
) -> dict:
    if terminal is None:
        expected, cvar, utility = 0.0, 0.0, 0.0
    else:
        expected = float(np.mean(terminal))
        _, cvar = var_cvar_95(terminal)
        utility = expected - LAMBDA_TAIL * max(0.0, -cvar)
    row = {
        "name": name,
        "position": float(position),
        "expected_return": expected,
        "cvar_95": cvar,
        "utility": float(utility),
        "chosen": bool(chosen),
    }
    missing = [key for key in CANDIDATE_KEYS if key not in row]
    if missing:
        raise RuntimeError(f"候选动作缺字段: {missing}")
    return row


def _empty_estimate() -> dict:
    return {
        "posterior_win_rate": None,
        "payoff_b": None,
        "kelly_raw": None,
        "pdf_mean": None,
        "pdf_var_95": None,
        "pdf_cvar_95": None,
        "max_correlation": None,
        "max_pair": None,
        "historical_all_negative": None,
        "independent_all_negative": None,
        "gaussian_all_negative": None,
        "sampler": "样本不足",
    }


def _estimate(
    history: np.ndarray,
    panel: np.ndarray | None,
    *,
    n_paths: int,
    seed: int,
    include_gaussian: bool,
) -> dict:
    estimate = _empty_estimate()
    estimate["sampler"] = "历史同日"
    var_95, cvar_95 = var_cvar_95(history)
    estimate["pdf_mean"] = float(np.mean(history))
    estimate["pdf_var_95"] = var_95
    estimate["pdf_cvar_95"] = cvar_95
    try:
        kelly = estimate_quarter_kelly(history)
    except ValueError:
        kelly = None
    if kelly is not None:
        estimate["posterior_win_rate"] = float(kelly["posterior_win_rate"])
        estimate["payoff_b"] = float(kelly["payoff_b"])
        estimate["kelly_raw"] = float(kelly["kelly_raw"])
    if panel is None or len(panel) < 2:
        return estimate
    if np.any(np.std(panel, axis=0) == 0):
        return estimate
    corr = np.corrcoef(panel, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    best_value = -1.0
    best_pair = ""
    for left in range(panel.shape[1]):
        for right in range(left + 1, panel.shape[1]):
            value = float(corr[left, right])
            if value > best_value:
                best_value = value
                best_pair = f"{SLEEVES[left]} 与 {SLEEVES[right]}"
    loss = np.mean(panel < 0, axis=0)
    estimate["max_correlation"] = None if best_value < 0 else best_value
    estimate["max_pair"] = best_pair or None
    estimate["historical_all_negative"] = float(np.mean(np.all(panel < 0, axis=1)))
    estimate["independent_all_negative"] = float(np.prod(loss))
    if not include_gaussian:
        return estimate
    try:
        simulated = simulate_gaussian(panel, max(200, min(int(n_paths), 2000)), int(seed) + 17)
        estimate["gaussian_all_negative"] = float(np.mean(np.all(simulated < 0, axis=1)))
        estimate["sampler"] = "历史同日与正态相关取更差"
    except (ValueError, np.linalg.LinAlgError):
        estimate["sampler"] = "历史同日"
    return estimate


def _terminal_returns(draws: np.ndarray, position: float) -> np.ndarray:
    if position == 0.0:
        return np.zeros(draws.shape[0], dtype=float)
    step = np.maximum(1.0 + float(position) * draws, 0.0)
    return np.prod(step, axis=1) - 1.0


def rotate_weights(panel: np.ndarray) -> np.ndarray:
    """同档样本上的多头权重。均值为负的组退出，后验缩小其余组，再按协方差分配。"""
    values = np.asarray(panel, dtype=float)
    n_sleeves = values.shape[1]
    scores = np.zeros(n_sleeves, dtype=float)
    for index in range(n_sleeves):
        column = values[:, index]
        posterior, _ = beta_binomial_posterior(int(np.sum(column > 0)), int(np.sum(column <= 0)))
        sigma = float(np.std(column, ddof=1)) if len(column) > 1 else 0.0
        mean = float(np.mean(column))
        if mean > 0.0 and sigma > 0.0:
            scores[index] = float(posterior) * mean / sigma
    if float(scores.sum()) <= 0.0:
        return np.zeros(n_sleeves, dtype=float)
    cov = np.cov(values, rowvar=False)
    if np.ndim(cov) == 0:
        cov = np.array([[float(cov)]], dtype=float)
    cov = np.atleast_2d(cov) + 1e-6 * np.eye(n_sleeves)
    try:
        raw = np.linalg.solve(cov, scores)
    except np.linalg.LinAlgError:
        raw = scores
    raw = np.where(scores > 0.0, np.maximum(np.asarray(raw, dtype=float), 0.0), 0.0)
    if float(raw.sum()) <= 0.0:
        raw = scores
    return raw / float(raw.sum())


def _weight_map(weights: np.ndarray) -> dict[str, float]:
    return {name: float(weights[index]) for index, name in enumerate(SLEEVES)}


def _gaussian_draws(
    panel: np.ndarray,
    weights: np.ndarray,
    n_paths: int,
    horizon: int,
    seed: int,
) -> np.ndarray | None:
    try:
        simulated = simulate_gaussian(panel, int(n_paths) * int(horizon), int(seed) + 91)
    except (ValueError, np.linalg.LinAlgError):
        return None
    return (simulated @ weights).reshape(int(n_paths), int(horizon))


def choose_action(
    prior: np.ndarray,
    temperature_position: float,
    *,
    sleeves: np.ndarray | None = None,
    use_gaussian: bool = False,
    n_paths: int = DEFAULT_PATHS,
    horizon: int = HORIZON_DAYS,
    seed: int = DEFAULT_SEED,
) -> dict:
    """估计器先看同档样本，决策器再在三个候选里取更差路径上效用更高的仓位。"""
    panel = None
    if sleeves is not None:
        panel = np.asarray(sleeves, dtype=float)
        if panel.ndim != 2 or panel.shape[1] != len(SLEEVES):
            raise ValueError("五组样本必须是五行一组")
        panel = panel[np.isfinite(panel).all(axis=1)]
        count = int(len(panel))
    else:
        history = np.asarray(prior, dtype=float)
        history = history[np.isfinite(history)]
        count = int(history.size)
    n_prior = count
    temperature_position = float(temperature_position)
    if not 0.0 <= temperature_position <= 1.0:
        raise ValueError("温度仓位必须在 0 和 1 之间")
    if n_prior < SMALL_N:
        only = _candidate_row("空仓", 0.0, None, chosen=True)
        return {
            "action": "空仓",
            "position": 0.0,
            "weights": _weight_map(np.zeros(len(SLEEVES))),
            "n_prior": n_prior,
            "estimate": _empty_estimate(),
            "candidates": [only],
        }
    if panel is None:
        weights = np.full(len(SLEEVES), 1.0 / len(SLEEVES))
        book = history
    else:
        weights = rotate_weights(panel)
        book = panel @ weights if float(weights.sum()) > 0.0 else np.zeros(len(panel))
    estimate = _estimate(
        book if book.size else np.zeros(1),
        panel,
        n_paths=n_paths,
        seed=seed,
        include_gaussian=use_gaussian and panel is not None,
    )
    if book.size == 0 or float(np.std(book)) == 0.0 and float(np.mean(book)) == 0.0:
        estimate["kelly_raw"] = None
    names: list[tuple[str, float]] = [("空仓", 0.0)]
    if estimate["kelly_raw"] is not None:
        names.append(("四分之一凯利", 0.25 * max(0.0, float(estimate["kelly_raw"]))))
    names.append(("温度档", temperature_position))
    rng = np.random.default_rng(int(seed))
    if panel is None:
        historical = rng.choice(history, size=(int(n_paths), int(horizon)), replace=True)
    else:
        picked = rng.choice(len(panel), size=(int(n_paths), int(horizon)), replace=True)
        historical = panel[picked] @ weights
    gaussian = (
        _gaussian_draws(panel, weights, int(n_paths), int(horizon), int(seed))
        if use_gaussian and panel is not None
        else None
    )
    if use_gaussian and gaussian is None:
        estimate["sampler"] = "历史同日"
    scored: list[dict] = []
    for name, position in names:
        historical_terminal = _terminal_returns(historical, position)
        historical_row = _candidate_row(name, position, historical_terminal, chosen=False)
        utility = float(historical_row["utility"])
        expected = float(historical_row["expected_return"])
        cvar = float(historical_row["cvar_95"])
        if gaussian is not None and position != 0.0:
            gaussian_row = _candidate_row(name, position, _terminal_returns(gaussian, position), chosen=False)
            if float(gaussian_row["utility"]) < utility:
                utility = float(gaussian_row["utility"])
                expected = float(gaussian_row["expected_return"])
                cvar = float(gaussian_row["cvar_95"])
        row = _candidate_row(name, position, None, chosen=False)
        row["expected_return"] = expected
        row["cvar_95"] = cvar
        row["utility"] = utility
        scored.append(row)
    ranked = sorted(
        scored,
        key=lambda row: (
            -float(row["utility"]),
            float(row["position"]),
            CANDIDATE_ORDER.index(str(row["name"])),
        ),
    )
    winner = str(ranked[0]["name"])
    for row in scored:
        row["chosen"] = row["name"] == winner
    chosen = next(row for row in scored if row["chosen"])
    return {
        "action": winner,
        "position": float(chosen["position"]),
        "weights": _weight_map(weights),
        "n_prior": n_prior,
        "estimate": estimate,
        "candidates": scored,
    }


def _state_rows(ledger: list[dict]) -> list[dict]:
    order = {name: index for index, name in enumerate(STATE_ORDER)}
    labels = sorted({str(row["state"]) for row in ledger}, key=lambda name: (order.get(name, 99), name))
    rows: list[dict] = []
    for label in labels:
        block = [row for row in ledger if row["state"] == label]
        last = block[-1]
        realized = np.array([float(row["realized"]) for row in block], dtype=float)
        position = np.array([float(row["position"]) for row in block], dtype=float)
        item = {
            "label": label,
            "n_days": int(len(block)),
            "mean_position": float(position.mean()),
            "mean_realized": float(realized.mean()),
            "last_action": str(last["action"]),
            "last_date": str(last["date"]),
        }
        missing = [key for key in STATE_KEYS if key not in item]
        if missing:
            raise RuntimeError(f"状态摘要缺字段: {missing}")
        rows.append(item)
    return rows


def _boundary(next_action: dict, terminal_wealth: float) -> str:
    state = str(next_action["state"])
    score = next_action["score"]
    score_text = "缺少温度分" if score is None else f"温度分 {float(score):.0f}"
    wealth = f"{terminal_wealth:.3f}"
    if int(next_action["n_prior"]) < SMALL_N:
        return (
            f"下一日状态是{state}（{score_text}），同档已有样本 {int(next_action['n_prior'])} 天，"
            f"少于 {SMALL_N}，动作是空仓。账上期末资金 {wealth}。"
        )
    position = float(next_action["position"]) * 100.0
    return (
        f"下一日状态是{state}（{score_text}），效用最高的动作是{next_action['action']}，"
        f"仓位 {position:.1f}%。账上期末资金 {wealth}。"
    )


def build_decision_report(
    aligned: pd.DataFrame,
    temperature: pd.DataFrame,
    *,
    n_paths: int = DEFAULT_PATHS,
    horizon: int = HORIZON_DAYS,
    seed: int = DEFAULT_SEED,
) -> dict:
    joined = attach_prior_temperature(aligned, temperature)
    if joined.empty:
        raise ValueError("温度档没有覆盖这些收益日")
    joined = joined.sort_values("date").reset_index(drop=True)
    returns = equal_weight_return(joined).to_numpy(dtype=float)
    panel = joined[list(SLEEVES)].to_numpy(dtype=float)
    labels = joined["position_label"].astype(str).to_numpy()
    scores = pd.to_numeric(joined["total_score"], errors="coerce").to_numpy(dtype=float)
    temperature_position = pd.to_numeric(joined["position_pct"], errors="coerce").to_numpy(dtype=float) / 100.0
    if not np.isfinite(temperature_position).all():
        raise ValueError("温度仓位有缺失")
    ledger: list[dict] = []
    positions = np.zeros(len(joined), dtype=float)
    book_returns = np.zeros(len(joined), dtype=float)
    for index in range(len(joined)):
        mask = labels[:index] == labels[index]
        chosen = choose_action(
            returns[:index][mask],
            float(temperature_position[index]),
            sleeves=panel[:index][mask],
            n_paths=n_paths,
            horizon=horizon,
            seed=int(seed) + index,
        )
        position = float(chosen["position"])
        weight_vec = np.array([float(chosen["weights"][name]) for name in SLEEVES], dtype=float)
        book_today = float(weight_vec @ panel[index])
        positions[index] = position
        book_returns[index] = book_today
        score = None if scores[index] != scores[index] else float(scores[index])
        row = {
            "date": pd.Timestamp(joined.loc[index, "date"]).strftime("%Y-%m-%d"),
            "state": str(labels[index]),
            "score": score,
            "action": str(chosen["action"]),
            "position": position,
            "weights": dict(chosen["weights"]),
            "realized": float(position * book_today),
            "n_prior": int(chosen["n_prior"]),
        }
        missing = [key for key in LEDGER_KEYS if key not in row]
        if missing:
            raise RuntimeError(f"决策账缺字段: {missing}")
        ledger.append(row)
    stats = path_stats("决策", positions, book_returns)
    last_return = pd.Timestamp(joined["date"].max())
    known = temperature.sort_values("temp_date")
    known = known[known["temp_date"] <= last_return]
    if known.empty:
        raise ValueError("没有早于或等于最后收益日的温度档")
    latest = known.iloc[-1]
    next_label = str(latest["position_label"])
    next_position = float(pd.to_numeric(latest["position_pct"], errors="coerce")) / 100.0
    if next_position != next_position or not 0.0 <= next_position <= 1.0:
        raise ValueError("下一日温度仓位无效")
    next_mask = labels == next_label
    next_choice = choose_action(
        returns[next_mask],
        next_position,
        sleeves=panel[next_mask],
        use_gaussian=True,
        n_paths=n_paths,
        horizon=horizon,
        seed=int(seed) + 10_000_003,
    )
    last = ledger[-1]
    next_action = {
        "as_of": pd.Timestamp(latest["temp_date"]).strftime("%Y-%m-%d"),
        "state": next_label,
        "score": _finite_score(latest["total_score"]),
        "temperature_position": next_position,
        "action": str(next_choice["action"]),
        "position": float(next_choice["position"]),
        "weights": dict(next_choice["weights"]),
        "n_prior": int(next_choice["n_prior"]),
        "estimate": dict(next_choice["estimate"]),
        "candidates": list(next_choice["candidates"]),
        "feedback": {
            "date": last["date"],
            "state": last["state"],
            "action": last["action"],
            "realized": last["realized"],
            "next_state": next_label,
        },
    }
    missing = [key for key in NEXT_KEYS if key not in next_action]
    if missing:
        raise RuntimeError(f"下一日动作缺字段: {missing}")
    report = {
        "schema_version": SCHEMA_VERSION,
        "sleeves": list(SLEEVES),
        "n_days": int(len(ledger)),
        "sample_start": ledger[0]["date"],
        "sample_end": ledger[-1]["date"],
        "lambda_tail": LAMBDA_TAIL,
        "horizon_days": int(horizon),
        "n_paths": int(n_paths),
        "min_prior": SMALL_N,
        "seed": int(seed),
        "next_action": next_action,
        "states": _state_rows(ledger),
        "ledger": ledger,
        "terminal_wealth": float(stats["terminal_wealth"]),
        "total_return": float(stats["total_return"]),
        "max_drawdown": float(stats["max_drawdown"]),
        "boundary": _boundary(next_action, float(stats["terminal_wealth"])),
        "notes": list(NOTES),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    missing = [key for key in TOP_LEVEL_KEYS if key not in report]
    if missing:
        raise RuntimeError(f"决策结果缺字段: {missing}")
    return report


def load_decision_inputs(
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    return load_aligned(group_path, sleeve_path), load_temperature(temperature_path or TEMPERATURE_CSV)
