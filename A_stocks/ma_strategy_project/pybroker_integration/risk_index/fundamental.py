# -*- coding: utf-8 -*-
"""用年报序列和最新财务截面计算成长、盈利波动、杠杆和部分价值的原始描述变量。"""
from __future__ import annotations

import numpy as np
import pandas as pd


def apply_market_value(latest: pd.DataFrame, total_mv: pd.Series) -> pd.DataFrame:
    """用总市值（万元）把现金流和企业价值换成估值倍数。财务金额按元。"""
    if latest is None or latest.empty or total_mv is None or total_mv.empty:
        return latest
    out = latest.copy()
    mv = pd.to_numeric(total_mv, errors="coerce")
    mv.index = mv.index.astype(str).str[-6:].str.zfill(6)
    yuan = mv.reindex(out.index) * 10000.0
    cfo = pd.to_numeric(out["cfo"], errors="coerce") if "cfo" in out.columns else pd.Series(np.nan, index=out.index)
    ebitda = pd.to_numeric(out["ebitda"], errors="coerce") if "ebitda" in out.columns else pd.Series(np.nan, index=out.index)
    revenue = pd.to_numeric(out["revenue"], errors="coerce") if "revenue" in out.columns else pd.Series(np.nan, index=out.index)
    debt = pd.to_numeric(out["interest_debt"], errors="coerce") if "interest_debt" in out.columns else pd.Series(0.0, index=out.index)
    cash = pd.to_numeric(out["cash_hold"], errors="coerce") if "cash_hold" in out.columns else pd.Series(0.0, index=out.index)
    ev = yuan + debt.fillna(0.0) - cash.fillna(0.0)
    out["pcf"] = yuan / cfo.where(cfo > 0)
    out["ev_ebitda"] = ev / ebitda.where(ebitda > 0)
    out["ev_sales"] = ev / revenue.where(revenue > 0)
    return out


def fundamental_raw(latest: pd.DataFrame, annual: pd.DataFrame | None = None) -> pd.DataFrame:
    """latest 以 symbol 为索引。annual 列：symbol, year, revenue, net_profit, eps, roe, cfo, ebit, ebitda, interest, equity, debt, cash, assets, liab。"""
    if latest is None or latest.empty:
        base = pd.DataFrame()
    else:
        base = latest.copy()
        base.index = base.index.astype(str).str[-6:].str.zfill(6)
    history = _annual(annual)
    symbols = base.index.union(history.index.unique() if not history.empty else [])
    out = pd.DataFrame(index=pd.Index(symbols, name="symbol"))
    _copy_latest(out, base)
    if not history.empty:
        _from_history(out, history)
    return out


def _copy_latest(out: pd.DataFrame, base: pd.DataFrame) -> None:
    mapping = {
        "or_yoy": "营业收入同比",
        "netprofit_yoy": "净利润同比",
        "dt_netprofit_yoy": "扣非净利润同比",
        "basic_eps_yoy": "EPS同比",
        "roe_yoy": "ROE增长率",
        "op_yoy": "营业利润增长率",
        "pcf": "PCF",
        "ev_ebitda": "EV/EBITDA",
        "ev_sales": "EV/Sales",
        "debt_to_assets": "资产负债率",
        "interest_debt_ratio": "有息负债率",
        "net_debt_ebitda": "净负债/EBITDA",
        "debt_equity": "Debt/Equity",
        "interest_cover": "利息保障倍数",
        "ebitda_interest": "EBITDA/利息支出",
        "current_ratio": "流动比率",
        "quick_ratio": "速动比率",
        "interest_debt_to_liab": "有息负债/总负债",
    }
    for src, dest in mapping.items():
        if src in base.columns:
            out[dest] = pd.to_numeric(base[src], errors="coerce")


def _annual(frame: pd.DataFrame | None) -> pd.DataFrame:
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return pd.DataFrame()
    work = frame.copy()
    work["symbol"] = work["symbol"].astype(str).str[-6:].str.zfill(6)
    work["year"] = pd.to_numeric(work["year"], errors="coerce")
    work = work.dropna(subset=["symbol", "year"])
    work["year"] = work["year"].astype(int)
    return work.sort_values(["symbol", "year"])


def _from_history(out: pd.DataFrame, history: pd.DataFrame) -> None:
    for symbol, group in history.groupby("symbol", sort=False):
        group = group.drop_duplicates("year", keep="last").sort_values("year")
        out.loc[symbol, "营业收入3年CAGR"] = _cagr(group["revenue"] if "revenue" in group else None, 3)
        out.loc[symbol, "净利润3年CAGR"] = _cagr(group["net_profit"] if "net_profit" in group else None, 3)
        out.loc[symbol, "5年净利润标准差"] = _std_last(group, "net_profit", 5)
        out.loc[symbol, "3年净利润标准差"] = _std_last(group, "net_profit", 3)
        out.loc[symbol, "5年净利润增长率标准差"] = _growth_std(group, "net_profit", 5)
        out.loc[symbol, "3年净利润增长率标准差"] = _growth_std(group, "net_profit", 3)
        out.loc[symbol, "5年收入增长率标准差"] = _growth_std(group, "revenue", 5)
        out.loc[symbol, "3年EPS增长率标准差"] = _growth_std(group, "eps", 3)
        out.loc[symbol, "5年EPS增长率标准差"] = _growth_std(group, "eps", 5)
        out.loc[symbol, "ROE标准差"] = _std_last(group, "roe", 5)
        out.loc[symbol, "CFO增长率标准差"] = _growth_std(group, "cfo", 5)


def _cagr(values: pd.Series | None, years: int) -> float:
    if values is None:
        return np.nan
    number = pd.to_numeric(values, errors="coerce").dropna()
    if len(number) <= years:
        return np.nan
    start = float(number.iloc[-1 - years])
    end = float(number.iloc[-1])
    if start <= 0 or end <= 0:
        return np.nan
    return float((end / start) ** (1.0 / years) - 1.0)


def _std_last(group: pd.DataFrame, column: str, n: int) -> float:
    if column not in group.columns:
        return np.nan
    number = pd.to_numeric(group[column], errors="coerce").dropna()
    sample = number.iloc[-n:]
    if len(sample) < n:
        return np.nan
    return float(sample.std(ddof=0))


def _growth_std(group: pd.DataFrame, column: str, n: int) -> float:
    if column not in group.columns:
        return np.nan
    number = pd.to_numeric(group[column], errors="coerce").dropna()
    if len(number) < n + 1:
        return np.nan
    sample = number.iloc[-(n + 1) :]
    prev = sample.shift(1)
    growth = (sample - prev) / prev.abs()
    growth = growth.replace([np.inf, -np.inf], np.nan).dropna()
    if len(growth) < n:
        return np.nan
    return float(growth.iloc[-n:].std(ddof=0))
