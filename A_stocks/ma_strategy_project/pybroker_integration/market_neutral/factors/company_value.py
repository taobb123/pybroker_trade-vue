# -*- coding: utf-8 -*-
"""轻量公司估值因子 Q：ROE + FCF质量 + 相对PE upside。"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from market_neutral.config import ensure_sys_path


def _sleep(sec: float = 0.12) -> None:
    time.sleep(sec)


def fetch_fina_lite(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    sleep_sec: float = 0.12,
) -> pd.DataFrame:
    """
    Tushare fina_indicator：ROE + 经营现金流/营业收入。
    返回长表: ann_date, end_date, symbol, roe, ocf_to_or
    用 ann_date 做点-in-time（防明显未来函数）。
    """
    ensure_sys_path()
    from backtest_sy_002028_threshold import six_digit_to_ts_code
    from trend_pullback_chips import get_tushare_pro

    pro = get_tushare_pro()
    s = start_date.replace("-", "")
    e = end_date.replace("-", "")
    # 财务需更早起点
    s_ext = (pd.Timestamp(start_date) - pd.Timedelta(days=800)).strftime("%Y%m%d")
    rows: List[pd.DataFrame] = []
    n = len(symbols)
    for i, sym in enumerate(symbols):
        code = "".join(c for c in str(sym) if c.isdigit()).zfill(6)
        ts_code = six_digit_to_ts_code(code)
        try:
            df = pro.fina_indicator(
                ts_code=ts_code,
                start_date=s_ext,
                end_date=e,
                fields="ts_code,ann_date,end_date,roe,ocf_to_or",
            )
        except Exception as exc:
            print(f"  [fina] {code} 跳过: {exc}", flush=True)
            df = None
        if df is not None and not df.empty:
            d = df.copy()
            d["symbol"] = code
            d["ann_date"] = pd.to_datetime(d["ann_date"], errors="coerce")
            d["end_date"] = pd.to_datetime(d["end_date"], errors="coerce")
            d["roe"] = pd.to_numeric(d["roe"], errors="coerce")
            d["ocf_to_or"] = pd.to_numeric(d["ocf_to_or"], errors="coerce")
            rows.append(d[["symbol", "ann_date", "end_date", "roe", "ocf_to_or"]])
        if (i + 1) % 10 == 0 or i + 1 == n:
            print(f"  [fina] {i + 1}/{n}", flush=True)
        _sleep(sleep_sec)
    if not rows:
        return pd.DataFrame(columns=["symbol", "ann_date", "end_date", "roe", "ocf_to_or"])
    return pd.concat(rows, ignore_index=True)


def build_company_q_panel(
    fina: pd.DataFrame,
    valuation: pd.DataFrame,
    rebal_dates: Sequence[pd.Timestamp],
    *,
    name_map: Optional[Dict[str, str]] = None,
) -> pd.DataFrame:
    """
    轻量 Q = 0.4*ROE分位 + 0.3*OCF/营收分位 + 0.3*upside分位。
    财务用 ann_date <= 调仓日的最新一期。
    """
    nm = name_map or {}
    if not rebal_dates:
        return pd.DataFrame()

    v = valuation.copy() if valuation is not None else pd.DataFrame()
    if not v.empty:
        v["date"] = pd.to_datetime(v["date"]).dt.normalize()
        v["symbol"] = v["symbol"].astype(str).str.zfill(6)

    f = fina.copy() if fina is not None else pd.DataFrame()
    if not f.empty:
        f["ann_date"] = pd.to_datetime(f["ann_date"], errors="coerce")
        f["symbol"] = f["symbol"].astype(str).str.zfill(6)

    out_rows: List[pd.DataFrame] = []
    for dt in rebal_dates:
        dt = pd.Timestamp(dt).normalize()
        # 估值 asof
        ups = pd.DataFrame(columns=["symbol", "upside", "close"])
        if not v.empty:
            sub_v = v[v["date"] <= dt]
            if not sub_v.empty:
                last = sub_v["date"].max()
                ups = sub_v[sub_v["date"] == last][["symbol", "upside", "close"]].copy()

        # 财务 asof
        fin_asof = pd.DataFrame(columns=["symbol", "roe", "ocf_to_or"])
        if not f.empty:
            sub_f = f[f["ann_date"].notna() & (f["ann_date"] <= dt)]
            if not sub_f.empty:
                sub_f = sub_f.sort_values(["symbol", "ann_date"])
                fin_asof = sub_f.groupby("symbol", as_index=False).tail(1)[
                    ["symbol", "roe", "ocf_to_or"]
                ]

        # 宇宙：估值 ∪ 财务
        syms = sorted(
            set(ups["symbol"].tolist() if not ups.empty else [])
            | set(fin_asof["symbol"].tolist() if not fin_asof.empty else [])
        )
        if not syms:
            continue
        base = pd.DataFrame({"symbol": syms})
        base = base.merge(fin_asof, on="symbol", how="left")
        base = base.merge(ups, on="symbol", how="left")
        base["date"] = dt
        base["stock_name"] = base["symbol"].map(lambda s: nm.get(s, ""))

        base["roe_pct"] = pd.to_numeric(base["roe"], errors="coerce").rank(
            method="average", pct=True
        )
        base["fcf_pct"] = pd.to_numeric(base["ocf_to_or"], errors="coerce").rank(
            method="average", pct=True
        )
        base["up_pct"] = pd.to_numeric(base["upside"], errors="coerce").rank(
            method="average", pct=True
        )
        base["company_q"] = (
            0.4 * base["roe_pct"].fillna(0.5)
            + 0.3 * base["fcf_pct"].fillna(0.5)
            + 0.3 * base["up_pct"].fillna(0.5)
        )
        all_nan = (
            base["roe"].isna()
            & base["ocf_to_or"].isna()
            & base["upside"].isna()
        )
        base.loc[all_nan, "company_q"] = np.nan
        out_rows.append(base)

    if not out_rows:
        return pd.DataFrame()
    return pd.concat(out_rows, ignore_index=True)
