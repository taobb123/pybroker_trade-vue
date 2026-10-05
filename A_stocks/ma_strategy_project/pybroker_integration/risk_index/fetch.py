# -*- coding: utf-8 -*-
"""拉取全市场日线、估值和财务，供风险指数标准化。"""
from __future__ import annotations

import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from industry_factor.build import symbol6

CACHE = Path(__file__).resolve().parent / "cache"
DAILY_DIR = CACHE / "daily"


def fetch_price_panel(pro: Any, asof: str, *, n_days: int = 260, sleep_sec: float = 0.12) -> tuple[pd.DataFrame, str]:
    """按交易日缓存全市场日线。返回 (panel, 实际截面日)。"""
    end = _open_day(pro, asof)
    dates = _trade_dates(pro, end, n_days)
    frames: list[pd.DataFrame] = []
    DAILY_DIR.mkdir(parents=True, exist_ok=True)
    for i, day in enumerate(dates):
        path = DAILY_DIR / f"{day}.csv"
        if path.is_file():
            frame = pd.read_csv(path, dtype={"symbol": str})
        else:
            frame = _one_day(pro, day)
            if frame.empty:
                continue
            frame.to_csv(path, index=False, encoding="utf-8-sig")
            time.sleep(sleep_sec)
        frames.append(frame)
        if (i + 1) % 40 == 0:
            print(f"  [risk] 日线 {i + 1}/{len(dates)}", flush=True)
    if not frames:
        return pd.DataFrame(columns=["symbol", "date", "close", "ret", "vol", "amount"]), ""
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    used = panel["date"].max().strftime("%Y-%m-%d")
    return panel, used


def fetch_daily_basic(pro: Any, asof: str) -> pd.DataFrame:
    end = datetime.strptime(asof[:10], "%Y-%m-%d")
    fields = "ts_code,trade_date,turnover_rate,pe_ttm,pb,ps_ttm,dv_ttm,circ_mv,total_mv"
    for i in range(12):
        day = end - timedelta(days=i)
        if day.weekday() >= 5:
            continue
        stamp = day.strftime("%Y%m%d")
        try:
            frame = pro.daily_basic(trade_date=stamp, fields=fields)
        except Exception:
            frame = None
        if frame is None or frame.empty:
            continue
        out = pd.DataFrame(
            {
                "symbol": frame["ts_code"].map(symbol6),
                "turnover_rate": pd.to_numeric(frame["turnover_rate"], errors="coerce"),
                "pe_ttm": pd.to_numeric(frame["pe_ttm"], errors="coerce"),
                "pb": pd.to_numeric(frame["pb"], errors="coerce"),
                "ps_ttm": pd.to_numeric(frame["ps_ttm"], errors="coerce"),
                "dv_ttm": pd.to_numeric(frame["dv_ttm"], errors="coerce"),
                "circ_mv": pd.to_numeric(frame["circ_mv"], errors="coerce"),
                "total_mv": pd.to_numeric(frame["total_mv"], errors="coerce"),
            }
        )
        return out[out["symbol"] != ""].drop_duplicates("symbol").set_index("symbol")
    return pd.DataFrame()


def fetch_hs300_ret60(pro: Any, asof: str) -> float | None:
    end = asof.replace("-", "")[:8]
    start = (pd.Timestamp(asof) - pd.Timedelta(days=160)).strftime("%Y%m%d")
    try:
        frame = pro.index_daily(ts_code="000300.SH", start_date=start, end_date=end)
    except Exception:
        return None
    if frame is None or frame.empty or "close" not in frame.columns:
        return None
    close = pd.to_numeric(frame.sort_values("trade_date")["close"], errors="coerce").dropna()
    if len(close) <= 60:
        return None
    return float(close.iloc[-1] / close.iloc[-61] - 1.0)


def fetch_fundamental(pro: Any) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """尝试财报 VIP。没有权限时返回空表，价格类指数仍可计算。"""
    notes: list[str] = []
    periods = ["20201231", "20211231", "20221231", "20231231", "20241231", "20251231"]
    annual_rows: list[pd.DataFrame] = []
    latest_parts: list[pd.DataFrame] = []
    for period in periods:
        income = _vip(pro, "income_vip", period, "ts_code,end_date,total_revenue,n_income_attr_p,operate_profit,fin_exp")
        fina = _vip(
            pro,
            "fina_indicator_vip",
            period,
            "ts_code,end_date,eps,roe,or_yoy,netprofit_yoy,dt_netprofit_yoy,basic_eps_yoy,roe_yoy,op_yoy,debt_to_assets,current_ratio,quick_ratio,ebit,ebitda,interestdebt",
        )
        cash = _vip(pro, "cashflow_vip", period, "ts_code,end_date,n_cashflow_act")
        balance = _vip(
            pro,
            "balancesheet_vip",
            period,
            "ts_code,end_date,total_assets,total_liab,st_borr,lt_borr,bond_payable,non_cur_liab_due_1y,money_cap,total_hldr_eqy_exc_min_int",
        )
        if all(item is None for item in (income, fina, cash, balance)):
            notes.append(f"{period} 财务 VIP 不可用")
            continue
        annual_rows.append(_annual_row(period, income, fina, cash, balance))
        latest_parts.append(_latest_row(income, fina, cash, balance))
        time.sleep(0.2)
    if not annual_rows:
        return pd.DataFrame(), pd.DataFrame(), notes or ["财务 VIP 无数据，成长、盈利波动、杠杆和 EV/PCF 未纳入"]
    annual = pd.concat(annual_rows, ignore_index=True)
    latest = pd.concat([p for p in latest_parts if p is not None and not p.empty], ignore_index=True)
    if latest.empty:
        return pd.DataFrame(), annual, notes
    latest = latest.sort_values("end_date").drop_duplicates("symbol", keep="last").set_index("symbol")
    return latest, annual, notes


def _vip(pro: Any, name: str, period: str, fields: str) -> pd.DataFrame | None:
    method = getattr(pro, name, None)
    if method is None:
        return None
    try:
        frame = method(period=period, fields=fields)
    except Exception:
        return None
    if frame is None or frame.empty:
        return None
    return frame


def _annual_row(period: str, income: pd.DataFrame | None, fina: pd.DataFrame | None, cash: pd.DataFrame | None, balance: pd.DataFrame | None) -> pd.DataFrame:
    year = int(period[:4])
    base = _symbol_frame(income if income is not None else fina if fina is not None else cash if cash is not None else balance)
    if base.empty:
        return pd.DataFrame(columns=["symbol", "year"])
    out = pd.DataFrame({"symbol": base["symbol"], "year": year})
    if income is not None:
        inc = _symbol_frame(income)
        out = out.merge(inc[["symbol", "total_revenue", "n_income_attr_p"]], on="symbol", how="left")
        out = out.rename(columns={"total_revenue": "revenue", "n_income_attr_p": "net_profit"})
    if fina is not None:
        fin = _symbol_frame(fina)
        keep = [c for c in ("symbol", "eps", "roe") if c in fin.columns]
        out = out.merge(fin[keep], on="symbol", how="left")
    if cash is not None:
        cf = _symbol_frame(cash).rename(columns={"n_cashflow_act": "cfo"})
        out = out.merge(cf[["symbol", "cfo"]], on="symbol", how="left")
    return out


def _latest_row(income, fina, cash, balance) -> pd.DataFrame:
    frames = [f for f in (income, fina, cash, balance) if f is not None and not f.empty]
    if not frames:
        return pd.DataFrame()
    merged = _symbol_frame(frames[0])
    for frame in frames[1:]:
        part = _symbol_frame(frame)
        cols = [c for c in part.columns if c == "symbol" or c not in merged.columns]
        merged = merged.merge(part[cols], on="symbol", how="outer")
    if "end_date" not in merged.columns:
        merged["end_date"] = ""
    debt = _interest_debt(merged)
    assets = _num(merged, "total_assets")
    liab = _num(merged, "total_liab")
    equity = _num(merged, "total_hldr_eqy_exc_min_int")
    cash_hold = _num(merged, "money_cap")
    ebitda = _num(merged, "ebitda")
    ebit = _num(merged, "ebit")
    interest = _num(merged, "fin_exp")
    revenue = _num(merged, "total_revenue")
    cfo = _num(merged, "n_cashflow_act")
    merged["interest_debt_ratio"] = debt / assets
    merged["interest_debt_to_liab"] = debt / liab
    merged["debt_equity"] = debt / equity
    merged["net_debt_ebitda"] = (debt - cash_hold) / ebitda
    merged["interest_cover"] = ebit / interest.where(interest > 0)
    merged["ebitda_interest"] = ebitda / interest.where(interest > 0)
    merged["cfo"] = cfo
    merged["ebitda"] = ebitda
    merged["revenue"] = revenue
    merged["interest_debt"] = debt
    merged["cash_hold"] = cash_hold
    return merged


def _num(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def _interest_debt(frame: pd.DataFrame) -> pd.Series:
    total = None
    for column in ("st_borr", "lt_borr", "bond_payable", "non_cur_liab_due_1y"):
        if column not in frame.columns:
            continue
        number = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
        total = number if total is None else total + number
    if total is None and "interestdebt" in frame.columns:
        return pd.to_numeric(frame["interestdebt"], errors="coerce")
    if total is None:
        return pd.Series(np.nan, index=frame.index)
    return total


def _symbol_frame(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(columns=["symbol"])
    out = frame.copy()
    key = "ts_code" if "ts_code" in out.columns else "symbol"
    out["symbol"] = out[key].map(symbol6)
    return out[out["symbol"] != ""]


def _one_day(pro: Any, day: str) -> pd.DataFrame:
    try:
        frame = pro.daily(trade_date=day, fields="ts_code,trade_date,close,pct_chg,vol,amount")
    except Exception:
        return pd.DataFrame()
    if frame is None or frame.empty:
        return pd.DataFrame()
    return pd.DataFrame(
        {
            "symbol": frame["ts_code"].map(symbol6),
            "date": pd.to_datetime(frame["trade_date"].astype(str)),
            "close": pd.to_numeric(frame["close"], errors="coerce"),
            "ret": pd.to_numeric(frame["pct_chg"], errors="coerce") / 100.0,
            "vol": pd.to_numeric(frame["vol"], errors="coerce"),
            "amount": pd.to_numeric(frame["amount"], errors="coerce"),
        }
    )


def _trade_dates(pro: Any, end: str, n_days: int) -> list[str]:
    start = (pd.Timestamp(end) - pd.Timedelta(days=int(n_days * 1.8) + 30)).strftime("%Y%m%d")
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end.replace("-", ""), is_open="1")
    except Exception:
        cal = None
    if cal is None or cal.empty or "cal_date" not in cal.columns:
        return []
    dates = sorted(cal["cal_date"].astype(str).tolist())
    return dates[-n_days:]


def _open_day(pro: Any, asof: str) -> str:
    end = asof.replace("-", "")[:8]
    start = (pd.Timestamp(asof) - pd.Timedelta(days=20)).strftime("%Y%m%d")
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end, is_open="1")
    except Exception:
        cal = None
    if cal is None or cal.empty:
        return end
    return str(sorted(cal["cal_date"].astype(str).tolist())[-1])
