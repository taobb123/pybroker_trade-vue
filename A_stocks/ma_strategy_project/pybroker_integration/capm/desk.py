# -*- coding: utf-8 -*-
"""交易部门：按 Alpha 状态机记下价格确认后的买入，并检验收敛速度假设。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from capm.alpha_state import (
    FORWARD,
    LAG,
    OBSERVE_STEP,
    PERSIST_COUNT,
    PRICE_WINDOW,
    STATE_LABEL,
    VOLUME_MULT,
    collect_speed_observations,
    explain_state,
    snapshot_factors,
    summarize_speed_groups,
)
from capm.sources import (
    BARS_CACHE,
    BARS_FALLBACK,
    BENCH_CACHE,
    BENCH_CSV,
    HISTORY_LEDGER,
    OHLC_CACHE,
    OPEN_LEDGER,
    STOCK_WATCH_FILES,
    backfill_benchmark,
    backfill_earlier_closes,
    backfill_opens,
    closes_to_returns,
    load_closes,
    load_market,
    load_ohlc,
    load_watch,
)

SCHEMA_VERSION = "capm_desk_v1"
_CACHE: dict = {"stamp": None, "payload": None}

NOTES = (
    "交易部门只记下价格确认后的买入。不加仓，不止盈，不止损，不写观察池，不改仓位。",
    "候选要同时满足：250 日 β 在 0 到 0.5，250 日 α 小于 0，120 日 α 小于 0。",
    f"收敛看 120 日 α 相对 {LAG} 个交易日前是否上升。连续改善是每 {OBSERVE_STEP} 日观察一次、最近 {PERSIST_COUNT} 次都在改善。",
    f"价格确认要同时满足：当日最低价高于前 {PRICE_WINDOW} 日最低价；收盘价高于前 {PRICE_WINDOW} 日最高价；"
    f"成交量大于前 {PRICE_WINDOW} 日均量的 {VOLUME_MULT} 倍；收盘价高于开盘价。这些是初始参数。",
    "信号用到当日收盘和成交量。买入日记在下一交易日，不把当天收盘当成已经成交。",
    "状态机用本地已有高低价和成交量的股票。假设检验用本地已有收盘，不是全市场，也不要求已经价格确认。",
    f"假设在每个取样日把候选按收敛速度分成五组，看其后 {FORWARD} 个交易日相对沪深300的超额。"
    f"取样每隔 {FORWARD} 个交易日。未来收益里若有停牌，这一笔不计入。",
)


def desk_payload(
    *,
    bench_path: Path | None = None,
    cache_path: Path | None = None,
    fallback_path: Path | None = None,
    ohlc_path: Path | None = None,
    watch_paths: tuple[Path, ...] | None = None,
) -> dict:
    default_inputs = (
        bench_path is None
        and cache_path is None
        and fallback_path is None
        and ohlc_path is None
        and watch_paths is None
    )
    history_notes: list[str] = []
    if default_inputs:
        stamp = _source_stamp()
        if _CACHE["stamp"] == stamp and _CACHE["payload"] is not None:
            return _CACHE["payload"]
        history_notes = [
            note
            for note in (backfill_benchmark(), backfill_earlier_closes(), backfill_opens())
            if note
        ]
    try:
        market = load_market(bench_path)
    except (FileNotFoundError, ValueError) as exc:
        return _empty(str(exc))
    if market is None or len(market) == 0:
        return _empty("没有沪深300收益")
    names = _names(watch_paths)
    closes = load_closes(
        None,
        cache_path=Path(cache_path) if cache_path is not None else BARS_CACHE,
        fallback_path=Path(fallback_path) if fallback_path is not None else BARS_FALLBACK,
    )
    returns = closes_to_returns(closes)
    ohlc = load_ohlc(None, cache_path=Path(ohlc_path) if ohlc_path is not None else OHLC_CACHE)
    rows = _rows(returns, market, ohlc, names)
    hypothesis = summarize_speed_groups(collect_speed_observations(returns, market))
    market_end = pd.Timestamp(market.index.max()).date().isoformat()
    buys = [row for row in rows if row["state"] == "S2" and row["current"]]
    counts = {key: 0 for key in ("S2", "S1", "S0", "excluded", "insufficient")}
    for row in rows:
        counts[row["state"]] = counts.get(row["state"], 0) + 1
    open_missing = bool(rows) and all(row["open_missing"] for row in rows)
    notes = history_notes + list(NOTES)
    if open_missing:
        notes.insert(0, "当前量价缓存没有开盘价，收盘高于开盘这一关过不了，所以不会记下买入。")
    payload = {
        "ok": True,
        "empty": False,
        "error": None,
        "message": None,
        "report": {
            "schema_version": SCHEMA_VERSION,
            "benchmark": "沪深300",
            "as_of": market_end,
            "counts": counts,
            "open_missing": open_missing,
            "rows": rows,
            "buys": buys,
            "hypothesis": hypothesis,
            "notes": notes,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }
    if default_inputs:
        _CACHE["stamp"] = _source_stamp()
        _CACHE["payload"] = payload
    return payload


def _source_stamp() -> tuple:
    paths = (BENCH_CSV, BENCH_CACHE, BARS_CACHE, BARS_FALLBACK, OHLC_CACHE, HISTORY_LEDGER, OPEN_LEDGER, *STOCK_WATCH_FILES)
    stamp = []
    for path in paths:
        file = Path(path)
        if not file.is_file():
            stamp.append((str(file), None))
            continue
        stat = file.stat()
        stamp.append((str(file), stat.st_mtime_ns, stat.st_size))
    return tuple(stamp)


def _rows(
    returns: dict[str, pd.Series],
    market: pd.Series,
    ohlc: pd.DataFrame,
    names: dict[str, str],
) -> list[dict]:
    grouped: dict[str, pd.DataFrame] = {}
    if ohlc is not None and not ohlc.empty and "symbol" in ohlc.columns:
        grouped = {str(symbol): part for symbol, part in ohlc.groupby("symbol", sort=False)}
    market_end = pd.Timestamp(market.index.max()).normalize()
    rows = []
    for symbol in sorted(grouped):
        bars = grouped[symbol]
        series = returns.get(symbol, pd.Series(dtype=float))
        factor = snapshot_factors(series, market, bars)
        rows.append(_public_row(symbol, names.get(symbol, ""), factor, market_end))
    return rows


def _public_row(symbol: str, name: str, factor: dict | None, market_end: pd.Timestamp) -> dict:
    if factor is None:
        state = "insufficient"
        gates = {
            "no_new_low": False,
            "breakout": False,
            "volume_ok": False,
            "close_above_open": False,
            "open_missing": True,
            "same_day": False,
        }
        reason = explain_state(state, float("nan"), float("nan"), float("nan"), float("nan"), False, gates, current=False)
        return {
            "symbol": symbol,
            "stock_name": name,
            "state": state,
            "state_label": STATE_LABEL[state],
            "current": False,
            "signal_date": None,
            "buy_date": None,
            "beta250": None,
            "alpha250": None,
            "alpha120": None,
            "delta120": None,
            "speed": None,
            "persisted": False,
            "no_new_low": False,
            "breakout": False,
            "volume_ok": False,
            "close_above_open": False,
            "open_missing": True,
            "reason": reason,
        }
    gates = factor["gates"]
    signal = pd.Timestamp(factor["signal_date"]).normalize()
    current = signal == market_end
    state = factor["state"]
    return {
        "symbol": symbol,
        "stock_name": name,
        "state": state,
        "state_label": STATE_LABEL.get(state, state),
        "current": current,
        "signal_date": factor["signal_date"],
        "buy_date": None,
        "beta250": factor["beta250"],
        "alpha250": factor["alpha250"],
        "alpha120": factor["alpha120"],
        "delta120": factor["delta120"],
        "speed": factor["speed"],
        "persisted": bool(factor["persisted"]),
        "no_new_low": bool(gates.get("no_new_low")),
        "breakout": bool(gates.get("breakout")),
        "volume_ok": bool(gates.get("volume_ok")),
        "close_above_open": bool(gates.get("close_above_open")),
        "open_missing": bool(gates.get("open_missing")),
        "reason": explain_state(
            state,
            factor["beta250"],
            factor["alpha250"],
            factor["alpha120"],
            factor["delta120"],
            bool(factor["persisted"]),
            gates,
            current=current,
        ),
    }


def _names(watch_paths: tuple[Path, ...] | None) -> dict[str, str]:
    try:
        rows = load_watch(watch_paths or STOCK_WATCH_FILES)
    except FileNotFoundError:
        return {}
    return {item["symbol"]: item["stock_name"] for item in rows if item.get("stock_name")}


def _empty(message: str) -> dict:
    return {
        "ok": True,
        "empty": True,
        "error": None,
        "message": message,
        "report": None,
    }
