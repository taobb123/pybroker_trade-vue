# -*- coding: utf-8 -*-
"""把市场模型和本地行情收成页面用的报告。不写观察池，不改仓位。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from capm.model import NOTES, PRIMARY_WINDOW, align_returns, as_jsonable, attribute_frame
from capm.sources import (
    BARS_CACHE,
    BARS_FALLBACK,
    FETCH_PAD_START,
    SLEEVES,
    fetch_closes,
    load_books,
    load_closes,
    load_market,
    load_watch,
    parse_symbols,
    store_closes,
    closes_to_returns,
    _code,
)

SCHEMA_VERSION = "capm_attr_v1"
SYMBOL_LIMIT = 80


def sleeves_payload(
    *,
    bench_path: Path | None = None,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
) -> dict:
    try:
        market = load_market(bench_path)
        books = load_books(group_path, sleeve_path)
    except (FileNotFoundError, ValueError) as exc:
        return _empty(str(exc))
    rows = []
    for name in SLEEVES:
        series = pd.Series(books[name].to_numpy(), index=books["date"])
        rows.append(_row(name, series, market))
    return _report(rows, market, extra_notes=())


def stocks_payload(
    *,
    universe: str = "watch46",
    symbols: str = "",
    refresh: bool = False,
    bench_path: Path | None = None,
    watch_paths: tuple[Path, ...] | None = None,
    cache_path: Path | None = None,
    fallback_path: Path | None = None,
    fetcher: Callable[[list[str], str, str], pd.DataFrame] | None = None,
) -> dict:
    try:
        market = load_market(bench_path)
        picked, truncated, names = _resolve_universe(universe, symbols, watch_paths)
    except (FileNotFoundError, ValueError) as exc:
        return _empty(str(exc))
    if not picked:
        return _empty("没有可计算的股票代码")
    cache = Path(cache_path or BARS_CACHE)
    fallback = Path(fallback_path) if fallback_path is not None else BARS_FALLBACK
    note = ""
    if refresh:
        note = _refresh_missing(picked, market, cache, fallback, fetcher or fetch_closes)
    closes = load_closes(set(picked), cache_path=cache, fallback_path=fallback)
    returns = closes_to_returns(closes)
    rows = [
        _row(names.get(code) or code, returns.get(code, pd.Series(dtype=float)), market, symbol=code, stock_name=names.get(code, ""))
        for code in picked
    ]
    ready = sum(1 for row in rows if row["w250"] or row["w120"])
    extra = [
        "个股先用本地日线。缓存写在 capm/cache/bars.csv，没有再读已有的 bars.csv。",
        "补齐只补本地对不齐主窗口的代码，并只写入这份缓存。",
        f"本次请求 {len(picked)} 只，其中 {ready} 只能做出 120 日或 250 日窗口。",
    ]
    if truncated:
        extra.append(f"粘贴代码超过 {SYMBOL_LIMIT} 只，只取前 {SYMBOL_LIMIT} 只。")
    if note:
        extra.insert(0, note)
    report = _report(rows, market, extra_notes=tuple(extra))
    if note:
        report["message"] = note
    report["report"]["universe"] = "paste" if universe == "paste" else "watch46"
    report["report"]["requested"] = len(picked)
    report["report"]["ready"] = ready
    return report


def _refresh_missing(
    symbols: list[str],
    market: pd.Series,
    cache: Path,
    fallback: Path,
    fetcher: Callable[[list[str], str, str], pd.DataFrame],
) -> str:
    closes = load_closes(set(symbols), cache_path=cache, fallback_path=fallback)
    returns = closes_to_returns(closes)
    need = []
    for code in symbols:
        both = align_returns(returns.get(code, pd.Series(dtype=float)), market)
        if len(both) < PRIMARY_WINDOW:
            need.append(code)
    if not need:
        return "本地日线已覆盖 250 日窗口，未再请求行情。"
    end = pd.Timestamp(market.index.max()).date().isoformat()
    fresh = fetcher(need, FETCH_PAD_START, end)
    if fresh is None or fresh.empty:
        return f"有 {len(need)} 只不足 250 日，本次没有补到新日线。"
    store_closes(fresh, cache)
    got = {code for code in (_code(item) for item in fresh["symbol"]) if code}
    return f"补齐请求 {len(need)} 只，写入缓存 {len(got)} 只。"


def _resolve_universe(
    universe: str,
    symbols: str,
    watch_paths: tuple[Path, ...] | None,
) -> tuple[list[str], bool, dict[str, str]]:
    if universe == "paste":
        codes, truncated = parse_symbols(symbols, SYMBOL_LIMIT)
        names = {}
        try:
            for item in load_watch(watch_paths):
                names[item["symbol"]] = item["stock_name"]
        except FileNotFoundError:
            names = {}
        return codes, truncated, names
    watch = load_watch(watch_paths)
    return [item["symbol"] for item in watch], False, {item["symbol"]: item["stock_name"] for item in watch}


def _row(
    name: str,
    asset: pd.Series,
    market: pd.Series,
    *,
    symbol: str = "",
    stock_name: str = "",
) -> dict:
    both = align_returns(asset, market)
    attributed = attribute_frame(both)
    quadrant = attributed["quadrant"]
    return {
        "key": symbol or name,
        "name": stock_name or name,
        "symbol": symbol,
        "stock_name": stock_name,
        "n_overlap": attributed["n_overlap"],
        "label": attributed["label"],
        "label_window": attributed["label_window"],
        "quadrant_id": quadrant["id"],
        "quadrant": quadrant["title"],
        "quadrant_action": quadrant["action"],
        "quadrant_hint": quadrant["hint"],
        "reason": attributed["reason"],
        "w250": as_jsonable(attributed["w250"]),
        "w120": as_jsonable(attributed["w120"]),
    }


def _report(rows: list[dict], market: pd.Series, extra_notes: tuple[str, ...]) -> dict:
    start = pd.Timestamp(market.index.min()).date().isoformat() if len(market) else None
    end = pd.Timestamp(market.index.max()).date().isoformat() if len(market) else None
    return {
        "ok": True,
        "empty": False,
        "error": None,
        "message": None,
        "report": {
            "schema_version": SCHEMA_VERSION,
            "benchmark": "沪深300",
            "rf": 0,
            "primary_window": 250,
            "alt_window": 120,
            "min_obs": 60,
            "sample_start": start,
            "sample_end": end,
            "rows": rows,
            "notes": list(NOTES) + list(extra_notes),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        },
    }


def _empty(message: str) -> dict:
    return {
        "ok": True,
        "empty": True,
        "error": None,
        "message": message,
        "report": None,
    }
