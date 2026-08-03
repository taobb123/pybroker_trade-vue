# -*- coding: utf-8 -*-
from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence

import pandas as pd

from market_neutral.config import HEDGE_INDEX, ensure_sys_path


def get_tushare_pro():
    ensure_sys_path()
    from trend_pullback_chips import get_tushare_pro as _get

    return _get()


def _sleep(sec: float = 0.15) -> None:
    time.sleep(sec)


def fetch_stock_bars(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    sleep_sec: float = 0.12,
) -> Dict[str, pd.DataFrame]:
    """前复权 OHLCV + turnover_rate；key=6 位代码。"""
    ensure_sys_path()
    from fetch_vp_six_combo import fetch_bars_with_turnover

    out: Dict[str, pd.DataFrame] = {}
    n = len(symbols)
    for i, sym in enumerate(symbols):
        s = "".join(c for c in str(sym) if c.isdigit()).zfill(6)
        try:
            df = fetch_bars_with_turnover(s, start_date, end_date)
            if df is not None and not df.empty:
                d = df.copy()
                d["date"] = pd.to_datetime(d["date"]).dt.normalize()
                for c in ("open", "high", "low", "close", "volume", "turnover_rate"):
                    if c in d.columns:
                        d[c] = pd.to_numeric(d[c], errors="coerce")
                out[s] = d.sort_values("date").reset_index(drop=True)
        except Exception as exc:
            print(f"  [bars] {s} 跳过: {exc}", flush=True)
        if (i + 1) % 10 == 0 or i + 1 == n:
            print(f"  [bars] {i + 1}/{n}", flush=True)
        _sleep(sleep_sec)
    return out


def fetch_index_bars(
    start_date: str,
    end_date: str,
    ts_code: str = HEDGE_INDEX,
) -> pd.DataFrame:
    """指数日线（中证500 默认）。"""
    pro = get_tushare_pro()
    s = start_date.replace("-", "")
    e = end_date.replace("-", "")
    df = pro.index_daily(ts_code=ts_code, start_date=s, end_date=e)
    _sleep()
    if df is None or df.empty:
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
    d = df.copy()
    d["date"] = pd.to_datetime(d["trade_date"].astype(str))
    for c in ("open", "high", "low", "close", "vol"):
        if c in d.columns:
            d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d.rename(columns={"vol": "volume"})
    return (
        d[["date", "open", "high", "low", "close", "volume"]]
        .sort_values("date")
        .reset_index(drop=True)
    )


def fetch_daily_basic_panel(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    sleep_sec: float = 0.12,
) -> pd.DataFrame:
    """
    估值面板：pe_ttm / pb / close。
    返回长表 columns: date, symbol, pe_ttm, pb, close
    """
    ensure_sys_path()
    from backtest_sy_002028_threshold import six_digit_to_ts_code

    pro = get_tushare_pro()
    s = start_date.replace("-", "")
    e = end_date.replace("-", "")
    rows: List[pd.DataFrame] = []
    n = len(symbols)
    for i, sym in enumerate(symbols):
        code = "".join(c for c in str(sym) if c.isdigit()).zfill(6)
        ts_code = six_digit_to_ts_code(code)
        try:
            df = pro.daily_basic(
                ts_code=ts_code,
                start_date=s,
                end_date=e,
                fields="ts_code,trade_date,close,pe_ttm,pb",
            )
        except Exception as exc:
            print(f"  [basic] {code} 跳过: {exc}", flush=True)
            df = None
        if df is not None and not df.empty:
            d = df.copy()
            d["symbol"] = code
            d["date"] = pd.to_datetime(d["trade_date"].astype(str))
            d["pe_ttm"] = pd.to_numeric(d["pe_ttm"], errors="coerce")
            d["pb"] = pd.to_numeric(d["pb"], errors="coerce")
            d["close"] = pd.to_numeric(d["close"], errors="coerce")
            rows.append(d[["date", "symbol", "pe_ttm", "pb", "close"]])
        if (i + 1) % 10 == 0 or i + 1 == n:
            print(f"  [basic] {i + 1}/{n}", flush=True)
        _sleep(sleep_sec)
    if not rows:
        return pd.DataFrame(columns=["date", "symbol", "pe_ttm", "pb", "close"])
    return pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"])


def fetch_industry_map(symbols: Sequence[str]) -> Dict[str, str]:
    """stock_basic.industry → {symbol: industry}。"""
    ensure_sys_path()
    from backtest_sy_002028_threshold import six_digit_to_ts_code

    pro = get_tushare_pro()
    out: Dict[str, str] = {}
    # 一次拉全市场 industry，再过滤（比逐只快）
    try:
        basic = pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,industry,name")
        _sleep()
    except Exception:
        basic = None
    if basic is None or basic.empty:
        for sym in symbols:
            out["".join(c for c in str(sym) if c.isdigit()).zfill(6)] = "未知"
        return out
    basic = basic.copy()
    basic["symbol6"] = basic["symbol"].astype(str).str.zfill(6)
    want = {"".join(c for c in str(s) if c.isdigit()).zfill(6) for s in symbols}
    for _, r in basic.iterrows():
        sym = str(r["symbol6"])
        if sym in want:
            out[sym] = str(r.get("industry") or "未知")
    for sym in want:
        out.setdefault(sym, "未知")
    return out


def trading_calendar_from_index(index_df: pd.DataFrame) -> pd.DatetimeIndex:
    if index_df is None or index_df.empty:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(pd.to_datetime(index_df["date"]).dt.normalize().unique()).sort_values()


def rebalance_dates(
    calendar: pd.DatetimeIndex,
    start: str,
    end: str,
    freq: str = "weekly",
) -> List[pd.Timestamp]:
    """在交易日历上取周频（每周最后一个交易日）或月频。"""
    if calendar is None or len(calendar) == 0:
        return []
    s = pd.Timestamp(str(start)[:10])
    e = pd.Timestamp(str(end)[:10])
    cal = calendar[(calendar >= s) & (calendar <= e)]
    if len(cal) == 0:
        return []
    ser = pd.Series(cal, index=cal)
    if str(freq).lower().startswith("month"):
        picked = ser.groupby([cal.year, cal.month]).max()
    elif str(freq).lower().startswith("quarter"):
        qtr = ((cal.month - 1) // 3) + 1
        picked = ser.groupby([cal.year, qtr]).max()
    else:
        # ISO 周：每周最后一个交易日
        iso = cal.isocalendar()
        picked = ser.groupby([iso.year, iso.week]).max()
    dates = [pd.Timestamp(x).normalize() for x in picked.tolist()]
    dates = sorted({d for d in dates if s <= d <= e})
    return dates
