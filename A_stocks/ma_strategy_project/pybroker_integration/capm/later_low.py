# -*- coding: utf-8 -*-
"""稍后低点到最新收盘是否贴近 20%。只读，不写观察池，不并入百亚启动段。"""
from __future__ import annotations

import math
from datetime import datetime

import pandas as pd

from capm.launch_match import FETCH_START, PASTE_LIMIT, swing_lows
from capm.sources import (
    OHLC_CACHE,
    fetch_act_bars,
    load_ohlc,
    load_watch,
    parse_symbols,
    store_ohlc,
)

SCHEMA_VERSION = "later_low_v1"
NEAR_BAND = 0.05
LIFT_TARGET = 0.20
LIFT_SCALE = 0.08
RELATED_MIN = 0.50
MIN_BARS = 80

NOTES = (
    "螺旋最低点之后，取仍高出不超过 5% 的最后一根摆动低点。",
    "涨幅用这根最低价到最新收盘。贴近 20% 记 1，再低或再高都减分。",
    "相似度就是这一项。达到 0.50 才列出，大约对应 14% 到 26%。",
    "名单是组合 1、2、3、4、5 观察表，再加上粘贴代码。只在本页对照，不写观察池，不记买入。",
    "这一项不并入百亚启动段。",
)


def later_low_payload(
    *,
    symbols: str = "",
    ohlc_path=None,
    watch_paths=None,
    fetch_missing: bool = True,
    fetcher=None,
) -> dict:
    cache = OHLC_CACHE if ohlc_path is None else ohlc_path
    try:
        watch = load_watch(watch_paths)
    except FileNotFoundError as exc:
        return _empty(str(exc))
    pasted, truncated = parse_symbols(symbols or "", PASTE_LIMIT)
    names = {item["symbol"]: item["stock_name"] for item in watch}
    order: list[str] = []
    seen: set[str] = set()
    for item in watch:
        code = item["symbol"]
        if code in seen:
            continue
        seen.add(code)
        order.append(code)
    pasted_set = set()
    for code in pasted:
        if code in seen:
            pasted_set.add(code)
            continue
        seen.add(code)
        pasted_set.add(code)
        order.append(code)
        names.setdefault(code, "")
    notes = list(NOTES)
    if truncated:
        notes.append(f"粘贴超过 {PASTE_LIMIT} 只，只取前 {PASTE_LIMIT} 只。")
    bars = load_ohlc(set(order), cache_path=cache)
    if fetch_missing and pasted_set:
        need = _short_codes(bars, pasted_set)
        if need:
            pull = fetcher or fetch_act_bars
            end = _cache_end(bars)
            fresh = pull(need, FETCH_START, end)
            if fresh is not None and not getattr(fresh, "empty", True):
                store_ohlc(fresh, cache)
                bars = load_ohlc(set(order), cache_path=cache)
                notes.append(f"粘贴代码补进日线 {len(need)} 只。")
            else:
                notes.append("有粘贴代码缺日线，这次没有补到。")
    rows = []
    missing = []
    for code in order:
        frame = _symbol_frame(bars, code)
        if frame is None or len(frame) < MIN_BARS:
            missing.append(code)
            continue
        scored = score_later_low(frame)
        scored["symbol"] = code
        scored["stock_name"] = names.get(code, "")
        scored["pasted"] = code in pasted_set
        rows.append(scored)
    rows.sort(key=lambda item: (-item["similarity"], item["symbol"]))
    related = [item for item in rows if item["related"]]
    unrelated = [item["symbol"] for item in rows if not item["related"]]
    if missing:
        notes.append(f"{len(missing)} 只日线不足 {MIN_BARS} 根，没有计算。")
    for item in related:
        item["reason"] = _reason(item)
    for item in rows:
        if not item["related"]:
            item["reason"] = ""
    as_of = ""
    if bars is not None and not bars.empty:
        as_of = pd.Timestamp(bars["date"].max()).date().isoformat()
    report = {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "watched": len(watch),
        "pasted": len(pasted_set),
        "related_count": len(related),
        "unrelated_count": len(unrelated),
        "missing_count": len(missing),
        "rows": related,
        "unrelated_pasted": [code for code in unrelated if code in pasted_set],
        "missing_pasted": [code for code in missing if code in pasted_set],
        "notes": notes,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    empty = not related and not unrelated and not missing
    return {
        "ok": True,
        "empty": empty,
        "error": None,
        "message": "没有可计算的股票。" if empty else None,
        "report": None if empty else report,
    }


def score_later_low(frame: pd.DataFrame) -> dict:
    index = later_low_index(frame)
    gain = None
    low_date = ""
    low_price = None
    if index is not None:
        low_price = float(frame["low"].iloc[index])
        close = float(frame["close"].iloc[-1])
        low_date = pd.Timestamp(frame["date"].iloc[index]).date().isoformat()
        if low_price > 0 and math.isfinite(low_price) and math.isfinite(close):
            gain = close / low_price - 1.0
    similarity = lift_score(gain)
    return {
        "similarity": round(similarity, 4),
        "gain": None if gain is None else round(gain, 4),
        "low_date": low_date,
        "low_price": None if low_price is None else round(low_price, 4),
        "related": similarity >= RELATED_MIN,
        "reason": "",
    }


def later_low_index(frame: pd.DataFrame) -> int | None:
    """螺旋最低点之后，仍在其 5% 以内的最后一根摆动低点。"""
    lows = frame["low"].to_numpy(dtype=float)
    swings = [i for i in swing_lows(lows, 5) if i <= len(frame) - 4]
    if not swings:
        return None
    window = [i for i in swings if i >= len(frame) - 160]
    if not window:
        window = swings
    trough = min(window, key=lambda i: lows[i])
    ceiling = float(lows[trough]) * (1.0 + NEAR_BAND)
    later = [i for i in window if i > trough and float(lows[i]) <= ceiling]
    if not later:
        return None
    return later[-1]


def lift_score(gain: float | None) -> float:
    if gain is None or not math.isfinite(gain):
        return 0.0
    if LIFT_SCALE <= 0:
        return 0.0
    return math.exp(-abs(gain - LIFT_TARGET) / LIFT_SCALE)


def _reason(row: dict) -> str:
    gain = row["gain"]
    price = row["low_price"]
    if gain is None or price is None:
        return ""
    text = f"稍后低点 {row['low_date']}，最低价 {price:.2f}，至今涨了 {gain * 100:.1f}%"
    if abs(gain - LIFT_TARGET) > 0.02:
        text += "。偏离 20%"
    else:
        text += "。贴近 20%"
    return text


def _symbol_frame(bars: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    if bars is None or bars.empty:
        return None
    part = bars[bars["symbol"] == symbol]
    if part.empty:
        return None
    return part.sort_values("date").reset_index(drop=True)


def _short_codes(bars: pd.DataFrame, codes: set[str]) -> list[str]:
    if bars is None or bars.empty:
        return sorted(codes)
    counts = bars.groupby("symbol").size()
    return sorted(code for code in codes if int(counts.get(code, 0)) < MIN_BARS)


def _cache_end(bars: pd.DataFrame) -> str:
    if bars is None or bars.empty:
        return datetime.now().date().isoformat()
    return pd.Timestamp(bars["date"].max()).date().isoformat()


def _empty(message: str) -> dict:
    return {"ok": False, "empty": True, "error": message, "message": message, "report": None}
