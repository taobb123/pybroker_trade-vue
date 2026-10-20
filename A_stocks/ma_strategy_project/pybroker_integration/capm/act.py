# -*- coding: utf-8 -*-
"""用最近 10 个交易日的量价组合序列标记主力表演。不改组合门槛，不写观察池。"""
from __future__ import annotations

from typing import Callable, Sequence

import pandas as pd

STATE_DAYS = 10
FORWARD_DAYS = 3
RISK = (5, 6)
WASH = "震仓洗盘"
RELEASE = "释放套牢盘"
BROKEN = "打断"
OPEN = "未走完"
NONE = "无"
NO_BARS = "无日线"


def assess_act(combo_ids: Sequence[int], closes: Sequence[float]) -> dict:
    """在已经对齐的组合序列上给出最后一次表演。

    序列按时间从早到晚，调用方只传入最近 10 个交易日。
    震仓洗盘：先有 2 或 4，之后第一次出现 3，结束日是这个 3。
    释放套牢盘：先有 2、4 或 3，随后只有 1 日 5 或 6，再回到 1 或 3。
    5 与 6 连续两个交易日（含交替）记为打断，并取消尚未被新路径盖过的结果。
    窗口结束时若只武装过、没有走完，记为未走完。
    收益是结束日收盘到其后第 3 个交易日收盘；不够 3 日则为空。
    """
    ids = [int(item) for item in combo_ids]
    prices = [float(item) for item in closes]
    if not ids or len(ids) != len(prices):
        return _result(NONE, None, None)
    if len(ids) > STATE_DAYS:
        ids = ids[-STATE_DAYS:]
        prices = prices[-STATE_DAYS:]

    completed: tuple[str, int | None] | None = None
    armed_wash = False
    armed_release = False
    pending_release = False

    for index, combo in enumerate(ids):
        previous = ids[index - 1] if index else None
        if combo in RISK and previous in RISK:
            completed = (BROKEN, None)
            armed_wash = False
            armed_release = False
            pending_release = False
            continue

        if pending_release:
            pending_release = False
            if combo in (1, 3):
                completed = (RELEASE, index)
                armed_wash = False
                armed_release = False
                continue

        if combo in RISK and armed_release:
            pending_release = True
            continue

        if combo in (2, 4):
            armed_wash = True
            armed_release = True
            continue

        if combo == 3 and armed_wash:
            completed = (WASH, index)
            armed_wash = False
            armed_release = True
            continue

        if combo == 3:
            armed_release = True

    if completed is not None:
        label, end = completed
    elif pending_release or armed_wash:
        label, end = OPEN, None
    else:
        label, end = NONE, None

    forward = None
    if label in (WASH, RELEASE) and end is not None:
        target = end + FORWARD_DAYS
        base = prices[end]
        if target < len(prices) and base > 0:
            forward = prices[target] / base - 1.0
    return _result(label, forward, end)


def sequence_from_frame(
    frame: pd.DataFrame,
    classify: Callable[[pd.DataFrame], int | None],
) -> tuple[list[str], list[int], list[float]]:
    """用分类函数给最近 10 个交易日打上组合编号。历史切片含当日之前的全部 K 线。"""
    if frame is None or frame.empty or "date" not in frame.columns or "close" not in frame.columns:
        return [], [], []
    ordered = frame.sort_values("date").reset_index(drop=True)
    tail_from = max(0, len(ordered) - STATE_DAYS)
    dates: list[str] = []
    ids: list[int] = []
    closes: list[float] = []
    for cursor in range(tail_from, len(ordered)):
        hist = ordered.iloc[: cursor + 1]
        try:
            combo = classify(hist)
        except Exception:
            combo = None
        if combo is None:
            continue
        close = float(hist.iloc[-1]["close"])
        if close != close:
            continue
        dates.append(pd.Timestamp(hist.iloc[-1]["date"]).date().isoformat())
        ids.append(int(combo))
        closes.append(close)
    return dates, ids, closes


def act_from_frame(
    frame: pd.DataFrame | None,
    classify: Callable[[pd.DataFrame], int | None],
) -> dict:
    if frame is None or frame.empty:
        return {"act_label": NO_BARS, "act_return": None, "act_end": None}
    dates, ids, closes = sequence_from_frame(frame, classify)
    if not ids:
        return {"act_label": NO_BARS, "act_return": None, "act_end": None}
    assessed = assess_act(ids, closes)
    end = assessed["end_index"]
    return {
        "act_label": assessed["label"],
        "act_return": assessed["ret"],
        "act_end": None if end is None else dates[end],
    }


def phase1_combo_id(frame: pd.DataFrame) -> int | None:
    """复用六组合第一次归类：位置、价格方向、量比。不跑筹码覆写。"""
    from fetch_vp_six_combo import VP_SIX_CONFIG, evaluate_vp_six

    cfg = VP_SIX_CONFIG
    snap = evaluate_vp_six(
        frame,
        symbol=str(frame.iloc[-1].get("symbol", "") if "symbol" in frame.columns else ""),
        stock_name="",
        ma5_score_total=None,
        chip=None,
        enable_phase2=False,
        range_lookback_bars=int(cfg["range_lookback_bars"]),
        vol_ma_bars=int(cfg["vol_ma_bars"]),
        breakout_lookback_bars=int(cfg["breakout_lookback_bars"]),
        vol_amplify_ratio=float(cfg["vol_amplify_ratio"]),
        vol_shrink_ratio=float(cfg["vol_shrink_ratio"]),
        stagnant_abs_pct=float(cfg["stagnant_abs_pct"]),
        bottom_range_pct=float(cfg["bottom_range_pct"]),
        high_range_pct=float(cfg["high_range_pct"]),
        downtrend_ma20_lookback=int(cfg["downtrend_ma20_lookback"]),
        min_bars=int(cfg["min_bars"]),
        turnover_ma_bars=int(cfg["turnover_ma_bars"]),
        turnover_high_pct=float(cfg["turnover_high_pct"]),
        turnover_low_pct=float(cfg["turnover_low_pct"]),
        turnover_amplify_ratio=float(cfg["turnover_amplify_ratio"]),
        turnover_shrink_ratio=float(cfg["turnover_shrink_ratio"]),
        resonance_pass_score=float(cfg["resonance_pass_score"]),
    )
    if snap is None:
        return None
    return int(snap.combo_id)


def _result(label: str, forward: float | None, end: int | None) -> dict:
    return {
        "label": label,
        "ret": None if forward is None else round(float(forward), 6),
        "end_index": end,
    }
