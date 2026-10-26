# -*- coding: utf-8 -*-
"""低 β / α / 超额筛选能否提高未来持有期的成本后超额。

离线对照，不改观察池，不改动量入池规则。
回归口径与 capm.model 相同：无风险利率按 0，日收益对沪深300，年化 α = 日截距 × 252。
信号只用决策日及之前的重叠交易日；组合赚的是之后持有期的收益。
"""
from __future__ import annotations

import os
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from capm.model import ANN_FACTOR, PRIMARY_WINDOW, _fit
from capm.sources import BARS_CACHE, load_market

HOLD_DAYS = 20
ROBUST_HOLD_DAYS = 10
ALT_WINDOW = 120
STABILITY_BLOCK = 60
STABILITY_BLOCKS = 4
MIN_PERIODS = 8
MIN_HOLDOUT = 2
COMMISSION = 0.0003
STAMP = 0.0005
ROUND_TRIP = COMMISSION + COMMISSION + STAMP
# D 相对 A/B/C 的累计超额至少再盖过一轮完整买卖，才算「明显高于」。
MARGIN = ROUND_TRIP
ALPHA_LOW = -0.10
ALPHA_HIGH = 0.40
BETA_LOW = 0.0
BETA_HIGH = 0.5
T_MIN = 1.0
STABILITY_MIN = 0.5

GROUPS = ("A", "B", "C", "D", "E", "U", "R")
GROUP_TITLE = {
    "A": "A 基准组：有效回归，不筛 α/β",
    "B": "B 低 β：0≤β₂₅₀≤0.5",
    "C": "C 历史优势：B 且年化 α₂₅₀>0",
    "D": "D 近期优势：C 且 α₁₂₀>0",
    "E": "E 质量：D 且 t(α)≥1、IR>0、稳定比例≥0.5",
    "U": "U 原假设：低 β，-10%<年化 α₂₅₀<40%，α₁₂₀>0，120 日毛超额>0",
    "R": "R 文档初始规则：低 β，α₂₅₀>0，α₁₂₀>0，120 日成本后超额>0",
}


def _num(value: object) -> float | None:
    if isinstance(value, (bool, str)):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not np.isfinite(number):
        return None
    return number


def group_flags(row: Mapping) -> dict[str, bool]:
    """七组门闩。阈值在看结果之前写死，不在样本里搜索。"""
    beta = _num(row.get("beta_250"))
    alpha_250 = _num(row.get("alpha_250"))
    alpha_120 = _num(row.get("alpha_120"))
    excess_120 = _num(row.get("excess_120"))
    t_alpha = _num(row.get("t_alpha_250"))
    ir = _num(row.get("ir_250"))
    stability = _num(row.get("stability"))
    valid = None not in (beta, alpha_250, alpha_120, excess_120)
    low_beta = bool(valid and BETA_LOW <= beta <= BETA_HIGH)
    history = bool(low_beta and alpha_250 > 0.0)
    recent = bool(history and alpha_120 > 0.0)
    user = bool(
        low_beta
        and ALPHA_LOW < alpha_250 < ALPHA_HIGH
        and alpha_120 > 0.0
        and excess_120 > 0.0
    )
    recommended = bool(
        low_beta
        and alpha_250 > 0.0
        and alpha_120 > 0.0
        and excess_120 - ROUND_TRIP > 0.0
    )
    quality = bool(
        recent
        and t_alpha is not None
        and t_alpha >= T_MIN
        and ir is not None
        and ir > 0.0
        and stability is not None
        and stability >= STABILITY_MIN
    )
    return {
        "A": valid,
        "B": low_beta,
        "C": history,
        "D": recent,
        "E": quality,
        "U": user,
        "R": recommended,
    }


def trade_cost(prev: set[str], curr: set[str]) -> float:
    """等权换仓。买入只计佣金，卖出计佣金和印花税。"""
    if not prev and not curr:
        return 0.0
    names = prev | curr
    prev_w = 1.0 / len(prev) if prev else 0.0
    curr_w = 1.0 / len(curr) if curr else 0.0
    buy = 0.0
    sell = 0.0
    for name in names:
        delta = (curr_w if name in curr else 0.0) - (prev_w if name in prev else 0.0)
        if delta > 0.0:
            buy += delta
        elif delta < 0.0:
            sell += -delta
    return buy * COMMISSION + sell * (COMMISSION + STAMP)


def _apply_cost(ret: float, cost: float) -> float:
    if cost <= 0.0:
        return float(ret)
    return (1.0 + float(ret)) * (1.0 - cost) - 1.0


def select_excess_pair(rows: Sequence[Mapping]) -> dict | None:
    """低 β 池内，做空 120 日超额最高的一只，做多最低的一只。

    超额相同则按代码升序排。两端不是两只不同的股票时，这一段不持仓。
    """
    clean: list[tuple[float, str, Mapping]] = []
    for row in rows:
        excess = _num(row.get("excess_120"))
        symbol = str(row.get("symbol") or "")
        if excess is None or not symbol:
            continue
        clean.append((excess, symbol, row))
    if len(clean) < 2:
        return None
    clean.sort(key=lambda item: (item[0], item[1]))
    worst, best = clean[0], clean[-1]
    if worst[1] == best[1] or not best[0] > worst[0]:
        return None
    return {
        "long": worst[1],
        "short": best[1],
        "long_excess": worst[0],
        "short_excess": best[0],
        "long_col": int(worst[2]["col"]),
        "short_col": int(best[2]["col"]),
        "long_beta": _num(worst[2].get("beta_250")),
        "short_beta": _num(best[2].get("beta_250")),
    }


def _transition_cost(prev: str | None, curr: str | None, side: str) -> float:
    """换仓成本，按该边名义本金。多头卖出、空头卖出开仓计印花税。"""
    if prev == curr:
        return 0.0
    cost = 0.0
    if prev is not None:
        cost += (COMMISSION + STAMP) if side == "long" else COMMISSION
    if curr is not None:
        cost += COMMISSION if side == "long" else (COMMISSION + STAMP)
    return cost


def _exit_cost(curr: str | None, side: str) -> float:
    if curr is None:
        return 0.0
    return (COMMISSION + STAMP) if side == "long" else COMMISSION


def _sided_return(ret: float, costs: Sequence[float], side: str) -> float:
    level = (1.0 + ret) if side == "long" else (1.0 - ret)
    for cost in costs:
        if cost > 0.0:
            level *= 1.0 - cost
    return level - 1.0


def _pair_return(ret_long: float, ret_short: float, long_costs: Sequence[float], short_costs: Sequence[float]) -> float:
    """做多 1、做空 1 的盈亏，分母是单边名义本金。"""
    long_level = 1.0 + _sided_return(ret_long, long_costs, "long")
    short_level = 1.0 + _sided_return(ret_short, short_costs, "short")
    return long_level + short_level - 2.0


def _compound(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return 0.0
    return float(np.prod(1.0 + returns) - 1.0)


def _overlap(asset: np.ndarray, market: np.ndarray, end: int, window: int) -> tuple[np.ndarray, np.ndarray] | None:
    """决策日 end（含）之前，最近 window 个两边都有成交的交易日。最后一天必须是决策日。"""
    if end < 0 or end >= len(asset):
        return None
    if not np.isfinite(asset[end]) or not np.isfinite(market[end]):
        return None
    mask = np.isfinite(asset[: end + 1]) & np.isfinite(market[: end + 1])
    idx = np.flatnonzero(mask)
    if len(idx) < window or int(idx[-1]) != end:
        return None
    chosen = idx[-window:]
    return asset[chosen], market[chosen]


def snapshot(asset: np.ndarray, market: np.ndarray, end: int) -> dict | None:
    pair = _overlap(asset, market, end, PRIMARY_WINDOW)
    if pair is None:
        return None
    asset_250, market_250 = pair
    fit_250 = _fit(asset_250, market_250, pd.RangeIndex(PRIMARY_WINDOW))
    short = _overlap(asset, market, end, ALT_WINDOW)
    if fit_250 is None or short is None:
        return None
    asset_120, market_120 = short
    fit_120 = _fit(asset_120, market_120, pd.RangeIndex(ALT_WINDOW))
    if fit_120 is None or fit_250.get("excess") is None or fit_120.get("excess") is None:
        return None
    active = asset_250 - market_250
    std = float(np.std(active, ddof=1))
    ir = None if std < 1e-12 else float(np.mean(active) / std * np.sqrt(ANN_FACTOR))
    hits: list[float] = []
    usable = STABILITY_BLOCK * STABILITY_BLOCKS
    if len(asset_250) < usable:
        stability = None
    else:
        block = asset_250[-usable:]
        block_m = market_250[-usable:]
        for k in range(STABILITY_BLOCKS):
            sl = slice(k * STABILITY_BLOCK, (k + 1) * STABILITY_BLOCK)
            fitted = _fit(block[sl], block_m[sl], pd.RangeIndex(STABILITY_BLOCK))
            if fitted is None or fitted.get("alpha_ann") is None:
                hits = []
                break
            hits.append(1.0 if float(fitted["alpha_ann"]) > 0.0 else 0.0)
        stability = float(np.mean(hits)) if len(hits) == STABILITY_BLOCKS else None
    r2 = fit_250.get("r2")
    return {
        "beta_250": fit_250["beta"],
        "alpha_250": fit_250["alpha_ann"],
        "t_alpha_250": fit_250["t_alpha"],
        "r2_250": np.nan if r2 is None else float(r2),
        "alpha_120": fit_120["alpha_ann"],
        "excess_120": fit_120["excess"],
        "ir_250": np.nan if ir is None else ir,
        "stability": np.nan if stability is None else stability,
    }


def _median(rows: Sequence[Mapping], key: str) -> float:
    values = [_num(row.get(key)) for row in rows]
    clean = [item for item in values if item is not None]
    if not clean:
        return float("nan")
    return float(np.median(clean))


def _share_low_r2(rows: Sequence[Mapping], ceiling: float = 0.05) -> float:
    values = [_num(row.get("r2_250")) for row in rows]
    clean = [item for item in values if item is not None]
    if not clean:
        return float("nan")
    return float(np.mean([item < ceiling for item in clean]))


def run_from_returns(
    asset: pd.DataFrame,
    market: pd.Series,
    hold: int = HOLD_DAYS,
) -> dict:
    """asset 是成交日收益，停牌日记为 NaN。持有期内停牌按当日收益 0。"""
    if hold < 1:
        raise ValueError("持有期至少 1 个交易日")
    frame = asset.sort_index()
    market = market.reindex(frame.index).astype(float)
    values = frame.to_numpy(dtype=float)
    market_values = market.to_numpy(dtype=float)
    symbols = [str(col) for col in frame.columns]
    n = len(frame)
    starts = list(range(PRIMARY_WINDOW - 1, n - hold, hold))
    prev = {name: set() for name in GROUPS}
    period_rows: dict[str, list[dict]] = {name: [] for name in GROUPS}
    gross_parts: dict[str, list[np.ndarray]] = {name: [] for name in GROUPS}
    net_parts: dict[str, list[np.ndarray]] = {name: [] for name in GROUPS}
    bench_parts: list[np.ndarray] = []
    date_parts: list[pd.Index] = []
    pair_prev_long: str | None = None
    pair_prev_short: str | None = None
    pair_periods: list[dict] = []
    pair_gross_parts: list[np.ndarray] = []
    pair_net_parts: list[np.ndarray] = []
    pair_long_parts: list[np.ndarray] = []
    pair_short_parts: list[np.ndarray] = []

    for ordinal, end in enumerate(starts):
        feature_rows: dict[str, list[dict]] = {name: [] for name in GROUPS}
        members: dict[str, list[str]] = {name: [] for name in GROUPS}
        member_pos: dict[str, list[int]] = {name: [] for name in GROUPS}
        low_beta: list[dict] = []
        for col, symbol in enumerate(symbols):
            snap = snapshot(values[:, col], market_values, end)
            if snap is None:
                continue
            flags = group_flags(snap)
            if flags["B"]:
                low_beta.append({**snap, "symbol": symbol, "col": col})
            for name in GROUPS:
                if flags[name]:
                    members[name].append(symbol)
                    member_pos[name].append(col)
                    feature_rows[name].append(snap)
        fwd_idx = slice(end + 1, end + 1 + hold)
        future = values[fwd_idx]
        bench = market_values[fwd_idx]
        if not np.isfinite(bench).all():
            continue
        is_last = ordinal == len(starts) - 1
        hold_index = frame.index[fwd_idx]
        bench_parts.append(bench.copy())
        date_parts.append(hold_index)
        for name in GROUPS:
            cols = member_pos[name]
            if cols:
                picked = future[:, cols]
                picked = np.where(np.isfinite(picked), picked, 0.0)
                gross = picked.mean(axis=1)
            else:
                gross = np.zeros(hold, dtype=float)
            entry = trade_cost(prev[name], set(members[name]))
            net = gross.copy()
            net[0] = _apply_cost(float(net[0]), entry)
            if is_last:
                net[-1] = _apply_cost(float(net[-1]), trade_cost(set(members[name]), set()))
            prev[name] = set(members[name])
            gross_parts[name].append(gross)
            net_parts[name].append(net)
            period_rows[name].append(
                {
                    "signal": pd.Timestamp(frame.index[end]).date().isoformat(),
                    "start": pd.Timestamp(hold_index[0]).date().isoformat(),
                    "end": pd.Timestamp(hold_index[-1]).date().isoformat(),
                    "n": len(members[name]),
                    "ret_gross": _compound(gross),
                    "ret_net": _compound(net),
                    "ret_bench": _compound(bench),
                    "median_beta": _median(feature_rows[name], "beta_250"),
                    "median_alpha": _median(feature_rows[name], "alpha_250"),
                    "median_r2": _median(feature_rows[name], "r2_250"),
                    "share_r2_below_05": _share_low_r2(feature_rows[name]),
                    "members": list(members[name]),
                }
            )
        chosen = select_excess_pair(low_beta)
        long_name = chosen["long"] if chosen else None
        short_name = chosen["short"] if chosen else None
        if chosen:
            long_path = future[:, chosen["long_col"]]
            short_path = future[:, chosen["short_col"]]
            long_path = np.where(np.isfinite(long_path), long_path, 0.0)
            short_path = np.where(np.isfinite(short_path), short_path, 0.0)
        else:
            long_path = np.zeros(hold, dtype=float)
            short_path = np.zeros(hold, dtype=float)
        long_entry = _transition_cost(pair_prev_long, long_name, "long")
        short_entry = _transition_cost(pair_prev_short, short_name, "short")
        long_exit = _exit_cost(long_name, "long") if is_last else 0.0
        short_exit = _exit_cost(short_name, "short") if is_last else 0.0
        gross = np.empty(hold, dtype=float)
        net = np.empty(hold, dtype=float)
        long_net = np.empty(hold, dtype=float)
        short_net = np.empty(hold, dtype=float)
        for day in range(hold):
            long_costs: list[float] = []
            short_costs: list[float] = []
            if day == 0:
                long_costs.append(long_entry)
                short_costs.append(short_entry)
            if day == hold - 1:
                long_costs.append(long_exit)
                short_costs.append(short_exit)
            gross[day] = _pair_return(float(long_path[day]), float(short_path[day]), (), ())
            net[day] = _pair_return(float(long_path[day]), float(short_path[day]), long_costs, short_costs)
            long_net[day] = _sided_return(float(long_path[day]), long_costs, "long")
            short_net[day] = _sided_return(float(short_path[day]), short_costs, "short")
        pair_prev_long = long_name
        pair_prev_short = short_name
        pair_gross_parts.append(gross)
        pair_net_parts.append(net)
        pair_long_parts.append(long_net)
        pair_short_parts.append(short_net)
        pair_periods.append(
            {
                "signal": pd.Timestamp(frame.index[end]).date().isoformat(),
                "start": pd.Timestamp(hold_index[0]).date().isoformat(),
                "end": pd.Timestamp(hold_index[-1]).date().isoformat(),
                "long": long_name or "",
                "short": short_name or "",
                "long_excess": None if chosen is None else chosen["long_excess"],
                "short_excess": None if chosen is None else chosen["short_excess"],
                "long_beta": None if chosen is None else chosen["long_beta"],
                "short_beta": None if chosen is None else chosen["short_beta"],
                "n_pool": len(low_beta),
                "ret_long": _compound(long_net),
                "ret_short": _compound(short_net),
                "ret_gross": _compound(gross),
                "ret_net": _compound(net),
                "ret_bench": _compound(bench),
            }
        )

    dates = date_parts[0].append(date_parts[1:]) if date_parts else frame.index[:0]
    bench_daily = np.concatenate(bench_parts) if bench_parts else np.array([], dtype=float)
    groups = {}
    for name in GROUPS:
        gross_daily = np.concatenate(gross_parts[name]) if gross_parts[name] else np.array([], dtype=float)
        net_daily = np.concatenate(net_parts[name]) if net_parts[name] else np.array([], dtype=float)
        groups[name] = _summarize(name, period_rows[name], gross_daily, net_daily, bench_daily, dates)
    return {
        "hold": hold,
        "n_periods": len(bench_parts),
        "n_days": int(len(bench_daily)),
        "n_symbols": int(len(symbols)),
        "start": groups["A"]["periods"][0]["start"] if groups["A"]["periods"] else "",
        "end": groups["A"]["periods"][-1]["end"] if groups["A"]["periods"] else "",
        "groups": groups,
        "bench_daily": bench_daily,
        "dates": dates,
        "verdict": judge(groups, len(bench_parts)),
        "pair": _summarize_pair(
            pair_periods,
            np.concatenate(pair_gross_parts) if pair_gross_parts else np.array([], dtype=float),
            np.concatenate(pair_net_parts) if pair_net_parts else np.array([], dtype=float),
            np.concatenate(pair_long_parts) if pair_long_parts else np.array([], dtype=float),
            np.concatenate(pair_short_parts) if pair_short_parts else np.array([], dtype=float),
            bench_daily,
        ),
    }


def _ann(total: float, n_days: int) -> float:
    if n_days <= 0 or not np.isfinite(total) or total <= -1.0:
        return float("nan")
    return float((1.0 + total) ** (ANN_FACTOR / n_days) - 1.0)


def _max_dd(returns: np.ndarray) -> float:
    if len(returns) == 0:
        return float("nan")
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    return float((equity / peak - 1.0).min())


def _ir(active: np.ndarray) -> float:
    if len(active) < 2:
        return float("nan")
    std = float(np.std(active, ddof=1))
    if std < 1e-12:
        return float("nan")
    return float(np.mean(active) / std * np.sqrt(ANN_FACTOR))


def _holdout_count(n_periods: int) -> int:
    if n_periods <= 0:
        return 0
    return max(1, int(round(n_periods * 0.2)))


def _summarize(
    name: str,
    periods: list[dict],
    gross: np.ndarray,
    net: np.ndarray,
    bench: np.ndarray,
    dates: pd.Index,
) -> dict:
    total_gross = _compound(gross)
    total_net = _compound(net)
    total_bench = _compound(bench)
    n_days = int(len(net))
    n_periods = len(periods)
    n_holdout = _holdout_count(n_periods)
    if n_holdout and n_days:
        hold_len = n_holdout * (n_days // n_periods)
        holdout_excess = _compound(net[-hold_len:]) - _compound(bench[-hold_len:])
    else:
        holdout_excess = float("nan")
    up = [row["ret_net"] - row["ret_bench"] for row in periods if row["ret_bench"] > 0.0]
    down = [row["ret_net"] - row["ret_bench"] for row in periods if row["ret_bench"] <= 0.0]
    counts = [row["n"] for row in periods]
    return {
        "name": name,
        "title": GROUP_TITLE[name],
        "periods": periods,
        "dates": dates,
        "gross_daily": gross,
        "net_daily": net,
        "total_gross": total_gross,
        "total_net": total_net,
        "total_bench": total_bench,
        "excess_net": total_net - total_bench,
        "ann_excess_net": _ann(total_net, n_days) - _ann(total_bench, n_days),
        "ir_net": _ir(net - bench) if n_days else float("nan"),
        "max_dd_net": _max_dd(net),
        "avg_names": float(np.mean(counts)) if counts else 0.0,
        "holdout_excess_net": holdout_excess,
        "up_excess": float(np.mean(up)) if up else float("nan"),
        "down_excess": float(np.mean(down)) if down else float("nan"),
        "n_up": len(up),
        "n_down": len(down),
    }


def _summarize_pair(
    periods: list[dict],
    gross: np.ndarray,
    net: np.ndarray,
    long_net: np.ndarray,
    short_net: np.ndarray,
    bench: np.ndarray,
) -> dict:
    total_net = _compound(net)
    n_days = int(len(net))
    held = [row for row in periods if row.get("long")]
    spreads = [
        float(row["short_excess"]) - float(row["long_excess"])
        for row in held
        if _num(row.get("short_excess")) is not None and _num(row.get("long_excess")) is not None
    ]
    return {
        "periods": periods,
        "net_daily": net,
        "total_gross": _compound(gross),
        "total_net": total_net,
        "total_bench": _compound(bench),
        "excess_net": total_net - _compound(bench),
        "long_net": _compound(long_net),
        "short_net": _compound(short_net),
        "ann_net": _ann(total_net, n_days),
        "ir_net": _ir(net - bench) if n_days else float("nan"),
        "max_dd_net": _max_dd(net),
        "n_held": len(held),
        "avg_spread": float(np.mean(spreads)) if spreads else float("nan"),
    }


def judge(groups: Mapping[str, Mapping], n_periods: int) -> dict:
    """确认规则事先写死：D 要盖过 A/B/C 一轮成本，E 的最后一段为正，且持有期数量够。"""
    excess = {name: float(groups[name]["excess_net"]) for name in ("A", "B", "C", "D", "E", "U")}
    holdout = {name: float(groups[name]["holdout_excess_net"]) for name in ("E", "U")}
    n_holdout = _holdout_count(n_periods)
    d_beats = all(excess["D"] > excess[name] + MARGIN for name in ("A", "B", "C"))
    e_holdout = bool(np.isfinite(holdout["E"]) and holdout["E"] > 0.0)
    sample_enough = n_periods >= MIN_PERIODS and n_holdout >= MIN_HOLDOUT
    return {
        "confirmed": bool(d_beats and e_holdout and sample_enough),
        "d_beats_prior": d_beats,
        "e_holdout_positive": e_holdout,
        "sample_enough": sample_enough,
        "n_periods": n_periods,
        "n_holdout": n_holdout,
        "u_beats_market": bool(excess["U"] > 0.0),
        "u_beats_pool": bool(excess["U"] > excess["A"] + MARGIN),
        "excess_net": excess,
        "holdout": holdout,
    }


def load_panel() -> tuple[pd.DataFrame, pd.Series]:
    """本地收盘与沪深300对齐。停牌日收益为 NaN，复牌日收益相对最近成交价。

    沪深300用各文件自己的收益率再拼接。两份净值基数不同，不能先拼价格再算涨跌。
    """
    market = load_market().sort_index()
    market = market.replace([np.inf, -np.inf], np.nan).dropna()
    worst = float(market.abs().max()) if len(market) else 0.0
    if worst > 0.15:
        raise ValueError(f"沪深300单日收益 {worst:.2%}，基准净值可能接错了")

    bars = pd.read_csv(BARS_CACHE)
    bars["symbol"] = (
        bars["symbol"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    bars["date"] = pd.to_datetime(bars["date"], errors="coerce").dt.normalize()
    bars["close"] = pd.to_numeric(bars["close"], errors="coerce")
    bars = bars.dropna(subset=["date", "symbol", "close"])
    bars = bars.drop_duplicates(["date", "symbol"], keep="last")
    close = bars.pivot(index="date", columns="symbol", values="close").sort_index()
    close = close.reindex(close.index.union(market.index).sort_values())
    observed = close.notna().to_numpy()
    seen_from_start = np.maximum.accumulate(observed, axis=0)
    seen_from_end = np.maximum.accumulate(observed[::-1], axis=0)[::-1]
    alive = seen_from_start & seen_from_end
    prev = close.ffill().shift(1)
    tradable = close / prev - 1.0
    tradable = tradable.where(pd.DataFrame(alive, index=close.index, columns=close.columns))
    tradable = tradable.replace([np.inf, -np.inf], np.nan)
    tradable = tradable.loc[market.index]
    return tradable, market


def _pct(value: float) -> str:
    if not np.isfinite(value):
        return "—"
    return f"{value * 100:.2f}%"


def _num_text(value: float) -> str:
    if not np.isfinite(value):
        return "—"
    return f"{value:.2f}"


def _verdict_text(result: dict) -> str:
    verdict = result["verdict"]
    held = []
    missed = []
    if verdict["d_beats_prior"]:
        held.append("D 的成本后累计超额高于 A、B、C，且领先幅度超过一轮买卖成本")
    else:
        missed.append("D 没有同时以超过一轮买卖成本的幅度领先 A、B、C")
    if verdict["e_holdout_positive"]:
        held.append("E 在最后一段样本外的成本后超额为正")
    else:
        missed.append("E 在最后一段样本外的成本后超额不为正")
    if verdict["sample_enough"]:
        held.append(
            f"独立持有期 {verdict['n_periods']} 段、样本外 {verdict['n_holdout']} 段，达到事先要求的 {MIN_PERIODS} 段和 {MIN_HOLDOUT} 段"
        )
    else:
        missed.append(
            f"独立持有期只有 {verdict['n_periods']} 段，样本外一段只有 {verdict['n_holdout']} 段，少于事先要求的 {MIN_PERIODS} 段和 {MIN_HOLDOUT} 段"
        )
    u_excess = float(result["groups"]["U"]["excess_net"])
    a_excess = float(result["groups"]["A"]["excess_net"])
    if verdict["u_beats_market"] and verdict["u_beats_pool"]:
        user = "原假设 U 的成本后累计收益高于沪深300，也高于同一股票池的未筛选组合 A，领先 A 的幅度超过一轮买卖成本。"
    elif verdict["u_beats_market"] and u_excess > a_excess:
        user = "原假设 U 的成本后累计收益高于沪深300，也略高于未筛选组合 A，领先幅度不到一轮买卖成本。"
    elif verdict["u_beats_market"]:
        user = "原假设 U 的成本后累计收益高于沪深300。同一股票池里，不做 α/β 筛选的 A 组成本后超额更高。"
    elif verdict["u_beats_pool"]:
        user = "原假设 U 的成本后累计收益高于未筛选组合 A，同期低于沪深300。"
    else:
        user = "原假设 U 的成本后累计收益低于沪深300，也低于未筛选组合 A。"
    head = "这套分层筛选满足事先写好的确认条件。" if verdict["confirmed"] else "这套分层筛选还不满足事先写好的确认条件。"
    detail = "成立的有：" + ("；".join(held) if held else "无") + "。未成立的有：" + "；".join(missed) + "。"
    return head + detail + user


def _path_text(result: dict) -> str:
    groups = result["groups"]
    order = ("A", "B", "C", "D", "E", "U", "R")
    best = max(order, key=lambda name: groups[name]["total_net"])
    parts = "，".join(f"{name} {_pct(groups[name]['total_net'])}" for name in order)
    return (
        f"成本后收益：{parts}，沪深300 {_pct(groups['A']['total_bench'])}。"
        f"这段路径里最高的是 {best}。"
    )


def render_report(primary: dict, robust: dict) -> str:
    lines = [
        "# 低 β、α、超额筛选的持有期对照",
        "",
        "## 需求",
        "",
        "目标是超越沪深300的成本后超额，而不是描述已经涨过的股票。",
        "待检验的原假设是四条同时成立才入选：0≤β≤0.5；-10%<年化 α<40%；120 日 α>0；超额>0。",
        "验证方式跟文档一致：同一股票池、同一调仓日、同一持有期，比较 A 到 E，并单列原假设 U 和文档初始规则 R。",
        "β 用的是相对沪深300的 250 日敏感度。年化 α 是 250 日回归的日截距乘 252。120 日 α 是同一公式在最近 120 个重叠交易日上的结果，大于 0 只看截距方向。",
        "超额是最近 120 个重叠交易日的累计收益减去沪深300累计收益。R 在这条超额上扣除一轮买卖成本；U 按原假设使用毛超额。",
        "",
        "## 实验",
        "",
        f"- 股票池：本地已缓存日线，共 {primary['n_symbols']} 只。各组从这同一个池子里选，基准是沪深300。",
        f"- 主检验持有 {primary['hold']} 个交易日，互不重叠。稳健性持有 {robust['hold']} 个交易日，不参与确认。",
        f"- 主检验区间：{primary['start']} 至 {primary['end']}，共 {primary['n_periods']} 段、{primary['n_days']} 个交易日。",
        "- 信号日收盘才能算出 β 和 α。组合从下一交易日起持有。250 日窗口不满的股票当天不进任何组。",
        f"- 成本：买入佣金 {COMMISSION:.2%}，卖出佣金 {COMMISSION:.2%}，卖出印花税 {STAMP:.2%}。期末清仓。",
        "- E 的 t(α)≥1、IR>0、四个 60 日块里 α 为正的比例≥0.5，是事先写死的门闩。样本只有几段持有期，没有估计评分权重。",
        f"- 确认要三件事同时成立：D 的成本后累计超额比 A、B、C 各自至少高出 {MARGIN:.2%}；E 的最后约 20% 持有期成本后超额为正；持有期不少于 {MIN_PERIODS} 段且样本外不少于 {MIN_HOLDOUT} 段。",
        "",
        "## 主检验（20 个交易日）",
        "",
        "| 组别 | 平均只数 | 毛收益 | 成本后收益 | 沪深300 | 成本后超额 | 年化超额 | IR | 最大回撤 | 上涨段平均超额 | 下跌段平均超额 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name in GROUPS:
        item = primary["groups"][name]
        lines.append(
            "| {title} | {avg:.1f} | {gross} | {net} | {bench} | {excess} | {ann} | {ir} | {dd} | {up} | {down} |".format(
                title=item["title"],
                avg=item["avg_names"],
                gross=_pct(item["total_gross"]),
                net=_pct(item["total_net"]),
                bench=_pct(item["total_bench"]),
                excess=_pct(item["excess_net"]),
                ann=_pct(item["ann_excess_net"]),
                ir=_num_text(item["ir_net"]),
                dd=_pct(item["max_dd_net"]),
                up=_pct(item["up_excess"]) + f"（{item['n_up']}）",
                down=_pct(item["down_excess"]) + f"（{item['n_down']}）",
            )
        )
    lines.extend(
        [
            "",
            "上涨段、下跌段按该持有期沪深300收益是否大于 0 划分，括号内是段数。平均超额是各段成本后超额的算术平均。",
            "",
            "### 逐段",
            "",
            "| 组别 | 信号日 | 持有开始 | 持有结束 | 只数 | 成本后收益 | 沪深300 | 成本后超额 | β中位 | 年化α中位 | R²中位 |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name in GROUPS:
        for row in primary["groups"][name]["periods"]:
            lines.append(
                "| {group} | {signal} | {start} | {end} | {n} | {net} | {bench} | {excess} | {beta} | {alpha} | {r2} |".format(
                    group=name,
                    signal=row["signal"],
                    start=row["start"],
                    end=row["end"],
                    n=row["n"],
                    net=_pct(row["ret_net"]),
                    bench=_pct(row["ret_bench"]),
                    excess=_pct(row["ret_net"] - row["ret_bench"]),
                    beta=_num_text(row["median_beta"]),
                    alpha=_pct(row["median_alpha"]),
                    r2=_num_text(row["median_r2"]),
                )
            )
    u_rows = primary["groups"]["U"]["periods"]
    r2_values = [row["median_r2"] for row in u_rows if np.isfinite(row["median_r2"])]
    low_r2 = [row["share_r2_below_05"] for row in u_rows if np.isfinite(row["share_r2_below_05"])]
    r2_text = _num_text(float(np.mean(r2_values))) if r2_values else "—"
    low_text = _pct(float(np.mean(low_r2))) if low_r2 else "—"
    u_excess_20 = primary["groups"]["U"]["excess_net"]
    u_excess_10 = robust["groups"]["U"]["excess_net"]
    lines.extend(
        [
            "",
            f"U 入选股票的 R² 中位，各段再平均，是 {r2_text}。R² 低于 0.05 的占比，各段再平均，是 {low_text}。R² 低时，单因子 α 里混有行业、规模和个股残差。",
            "",
            "## 判定",
            "",
            _verdict_text(primary),
            _path_text(primary),
            "年化超额把这段持有期按 252 个交易日放大，只用于横向比较，不能当成下一年还会重复的收益率。",
            "",
            f"20 日持有下，U 的成本后累计超额是 {_pct(u_excess_20)}。10 日持有、同一规则、不参与确认，U 的成本后累计超额是 {_pct(u_excess_10)}。",
            (
                "两个持有期的 U 超额同号。"
                if np.isfinite(u_excess_20) and np.isfinite(u_excess_10) and ((u_excess_20 > 0) == (u_excess_10 > 0))
                else "两个持有期的 U 超额不同号，原假设对持有期长度敏感。"
            ),
            "",
            "确认条件未成立时，点估计只说明这段路径，不能外推成持续跑赢。文档里的评分权重也没有估计：持有期数量不够做样本外选权。",
            "",
            "## 10 日持有（稳健性）",
            "",
            f"区间 {robust['start']} 至 {robust['end']}，{robust['n_periods']} 段、{robust['n_days']} 个交易日。",
            "",
            "| 组别 | 平均只数 | 成本后收益 | 沪深300 | 成本后超额 | 年化超额 | IR | 最大回撤 |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for name in GROUPS:
        item = robust["groups"][name]
        lines.append(
            "| {title} | {avg:.1f} | {net} | {bench} | {excess} | {ann} | {ir} | {dd} |".format(
                title=item["title"],
                avg=item["avg_names"],
                net=_pct(item["total_net"]),
                bench=_pct(item["total_bench"]),
                excess=_pct(item["excess_net"]),
                ann=_pct(item["ann_excess_net"]),
                ir=_num_text(item["ir_net"]),
                dd=_pct(item["max_dd_net"]),
            )
        )
    lines.extend(
        [
            "",
            "各组持仓名单在 `periods.csv`。",
            "",
        ]
    )
    lines.extend(_pair_lines(primary, robust))
    return "\n".join(lines)


def _pair_lines(primary: dict, robust: dict) -> list[str]:
    pair = primary["pair"]
    robust_pair = robust["pair"]
    bench_b = primary["groups"]["B"]["total_net"]
    lines = [
        "## 低 β 之后做空超额第一、做多超额最后",
        "",
        "股票池仍是低 β 组：0≤β₂₅₀≤0.5，并且 250 日、120 日回归都有效。",
        "在这个池子里按最近 120 个重叠交易日的累计超额排序。做空超额最高的一只，做多超额最低的一只。",
        "超额相同则按代码升序。两端不是两只不同的股票时，这一段空仓。",
        "配对收益的分母是单边名义本金：做多 1 元、做空 1 元，收益等于两边盈亏相加。空头在标的下跌时赚钱。",
        "多头买入、空头买回只计佣金 0.03%。多头卖出、空头卖出开仓再加印花税 0.05%。期末两边都平仓。",
        "",
        (
            f"20 日持有：配对成本后 {_pct(pair['total_net'])}，毛收益 {_pct(pair['total_gross'])}，"
            f"多头 {_pct(pair['long_net'])}，空头 {_pct(pair['short_net'])}，"
            f"沪深300 {_pct(pair['total_bench'])}，相对沪深300 {_pct(pair['excess_net'])}，"
            f"同期低 β 等权 B 组 {_pct(bench_b)}。"
            f"有持仓 {pair['n_held']} 段，两端超额差平均 {_pct(pair['avg_spread'])}。"
            f"IR {_num_text(pair['ir_net'])}，最大回撤 {_pct(pair['max_dd_net'])}。"
        ),
        (
            f"10 日持有、同一规则：配对成本后 {_pct(robust_pair['total_net'])}，"
            f"多头 {_pct(robust_pair['long_net'])}，空头 {_pct(robust_pair['short_net'])}，"
            f"相对沪深300 {_pct(robust_pair['excess_net'])}，最大回撤 {_pct(robust_pair['max_dd_net'])}。"
        ),
        "",
        "| 信号日 | 持有开始 | 持有结束 | 低β只数 | 做多 | 做多时超额 | 做空 | 做空时超额 | 多头收益 | 空头收益 | 配对收益 | 沪深300 |",
        "| --- | --- | --- | ---: | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in pair["periods"]:
        lines.append(
            "| {signal} | {start} | {end} | {n} | {long} | {long_ex} | {short} | {short_ex} | {long_ret} | {short_ret} | {net} | {bench} |".format(
                signal=row["signal"],
                start=row["start"],
                end=row["end"],
                n=row["n_pool"],
                long=row["long"] or "—",
                long_ex=_pct(row["long_excess"] if row["long_excess"] is not None else float("nan")),
                short=row["short"] or "—",
                short_ex=_pct(row["short_excess"] if row["short_excess"] is not None else float("nan")),
                long_ret=_pct(row["ret_long"]),
                short_ret=_pct(row["ret_short"]),
                net=_pct(row["ret_net"]),
                bench=_pct(row["ret_bench"]),
            )
        )
    lines.append("")
    return lines


def _write_periods(path: str, results: Sequence[dict]) -> None:
    rows = []
    for result in results:
        for name in GROUPS:
            for row in result["groups"][name]["periods"]:
                rows.append(
                    {
                        "hold": result["hold"],
                        "group": name,
                        "signal": row["signal"],
                        "start": row["start"],
                        "end": row["end"],
                        "n": row["n"],
                        "ret_net": row["ret_net"],
                        "ret_gross": row["ret_gross"],
                        "ret_bench": row["ret_bench"],
                        "excess_net": row["ret_net"] - row["ret_bench"],
                        "median_beta": row["median_beta"],
                        "median_alpha": row["median_alpha"],
                        "median_r2": row["median_r2"],
                        "members": " ".join(row["members"]),
                    }
                )
        for row in result.get("pair", {}).get("periods", []):
            rows.append(
                {
                    "hold": result["hold"],
                    "group": "LS",
                    "signal": row["signal"],
                    "start": row["start"],
                    "end": row["end"],
                    "n": row["n_pool"],
                    "ret_net": row["ret_net"],
                    "ret_gross": row["ret_gross"],
                    "ret_bench": row["ret_bench"],
                    "excess_net": row["ret_net"] - row["ret_bench"],
                    "median_beta": row["long_beta"],
                    "median_alpha": "",
                    "median_r2": "",
                    "members": f"L {row['long']} S {row['short']}".strip(),
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def _write_equity(path: str, result: dict) -> None:
    frame: dict[str, object] = {"date": result["dates"]}
    bench = result["bench_daily"]
    if len(bench):
        frame["沪深300"] = np.cumprod(1.0 + bench)
    for name in GROUPS:
        net = result["groups"][name]["net_daily"]
        if len(net) == 0:
            continue
        frame[name] = np.cumprod(1.0 + net)
    pair = result.get("pair") or {}
    pair_net = pair.get("net_daily", np.array([], dtype=float))
    if len(pair_net):
        frame["LS"] = np.cumprod(1.0 + pair_net)
    pd.DataFrame(frame).to_csv(path, index=False, encoding="utf-8-sig")


def main() -> None:
    asset, market = load_panel()
    primary = run_from_returns(asset, market, HOLD_DAYS)
    robust = run_from_returns(asset, market, ROBUST_HOLD_DAYS)
    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output", "excess_screen")
    os.makedirs(out_dir, exist_ok=True)
    report = render_report(primary, robust)
    with open(os.path.join(out_dir, "report.md"), "w", encoding="utf-8") as handle:
        handle.write(report)
    _write_periods(os.path.join(out_dir, "periods.csv"), (primary, robust))
    _write_equity(os.path.join(out_dir, "equity.csv"), primary)
    safe = report.encode("gbk", errors="replace").decode("gbk")
    print(safe)
    print(f"确认: {primary['verdict']['confirmed']}")


if __name__ == "__main__":
    main()
