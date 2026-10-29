# -*- coding: utf-8 -*-
"""启动前的左降与山尖。只读，不写观察池，不记买入。"""
from __future__ import annotations

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

SCHEMA_VERSION = "wing_tip_v7"
LOOKBACK = 80
WING_BARS = 60
MIN_BASE = 10
BASE_LONG = 40
MIN_BARS = 30
TIP_PAD = 5
TROUGH_BARS = 18
RADIUS = 3
DROP_MIN = 0.05
RISE_MAX = 0.12
BOUNCE_MAX = 0.10
BOWL_BAND = 0.03
BOWL_BARS = 5
HALF_RATIO = 1.5
QUIET_BARS = 20
TIP_FLOOR = 2.0
PASTE_LIMIT = 80
FETCH_START = "2025-12-01"

NOTES = (
    "锚在最新一根 K。左边画面要看得见圆弧底：碗底贴着走，进碗时跌势变缓。右翼不画进规则。",
    "左翼看同一段整理，高点可以落在大约 40 到 60 个交易日前。中间先反弹超过 10% 再跌回的，是上一只翅膀，不取。",
    "碗底至少连续 5 根收盘在低点上方 3% 以内。左翼前半段跌幅至少是靠近低点那一段的 1.5 倍。",
    "山尖和圆弧底落在同一带即可，可以相差几天，不必同一天。",
    "山尖按百亚启动段的放量来认：这根 K 的量除以前面 20 日均量，达到 2 倍才算一根。不按贴近 3.75 倍排队。",
    "冒出来的量柱越少价值越高：1 根最高，2 根次之，再多就明显靠后。堆得越宽，越接近上涨中途。",
    "整理满大约 40 根（两个月）的排在前面。只有两三周的急跌不是这幅图，排在后面。同一档里仍按山尖根数，少的在前。",
    "低点之后任一收盘抬升超过 12%，右边已经走出来，不算这幅左边。",
    "相似度只用来排序。名单只在本页对照，不写观察池，不记买入。",
)


def tip_payload(
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
    pasted_set: set[str] = set()
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
        if frame is None or len(frame) < LOOKBACK:
            missing.append(code)
            continue
        scored = score_tip(frame)
        scored["symbol"] = code
        scored["stock_name"] = names.get(code, "")
        scored["pasted"] = code in pasted_set
        rows.append(scored)
    rows.sort(key=_row_key)
    matched = [item for item in rows if item["matched"]]
    unrelated = [item["symbol"] for item in rows if not item["matched"]]
    if missing:
        notes.append(f"{len(missing)} 只日线不足 {LOOKBACK} 根，没有对照。")
    as_of = ""
    if bars is not None and not bars.empty:
        as_of = pd.Timestamp(bars["date"].max()).date().isoformat()
    report = {
        "schema_version": SCHEMA_VERSION,
        "as_of": as_of,
        "watched": len(watch),
        "pasted": len(pasted_set),
        "matched_count": len(matched),
        "unrelated_count": len(unrelated),
        "missing_count": len(missing),
        "rows": matched,
        "unrelated_pasted": [code for code in unrelated if code in pasted_set],
        "missing_pasted": [code for code in missing if code in pasted_set],
        "notes": notes,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    empty = not matched and not unrelated and not missing
    return {
        "ok": True,
        "empty": empty,
        "error": None,
        "message": "没有可对照的股票。" if empty else None,
        "report": None if empty else report,
    }


def score_tip(frame: pd.DataFrame) -> dict:
    """最新一根为锚。看得见的圆弧底，加上这一带里达到 2 倍的放量。"""
    base = {
        "matched": False,
        "drop": None,
        "tip": None,
        "tip_n": None,
        "similarity": None,
        "base_n": None,
        "peak": "",
        "anchor": "",
        "reason": "",
    }
    if frame is None or len(frame) < MIN_BARS:
        return base
    closes = frame["close"].to_numpy(dtype=float)
    volumes = frame["volume"].to_numpy(dtype=float)
    end = len(frame) - 1
    last = float(closes[end])
    if not np.isfinite(last) or last <= 0:
        return base
    for peak_i in _peak_candidates(closes, end):
        scored = _score_from_peak(frame, closes, volumes, end, peak_i, base)
        if scored is not None:
            return scored
    return base


def _row_key(item: dict) -> tuple:
    base_n = item.get("base_n") or 0
    tier = 0 if base_n >= BASE_LONG else 1
    return (tier, item.get("tip_n") or 99, -(item.get("similarity") or 0.0), -base_n, item["symbol"])


def _score_from_peak(frame, closes, volumes, end: int, peak_i: int, base: dict) -> dict | None:
    peak_close = float(closes[peak_i])
    if peak_close <= 0:
        return None
    span = closes[peak_i : end + 1]
    if span.size < MIN_BASE or not np.isfinite(span).all() or np.any(span <= 0):
        return None
    trough_at = span.size - 1 - int(np.argmin(span[::-1]))
    trough = float(span[trough_at])
    trough_i = peak_i + trough_at
    if end - trough_i > TROUGH_BARS or trough <= 0:
        return None
    drop = (peak_close - trough) / peak_close
    risen = (float(np.max(span[trough_at:])) - trough) / trough
    if drop < DROP_MIN or risen > RISE_MAX:
        return None
    descent = span[: trough_at + 1]
    if _broke_wing(descent):
        return None
    bowl_n = _bowl_run(span, trough_at, trough)
    if bowl_n < BOWL_BARS:
        return None
    strength = _descent_strength(descent)
    if strength < HALF_RATIO:
        return None
    zone_start = max(peak_i + 1, trough_i - TIP_PAD)
    raised = _raised_bars(volumes, zone_start, end)
    if not raised:
        return None
    tip_i, ratio = raised[0]
    tip_n = len(raised)
    base_n = end - peak_i + 1
    arc_score = min(1.0, max(0.0, (strength - 1.0) / 1.0))
    tip_score = _tip_bar_score(tip_n)
    similarity = tip_score * (0.7 + 0.3 * arc_score) if tip_score > 0 else 0.0
    peak_day = _day(frame, peak_i)
    anchor_day = _day(frame, end)
    tip_day = _day(frame, tip_i)
    scored = dict(base)
    scored.update(
        {
            "matched": True,
            "drop": round(drop, 4),
            "tip": round(ratio, 4),
            "tip_n": tip_n,
            "similarity": round(similarity, 4),
            "base_n": base_n,
            "peak": peak_day,
            "anchor": anchor_day,
            "reason": (
                f"左翼 {peak_day} 起 {base_n} 个交易日整理，收盘 {peak_close:.2f} 降到 {trough:.2f}，"
                f"碗底有 {bowl_n} 根贴着走。"
                f"山尖从 {tip_day} 起 {tip_n} 根，第一根是前 20 日均量的 {ratio:.2f} 倍。"
            ),
        }
    )
    return scored


def _tip_bar_score(count: int) -> float:
    """冒出来的量柱越少越值钱。1 根最高，2 根次之，再多迅速掉分。"""
    if count <= 1:
        return 1.0
    if count == 2:
        return 0.65
    if count == 3:
        return 0.30
    return 0.12


def _peak_candidates(closes: np.ndarray, end: int) -> list[int]:
    """同一段整理里的转折高点，从更早的开始，先看更长的整理。"""
    latest = end - (MIN_BASE - 1)
    earliest = end - (WING_BARS - 1)
    if earliest < RADIUS or latest < earliest:
        return []
    found = []
    for index in range(earliest, latest + 1):
        price = float(closes[index])
        if not np.isfinite(price) or price <= 0:
            continue
        left = closes[index - RADIUS : index]
        right = closes[index + 1 : index + RADIUS + 1]
        if left.size < RADIUS or right.size < RADIUS:
            continue
        if not np.isfinite(left).all() or not np.isfinite(right).all():
            continue
        if price < float(np.max(left)) or price < float(np.max(right)):
            continue
        later = closes[index : end + 1]
        trough = float(np.min(later))
        if trough <= 0 or (price - trough) / price < DROP_MIN:
            continue
        found.append(index)
    return found


def _bowl_run(span: np.ndarray, trough_at: int, trough: float) -> int:
    """含低点的那一段里，收盘贴着低点连续走了几根。"""
    if trough <= 0 or trough_at < 0 or trough_at >= span.size:
        return 0
    limit = trough * (1.0 + BOWL_BAND)
    left = trough_at
    while left > 0 and float(span[left - 1]) <= limit:
        left -= 1
    right = trough_at
    while right + 1 < span.size and float(span[right + 1]) <= limit:
        right += 1
    return right - left + 1


def _descent_strength(descent: np.ndarray) -> float:
    """前半段跌幅除以靠近低点那一段的跌幅。直线下滑接近 1，进碗变缓会更大。"""
    if descent.size < 6 or np.any(descent <= 0):
        return 0.0
    mid = descent.size // 2
    peak = float(descent[0])
    middle = float(descent[mid])
    trough = float(descent[-1])
    drop_far = (peak - middle) / peak
    drop_near = (middle - trough) / middle
    if drop_far <= 0 or drop_near < 0:
        return 0.0
    if drop_near == 0:
        return HALF_RATIO + 1.0
    return drop_far / drop_near


def _raised_bars(volumes: np.ndarray, zone_start: int, end: int) -> list[tuple[int, float]]:
    """圆弧这一带里，达到前 20 日均量 2 倍的 K。"""
    found = []
    for index in range(zone_start, end + 1):
        if index < QUIET_BARS:
            continue
        prior = volumes[index - QUIET_BARS : index]
        if prior.size < QUIET_BARS or not np.isfinite(prior).all():
            continue
        base = float(np.mean(prior))
        volume = float(volumes[index])
        if base <= 0 or not np.isfinite(volume):
            continue
        ratio = volume / base
        if ratio >= TIP_FLOOR:
            found.append((index, ratio))
    return found


def _broke_wing(path: np.ndarray) -> bool:
    """下跌途中先抬起一截再跌回，左边就不是一只翅膀。"""
    low = float(path[0])
    for price in path[1:]:
        price = float(price)
        if price < low:
            low = price
            continue
        if low > 0 and price > low * (1.0 + BOUNCE_MAX):
            return True
    return False


def _day(frame: pd.DataFrame, index: int) -> str:
    return pd.Timestamp(frame["date"].iloc[index]).date().isoformat()


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
    return sorted(code for code in codes if int(counts.get(code, 0)) < LOOKBACK)


def _cache_end(bars: pd.DataFrame) -> str:
    if bars is None or bars.empty:
        return datetime.now().date().isoformat()
    return pd.Timestamp(bars["date"].max()).date().isoformat()


def _empty(message: str) -> dict:
    return {"ok": False, "empty": True, "error": message, "message": message, "report": None}
