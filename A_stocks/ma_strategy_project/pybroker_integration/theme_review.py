# -*- coding: utf-8 -*-
"""题材复盘：东财概念成分 → 百亚启动段 → 量价六组合标注。

只读。不写观察池，不导出六组合观察表，不改六组合分类规则。
"""
from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Callable

import pandas as pd

from capm.launch_match import (
    FETCH_START,
    RELATED_MIN,
    TEMPLATE_SYMBOL,
    _cache_end,
    _reason,
    _short_codes,
    _symbol_frame,
    measure_template,
    score_frame,
)
from capm.sources import OHLC_CACHE, fetch_act_bars, load_ohlc, store_ohlc

SCHEMA_VERSION = "theme_review_v1"
_SPLIT = re.compile(r"[\s,，;；、]+")


def _symbol(con_code: object) -> str | None:
    text = str(con_code or "").strip().upper()
    if not text:
        return None
    digits = "".join(char for char in text.split(".")[0] if char.isdigit())
    if len(digits) < 6:
        return None
    return digits[-6:]


def parse_themes(text: str) -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for part in _SPLIT.split(text or ""):
        name = part.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name)
    return names


def match_concepts(names: list[str], index: pd.DataFrame) -> tuple[list[dict], list[str]]:
    """按东财概念名称精确匹配。对不上的名字原样返回。"""
    lookup: dict[str, str] = {}
    if index is not None and not index.empty and {"ts_code", "name"}.issubset(index.columns):
        for code, raw in zip(index["ts_code"], index["name"]):
            label = str(raw or "").strip()
            concept = str(code or "").strip()
            if label and concept and label not in lookup:
                lookup[label] = concept
    matched: list[dict] = []
    missing: list[str] = []
    for name in names:
        code = lookup.get(name)
        if code is None:
            missing.append(name)
            continue
        matched.append({"name": name, "ts_code": code})
    return matched, missing


def collect_members(matched: list[dict], members: pd.DataFrame) -> list[dict]:
    """同一只股票落在多个题材里时合并成一行。"""
    if not matched:
        return []
    frame = members if members is not None else pd.DataFrame()
    grouped: dict[str, pd.DataFrame] = {}
    if not frame.empty and {"concept_code", "con_code"}.issubset(frame.columns):
        for code, part in frame.groupby("concept_code", sort=False):
            grouped[str(code)] = part
    order: list[str] = []
    bucket: dict[str, dict] = {}
    for concept in matched:
        part = grouped.get(concept["ts_code"])
        count = 0
        seen: set[str] = set()
        if part is not None:
            name_col = "con_name" if "con_name" in part.columns else "name"
            for raw_code, raw_name in zip(part["con_code"], part[name_col] if name_col in part.columns else [""] * len(part)):
                symbol = _symbol(raw_code)
                if not symbol or symbol in seen:
                    continue
                seen.add(symbol)
                count += 1
                stock_name = "" if raw_name is None or (isinstance(raw_name, float) and math.isnan(raw_name)) else str(raw_name).strip()
                if stock_name == "nan":
                    stock_name = ""
                row = bucket.get(symbol)
                if row is None:
                    bucket[symbol] = {
                        "symbol": symbol,
                        "stock_name": stock_name,
                        "themes": [concept["name"]],
                    }
                    order.append(symbol)
                    continue
                if concept["name"] not in row["themes"]:
                    row["themes"].append(concept["name"])
                if not row["stock_name"] and stock_name:
                    row["stock_name"] = stock_name
        concept["member_count"] = count
    return [bucket[symbol] for symbol in order]


def score_members(members: list[dict], bars: pd.DataFrame) -> tuple[list[dict], list[str]]:
    template = measure_template(_symbol_frame(bars, TEMPLATE_SYMBOL))
    related: list[dict] = []
    short: list[str] = []
    for member in members:
        frame = _symbol_frame(bars, member["symbol"])
        if frame is None or len(frame) < 80:
            short.append(member["symbol"])
            continue
        scored = score_frame(frame, template)
        if not scored["related"]:
            continue
        scored["reason"] = _reason(scored)
        related.append({**member, **scored})
    related.sort(key=lambda item: (-item["similarity"], item["symbol"]))
    return related, short


def combo_from_turnover(combo_name: str, turnover: float | None) -> tuple[str, str]:
    """换手率缺失时不标六组合。分类规则本身不在这里改。"""
    if turnover is None:
        return "", "缺换手率，未标形态"
    try:
        value = float(turnover)
    except (TypeError, ValueError):
        return "", "缺换手率，未标形态"
    if not math.isfinite(value):
        return "", "缺换手率，未标形态"
    return str(combo_name or ""), ""


def review_themes(
    text: str,
    *,
    index_loader: Callable[[], tuple[str, pd.DataFrame]],
    member_loader: Callable[[str, list[str]], pd.DataFrame],
    bars_loader: Callable[[list[str]], pd.DataFrame],
    combo_loader: Callable[[list[dict]], dict[str, tuple[str, str]]],
) -> dict:
    names = parse_themes(text)
    if not names:
        return _payload(None, "请输入东财概念名。", empty=True)
    try:
        trade_date, index = index_loader()
    except Exception as exc:
        return _payload(None, f"没有取到东财概念列表：{exc}", ok=False)
    matched, missing = match_concepts(names, index)
    notes: list[str] = []
    if index is None or index.empty:
        notes.append("没有取到东财概念列表。")
    else:
        for name in missing:
            notes.append(f"{name} 不是东财概念板块，没有成分。")
    members: list[dict] = []
    if matched:
        try:
            member_frame = member_loader(trade_date, [item["ts_code"] for item in matched])
        except Exception as exc:
            return _payload(None, f"没有取到概念成分：{exc}", ok=False)
        members = collect_members(matched, member_frame)
    for concept in matched:
        if concept.get("member_count", 0) == 0:
            notes.append(f"{concept['name']} 没有成分。")
    if not members:
        report = _report(trade_date, names, matched, missing, [], notes)
        message = "没有可对照的成分。" if matched or missing else "请输入东财概念名。"
        return _payload(report, message, empty=True)

    try:
        bars = bars_loader([item["symbol"] for item in members])
    except Exception as exc:
        return _payload(None, f"没有取到日线：{exc}", ok=False)
    related, short = score_members(members, bars)
    if short:
        notes.append(f"{len(short)} 只日线不足 80 根，没有对照百亚启动段。")
    labels: dict[str, tuple[str, str]] = {}
    if related:
        try:
            labels = combo_loader(related)
        except Exception as exc:
            notes.append(f"六组合没有标上：{exc}")
            labels = {}
    rows = []
    for item in related:
        combo_name, combo_note = labels.get(item["symbol"], ("", "未标形态"))
        rows.append(
            {
                "themes": "、".join(item["themes"]),
                "symbol": item["symbol"],
                "stock_name": item["stock_name"],
                "similarity": item["similarity"],
                "combo_name": combo_name,
                "combo_note": combo_note,
                "reason": item.get("reason", ""),
            }
        )
    if not rows and members:
        notes.append(f"成分里没有相似度达到 {RELATED_MIN:.2f} 的股票。")
    report = _report(trade_date, names, matched, missing, rows, notes)
    report["member_count"] = len(members)
    message = None if rows else f"没有相似度达到 {RELATED_MIN:.2f} 的股票。"
    return _payload(report, message, empty=not rows)


def list_concepts(index: pd.DataFrame, trade_date: str = "") -> dict:
    """东财概念板块名称。只读列表，不拉成分。"""
    names: list[str] = []
    seen: set[str] = set()
    if index is not None and not index.empty and "name" in index.columns:
        for raw in index["name"]:
            label = str(raw or "").strip()
            if not label or label.lower() == "nan" or label in seen:
                continue
            seen.add(label)
            names.append(label)
    names.sort()
    return {
        "ok": True,
        "empty": not names,
        "error": None,
        "message": None if names else "没有取到东财概念列表。",
        "trade_date": trade_date,
        "count": len(names),
        "names": names,
    }


def list_concepts_live() -> dict:
    try:
        trade_date, frame = _load_index()
    except Exception as exc:
        return {
            "ok": False,
            "empty": True,
            "error": f"没有取到东财概念列表：{exc}",
            "message": f"没有取到东财概念列表：{exc}",
            "trade_date": "",
            "count": 0,
            "names": [],
        }
    return list_concepts(frame, trade_date)


def review_themes_live(text: str) -> dict:
    return review_themes(
        text,
        index_loader=_load_index,
        member_loader=_load_members,
        bars_loader=_load_bars,
        combo_loader=_label_combos,
    )


def _load_index() -> tuple[str, pd.DataFrame]:
    from fetch_dc_concept_ma5 import resolve_dc_index_trade_date
    from market_radar import get_tushare_bundle

    _, pro = get_tushare_bundle()
    trade_date, frame = resolve_dc_index_trade_date(pro, datetime.now().strftime("%Y-%m-%d"))
    return trade_date, frame


def _load_members(trade_date: str, codes: list[str]) -> pd.DataFrame:
    from fetch_dc_concept_ma5 import REQUEST_SLEEP_SEC, fetch_members_for_concepts
    from market_radar import get_tushare_bundle

    _, pro = get_tushare_bundle()
    return fetch_members_for_concepts(pro, codes, trade_date, REQUEST_SLEEP_SEC)


def _load_bars(symbols: list[str]) -> pd.DataFrame:
    codes = set(symbols) | {TEMPLATE_SYMBOL}
    bars = load_ohlc(codes, cache_path=OHLC_CACHE)
    need = _short_codes(bars, codes)
    if not need:
        return bars
    fresh = fetch_act_bars(need, FETCH_START, _cache_end(bars))
    if fresh is not None and not getattr(fresh, "empty", True):
        store_ohlc(fresh, OHLC_CACHE)
        return load_ohlc(codes, cache_path=OHLC_CACHE)
    return bars


def _label_combos(rows: list[dict]) -> dict[str, tuple[str, str]]:
    """调用现有六组合分类，不写观察表。换手率缺失则形态留空。"""
    from fetch_vp_six_combo import VP_SIX_CONFIG, hits_from_symbols, scan_vp_six

    hits, _notes = hits_from_symbols([item["symbol"] for item in rows], source_note="题材复盘")
    names = {item["symbol"]: item["stock_name"] for item in rows}
    hits["stock_name"] = hits["symbol"].map(lambda code: names.get(code, ""))
    cfg = VP_SIX_CONFIG
    snaps, skipped = scan_vp_six(
        hits,
        end_date=datetime.now().strftime("%Y-%m-%d"),
        history_calendar_days=int(cfg["history_calendar_days"]),
        enable_phase2=True,
        skip_chips=True,
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
    labels = {
        snap.symbol: combo_from_turnover(snap.combo_name, snap.turnover_today_pct)
        for snap in snaps
    }
    for item in skipped:
        symbol = item.split("(", 1)[0]
        labels.setdefault(symbol, ("", "缺日线或数据不足，未标形态"))
    for item in rows:
        labels.setdefault(item["symbol"], ("", "未标形态"))
    return labels


def _report(
    trade_date: str,
    names: list[str],
    matched: list[dict],
    missing: list[str],
    rows: list[dict],
    notes: list[str],
) -> dict:
    by_name = {item["name"]: item for item in matched}
    themes = []
    for name in names:
        hit = by_name.get(name)
        themes.append(
            {
                "name": name,
                "matched": hit is not None,
                "member_count": 0 if hit is None else int(hit.get("member_count", 0)),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "trade_date": trade_date,
        "threshold": RELATED_MIN,
        "member_count": 0,
        "tracked_count": len(rows),
        "themes": themes,
        "rows": rows,
        "notes": notes,
        "unmatched": missing,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }


def _payload(report: dict | None, message: str | None, *, ok: bool = True, empty: bool = False) -> dict:
    return {
        "ok": ok,
        "empty": empty or report is None or not report.get("rows"),
        "error": None if ok else message,
        "message": message,
        "report": report,
    }
