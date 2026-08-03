# -*- coding: utf-8 -*-
"""观察池当日截面：Q / M+ / M- 排名（供 fetch_pattern_entry 推送东财自选）。"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from market_neutral.config import ensure_sys_path


def _norm_sym(s) -> str:
    return "".join(c for c in str(s) if c.isdigit()).zfill(6)


def _uniq_symbols(symbols: Sequence[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for s in symbols:
        sym = _norm_sym(s)
        if len(sym) == 6 and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def _rank_frame(
    df: pd.DataFrame,
    *,
    score_col: str,
    asof: str,
    name_map: Optional[Dict[str, str]] = None,
    extra_cols: Optional[Sequence[str]] = None,
) -> pd.DataFrame:
    if df is None or df.empty or score_col not in df.columns:
        return pd.DataFrame()
    g = df.copy()
    g["symbol"] = g["symbol"].astype(str).map(_norm_sym)
    g[score_col] = pd.to_numeric(g[score_col], errors="coerce")
    g = g[g[score_col].notna()].copy()
    if g.empty:
        return pd.DataFrame()
    g = g.sort_values([score_col, "symbol"], ascending=[False, True]).reset_index(drop=True)
    g.insert(0, "rank", range(1, len(g) + 1))
    nm = name_map or {}
    if "stock_name" not in g.columns:
        g["stock_name"] = ""
    g["stock_name"] = g.apply(
        lambda r: str(r.get("stock_name") or "") or nm.get(str(r["symbol"]), ""),
        axis=1,
    )
    g["asof"] = asof
    cols = ["rank", "asof", "symbol", "stock_name", score_col]
    for c in extra_cols or ():
        if c in g.columns and c not in cols:
            cols.append(c)
    return g[cols]


def rank_observation_pool_qm(
    symbols: Sequence[str],
    *,
    end_date: str,
    name_map: Optional[Dict[str, str]] = None,
    skip_fina: bool = False,
    warm_calendar_days: int = 280,
) -> Tuple[Dict[str, pd.DataFrame], List[str]]:
    """
    对观察池算当日 Q / M+ / M- 截面排名。
    返回 ({"Q": df, "M+": df, "M-": df}, notes)。
    """
    notes: List[str] = []
    empty = {"Q": pd.DataFrame(), "M+": pd.DataFrame(), "M-": pd.DataFrame()}
    uniq = _uniq_symbols(symbols)
    if not uniq:
        return empty, ["观察池为空，跳过 Q/M+/M- 排名"]

    ensure_sys_path()
    try:
        from market_neutral.data.prices import (
            fetch_daily_basic_panel,
            fetch_industry_map,
            fetch_stock_bars,
        )
        from market_neutral.factors.company_value import (
            build_company_q_panel,
            fetch_fina_lite,
        )
        from market_neutral.factors.mud import compute_mud_panel
        from market_neutral.factors.value import build_valuation_panel
    except Exception as exc:
        return empty, [f"Q/M 模块导入失败: {exc}"]

    end_s = str(end_date)[:10]
    asof_ts = pd.Timestamp(end_s).normalize()
    warm_start = (
        datetime.strptime(end_s, "%Y-%m-%d") - timedelta(days=int(warm_calendar_days))
    ).strftime("%Y-%m-%d")
    basic_start = (
        datetime.strptime(end_s, "%Y-%m-%d") - timedelta(days=14)
    ).strftime("%Y-%m-%d")
    nm = name_map or {}

    # —— 估值 upside（Q 的一部分）——
    print(f"  [qm-rank] daily_basic {len(uniq)} …", flush=True)
    try:
        basic = fetch_daily_basic_panel(uniq, basic_start, end_s)
        industry = fetch_industry_map(uniq)
        valuation = build_valuation_panel(basic, industry)
        if not valuation.empty:
            # 对齐到最近有数据的交易日
            valuation = valuation.copy()
            valuation["date"] = pd.to_datetime(valuation["date"]).dt.normalize()
            last_d = valuation["date"].max()
            if last_d < asof_ts:
                asof_ts = pd.Timestamp(last_d).normalize()
                notes.append(f"估值 asof 回退至 {asof_ts.strftime('%Y-%m-%d')}")
    except Exception as exc:
        notes.append(f"估值截面失败: {exc}")
        valuation = pd.DataFrame()

    asof_label = asof_ts.strftime("%Y-%m-%d")

    # —— M+ / M- ——
    print(f"  [qm-rank] 行情(MUD) {len(uniq)} …", flush=True)
    try:
        bars = fetch_stock_bars(uniq, warm_start, end_s)
        mud = compute_mud_panel(bars, [asof_ts], name_map=nm)
    except Exception as exc:
        notes.append(f"MUD 计算失败: {exc}")
        mud = pd.DataFrame()
        bars = {}

    mplus = _rank_frame(
        mud,
        score_col="mud_plus",
        asof=asof_label,
        name_map=nm,
        extra_cols=("r60", "r20", "vol_ratio", "close"),
    )
    mminus = _rank_frame(
        mud,
        score_col="mud_minus",
        asof=asof_label,
        name_map=nm,
        extra_cols=("r60", "r20", "close"),
    )
    notes.append(f"M+ 有效 {len(mplus)}/{len(uniq)} · M- 有效 {len(mminus)}/{len(uniq)}")

    # —— Q ——
    print("  [qm-rank] 公司估值 Q …", flush=True)
    fina = pd.DataFrame()
    if skip_fina:
        notes.append("已跳过 fina（Q 仅靠 upside 分位）")
    else:
        try:
            # 财务公告需要更早起点，fetch_fina_lite 内部已扩展
            fina = fetch_fina_lite(uniq, end_s, end_s)
            notes.append(f"fina 行数 {len(fina)}")
        except Exception as exc:
            notes.append(f"fina 拉取失败，Q 降级: {exc}")
            fina = pd.DataFrame()

    try:
        q_panel = build_company_q_panel(fina, valuation, [asof_ts], name_map=nm)
    except Exception as exc:
        notes.append(f"Q 合成失败: {exc}")
        q_panel = pd.DataFrame()

    q_ranked = _rank_frame(
        q_panel,
        score_col="company_q",
        asof=asof_label,
        name_map=nm,
        extra_cols=("roe", "ocf_to_or", "upside", "close"),
    )
    notes.append(f"Q 有效 {len(q_ranked)}/{len(uniq)}")

    return {"Q": q_ranked, "M+": mplus, "M-": mminus}, notes
