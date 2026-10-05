# -*- coding: utf-8 -*-
"""从 Tushare 读取申万一级成分和总市值。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from typing import Any, List, Tuple

import pandas as pd

from industry_factor.build import symbol6


def fetch_sw_l1_members(pro: Any, *, sleep_sec: float = 0.15) -> Tuple[pd.DataFrame, str, List[str]]:
    """返回 (成分表, 分类版本, 说明)。成分表列：symbol, industry_code, industry_name, in_date。"""
    notes: List[str] = []
    meta = None
    src_used = ""
    for src in ("SW2021", "SW2014"):
        try:
            meta = pro.index_classify(level="L1", src=src)
        except Exception as exc:
            notes.append(f"index_classify {src} 失败: {exc}")
            meta = None
        if meta is not None and not meta.empty and "index_code" in meta.columns:
            src_used = src
            break
    if meta is None or meta.empty or not src_used:
        return pd.DataFrame(columns=["symbol", "industry_code", "industry_name", "in_date"]), "", notes

    rows: List[pd.DataFrame] = []
    for record in meta.itertuples(index=False):
        code = str(getattr(record, "index_code", "") or "").strip()
        name = str(getattr(record, "industry_name", "") or "").strip()
        if not code:
            continue
        frame = _members_of_index(pro, code)
        time.sleep(sleep_sec)
        if frame is None or frame.empty:
            notes.append(f"{name or code} 无成分")
            continue
        piece = pd.DataFrame(
            {
                "symbol": frame["con_code"].map(symbol6) if "con_code" in frame.columns else frame["ts_code"].map(symbol6),
                "industry_code": code,
                "industry_name": name,
                "in_date": frame["in_date"].astype(str) if "in_date" in frame.columns else "",
            }
        )
        rows.append(piece)
    if not rows:
        return pd.DataFrame(columns=["symbol", "industry_code", "industry_name", "in_date"]), src_used, notes
    out = pd.concat(rows, ignore_index=True)
    out = out[out["symbol"] != ""].reset_index(drop=True)
    return out, src_used, notes


def _members_of_index(pro: Any, index_code: str) -> pd.DataFrame:
    loaders = (
        lambda: pro.index_member(index_code=index_code, is_new="Y"),
        lambda: pro.index_member_all(l1_code=index_code, is_new="Y"),
    )
    for loader in loaders:
        try:
            frame = loader()
        except Exception:
            frame = None
        if frame is None or frame.empty:
            continue
        work = frame.copy()
        if "is_new" in work.columns:
            fresh = work[work["is_new"].astype(str).str.upper() == "Y"]
            if not fresh.empty:
                work = fresh
        if "out_date" in work.columns:
            out = work["out_date"]
            current = work[out.isna() | (out.astype(str).str.strip().str.upper().isin({"", "NONE", "NAN", "NAT", "NULL"}))]
            if not current.empty:
                work = current
        if "con_code" not in work.columns and "ts_code" in work.columns:
            work = work.rename(columns={"ts_code": "con_code"})
        if "con_code" not in work.columns:
            continue
        return work
    return pd.DataFrame()


def fetch_total_mv(pro: Any, asof: str, *, max_back: int = 12) -> Tuple[pd.DataFrame, str]:
    """按截面日取全市场 total_mv（万元）。当日无数据则向前找交易日。"""
    end_dt = datetime.strptime(str(asof)[:10], "%Y-%m-%d")
    for i in range(max(1, int(max_back))):
        day = end_dt - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        stamp = day.strftime("%Y%m%d")
        try:
            frame = pro.daily_basic(trade_date=stamp, fields="ts_code,trade_date,total_mv")
        except Exception:
            frame = None
        if frame is None or frame.empty or "ts_code" not in frame.columns:
            continue
        out = pd.DataFrame(
            {
                "symbol": frame["ts_code"].map(symbol6),
                "total_mv": pd.to_numeric(frame["total_mv"], errors="coerce"),
            }
        )
        out = out[out["symbol"] != ""].reset_index(drop=True)
        if not out.empty:
            return out, day.strftime("%Y-%m-%d")
    return pd.DataFrame(columns=["symbol", "total_mv"]), ""
