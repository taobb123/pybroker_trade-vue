#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
质量成长 7 因子财务数据获取与评分模块

数据源优先级：Tushare Pro（付费）财务三表。
指标与权重：ROE 20%、自由现金流率 20%、收入增长 15%、利润增长 15%、
           毛利率 10%、ROA 10%、负债率 10%。
输出：Z-score 标准化后加权总分，排序取前 10% 股票代码。
"""

from __future__ import annotations

import os
import sys
import time
from typing import Optional, Dict, List, Tuple

import numpy as np
import pandas as pd

# 项目根目录（ma_strategy_project）
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# 7 因子权重（与文档一致）
WEIGHTS = {
    "roe": 0.20,
    "fcf_ratio": 0.20,
    "revenue_growth": 0.15,
    "profit_growth": 0.15,
    "gross_margin": 0.10,
    "roa": 0.10,
    "debt_ratio": 0.10,
}

NEGATIVE_INDICATORS = {"debt_ratio"}
CAGR_YEARS = 5


def _normalize_code(code: str) -> str:
    if not code or pd.isna(code):
        return ""
    s = str(code).strip().upper().replace("SZ", "").replace("SH", "").replace("sz", "").replace("sh", "")
    s = "".join(c for c in s if c.isdigit())
    return s.zfill(6) if len(s) <= 6 else s[:6]


def _to_ts_code(code: str) -> str:
    code = _normalize_code(code)
    if not code:
        return ""
    if code.startswith(("0", "3", "1")):
        return f"{code}.SZ"
    if code.startswith(("6", "5")):
        return f"{code}.SH"
    return f"{code}.SH"


def _find_col_by_keywords(df: pd.DataFrame, keywords: List[str]) -> Optional[str]:
    for col in df.columns:
        c = str(col).strip()
        for kw in keywords:
            if kw in c:
                return col
    return None


def _extract_numeric_series(df: pd.DataFrame, keywords: List[str]) -> pd.Series:
    col = _find_col_by_keywords(df, keywords)
    if col is None:
        return pd.Series(dtype=float)
    date_col = _find_col_by_keywords(df, ["报表日期", "报告期", "end_date", "date"])
    if date_col is not None:
        s = df.set_index(date_col)[col].copy()
    else:
        s = df[col].copy()
    s = pd.to_numeric(s, errors="coerce").dropna()
    if hasattr(s.index, "dtype") and (np.issubdtype(getattr(s.index, "dtype", None), np.integer) or s.index.dtype == np.int64):
        s = s.sort_index(ascending=False)
    return s


def _parse_sina_income(df: pd.DataFrame) -> Dict[str, pd.Series]:
    if df is None or df.empty:
        return {}
    return {
        "revenue": _extract_numeric_series(df, ["营业收入", "营业总收入", "revenue"]),
        "cogs": _extract_numeric_series(df, ["营业成本", "营业总成本", "oper_cost"]),
        "net_income": _extract_numeric_series(df, ["净利润", "归属母公司净利润", "n_income", "net_profit"]),
    }


def _parse_sina_cashflow(df: pd.DataFrame) -> Dict[str, pd.Series]:
    if df is None or df.empty:
        return {}
    return {
        "ocf": _extract_numeric_series(df, ["经营活动产生的现金流量净额", "经营活动现金流", "n_cashflow_act"]),
        "capex": _extract_numeric_series(df, ["购建固定资产", "资本开支", "c_pay_acq_const_fiolta"]),
    }


def _parse_sina_balance(df: pd.DataFrame) -> Dict[str, pd.Series]:
    if df is None or df.empty:
        return {}
    return {
        "total_assets": _extract_numeric_series(df, ["总资产", "资产总计", "total_assets"]),
        "total_liab": _extract_numeric_series(df, ["总负债", "负债合计", "total_liab"]),
        "equity": _extract_numeric_series(df, ["股东权益合计", "净资产", "所有者权益", "total_hldr_eqy", "net_assets"]),
    }


def get_three_sheets_akshare(symbol: str) -> Optional[Dict]:
    code = _normalize_code(symbol)
    if not code:
        return None
    try:
        import akshare as ak
    except ImportError:
        return None
    result = {}
    for name, symbol_cn in [("income", "利润表"), ("cashflow", "现金流量表"), ("balance", "资产负债表")]:
        try:
            df = ak.stock_financial_report_sina(stock=code, symbol=symbol_cn)
            if df is None or df.empty:
                return None
            result[name] = _parse_sina_income(df) if name == "income" else (_parse_sina_cashflow(df) if name == "cashflow" else _parse_sina_balance(df))
        except Exception:
            return None
    income = result.get("income", {})
    rev_s = income.get("revenue", pd.Series())
    ni_s = income.get("net_income", pd.Series())
    ta_s = result.get("balance", {}).get("total_assets", pd.Series())
    if (rev_s is None or rev_s.empty) and (ni_s is None or ni_s.empty):
        return None
    if ta_s is None or ta_s.empty:
        return None
    return result


def _get_tushare_token() -> str:
    try:
        from config.settings import DATA_CONFIG
        return (DATA_CONFIG or {}).get("tushare_token", "") or ""
    except Exception:
        return ""


def get_three_sheets_tushare(symbol: str, years: int = 6) -> Optional[Dict[str, pd.DataFrame]]:
    token = _get_tushare_token()
    if not token:
        return None
    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
    except Exception:
        return None
    ts_code = _to_ts_code(symbol)
    if not ts_code:
        return None
    end_date = time.strftime("%Y%m%d", time.localtime())
    start_date = f"{int(end_date[:4]) - years}0101"
    result = {}
    try:
        income = pro.income(ts_code=ts_code, start_date=start_date, end_date=end_date, report_type="1",
                           fields="end_date,revenue,oper_cost,n_income_attr_p,total_revenue")
        if income is None or income.empty:
            return None
        income["end_date"] = pd.to_datetime(income["end_date"], format="%Y%m%d", errors="coerce")
        income = income.dropna(subset=["end_date"]).sort_values("end_date", ascending=False)
        result["income"] = income

        balance = pro.balancesheet(ts_code=ts_code, start_date=start_date, end_date=end_date, report_type="1",
                                  fields="end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int")
        if balance is None or balance.empty:
            return None
        balance["end_date"] = pd.to_datetime(balance["end_date"], format="%Y%m%d", errors="coerce")
        balance = balance.dropna(subset=["end_date"]).sort_values("end_date", ascending=False)
        result["balance"] = balance

        cashflow = pro.cashflow(ts_code=ts_code, start_date=start_date, end_date=end_date, report_type="1",
                                fields="end_date,n_cashflow_act,c_pay_acq_const_fiolta,free_cashflow")
        if cashflow is None or cashflow.empty:
            return None
        cashflow["end_date"] = pd.to_datetime(cashflow["end_date"], format="%Y%m%d", errors="coerce")
        cashflow = cashflow.dropna(subset=["end_date"]).sort_values("end_date", ascending=False)
        result["cashflow"] = cashflow
    except Exception:
        return None
    return result


def _tushare_to_series(df: Optional[pd.DataFrame], col: str) -> pd.Series:
    if df is None or df.empty or col not in df.columns:
        return pd.Series(dtype=float)
    s = df.set_index("end_date")[col].copy()
    s = pd.to_numeric(s, errors="coerce").dropna().sort_index(ascending=False)
    return s


def get_three_sheets(symbol: str, use_tushare_fallback: bool = True) -> Tuple[Optional[Dict], str]:
    """
    单票调试用：仅使用 Tushare Pro 获取单只股票三表，并统一为 7 因子字段结构。
    实际批量计算时推荐使用 fetch_tushare_financial_bulk。
    """
    code = _normalize_code(symbol)
    if not code:
        return None, ""

    raw_ts = get_three_sheets_tushare(code)
    if raw_ts is None:
        return None, ""

    income = raw_ts.get("income")
    balance = raw_ts.get("balance")
    cashflow = raw_ts.get("cashflow")
    unified = {
        "income": {
            "revenue": _tushare_to_series(income, "revenue"),
            "cogs": _tushare_to_series(income, "oper_cost"),
            "net_income": _tushare_to_series(income, "n_income_attr_p"),
        },
        "cashflow": {
            "ocf": _tushare_to_series(cashflow, "n_cashflow_act"),
            "capex": _tushare_to_series(cashflow, "c_pay_acq_const_fiolta"),
        },
        "balance": {
            "total_assets": _tushare_to_series(balance, "total_assets"),
            "total_liab": _tushare_to_series(balance, "total_liab"),
            "equity": _tushare_to_series(balance, "total_hldr_eqy_exc_min_int"),
        },
    }
    return unified, "tushare"


def fetch_tushare_financial_bulk(
    symbols: List[str],
    years: int = CAGR_YEARS + 1,
) -> Dict[str, Dict]:
    """
    使用 Tushare VIP 接口 income_vip / balancesheet_vip / cashflow_vip
    按报告期批量拉取整市场三表，再过滤并按 symbol 拆分。
    返回 {symbol: raw_dict_for__raw_to_indicators}。
    """
    token = _get_tushare_token()
    if not token:
        return {}
    try:
        import tushare as ts

        ts.set_token(token)
        pro = ts.pro_api()
    except Exception:
        return {}

    # 规范化代码并构造 ts_code 映射
    sym_to_ts: Dict[str, str] = {}
    for sym in symbols:
        code = _normalize_code(sym)
        if not code:
            continue
        ts_code = _to_ts_code(code)
        if ts_code:
            sym_to_ts[sym] = ts_code
    if not sym_to_ts:
        return {}

    ts_set = set(sym_to_ts.values())

    # 最近若干年年报 period（YYYY1231）
    from datetime import datetime

    current_year = datetime.now().year
    periods = [f"{y}1231" for y in range(current_year, current_year - years, -1)]

    def _vip_concat(fetch_fn):
        dfs: List[pd.DataFrame] = []
        for p in periods:
            try:
                df = fetch_fn(p)
                if df is None or df.empty:
                    continue
                df = df[df["ts_code"].isin(ts_set)].copy()
                if not df.empty:
                    dfs.append(df)
            except Exception:
                continue
        if not dfs:
            return pd.DataFrame()
        df_all = pd.concat(dfs, ignore_index=True)
        if "end_date" in df_all.columns:
            df_all["end_date"] = pd.to_datetime(df_all["end_date"], format="%Y%m%d", errors="coerce")
            df_all = df_all.dropna(subset=["end_date"]).sort_values(["ts_code", "end_date"], ascending=False)
        return df_all

    # 批量拉取三表
    income_all = _vip_concat(
        lambda period: pro.income_vip(
            period=period,
            fields="ts_code,end_date,revenue,oper_cost,n_income_attr_p,total_revenue",
        )
    )
    balance_all = _vip_concat(
        lambda period: pro.balancesheet_vip(
            period=period,
            fields="ts_code,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int",
        )
    )
    cashflow_all = _vip_concat(
        lambda period: pro.cashflow_vip(
            period=period,
            fields="ts_code,end_date,n_cashflow_act,c_pay_acq_const_fiolta,free_cashflow",
        )
    )

    bulk: Dict[str, Dict] = {}
    for sym, ts_code in sym_to_ts.items():
        inc_sym = income_all[income_all["ts_code"] == ts_code] if not income_all.empty else pd.DataFrame()
        bal_sym = balance_all[balance_all["ts_code"] == ts_code] if not balance_all.empty else pd.DataFrame()
        cf_sym = cashflow_all[cashflow_all["ts_code"] == ts_code] if not cashflow_all.empty else pd.DataFrame()

        raw = {
            "income": {
                "revenue": _tushare_to_series(inc_sym, "revenue"),
                "cogs": _tushare_to_series(inc_sym, "oper_cost"),
                "net_income": _tushare_to_series(inc_sym, "n_income_attr_p"),
            },
            "cashflow": {
                "ocf": _tushare_to_series(cf_sym, "n_cashflow_act"),
                "capex": _tushare_to_series(cf_sym, "c_pay_acq_const_fiolta"),
            },
            "balance": {
                "total_assets": _tushare_to_series(bal_sym, "total_assets"),
                "total_liab": _tushare_to_series(bal_sym, "total_liab"),
                "equity": _tushare_to_series(bal_sym, "total_hldr_eqy_exc_min_int"),
            },
        }
        bulk[sym] = raw

    return bulk


def _year_end_only(s: pd.Series) -> pd.Series:
    if s.empty:
        return s
    idx = s.index
    try:
        if hasattr(idx, "month"):
            return s[idx.month == 12]
    except Exception:
        pass
    try:
        return s[[str(i).endswith("1231") or (hasattr(i, "month") and i.month == 12) for i in idx]]
    except Exception:
        pass
    return s


def _raw_to_indicators(raw: Dict, symbol: str) -> Dict[str, float]:
    out = {"roe": np.nan, "fcf_ratio": np.nan, "revenue_growth": np.nan, "profit_growth": np.nan,
           "gross_margin": np.nan, "roa": np.nan, "debt_ratio": np.nan}
    income = raw.get("income") or {}
    balance = raw.get("balance") or {}
    cashflow = raw.get("cashflow") or {}
    revenue = _year_end_only(income.get("revenue", pd.Series(dtype=float)))
    cogs = _year_end_only(income.get("cogs", pd.Series(dtype=float)))
    net_income = _year_end_only(income.get("net_income", pd.Series(dtype=float)))
    ocf = _year_end_only(cashflow.get("ocf", pd.Series(dtype=float)))
    capex = _year_end_only(cashflow.get("capex", pd.Series(dtype=float)))
    total_assets = _year_end_only(balance.get("total_assets", pd.Series(dtype=float)))
    total_liab = _year_end_only(balance.get("total_liab", pd.Series(dtype=float)))
    equity = _year_end_only(balance.get("equity", pd.Series(dtype=float)))

    if revenue.empty or net_income.empty or total_assets.empty:
        return out

    rev_latest = revenue.iloc[0]
    ni_latest = net_income.iloc[0]
    ta_latest = total_assets.iloc[0]
    tl_latest = total_liab.iloc[0] if not total_liab.empty else np.nan
    eq_latest = equity.iloc[0] if not equity.empty else np.nan

    if rev_latest and rev_latest != 0 and not cogs.empty:
        cogs_latest = cogs.iloc[0]
        if pd.notna(cogs_latest):
            out["gross_margin"] = (float(rev_latest) - float(cogs_latest)) / float(rev_latest) * 100

    if eq_latest and eq_latest != 0 and pd.notna(ni_latest):
        out["roe"] = float(ni_latest) / float(eq_latest) * 100
    if ta_latest and ta_latest != 0 and pd.notna(ni_latest):
        out["roa"] = float(ni_latest) / float(ta_latest) * 100
    if ta_latest and ta_latest != 0 and pd.notna(tl_latest):
        out["debt_ratio"] = float(tl_latest) / float(ta_latest) * 100

    if rev_latest and rev_latest != 0 and not ocf.empty:
        ocf_latest = ocf.iloc[0]
        capex_latest = capex.iloc[0] if not capex.empty else 0
        if pd.notna(ocf_latest):
            fcf = float(ocf_latest) - (float(capex_latest) if pd.notna(capex_latest) else 0)
            out["fcf_ratio"] = fcf / float(rev_latest) * 100

    n_years = min(CAGR_YEARS, len(revenue), len(net_income))
    if n_years >= 2:
        rev_0, rev_t = revenue.iloc[n_years - 1], revenue.iloc[0]
        if rev_0 and rev_0 > 0 and rev_t and rev_t > 0:
            out["revenue_growth"] = ((float(rev_t) / float(rev_0)) ** (1 / (n_years - 1)) - 1) * 100
        ni_0, ni_t = net_income.iloc[n_years - 1], net_income.iloc[0]
        if ni_0 and ni_0 > 0 and ni_t and ni_t > 0:
            out["profit_growth"] = ((float(ni_t) / float(ni_0)) ** (1 / (n_years - 1)) - 1) * 100

    return out


def build_quality_growth_scores(
    symbols: List[str],
    use_tushare_fallback: bool = True,
    min_valid_indicators: int = 4,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Dict[str, float]]]:
    # 批量通过 Tushare VIP 获取三表，按 symbol 拆分后计算 7 因子
    bulk_raw = fetch_tushare_financial_bulk(symbols, years=CAGR_YEARS + 1)
    rows = []
    for i, sym in enumerate(symbols):
        raw = bulk_raw.get(sym)
        if not raw:
            continue
        ind = _raw_to_indicators(raw, sym)
        valid = sum(1 for v in ind.values() if pd.notna(v) and np.isfinite(v))
        if valid < min_valid_indicators:
            continue
        rows.append({"symbol": sym, **ind})
        if (i + 1) % 50 == 0:
            print(f"  已处理 {i + 1}/{len(symbols)} 只股票（财务数据）...")

    if not rows:
        return pd.DataFrame(), [], {}

    df = pd.DataFrame(rows)
    factor_cols = ["roe", "fcf_ratio", "revenue_growth", "profit_growth", "gross_margin", "roa", "debt_ratio"]

    df_z = df.copy()
    for col in factor_cols:
        if col not in df_z.columns:
            continue
        mu, sigma = df_z[col].mean(), df_z[col].std()
        if sigma == 0 or not np.isfinite(sigma):
            df_z[col] = 0.0
        else:
            z = (df_z[col] - mu) / sigma
            if col in NEGATIVE_INDICATORS:
                z = -z
            df_z[col] = z.fillna(0)

    df_z["total_score"] = sum(df_z.get(c, 0) * WEIGHTS.get(c, 0) for c in factor_cols)
    df_z = df_z.sort_values("total_score", ascending=False).reset_index(drop=True)
    n = len(df_z)
    k = max(1, int(np.ceil(n * 0.1)))
    top_10_pct = df_z.head(k)["symbol"].tolist()

    factor_details = {}
    for _, r in df_z.iterrows():
        sym = r["symbol"]
        raw_row = df[df["symbol"] == sym].iloc[0] if sym in df["symbol"].values else r
        factor_details[sym] = {c: float(raw_row.get(c, np.nan)) for c in factor_cols if c in raw_row}
        factor_details[sym]["total_score"] = float(r["total_score"])

    return df_z, top_10_pct, factor_details
