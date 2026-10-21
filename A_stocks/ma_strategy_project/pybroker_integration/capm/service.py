# -*- coding: utf-8 -*-
"""把市场模型和本地行情收成页面用的报告。不写观察池，不改仓位。"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

from capm.act import NO_BARS, act_from_frame, phase1_combo_id
from capm.model import NOTES, PRIMARY_WINDOW, align_returns, as_jsonable, attribute_frame
from capm.sources import (
    BARS_CACHE,
    BARS_FALLBACK,
    BENCH_CACHE,
    FETCH_PAD_START,
    OHLC_CACHE,
    SLEEVES,
    closes_to_returns,
    fetch_closes,
    load_books,
    load_closes,
    load_market,
    load_ohlc,
    load_theme_universe,
    load_watch,
    nav_to_returns,
    parse_symbols,
    store_benchmark,
    store_closes,
    store_ohlc,
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
    universe: str = "vp6",
    symbols: str = "",
    refresh: bool = False,
    bench_path: Path | None = None,
    watch_paths: tuple[Path, ...] | None = None,
    scan_path: Path | None = None,
    theme_rank_paths: tuple[Path, ...] | None = None,
    cache_path: Path | None = None,
    fallback_path: Path | None = None,
    ohlc_path: Path | None = None,
    fetcher: Callable[[list[str], str, str], pd.DataFrame] | None = None,
    ohlc_fetcher: Callable[[list[str], str, str], pd.DataFrame] | None = None,
    classify: Callable[[pd.DataFrame], int | None] | None = None,
    session_end: str | None = None,
    bench_fetcher: Callable[[str, str], pd.DataFrame] | None = None,
    bench_cache: Path | None = None,
) -> dict:
    try:
        market = load_market(bench_path)
        picked, truncated, names, missing = _resolve_universe(
            universe, symbols, watch_paths, scan_path, theme_rank_paths
        )
    except (FileNotFoundError, ValueError) as exc:
        return _empty(str(exc))
    if not picked:
        return _empty("没有可计算的股票代码")
    cache = Path(cache_path or BARS_CACHE)
    fallback = Path(fallback_path) if fallback_path is not None else BARS_FALLBACK
    ohlc_cache = Path(ohlc_path or OHLC_CACHE)
    note = ""
    bench_note = ""
    horizon = session_end if refresh else None
    if refresh and horizon and bench_fetcher is not None:
        market, bench_note = _extend_market(market, horizon, bench_fetcher, Path(bench_cache or BENCH_CACHE))
    if refresh:
        note = _refresh_missing(picked, market, cache, fallback, fetcher or fetch_closes, horizon=horizon)
        if ohlc_fetcher is not None:
            act_note = _refresh_act_bars(picked, market, ohlc_cache, ohlc_fetcher, horizon=horizon)
            note = f"{note} {act_note}".strip()
    closes = load_closes(set(picked), cache_path=cache, fallback_path=fallback)
    returns = closes_to_returns(closes)
    acts = _acts(picked, load_ohlc(set(picked), cache_path=ohlc_cache), classify or phase1_combo_id)
    rows = []
    for code in picked:
        series = returns.get(code, pd.Series(dtype=float))
        row = _row(
            names.get(code) or code,
            series,
            market,
            symbol=code,
            stock_name=names.get(code, ""),
        )
        row.update(acts.get(code, _blank_act()))
        row["session_return"] = _session_return(series)
        rows.append(row)
    ready = sum(1 for row in rows if row["w250"] or row["w120"])
    extra = [
        "个股先用本地日线。收盘缓存写在 capm/cache/bars.csv，没有再读已有的 bars.csv。",
        "补齐只补本地对不齐主窗口的代码，并只写入这份缓存。",
        "主力表演读最近 10 个交易日的量价组合，日线写在 capm/cache/ohlc.csv。",
        f"本次请求 {len(picked)} 只，其中 {ready} 只能做出 120 日或 250 日窗口。",
    ]
    if _universe_name(universe) == "vp6":
        extra.append("个股名单来自形态建仓和回测对比的题材全表，不按排名截取。")
        if missing:
            extra.append("未读到：" + "、".join(missing))
    if truncated:
        extra.append(f"粘贴代码超过 {SYMBOL_LIMIT} 只，只取前 {SYMBOL_LIMIT} 只。")
    if horizon:
        extra.append(f"本次补齐请求截止 {horizon}，按最近一个已收盘交易日。表上的区间终点是对齐后实际拿到的最后一天。")
    if bench_note:
        extra.insert(0, bench_note)
    if note:
        extra.insert(0, note)
    report = _report(rows, market, extra_notes=tuple(extra))
    message = " ".join(part for part in (bench_note, note) if part)
    if message:
        report["message"] = message
    report["report"]["universe"] = _universe_name(universe)
    report["report"]["requested"] = len(picked)
    report["report"]["ready"] = ready
    return report


def _extend_market(
    market: pd.Series,
    horizon: str,
    fetcher: Callable[[str, str], pd.DataFrame],
    cache: Path,
) -> tuple[pd.Series, str]:
    target = pd.Timestamp(horizon).normalize()
    if len(market) and pd.Timestamp(market.index.max()).normalize() >= target:
        return market, ""
    start = pd.Timestamp(market.index.max()).date().isoformat() if len(market) else FETCH_PAD_START
    fresh = fetcher(start, target.date().isoformat())
    if fresh is None or fresh.empty:
        last = pd.Timestamp(market.index.max()).date().isoformat() if len(market) else "空"
        return market, f"沪深300没有补到 {target.date().isoformat()}，窗口仍停在 {last}。"
    store_benchmark(fresh, cache)
    extra = nav_to_returns(fresh)
    merged = pd.concat([market, extra])
    merged = merged[~merged.index.duplicated(keep="last")].sort_index()
    merged = merged.replace([float("inf"), float("-inf")], pd.NA).dropna()
    last = pd.Timestamp(merged.index.max()).date().isoformat() if len(merged) else target.date().isoformat()
    return merged, f"沪深300补到 {last}。"


def _refresh_missing(
    symbols: list[str],
    market: pd.Series,
    cache: Path,
    fallback: Path,
    fetcher: Callable[[list[str], str, str], pd.DataFrame],
    horizon: str | None = None,
) -> str:
    closes = load_closes(set(symbols), cache_path=cache, fallback_path=fallback)
    returns = closes_to_returns(closes)
    target = pd.Timestamp(horizon).normalize() if horizon else None
    need = []
    for code in symbols:
        series = returns.get(code, pd.Series(dtype=float))
        both = align_returns(series, market)
        last = pd.Timestamp(series.index.max()).normalize() if len(series) else None
        stale = target is not None and (last is None or last < target)
        if len(both) < PRIMARY_WINDOW or stale:
            need.append(code)
    if not need:
        if target is not None:
            return f"本地日线已覆盖到 {target.date().isoformat()}，未再请求行情。"
        return "本地日线已覆盖 250 日窗口，未再请求行情。"
    end = target.date().isoformat() if target is not None else pd.Timestamp(market.index.max()).date().isoformat()
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
    scan_path: Path | None,
    theme_rank_paths: tuple[Path, ...] | None,
) -> tuple[list[str], bool, dict[str, str], list[str]]:
    if universe == "paste":
        codes, truncated = parse_symbols(symbols, SYMBOL_LIMIT)
        names, _missing = _known_names(watch_paths, scan_path, theme_rank_paths)
        return codes, truncated, names, []
    if universe == "watch46":
        watch = load_watch(watch_paths)
        return [item["symbol"] for item in watch], False, {item["symbol"]: item["stock_name"] for item in watch}, []
    scanned, missing = load_theme_universe(theme_rank_paths, scan_path)
    return [item["symbol"] for item in scanned], False, {item["symbol"]: item["stock_name"] for item in scanned}, missing


def _known_names(
    watch_paths: tuple[Path, ...] | None,
    scan_path: Path | None,
    theme_rank_paths: tuple[Path, ...] | None,
) -> tuple[dict[str, str], list[str]]:
    names: dict[str, str] = {}
    missing: list[str] = []
    try:
        for item in load_theme_universe(theme_rank_paths, scan_path)[0]:
            if item["stock_name"]:
                names[item["symbol"]] = item["stock_name"]
    except (FileNotFoundError, ValueError):
        names = {}
    try:
        for item in load_watch(watch_paths):
            if item["stock_name"]:
                names[item["symbol"]] = item["stock_name"]
    except FileNotFoundError:
        pass
    return names, missing


def _universe_name(universe: str) -> str:
    if universe == "paste":
        return "paste"
    if universe == "watch46":
        return "watch46"
    return "vp6"


def _blank_act() -> dict:
    return {"act_label": NO_BARS, "act_return": None, "act_end": None}


def _session_return(series: pd.Series) -> float | None:
    """最近一个有收盘的交易日相对前一交易日的涨跌。没有两根收盘则为空。"""
    if series is None or len(series) == 0:
        return None
    value = series.iloc[-1]
    if pd.isna(value):
        return None
    return float(value)


def _acts(
    symbols: list[str],
    ohlc: pd.DataFrame,
    classify: Callable[[pd.DataFrame], int | None],
) -> dict[str, dict]:
    grouped = {}
    if ohlc is not None and not ohlc.empty:
        grouped = {str(symbol): part for symbol, part in ohlc.groupby("symbol", sort=False)}
    out = {}
    for code in symbols:
        part = grouped.get(code)
        if part is None or len(part) < 2:
            out[code] = _blank_act()
            continue
        out[code] = act_from_frame(part, classify)
    return out


def _refresh_act_bars(
    symbols: list[str],
    market: pd.Series,
    cache: Path,
    fetcher: Callable[[list[str], str, str], pd.DataFrame],
    horizon: str | None = None,
) -> str:
    have = load_ohlc(set(symbols), cache_path=cache)
    counts = have.groupby("symbol").size().to_dict() if not have.empty else {}
    last_map = have.groupby("symbol")["date"].max().to_dict() if not have.empty else {}
    target = pd.Timestamp(horizon).normalize() if horizon else None
    need = []
    for code in symbols:
        last = last_map.get(code)
        stale = target is not None and (last is None or pd.Timestamp(last).normalize() < target)
        if int(counts.get(code, 0)) < 75 or stale:
            need.append(code)
    if not need:
        return "主力表演日线已覆盖最近窗口，未再请求行情。"
    end = target.date().isoformat() if target is not None else pd.Timestamp(market.index.max()).date().isoformat()
    fresh = fetcher(need, FETCH_PAD_START, end)
    if fresh is None or fresh.empty:
        return f"有 {len(need)} 只没有主力表演日线，本次没有补到。"
    store_ohlc(fresh, cache)
    got = {code for code in (_code(item) for item in fresh["symbol"]) if code}
    return f"主力表演日线请求 {len(need)} 只，写入缓存 {len(got)} 只。"


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
