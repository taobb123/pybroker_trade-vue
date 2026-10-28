# -*- coding: utf-8 -*-
"""百亚股份启动段的四项形态距离。只读，不写观察池，不记买入。"""
from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

from capm.sources import (
    OHLC_CACHE,
    fetch_act_bars,
    load_ohlc,
    load_watch,
    parse_symbols,
    store_ohlc,
)

SCHEMA_VERSION = "baiya_launch_v1"
TEMPLATE_SYMBOL = "003006"
TEMPLATE_NAME = "百亚股份"
IGNITION_DAY = "2026-09-09"
THIRD_DAY = "2026-09-11"
YANG_TARGET = 3
VOLUME_TARGET = 3.75
RELATED_MIN = 0.52
VR_FLOOR = 2.0
PASTE_LIMIT = 80
FETCH_START = "2025-12-01"

# 9 月 9 日到 9 月 11 日实测。本地日线缺这两天时用这组。
FROZEN_BANDS = {
    "c_ma20": (1.16, 1.28),
    "c_ma60": (1.16, 1.32),
    "ma_flat": (0.0, 0.05),
    "off_low": (0.30, 0.50),
    "pos120": (0.58, 0.90),
}
SCALES = {
    "c_ma20": 0.12,
    "c_ma60": 0.12,
    "ma_flat": 0.06,
    "off_low": 0.18,
    "pos120": 0.22,
}
PRICE_KEYS = ("c_ma20", "c_ma60", "ma_flat", "off_low", "pos120")

NOTES = (
    "模板是百亚股份 2026-09-09 的放量阳线到 2026-09-11 的第三根阳线。",
    "四项是螺旋桨（低点逐级下移后再止住）、价格位置、放量倍数、从放量日数起的阳线根数。",
    "名单是组合 1、2、3、4、5 观察表，再加上粘贴代码。只在本页对照，不写观察池，不记买入。",
    "相似度是四项的几何平均。有一项差很多，就没有相关性，也不写理由。",
)


def launch_payload(
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
        if code == TEMPLATE_SYMBOL or code in seen:
            continue
        seen.add(code)
        order.append(code)
    pasted_set = set()
    for code in pasted:
        if code == TEMPLATE_SYMBOL or code in seen:
            if code != TEMPLATE_SYMBOL:
                pasted_set.add(code)
            continue
        seen.add(code)
        pasted_set.add(code)
        order.append(code)
        names.setdefault(code, "")
    notes = list(NOTES)
    if truncated:
        notes.append(f"粘贴超过 {PASTE_LIMIT} 只，只取前 {PASTE_LIMIT} 只。")
    if TEMPLATE_SYMBOL in set(pasted):
        notes.append("百亚股份是模板，不参与对照。")
    bars = load_ohlc(set(order) | {TEMPLATE_SYMBOL}, cache_path=cache)
    if fetch_missing and pasted_set:
        need = _short_codes(bars, pasted_set)
        if need:
            pull = fetcher or fetch_act_bars
            end = _cache_end(bars)
            fresh = pull(need, FETCH_START, end)
            if fresh is not None and not getattr(fresh, "empty", True):
                store_ohlc(fresh, cache)
                bars = load_ohlc(set(order) | {TEMPLATE_SYMBOL}, cache_path=cache)
                notes.append(f"粘贴代码补进日线 {len(need)} 只。")
            else:
                notes.append("有粘贴代码缺日线，这次没有补到。")
    template = measure_template(_symbol_frame(bars, TEMPLATE_SYMBOL))
    if template["source"] == "frozen":
        notes.insert(0, "百亚股份在缓存里缺 2026-09-09 到 2026-09-11，模板用已测定的数值。")
    rows = []
    missing = []
    for code in order:
        frame = _symbol_frame(bars, code)
        if frame is None or len(frame) < 80:
            missing.append(code)
            continue
        scored = score_frame(frame, template)
        scored["symbol"] = code
        scored["stock_name"] = names.get(code, "")
        scored["pasted"] = code in pasted_set
        rows.append(scored)
    rows.sort(key=lambda item: (-item["similarity"], item["symbol"]))
    related = [item for item in rows if item["related"]]
    unrelated = [item["symbol"] for item in rows if not item["related"]]
    if missing:
        notes.append(f"{len(missing)} 只日线不足 80 根，没有对照。")
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
        "template": template,
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
        "message": "没有可对照的股票。" if empty else None,
        "report": None if empty else report,
    }


def measure_template(frame: pd.DataFrame | None) -> dict:
    base = {
        "symbol": TEMPLATE_SYMBOL,
        "name": TEMPLATE_NAME,
        "ignition": IGNITION_DAY,
        "third": THIRD_DAY,
        "volume": VOLUME_TARGET,
        "yang": YANG_TARGET,
        "bands": {key: list(FROZEN_BANDS[key]) for key in PRICE_KEYS},
        "source": "frozen",
    }
    if frame is None or frame.empty:
        return base
    indexed = {pd.Timestamp(day).date().isoformat(): pos for pos, day in enumerate(frame["date"])}
    i0 = indexed.get(IGNITION_DAY)
    i1 = indexed.get(THIRD_DAY)
    if i0 is None or i1 is None:
        return base
    first = price_features(frame, i0)
    third = price_features(frame, i1)
    vr = volume_ratio(frame, i0)
    if first is None or third is None or vr is None:
        return base
    bands = {}
    for key in PRICE_KEYS:
        lo = min(first[key], third[key])
        hi = max(first[key], third[key])
        pad = 0.02 if key != "pos120" else 0.03
        if key == "ma_flat":
            bands[key] = [0.0, round(max(hi + pad, 0.04), 4)]
        else:
            bands[key] = [round(lo - pad, 4), round(hi + pad, 4)]
    base["volume"] = round(vr, 4)
    base["bands"] = bands
    base["source"] = "bars"
    return base


def score_frame(frame: pd.DataFrame, template: dict) -> dict:
    last = len(frame) - 1
    price = price_features(frame, last)
    spiral = spiral_score(frame)
    ignition = find_ignition(frame)
    if ignition is None:
        vr = None
        yang_n = 0
        volume = 0.0
        yang = 0.0
    else:
        vr = volume_ratio(frame, ignition)
        yang_n = yang_count(frame, ignition)
        volume = _volume_score(vr, float(template["volume"]))
        yang = _yang_score(yang_n, int(template["yang"]))
    price_score = 0.0 if price is None else _price_score(price, template["bands"])
    parts = (spiral, price_score, volume, yang)
    if min(parts) <= 0:
        similarity = 0.0
    else:
        similarity = (spiral * price_score * volume * yang) ** 0.25
    return {
        "similarity": round(similarity, 4),
        "spiral": round(spiral, 4),
        "price": round(price_score, 4),
        "volume": round(volume, 4),
        "yang": round(yang, 4),
        "yang_n": yang_n,
        "vr": None if vr is None else round(vr, 4),
        "related": similarity >= RELATED_MIN,
        "reason": "",
    }


def price_features(frame: pd.DataFrame, index: int) -> dict | None:
    if index < 60:
        return None
    closes = frame["close"].to_numpy(dtype=float)
    highs = frame["high"].to_numpy(dtype=float)
    lows = frame["low"].to_numpy(dtype=float)
    close = float(closes[index])
    if not math.isfinite(close) or close <= 0:
        return None
    ma20 = float(np.mean(closes[index - 19 : index + 1]))
    ma60 = float(np.mean(closes[index - 59 : index + 1]))
    if ma20 <= 0 or ma60 <= 0:
        return None
    start = max(0, index - 119)
    low120 = float(np.min(lows[start : index + 1]))
    high120 = float(np.max(highs[start : index + 1]))
    if low120 <= 0 or high120 <= low120:
        return None
    return {
        "c_ma20": close / ma20,
        "c_ma60": close / ma60,
        "ma_flat": abs(ma20 / ma60 - 1.0),
        "off_low": close / low120 - 1.0,
        "pos120": (close - low120) / (high120 - low120),
    }


def volume_ratio(frame: pd.DataFrame, index: int) -> float | None:
    if index < 20:
        return None
    vols = frame["volume"].to_numpy(dtype=float)
    base = float(np.mean(vols[index - 20 : index]))
    if not math.isfinite(base) or base <= 0:
        return None
    return float(vols[index]) / base


def find_ignition(frame: pd.DataFrame) -> int | None:
    """螺旋低点之后的第一根放量阳线。"""
    lows = frame["low"].to_numpy(dtype=float)
    swings = [i for i in swing_lows(lows, 5) if i <= len(frame) - 4]
    if len(swings) < 1:
        return None
    window = [i for i in swings if i >= len(frame) - 160]
    if len(window) < 1:
        window = swings
    trough = min(window, key=lambda i: lows[i])
    for index in range(trough + 1, len(frame)):
        if _is_yang(frame, index) and (volume_ratio(frame, index) or 0.0) >= VR_FLOOR:
            return index
    return None


def yang_count(frame: pd.DataFrame, start: int) -> int:
    return sum(1 for index in range(start, len(frame)) if _is_yang(frame, index))


def spiral_score(frame: pd.DataFrame) -> float:
    lows = frame["low"].to_numpy(dtype=float)
    swings = [i for i in swing_lows(lows, 5) if i <= len(frame) - 4]
    swings = [i for i in swings if i >= len(frame) - 160]
    if len(swings) < 3:
        return 0.0
    prices = [float(lows[i]) for i in swings]
    trough_at = min(range(len(prices)), key=lambda i: prices[i])
    peak_at = max(range(trough_at + 1), key=lambda i: prices[i])
    segment = prices[peak_at : trough_at + 1]
    if len(segment) < 2:
        descent = 0.0
    else:
        down = sum(1 for i in range(1, len(segment)) if segment[i] < segment[i - 1] * 0.995)
        descent = down / (len(segment) - 1)
    trough = prices[trough_at]
    later = prices[trough_at + 1 :]
    close = float(frame["close"].iloc[-1])
    if any(price > trough * 1.02 for price in later):
        base = 1.0
    elif close > trough * 1.08:
        base = 0.55
    elif close <= trough * 1.04:
        base = 0.1
    else:
        base = 0.35
    return 0.65 * descent + 0.35 * base


def swing_lows(lows: np.ndarray, win: int = 5) -> list[int]:
    found = []
    count = len(lows)
    for index in range(win, count - win):
        left = lows[index - win : index]
        right = lows[index + 1 : index + win + 1]
        price = lows[index]
        if price <= left.min() and price <= right.min() and (price < left.min() or price < right.min()):
            found.append(index)
    return found


def _is_yang(frame: pd.DataFrame, index: int) -> bool:
    close = float(frame["close"].iloc[index])
    opened = frame["open"].iloc[index]
    if pd.notna(opened):
        return close > float(opened)
    if index == 0:
        return False
    return close > float(frame["close"].iloc[index - 1])


def _price_score(features: dict, bands: dict) -> float:
    scores = []
    for key in PRICE_KEYS:
        lo, hi = bands[key]
        scores.append(_band_score(float(features[key]), float(lo), float(hi), SCALES[key]))
    return sum(scores) / len(scores)


def _band_score(value: float, lo: float, hi: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    if lo <= value <= hi:
        return 1.0
    gap = lo - value if value < lo else value - hi
    return math.exp(-gap / scale)


def _volume_score(vr: float | None, target: float) -> float:
    if vr is None or vr <= 0 or target <= 0:
        return 0.0
    return math.exp(-abs(math.log(vr / target)) / 0.85)


def _yang_score(count: int, target: int) -> float:
    if count <= 0:
        return 0.0
    return math.exp(-abs(count - target) / 2.0)


def _reason(row: dict) -> str:
    vr = row["vr"]
    volume_text = "没有放量" if vr is None else f"放量 {vr:.1f} 倍"
    text = (
        f"螺旋桨 {row['spiral']:.2f}，位置 {row['price']:.2f}，"
        f"{volume_text}，阳线 {row['yang_n']} 根"
    )
    weak = []
    if row["spiral"] < 0.5:
        weak.append("低点没有逐级下移")
    if row["price"] < 0.5:
        weak.append("价格位置偏离模板")
    if row["volume"] < 0.5:
        weak.append("放量倍数偏离 3.75 倍")
    if row["yang"] < 0.5:
        weak.append(f"阳线是 {row['yang_n']} 根，模板是 {YANG_TARGET} 根")
    if weak:
        text += "。" + "，".join(weak)
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
    return sorted(code for code in codes if int(counts.get(code, 0)) < 80)


def _cache_end(bars: pd.DataFrame) -> str:
    if bars is None or bars.empty:
        return datetime.now().date().isoformat()
    return pd.Timestamp(bars["date"].max()).date().isoformat()


def _empty(message: str) -> dict:
    return {"ok": False, "empty": True, "error": message, "message": message, "report": None}
