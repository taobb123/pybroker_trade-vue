# -*- coding: utf-8 -*-
"""盯盘：低点、回调、压力、突破。

只读日线，不写观察池，不改入池条件。
低点：最近 20 个交易日里成交量最大的两天，各自取当天最低价。同一只股票这段流通股本不变，成交量排序就是换手排序。
回调：上攻高点之后回撤过程的最高价到最低价。
压力：上攻当日的事件 VWAP、收盘价、最高价分开记录。三个价格各自保留，并计算最新收盘相对每个价格的偏离。
突破：收盘价高于事件最高价。突破之后看价格有没有回踩这个最高价。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

REVERSAL = 0.05
LOOKBACK = 160
RECENT_DAYS = 20


def analyze_frame(frame: pd.DataFrame) -> dict[str, Any]:
    """单只股票的日线。列：date、open、high、low、close。成交额和成交量用来算事件 VWAP。"""
    rows = _rows(frame)
    if len(rows) < 5:
        return _empty("日线不足")
    swings = _zigzag(rows, REVERSAL)
    structure = _structure(rows, swings)
    return _assemble(rows, structure)


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    if frame is None or frame.empty:
        return []
    needed = {"date", "high", "low", "close"}
    if not needed.issubset(frame.columns):
        return []
    work = frame.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce")
    for col in ("open", "high", "low", "close"):
        if col not in work.columns:
            work[col] = pd.NA
        work[col] = pd.to_numeric(work[col], errors="coerce")
    work = work.dropna(subset=["date", "high", "low", "close"]).sort_values("date")
    work = work.tail(LOOKBACK)
    rows: list[dict[str, Any]] = []
    for rec in work.itertuples(index=False):
        opened = getattr(rec, "open", None)
        volume = getattr(rec, "volume", None)
        amount = getattr(rec, "amount", None)
        rows.append(
            {
                "date": pd.Timestamp(rec.date).strftime("%Y-%m-%d"),
                "open": None if opened is None or pd.isna(opened) else float(opened),
                "high": float(rec.high),
                "low": float(rec.low),
                "close": float(rec.close),
                "volume": None if volume is None or pd.isna(volume) else float(volume),
                "amount": None if amount is None or pd.isna(amount) else float(amount),
            }
        )
    return rows


def _path(row: dict[str, Any], prev_close: float | None) -> list[tuple[str, float]]:
    opened = row["open"]
    if opened is None:
        yang = prev_close is None or row["close"] >= prev_close
    else:
        yang = row["close"] >= opened
    if yang:
        return [("low", row["low"]), ("high", row["high"])]
    return [("high", row["high"]), ("low", row["low"])]


def _zigzag(rows: list[dict[str, Any]], reversal: float) -> dict[str, Any]:
    confirmed: list[dict[str, Any]] = []
    trend: str | None = None
    extreme_i = 0
    extreme_price = rows[0]["low"]
    seen_low_i = 0
    seen_low = rows[0]["low"]
    seen_high_i = 0
    seen_high = rows[0]["high"]
    prev_close: float | None = None

    def confirm(kind: str, index: int, price: float) -> None:
        point = {"kind": kind, "index": index, "price": price, "date": rows[index]["date"]}
        if confirmed and confirmed[-1]["kind"] == kind:
            last = confirmed[-1]
            if kind == "high" and price >= last["price"]:
                confirmed[-1] = point
            elif kind == "low" and price <= last["price"]:
                confirmed[-1] = point
            return
        confirmed.append(point)

    for index, row in enumerate(rows):
        for kind, price in _path(row, prev_close):
            if trend is None:
                if kind == "low" and price <= seen_low:
                    seen_low_i, seen_low = index, price
                if kind == "high" and price >= seen_high:
                    seen_high_i, seen_high = index, price
                if seen_high >= seen_low * (1 + reversal) and seen_high_i >= seen_low_i:
                    confirm("low", seen_low_i, seen_low)
                    trend = "up"
                    extreme_i, extreme_price = seen_high_i, seen_high
                elif seen_low <= seen_high * (1 - reversal) and seen_low_i >= seen_high_i:
                    confirm("high", seen_high_i, seen_high)
                    trend = "down"
                    extreme_i, extreme_price = seen_low_i, seen_low
                continue
            if trend == "up":
                if kind == "high" and price >= extreme_price:
                    extreme_i, extreme_price = index, price
                elif kind == "low" and price <= extreme_price * (1 - reversal):
                    confirm("high", extreme_i, extreme_price)
                    trend = "down"
                    extreme_i, extreme_price = index, price
            else:
                if kind == "low" and price <= extreme_price:
                    extreme_i, extreme_price = index, price
                elif kind == "high" and price >= extreme_price * (1 + reversal):
                    confirm("low", extreme_i, extreme_price)
                    trend = "up"
                    extreme_i, extreme_price = index, price
        prev_close = row["close"]
    return {
        "confirmed": confirmed,
        "trend": trend,
        "extreme_index": extreme_i,
        "extreme_price": extreme_price,
    }


def _structure(rows: list[dict[str, Any]], swings: dict[str, Any]) -> dict[str, Any]:
    confirmed: list[dict[str, Any]] = swings["confirmed"]
    trend = swings["trend"]
    highs = [item for item in confirmed if item["kind"] == "high"]
    last_high = highs[-1] if highs else None
    running_extends = (
        trend == "up"
        and last_high is not None
        and swings["extreme_index"] > last_high["index"]
        and swings["extreme_price"] > last_high["price"]
    )
    if trend == "up" and (last_high is None or running_extends):
        anchor_index = swings["extreme_index"]
        anchor_price = swings["extreme_price"]
        pullback_from = None
    elif last_high is not None:
        anchor_index = last_high["index"]
        anchor_price = last_high["price"]
        pullback_from = anchor_index
    else:
        return {"ok": False, "reason": "还没有上攻高点"}
    picked = _turnover_lows(rows)
    if picked is None:
        return {"ok": False, "reason": "近期没有两天成交量，无法按换手取低点"}
    pullback = _pullback(rows, pullback_from) if pullback_from is not None else None
    return {
        "ok": True,
        "kind": "高换手",
        "first": picked["first"],
        "second": picked["second"],
        "anchor_index": anchor_index,
        "anchor_price": anchor_price,
        "pullback": pullback,
    }


def _turnover_lows(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """最近一段里成交量最大的两天。各自的最低价就是两个低点。"""
    start = max(0, len(rows) - RECENT_DAYS)
    ranked = [
        (float(rows[index]["volume"]), index)
        for index in range(start, len(rows))
        if rows[index].get("volume") not in (None, 0) and rows[index]["volume"] > 0
    ]
    if len(ranked) < 2:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen = sorted(ranked[:2], key=lambda item: item[1])
    earlier = rows[chosen[0][1]]
    later = rows[chosen[1][1]]
    return {
        "first": {"price": earlier["low"], "date": earlier["date"]},
        "second": {"price": later["low"], "date": later["date"]},
    }


def _pullback(rows: list[dict[str, Any]], high_index: int) -> dict[str, Any] | None:
    """回撤过程的价格区间：上攻高点之后走到的最低价和最高价。"""
    segment = rows[high_index + 1 :]
    if not segment:
        return None
    floor = min(segment, key=lambda row: row["low"])
    ceiling = max(segment, key=lambda row: row["high"])
    lower = float(floor["low"])
    upper = float(ceiling["high"])
    return {
        "lower": _round(lower),
        "upper": _round(upper),
        "zone_low": _round(min(lower, upper)),
        "zone_high": _round(max(lower, upper)),
        "low_date": floor["date"],
        "high_date": ceiling["date"],
    }


def _event_vwap(row: dict[str, Any]) -> float | None:
    """成交额 / 成交量。单位对不上日线高低价时，按手和千元再换一次。"""
    amount = row.get("amount")
    volume = row.get("volume")
    if amount is None or volume is None or volume <= 0 or amount <= 0:
        return None
    direct = amount / volume
    scaled = amount * 10.0 / volume
    low = row["low"]
    high = row["high"]
    if low * 0.98 <= direct <= high * 1.02:
        return direct
    if low * 0.98 <= scaled <= high * 1.02:
        return scaled
    return None


def _assemble(rows: list[dict[str, Any]], structure: dict[str, Any]) -> dict[str, Any]:
    last = rows[-1]
    base = {
        "asof": last["date"],
        "close": _round(last["close"]),
        "stage": "未形成",
        "lows": None,
        "pullback": None,
        "pressure": None,
        "breakout": None,
        "ladder": [],
        "note": "",
    }
    if not structure.get("ok"):
        base["note"] = str(structure.get("reason") or "结构未形成")
        return base
    first = structure["first"]
    second = structure["second"]
    low_a = _round(first["price"])
    low_b = _round(second["price"])
    lows = {
        "kind": structure.get("kind") or "高换手",
        "first": low_a,
        "second": low_b,
        "first_date": first["date"],
        "second_date": second["date"],
        "zone_low": _round(min(low_a, low_b)),
        "zone_high": _round(max(low_a, low_b)),
    }
    anchor = rows[structure["anchor_index"]]
    vwap = _event_vwap(anchor)
    event_vwap = _round(vwap) if vwap is not None else None
    event_close = _round(anchor["close"])
    event_high = _round(anchor["high"])
    last_close = float(last["close"])
    pressure = {
        "vwap": event_vwap,
        "close": event_close,
        "high": event_high,
        "date": anchor["date"],
        "distance_vwap": _distance(last_close, event_vwap),
        "distance_close": _distance(last_close, event_close),
        "distance_high": _distance(last_close, event_high),
    }
    breakout = _breakout(rows, structure["anchor_index"], event_high)
    pullback = structure["pullback"]
    stage = _stage(last["close"], lows, pullback, pressure, breakout)
    ladder = _ladder(lows, pullback, pressure)
    return {
        "asof": last["date"],
        "close": _round(last["close"]),
        "stage": stage,
        "lows": lows,
        "pullback": pullback,
        "pressure": pressure,
        "breakout": breakout,
        "ladder": ladder,
        "note": "",
    }


def _distance(close: float, price: float | None) -> float | None:
    """最新收盘相对参考价的偏离，单位是百分数。"""
    if price is None or price == 0:
        return None
    return _round((close - price) / price * 100.0)


def _breakout(rows: list[dict[str, Any]], anchor_index: int, upper: float) -> dict[str, Any]:
    """收盘价站上事件最高价，再看之后有没有回踩这个最高价。"""
    later = rows[anchor_index + 1 :]
    broke_at = None
    for offset, row in enumerate(later):
        if row["close"] > upper:
            broke_at = offset
            break
    if broke_at is None:
        retest = "未突破"
    else:
        after = later[broke_at + 1 :]
        touched = any(row["low"] <= upper for row in after)
        if not after:
            retest = "待回踩"
        elif not touched:
            retest = "待回踩"
        elif after[-1]["close"] > upper:
            retest = "回踩后站稳"
        else:
            retest = "回踩后落回"
    return {
        "price": _round(upper),
        "date": rows[anchor_index]["date"],
        "confirmed": broke_at is not None,
        "retest": retest,
    }


def _stage(close: float, lows: dict, pullback: dict | None, pressure: dict | None, breakout: dict) -> str:
    if breakout["retest"] == "回踩后落回":
        return "回踩"
    if breakout["confirmed"] and close > breakout["price"]:
        return "突破"
    if pullback and _inside(close, pullback["zone_low"], pullback["zone_high"]):
        return "回调"
    if _inside(close, lows["zone_low"], lows["zone_high"]):
        return "低点"
    if close < lows["zone_low"]:
        return "低点下方"
    if pullback and lows["zone_high"] < close < pullback["zone_low"]:
        return "低点与回调之间"
    if pressure and pullback and pullback["zone_high"] < close < pressure["high"]:
        return "事件最高价下方"
    return "区间之间"


def _inside(price: float, low: float, high: float) -> bool:
    return low - 1e-9 <= price <= high + 1e-9


def _ladder(lows: dict, pullback: dict | None, pressure: dict | None) -> list[dict[str, Any]]:
    points = [
        {"label": "低点1", "price": lows["first"]},
        {"label": "低点2", "price": lows["second"]},
    ]
    if pullback:
        points.append({"label": "回调下沿", "price": pullback["lower"]})
        points.append({"label": "回调上沿", "price": pullback["upper"]})
    if pressure:
        if pressure["vwap"] is not None:
            points.append({"label": "事件VWAP", "price": pressure["vwap"]})
        points.append({"label": "事件收盘", "price": pressure["close"]})
        points.append({"label": "事件最高", "price": pressure["high"]})
    return points


def _round(value: float) -> float:
    return round(float(value) + 0.0, 2)


def reports_for_symbols(symbols: list[str], bars: pd.DataFrame) -> list[dict[str, Any]]:
    """按代码顺序出盯盘。没有日线的代码保留一行说明。"""
    items: list[dict[str, Any]] = []
    empty = bars is None or bars.empty or "symbol" not in getattr(bars, "columns", [])
    for code in symbols:
        part = bars.iloc[0:0] if empty else bars[bars["symbol"] == code]
        report = analyze_frame(part)
        report["symbol"] = code
        items.append(report)
    return items


def _empty(note: str) -> dict[str, Any]:
    return {
        "asof": None,
        "close": None,
        "stage": "未形成",
        "lows": None,
        "pullback": None,
        "pressure": None,
        "breakout": None,
        "ladder": [],
        "note": note,
    }
