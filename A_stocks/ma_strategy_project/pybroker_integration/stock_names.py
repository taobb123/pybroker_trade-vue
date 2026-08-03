# -*- coding: utf-8 -*-
"""通过 Tushare / AkShare 接口解析 A 股代码 -> 公司名称。"""

from __future__ import annotations

from train_model_symbols import normalize_a_share_symbol


def _fetch_batch_tushare(symbols: list[str]) -> dict[str, str]:
    """批量拉取 Tushare stock_basic，返回 6 位 code -> name。"""
    if not symbols:
        return {}
    try:
        from config.settings import DATA_CONFIG
    except ImportError:
        return {}

    token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
    if not token:
        return {}

    try:
        import tushare as ts

        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    except Exception:
        return {}

    if df is None or df.empty or "name" not in df.columns:
        return {}

    df = df.copy()
    df["symbol"] = (
        df["ts_code"].astype(str).str.split(".", n=1).str[0].str.zfill(6)
    )
    full_map = dict(zip(df["symbol"].astype(str), df["name"].astype(str)))
    wanted = {normalize_a_share_symbol(s) for s in symbols}
    return {sym: str(full_map.get(sym, "")).strip() for sym in wanted}


def resolve_stock_names(symbols: list[str]) -> dict[str, str]:
    """
    解析股票列表的公司名称。
    优先 Tushare 批量接口，缺失项逐只调用 fetch_stock_name（含 AkShare 回退）。
    仍无名称时回退为 6 位代码。
    """
    from backtest_sy_002028_threshold import fetch_stock_name

    ordered: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        sym = normalize_a_share_symbol(str(raw))
        if sym and sym not in seen:
            seen.add(sym)
            ordered.append(sym)

    batch = _fetch_batch_tushare(ordered)
    out: dict[str, str] = {}
    for sym in ordered:
        name = (batch.get(sym) or "").strip()
        if not name:
            name = fetch_stock_name(sym).strip()
        out[sym] = name or sym
    return out
