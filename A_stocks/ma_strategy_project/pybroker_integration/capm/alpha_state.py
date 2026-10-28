# -*- coding: utf-8 -*-
"""Alpha 状态机，只做到买入的价格确认。不含止盈、止损和加仓。"""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd

from capm.model import ANN_FACTOR, align_returns

BETA_LO = 0.0
BETA_HI = 0.5
WINDOW_LONG = 250
WINDOW_SHORT = 120
ALPHA_GAP_HI = 0.40
LAG = 20
OBSERVE_STEP = 5
PERSIST_COUNT = 2
PRICE_WINDOW = 20
VOLUME_MULT = 1.3
FORWARD = 10
GROUPS = 5
MIN_NAMES = 5

STATE_LABEL = {
    "S0": "禁止买入",
    "S1": "观察",
    "S2": "买入",
    "excluded": "排除",
    "insufficient": "样本不足",
}


def rolling_ols(asset: np.ndarray, market: np.ndarray, window: int) -> tuple[np.ndarray, np.ndarray]:
    """滚动截距和斜率。窗口不足或市场没有波动时留空。"""
    y = np.asarray(asset, dtype=float)
    x = np.asarray(market, dtype=float)
    n = int(len(y))
    alpha = np.full(n, np.nan)
    beta = np.full(n, np.nan)
    if window < 3 or n < window or len(x) != n:
        return alpha, beta
    cs_y = np.cumsum(y)
    cs_x = np.cumsum(x)
    cs_xy = np.cumsum(x * y)
    cs_xx = np.cumsum(x * x)
    idx = np.arange(window - 1, n)
    prev = idx - window

    def _sum(cs: np.ndarray) -> np.ndarray:
        out = cs[idx].copy()
        mask = prev >= 0
        out[mask] -= cs[prev[mask]]
        return out

    sum_y = _sum(cs_y)
    sum_x = _sum(cs_x)
    sum_xy = _sum(cs_xy)
    sum_xx = _sum(cs_xx)
    det = window * sum_xx - sum_x * sum_x
    ok = np.isfinite(det) & (np.abs(det) > 1e-18)
    slope = np.full(len(idx), np.nan)
    intercept = np.full(len(idx), np.nan)
    slope[ok] = (window * sum_xy[ok] - sum_x[ok] * sum_y[ok]) / det[ok]
    intercept[ok] = (sum_y[ok] - slope[ok] * sum_x[ok]) / window
    alpha[idx] = intercept
    beta[idx] = slope
    return alpha, beta


def alpha_gap(alpha_120: float, alpha_250: float) -> float:
    """年化 120 日 α 减年化 250 日 α。"""
    return float(alpha_120) - float(alpha_250)


def gap_admits(alpha_120: float, alpha_250: float) -> bool:
    """差为负，或严格大于 40%。等于 0、等于 40%，以及两者之间，都不进候选。"""
    if not (np.isfinite(alpha_120) and np.isfinite(alpha_250)):
        return False
    gap = alpha_gap(alpha_120, alpha_250)
    return bool(gap < 0.0 or gap > ALPHA_GAP_HI)


def in_risk_pool(beta: float, alpha_120: float, alpha_250: float) -> bool:
    return bool(np.isfinite(beta) and BETA_LO <= float(beta) <= BETA_HI and gap_admits(alpha_120, alpha_250))


def consecutive_improvement(alpha: np.ndarray, pos: int) -> bool:
    """每 5 个交易日看一次，最近两次的 20 日变化都要为正。"""
    if pos < 0 or pos >= len(alpha):
        return False
    for step in range(PERSIST_COUNT):
        end = pos - step * OBSERVE_STEP
        prev = end - LAG
        if prev < 0 or end >= len(alpha):
            return False
        now = alpha[end]
        before = alpha[prev]
        if not np.isfinite(now) or not np.isfinite(before) or not (now > before):
            return False
    return True


def price_gates(bars: pd.DataFrame | None, signal_date: pd.Timestamp) -> dict[str, bool]:
    """正式买入的价格确认。20 日最高价、最低价和均量都不含当日。"""
    gates = {
        "same_day": False,
        "no_new_low": False,
        "breakout": False,
        "volume_ok": False,
        "close_above_open": False,
        "open_missing": True,
    }
    if bars is None or bars.empty or "date" not in bars.columns:
        return gates
    ordered = bars.sort_values("date")
    day = pd.Timestamp(signal_date).normalize()
    ordered = ordered[pd.to_datetime(ordered["date"]).dt.normalize() <= day]
    if ordered.empty:
        return gates
    last = pd.Timestamp(ordered.iloc[-1]["date"]).normalize()
    if last != day or len(ordered) < PRICE_WINDOW + 1:
        return gates
    gates["same_day"] = True
    today = ordered.iloc[-1]
    prior = ordered.iloc[-(PRICE_WINDOW + 1) : -1]
    low_today = float(today["low"])
    close_today = float(today["close"])
    prior_low = float(prior["low"].min())
    prior_high = float(prior["high"].max())
    avg_vol = float(prior["volume"].mean())
    vol_today = float(today["volume"])
    gates["no_new_low"] = np.isfinite(low_today) and np.isfinite(prior_low) and low_today > prior_low
    gates["breakout"] = np.isfinite(close_today) and np.isfinite(prior_high) and close_today > prior_high
    gates["volume_ok"] = np.isfinite(vol_today) and np.isfinite(avg_vol) and avg_vol > 0 and vol_today > VOLUME_MULT * avg_vol
    opened = today["open"] if "open" in ordered.columns else np.nan
    try:
        open_px = float(opened)
    except (TypeError, ValueError):
        open_px = float("nan")
    gates["open_missing"] = not np.isfinite(open_px)
    gates["close_above_open"] = (not gates["open_missing"]) and close_today > open_px
    return gates


def price_confirmed(gates: dict[str, bool]) -> bool:
    return bool(
        gates.get("same_day")
        and gates.get("no_new_low")
        and gates.get("breakout")
        and gates.get("volume_ok")
        and gates.get("close_above_open")
    )


def classify_state(
    beta: float,
    alpha_120: float,
    alpha_250: float,
    delta: float,
    persisted: bool,
    confirmed: bool,
) -> str:
    if not all(np.isfinite(value) for value in (beta, alpha_120, alpha_250, delta)):
        return "insufficient"
    if not in_risk_pool(beta, alpha_120, alpha_250):
        return "excluded"
    if not (float(delta) > 0):
        return "S0"
    if not (persisted and confirmed):
        return "S1"
    return "S2"


def explain_state(
    state: str,
    beta: float,
    alpha_120: float,
    alpha_250: float,
    delta: float,
    persisted: bool,
    gates: dict[str, bool],
    *,
    current: bool,
) -> str:
    if state == "insufficient":
        return "重叠不足 250 日，或还看不了 20 日前的 120 日 α。"
    if state == "excluded":
        if not (np.isfinite(beta) and BETA_LO <= float(beta) <= BETA_HI):
            return "250 日 β 不在 0 到 0.5。"
        if not gap_admits(alpha_120, alpha_250):
            return "120 日与 250 日年化 α 之差不是负数，也没有大于 40%。"
        return "不在低 β、120 日与 250 日 α 之差的筛选里。"
    if state == "S0":
        if np.isfinite(delta) and float(delta) < 0:
            return "120 日 α 仍在扩大，不买。"
        return "120 日 α 没有明显收敛，不买。"
    gaps: list[str] = []
    if not persisted:
        gaps.append("改善还没连续两次")
    if not gates.get("same_day"):
        gaps.append("价格和回归不是同一天")
    else:
        if not gates.get("no_new_low"):
            gaps.append("仍在创新低")
        if not gates.get("breakout"):
            gaps.append("收盘没突破前 20 日最高价")
        if not gates.get("volume_ok"):
            gaps.append("量能没到 1.3 倍")
        if gates.get("open_missing"):
            gaps.append("缓存没有开盘价")
        elif not gates.get("close_above_open"):
            gaps.append("收盘不高于开盘")
    if state == "S2":
        text = "价格已确认。买入记在下一交易日，这里不记下止盈止损。"
        if not current:
            text += " 行情没有补到最近交易日，不作为今天的买入。"
        return text
    if gaps:
        return "α 在收敛，还不能买：" + "、".join(gaps) + "。"
    return "α 在收敛，价格还没确认。"


def forward_excess(asset: np.ndarray, market: np.ndarray, pos: int, horizon: int = FORWARD) -> float | None:
    """从信号日的下一根收益起，取 horizon 个交易日。信号日本身不计入。"""
    start = pos + 1
    end = start + horizon
    if start < 0 or end > len(asset) or end > len(market):
        return None
    left = np.asarray(asset[start:end], dtype=float)
    right = np.asarray(market[start:end], dtype=float)
    if len(left) < horizon or not np.isfinite(left).all() or not np.isfinite(right).all():
        return None
    return float(np.prod(1.0 + left) - np.prod(1.0 + right))


def _finite(value: float) -> bool:
    return bool(np.isfinite(value))


def snapshot_factors(asset: pd.Series, market: pd.Series, bars: pd.DataFrame | None) -> dict | None:
    """用对齐到最后一根可计算收益的窗口，给出状态机需要的数字。"""
    both = align_returns(asset, market)
    if bars is not None and not bars.empty and "date" in bars.columns:
        last_bar = pd.Timestamp(bars["date"].max()).normalize()
        both = both.loc[both.index <= last_bar]
    if len(both) < WINDOW_LONG:
        return None
    asset_np = both["asset"].to_numpy(dtype=float)
    market_np = both["market"].to_numpy(dtype=float)
    alpha_120, _ = rolling_ols(asset_np, market_np, WINDOW_SHORT)
    alpha_250, beta_250 = rolling_ols(asset_np, market_np, WINDOW_LONG)
    pos = len(both) - 1
    if pos < LAG or not _finite(alpha_120[pos]) or not _finite(alpha_120[pos - LAG]):
        return None
    if not _finite(alpha_250[pos]) or not _finite(beta_250[pos]):
        return None
    signal = pd.Timestamp(both.index[pos]).normalize()
    gates = price_gates(bars, signal)
    delta_daily = float(alpha_120[pos] - alpha_120[pos - LAG])
    persisted = consecutive_improvement(alpha_120, pos)
    confirmed = price_confirmed(gates)
    alpha_250_ann = float(alpha_250[pos] * ANN_FACTOR)
    alpha_120_ann = float(alpha_120[pos] * ANN_FACTOR)
    delta_ann = delta_daily * ANN_FACTOR
    state = classify_state(
        float(beta_250[pos]),
        alpha_120_ann,
        alpha_250_ann,
        delta_ann,
        persisted,
        confirmed,
    )
    return {
        "signal_date": signal.date().isoformat(),
        "beta250": float(beta_250[pos]),
        "alpha250": alpha_250_ann,
        "alpha120": alpha_120_ann,
        "alphaGap": alpha_gap(alpha_120_ann, alpha_250_ann),
        "delta120": float(delta_ann),
        "speed": float(delta_ann / LAG),
        "persisted": persisted,
        "confirmed": confirmed,
        "state": state,
        "gates": gates,
    }


def clock_dates(market: pd.Series) -> list[pd.Timestamp]:
    """每隔一个持有期取一个信号日，并且后面还留着 10 个交易日。"""
    idx = pd.DatetimeIndex(pd.to_datetime(market.index)).normalize()
    dates: list[pd.Timestamp] = []
    last = len(idx) - FORWARD
    pos = WINDOW_LONG - 1
    while pos < last:
        dates.append(pd.Timestamp(idx[pos]).normalize())
        pos += FORWARD
    return dates


def _next_market_dates(market: pd.Series, signal: pd.Timestamp, horizon: int) -> pd.DatetimeIndex | None:
    idx = pd.DatetimeIndex(pd.to_datetime(market.index)).normalize()
    signal = pd.Timestamp(signal).normalize()
    pos = int(idx.searchsorted(signal))
    if pos >= len(idx) or pd.Timestamp(idx[pos]) != signal:
        return None
    future = idx[pos + 1 : pos + 1 + horizon]
    if len(future) < horizon:
        return None
    return future


def collect_speed_observations(
    returns: dict[str, pd.Series],
    market: pd.Series,
    symbols: set[str] | None = None,
) -> list[dict]:
    """观察池里的候选，在每个取样日记录收敛速度和其后 10 日超额。"""
    clocks = set(clock_dates(market))
    if not clocks:
        return []
    rows: list[dict] = []
    for symbol, series in returns.items():
        if symbols is not None and str(symbol) not in symbols:
            continue
        both = align_returns(series, market)
        if len(both) < WINDOW_LONG + FORWARD:
            continue
        asset_np = both["asset"].to_numpy(dtype=float)
        market_np = both["market"].to_numpy(dtype=float)
        alpha_120, _ = rolling_ols(asset_np, market_np, WINDOW_SHORT)
        alpha_250, beta_250 = rolling_ols(asset_np, market_np, WINDOW_LONG)
        positions = {pd.Timestamp(day).normalize(): i for i, day in enumerate(both.index)}
        for day, pos in positions.items():
            if day not in clocks or pos < WINDOW_LONG - 1:
                continue
            beta = float(beta_250[pos])
            alpha_long = float(alpha_250[pos] * ANN_FACTOR)
            alpha_short = float(alpha_120[pos] * ANN_FACTOR)
            prev = alpha_120[pos - LAG]
            if not _finite(beta) or not _finite(alpha_long) or not _finite(alpha_short) or not _finite(prev):
                continue
            if not in_risk_pool(beta, alpha_short, alpha_long):
                continue
            future = _next_market_dates(market, day, FORWARD)
            if future is None:
                continue
            try:
                asset_fwd = both["asset"].reindex(future)
                market_fwd = both["market"].reindex(future)
            except (KeyError, ValueError):
                continue
            if asset_fwd.isna().any() or market_fwd.isna().any():
                continue
            left = asset_fwd.to_numpy(dtype=float)
            right = market_fwd.to_numpy(dtype=float)
            if len(left) < FORWARD or not np.isfinite(left).all() or not np.isfinite(right).all():
                continue
            excess = float(np.prod(1.0 + left) - np.prod(1.0 + right))
            speed = float((alpha_short - float(prev) * ANN_FACTOR) / LAG)
            rows.append(
                {
                    "date": day.date().isoformat(),
                    "symbol": str(symbol),
                    "speed": speed,
                    "excess": excess,
                }
            )
    return rows


def split_quintiles(speeds: Sequence[float]) -> list[str]:
    """速度从慢到快分成五组。G1 最慢，G5 最快。"""
    values = np.asarray(list(speeds), dtype=float)
    n = int(len(values))
    labels = [""] * n
    if n < MIN_NAMES:
        return labels
    order = np.argsort(values, kind="mergesort")
    edges = np.linspace(0, n, GROUPS + 1, dtype=int)
    for group in range(GROUPS):
        for cursor in order[edges[group] : edges[group + 1]]:
            labels[int(cursor)] = f"G{group + 1}"
    return labels


def _rising(values: list[float | None]) -> bool:
    if any(item is None for item in values):
        return False
    numbers = [float(item) for item in values if item is not None]
    if len(numbers) < 2 or not (numbers[-1] > numbers[0]):
        return False
    return all(numbers[i + 1] + 1e-12 >= numbers[i] for i in range(len(numbers) - 1))


def summarize_speed_groups(observations: list[dict]) -> dict:
    """每个取样日内部按速度分五组，再把各日的未来超额合在一起。"""
    by_date: dict[str, list[dict]] = {}
    for item in observations:
        by_date.setdefault(str(item["date"]), []).append(item)
    buckets: dict[str, list[float]] = {f"G{i}": [] for i in range(1, GROUPS + 1)}
    used_dates = 0
    skipped_dates = 0
    names: set[str] = set()
    for day in sorted(by_date):
        items = by_date[day]
        if len(items) < MIN_NAMES:
            skipped_dates += 1
            continue
        labels = split_quintiles([float(item["speed"]) for item in items])
        used_dates += 1
        for item, label in zip(items, labels):
            if not label:
                continue
            buckets[label].append(float(item["excess"]))
            names.add(str(item["symbol"]))
    groups = []
    for index in range(1, GROUPS + 1):
        key = f"G{index}"
        values = buckets[key]
        hit = None if not values else float(np.mean(np.asarray(values) > 0))
        mean = None if not values else float(np.mean(values))
        label = "最慢" if index == 1 else "最快" if index == GROUPS else key
        groups.append({"id": key, "label": label, "n": len(values), "hit_rate": hit, "mean_excess": mean})
    hits = [group["hit_rate"] for group in groups]
    means = [group["mean_excess"] for group in groups]
    hit_mono = _rising(hits)
    mean_mono = _rising(means)
    supported = bool(hit_mono and mean_mono)
    if used_dates == 0:
        verdict = "能对齐的股票不够分成五组，假设还不能检验。"
    elif supported:
        verdict = "收敛更快的组，未来 10 日超额为正的比例和平均超额都从最慢到最快不下降。"
    elif not hit_mono and not mean_mono:
        verdict = "超额为正的比例和平均超额都没有从最慢到最快递增。"
    elif not hit_mono:
        verdict = "平均超额有递增，但超额为正的比例没有从最慢到最快递增。"
    else:
        verdict = "超额为正的比例有递增，但平均超额没有从最慢到最快递增。"
    used = [day for day, items in by_date.items() if len(items) >= MIN_NAMES]
    return {
        "supported": supported,
        "hit_monotone": hit_mono,
        "mean_monotone": mean_mono,
        "n_dates": used_dates,
        "n_skipped_dates": skipped_dates,
        "n_obs": int(sum(group["n"] for group in groups)),
        "n_names": len(names),
        "sample_start": min(used) if used else None,
        "sample_end": max(used) if used else None,
        "groups": groups,
        "verdict": verdict,
    }
