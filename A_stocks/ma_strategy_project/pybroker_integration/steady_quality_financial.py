#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
稳健型高质量复利模型 - 四层评分模块

数据源：Tushare Pro 财务三表 + stock_basic(industry)。
四层结构：
  第一层 资产安全 25%：有息负债率(负向)、利息保障倍数、现金覆盖率、负债率趋势
  第二层 现金流质量 30%：FCF连续为正年数、OCF/NI、FCF波动率(负向)、FCF增长率
  第三层 盈利质量 30%：ROE、ROA、毛利率、毛利率_std(负向)、毛利率趋势
  第四层 运营效率 15%：存货周转率、存货增长-收入增长(负向)

指标缺失时用近似：利息费用用财务费用、EBIT用营业利润等。
行业用 stock_basic.industry，用于毛利率相对行业溢价（第三层可选）。
输出：各层得分 + 总分，排序取前 10%。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import numpy as np
import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# 工作流 PYTHONPATH 会把 pybroker_integration 放在前面，必须把 ma_strategy_project 顶到最前，
# 否则 `import config` 会命中本目录的 config 包，读不到上级 config/settings.py。
if _PROJECT_ROOT in sys.path:
    sys.path.remove(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)

YEARS = 6  # 拉取年数（含 5 年年报 + 1 年缓冲）

# 第一层 资产安全 25%
LAYER1_WEIGHTS = {
    "interest_bearing_debt_ratio": 0.25,   # 有息负债率，负向
    "interest_coverage": 0.35,             # 利息保障倍数
    "cash_coverage": 0.25,                 # 现金覆盖率
    "debt_ratio_trend": 0.15,              # 负债率趋势（斜率负向，即负债下降为正）
}
# 第二层 现金流质量 30%
LAYER2_WEIGHTS = {
    "fcf_positive_years": 0.30,            # FCF 连续为正年数
    "ocf_ni_ratio": 0.30,                  # OCF/NI
    "fcf_volatility": 0.20,                 # FCF 波动率，负向
    "fcf_growth": 0.20,                     # FCF 增长率
}
# 第三层 盈利质量 30%
LAYER3_WEIGHTS = {
    "roe": 0.25,
    "roa": 0.20,
    "gross_margin": 0.20,
    "gross_margin_std_5y": 0.15,            # 负向
    "gross_margin_trend": 0.20,             # 毛利率趋势斜率
}
# 第四层 运营效率 15%
LAYER4_WEIGHTS = {
    "inventory_turnover": 0.55,
    "inventory_minus_revenue_growth": 0.45,  # 负向
}

NEGATIVE_INDICATORS = {
    "interest_bearing_debt_ratio", "fcf_volatility", "gross_margin_std_5y",
    "inventory_minus_revenue_growth"
}
# 负债率趋势：斜率负向（负债率下降为好事）
DEBT_TREND_NEGATIVE = True


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


def _token_from_settings_file(path: Path) -> str:
    """按文件路径加载 DATA_CONFIG，避开 pybroker_integration/config 包遮挡。"""
    if not path.is_file():
        return ""
    try:
        spec = importlib.util.spec_from_file_location("_steady_quality_settings", path)
        if spec is None or spec.loader is None:
            return ""
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        cfg = getattr(mod, "DATA_CONFIG", None) or {}
        return str(cfg.get("tushare_token") or "").strip()
    except Exception:
        return ""


def _resolve_tushare_token() -> Tuple[str, str]:
    env = (os.getenv("TUSHARE_TOKEN") or "").strip()
    if env:
        return env, "TUSHARE_TOKEN"
    script_dir = Path(__file__).resolve().parent
    candidates = (
        (Path(_PROJECT_ROOT) / "config" / "settings.py", "ma_strategy_project/config/settings.py"),
        (script_dir / "config" / "settings.py", "pybroker_integration/config/settings.py"),
    )
    for path, label in candidates:
        tok = _token_from_settings_file(path)
        if tok:
            return tok, label
    return "", "missing"


def _get_tushare_token() -> str:
    token, _src = _resolve_tushare_token()
    return token


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


def _prepare_stmt(df: Optional[pd.DataFrame]) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "end_date" not in out.columns:
        return out
    parsed = pd.to_datetime(out["end_date"], errors="coerce")
    if parsed.isna().all():
        parsed = pd.to_datetime(out["end_date"], format="%Y%m%d", errors="coerce")
    out["end_date"] = parsed
    out = out.dropna(subset=["end_date"])
    subset = ["ts_code", "end_date"] if "ts_code" in out.columns else ["end_date"]
    out = out.drop_duplicates(subset=subset, keep="first")
    return out.sort_values("end_date", ascending=False)


def _tushare_to_series(df: Optional[pd.DataFrame], col: str) -> pd.Series:
    work = _prepare_stmt(df)
    if work.empty or col not in work.columns:
        return pd.Series(dtype=float)
    s = work.set_index("end_date")[col].copy()
    s = pd.to_numeric(s, errors="coerce").dropna()
    s = s[~s.index.duplicated(keep="first")].sort_index(ascending=False)
    return s


def _call_with_fields(fetch_fn, field_sets: List[str], **kwargs):
    """字段无权限时整表会空/抛错，从完整字段集回退到最小字段集。"""
    last_err: Optional[Exception] = None
    for fields in field_sets:
        try:
            df = fetch_fn(fields=fields, **kwargs)
            if df is not None and not getattr(df, "empty", True):
                return df
        except Exception as exc:
            last_err = exc
            continue
    if last_err and not field_sets:
        raise last_err
    return pd.DataFrame()


_INCOME_FIELDS = [
    "ts_code,end_date,revenue,oper_cost,n_income_attr_p,total_revenue,operate_profit,ebit,int_exp,fin_exp",
    "ts_code,end_date,revenue,oper_cost,n_income_attr_p,operate_profit,fin_exp",
    "ts_code,end_date,revenue,oper_cost,n_income_attr_p",
]
_BALANCE_FIELDS = [
    "ts_code,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int,money_cap,trad_asset,st_borr,lt_borr,bond_payable,inventories",
    "ts_code,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int,inventories",
    "ts_code,end_date,total_assets,total_liab,total_hldr_eqy_exc_min_int",
]
_CASHFLOW_FIELDS = [
    "ts_code,end_date,n_cashflow_act,c_pay_acq_const_fiolta,free_cashflow,net_profit",
    "ts_code,end_date,n_cashflow_act,c_pay_acq_const_fiolta,net_profit",
    "ts_code,end_date,n_cashflow_act,c_pay_acq_const_fiolta",
]


def _annual_periods(years: int) -> List[str]:
    now = datetime.now()
    # 当年年报尚未发布，VIP period=YYYY1231 会空；从最近已结束会计年度开始。
    last_year = now.year if now.month >= 12 else now.year - 1
    return [f"{y}1231" for y in range(last_year, last_year - years, -1)]


def _raw_from_stmts(inc, bal, cf) -> Dict:
    return {
        "income": {
            "revenue": _tushare_to_series(inc, "revenue"),
            "cogs": _tushare_to_series(inc, "oper_cost"),
            "net_income": _tushare_to_series(inc, "n_income_attr_p"),
            "operate_profit": _tushare_to_series(inc, "operate_profit"),
            "ebit": _tushare_to_series(inc, "ebit"),
            "int_exp": _tushare_to_series(inc, "int_exp"),
            "fin_exp": _tushare_to_series(inc, "fin_exp"),
        },
        "cashflow": {
            "ocf": _tushare_to_series(cf, "n_cashflow_act"),
            "capex": _tushare_to_series(cf, "c_pay_acq_const_fiolta"),
            "free_cashflow": _tushare_to_series(cf, "free_cashflow"),
            "net_profit": _tushare_to_series(cf, "net_profit"),
        },
        "balance": {
            "total_assets": _tushare_to_series(bal, "total_assets"),
            "total_liab": _tushare_to_series(bal, "total_liab"),
            "equity": _tushare_to_series(bal, "total_hldr_eqy_exc_min_int"),
            "money_cap": _tushare_to_series(bal, "money_cap"),
            "trad_asset": _tushare_to_series(bal, "trad_asset"),
            "st_borr": _tushare_to_series(bal, "st_borr"),
            "lt_borr": _tushare_to_series(bal, "lt_borr"),
            "bond_payable": _tushare_to_series(bal, "bond_payable"),
            "inventories": _tushare_to_series(bal, "inventories"),
        },
    }


def _linear_slope(y: np.ndarray) -> float:
    """线性回归斜率。y 为时间序列（从旧到新或从新到旧均可，按索引顺序）。"""
    if len(y) < 2 or np.all(np.isnan(y)) or not np.any(np.isfinite(y)):
        return np.nan
    x = np.arange(len(y), dtype=float)
    mask = np.isfinite(y)
    if np.sum(mask) < 2:
        return np.nan
    x, y = x[mask], y[mask]
    xm, ym = x.mean(), y.mean()
    den = np.sum((x - xm) ** 2)
    if den == 0:
        return np.nan
    return float(np.sum((x - xm) * (y - ym)) / den)


def fetch_tushare_bulk(
    symbols: List[str],
    years: int = YEARS,
) -> Dict[str, Dict]:
    """拉取 Tushare 三表（扩展字段）+ 年报过滤，按 symbol 拆分。"""
    token, token_src = _resolve_tushare_token()
    if not token:
        print("  未找到 Tushare token：请检查 ma_strategy_project/config/settings.py 或环境变量 TUSHARE_TOKEN")
        print("  （工作流 PYTHONPATH 会让 pybroker_integration/config 挡住 config.settings，已改为按文件路径读取）")
        return {}
    print(f"  Tushare token 已配置（来源 {token_src}，长度 {len(token)}）")
    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
    except Exception as exc:
        print(f"  初始化 Tushare 失败: {exc}")
        return {}

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
    periods = _annual_periods(years)
    now = datetime.now()
    end_date = f"{now.year}1231"
    start_date = f"{now.year - years}0101"

    def _vip_concat(api_fn, field_sets: List[str], name: str = ""):
        dfs: List[pd.DataFrame] = []
        for p in periods:
            df = _call_with_fields(api_fn, field_sets, period=p)
            if df is None or df.empty:
                continue
            if "ts_code" not in df.columns:
                continue
            df = df[df["ts_code"].isin(ts_set)].copy()
            if not df.empty:
                dfs.append(df)
        if not dfs:
            return pd.DataFrame()
        return _prepare_stmt(pd.concat(dfs, ignore_index=True))

    diag_period = periods[0]
    try:
        diag = _call_with_fields(
            pro.income_vip,
            ["ts_code,end_date,revenue"],
            period=diag_period,
        )
        if diag is None or diag.empty:
            print(f"  诊断: income_vip(period={diag_period}) 返回空，将回退非 VIP 单只接口")
        else:
            in_ts = diag[diag["ts_code"].isin(ts_set)] if "ts_code" in diag.columns else diag.iloc[0:0]
            print(f"  诊断: income_vip(period={diag_period}) 全市场 {len(diag)} 行，股票池匹配 {len(in_ts)} 行")
    except Exception as e:
        print(f"  诊断: income_vip 调用异常: {e}")

    income_all = _vip_concat(pro.income_vip, _INCOME_FIELDS, "income_vip")
    balance_all = _vip_concat(pro.balancesheet_vip, _BALANCE_FIELDS, "balancesheet_vip")
    cashflow_all = _vip_concat(pro.cashflow_vip, _CASHFLOW_FIELDS, "cashflow_vip")

    bulk: Dict[str, Dict] = {}
    if not (income_all.empty and balance_all.empty and cashflow_all.empty):
        for sym, ts_code in sym_to_ts.items():
            inc_sym = income_all[income_all["ts_code"] == ts_code] if not income_all.empty else pd.DataFrame()
            bal_sym = balance_all[balance_all["ts_code"] == ts_code] if not balance_all.empty else pd.DataFrame()
            cf_sym = cashflow_all[cashflow_all["ts_code"] == ts_code] if not cashflow_all.empty else pd.DataFrame()
            bulk[sym] = _raw_from_stmts(inc_sym, bal_sym, cf_sym)
        n_ok = sum(1 for raw in bulk.values() if not raw["income"]["revenue"].empty)
        print(f"  VIP 三表拆分完成，收入序列非空 {n_ok}/{len(bulk)} 只")
        if n_ok > 0:
            return bulk

    print("  Tushare VIP 三表不可用或股票池未匹配，尝试按单只拉取（非 VIP 接口）...")
    bulk_fallback: Dict[str, Dict] = {}
    for i, (sym, ts_code) in enumerate(sym_to_ts.items()):
        inc = _call_with_fields(
            pro.income, list(reversed(_INCOME_FIELDS)),
            ts_code=ts_code, start_date=start_date, end_date=end_date, report_type="1",
        )
        bal = _call_with_fields(
            pro.balancesheet, list(reversed(_BALANCE_FIELDS)),
            ts_code=ts_code, start_date=start_date, end_date=end_date, report_type="1",
        )
        cf = _call_with_fields(
            pro.cashflow, list(reversed(_CASHFLOW_FIELDS)),
            ts_code=ts_code, start_date=start_date, end_date=end_date, report_type="1",
        )
        if (inc is None or inc.empty) and (bal is None or bal.empty):
            time.sleep(0.12)
            continue
        bulk_fallback[sym] = _raw_from_stmts(inc, bal, cf)
        if (i + 1) % 10 == 0:
            print(f"    已拉取 {i + 1}/{len(sym_to_ts)} 只...")
        time.sleep(0.12)
    if not bulk_fallback:
        print("  按单只拉取仍无数据，请检查 Tushare token、积分权限或网络")
        return {}
    print(f"  按单只拉取成功 {len(bulk_fallback)} 只")
    return bulk_fallback


def get_industry_and_gross_margin_by_symbol(
    symbols: List[str],
    symbol_gross_margin: Dict[str, float],
) -> Tuple[Dict[str, str], Dict[str, float]]:
    """获取每只股票的 industry（stock_basic.industry），并计算各行业平均毛利率。"""
    industries: Dict[str, str] = {s: "" for s in symbols}
    industry_avg_gm: Dict[str, float] = {}
    token = _get_tushare_token()
    if not token:
        return industries, industry_avg_gm
    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,industry")
        if df is None or df.empty:
            return industries, industry_avg_gm
        code_to_ind: Dict[str, str] = {}
        for _, row in df.iterrows():
            ts_code = row["ts_code"]
            code = str(ts_code).split(".")[0]
            ind = (row.get("industry") or "") if pd.notna(row.get("industry")) else ""
            code_to_ind[code] = ind
            code_to_ind[ts_code] = ind
        for sym in symbols:
            code = _normalize_code(sym)
            industries[sym] = code_to_ind.get(code, "") or code_to_ind.get(sym, "")

        # 行业平均毛利率
        ind_gms: Dict[str, List[float]] = {}
        for sym, gm in symbol_gross_margin.items():
            if not np.isfinite(gm) or pd.isna(gm):
                continue
            ind = industries.get(sym, "")
            if not ind:
                continue
            ind_gms.setdefault(ind, []).append(float(gm))
        for ind, gms in ind_gms.items():
            if gms:
                industry_avg_gm[ind] = float(np.nanmean(gms))
    except Exception:
        pass
    return industries, industry_avg_gm


def _raw_to_steady_indicators(
    raw: Dict,
    symbol: str,
    industry: str,
    industry_avg_gm: float,
) -> Dict[str, float]:
    """从原始三表计算四层所需全部指标。缺失用近似。"""
    out: Dict[str, float] = {}
    income = raw.get("income") or {}
    balance = raw.get("balance") or {}
    cashflow = raw.get("cashflow") or {}

    rev = _year_end_only(income.get("revenue", pd.Series(dtype=float)))
    cogs = _year_end_only(income.get("cogs", pd.Series(dtype=float)))
    ni = _year_end_only(income.get("net_income", pd.Series(dtype=float)))
    oprofit = _year_end_only(income.get("operate_profit", pd.Series(dtype=float)))
    ebit_s = _year_end_only(income.get("ebit", pd.Series(dtype=float)))
    int_exp_s = _year_end_only(income.get("int_exp", pd.Series(dtype=float)))
    fin_exp_s = _year_end_only(income.get("fin_exp", pd.Series(dtype=float)))

    ocf = _year_end_only(cashflow.get("ocf", pd.Series(dtype=float)))
    capex = _year_end_only(cashflow.get("capex", pd.Series(dtype=float)))
    fcf_ts = _year_end_only(cashflow.get("free_cashflow", pd.Series(dtype=float)))
    cf_net_profit = _year_end_only(cashflow.get("net_profit", pd.Series(dtype=float)))

    ta = _year_end_only(balance.get("total_assets", pd.Series(dtype=float)))
    tl = _year_end_only(balance.get("total_liab", pd.Series(dtype=float)))
    eq = _year_end_only(balance.get("equity", pd.Series(dtype=float)))
    money_cap = _year_end_only(balance.get("money_cap", pd.Series(dtype=float)))
    trad_asset = _year_end_only(balance.get("trad_asset", pd.Series(dtype=float)))
    st_borr = _year_end_only(balance.get("st_borr", pd.Series(dtype=float)))
    lt_borr = _year_end_only(balance.get("lt_borr", pd.Series(dtype=float)))
    bond_payable = _year_end_only(balance.get("bond_payable", pd.Series(dtype=float)))
    inv = _year_end_only(balance.get("inventories", pd.Series(dtype=float)))

    if rev.empty or ni.empty or ta.empty:
        return out

    n = min(5, len(rev), len(ni), len(ta))
    if n < 2:
        return out

    rev_l = rev.iloc[0]
    ni_l = ni.iloc[0]
    ta_l = ta.iloc[0]
    tl_l = tl.iloc[0] if not tl.empty else 0.0
    eq_l = eq.iloc[0] if not eq.empty else np.nan
    cogs_l = cogs.iloc[0] if not cogs.empty else np.nan

    # 有息负债 = 短期借款 + 长期借款 + 应付债券
    def _get(s: pd.Series, i: int = 0) -> float:
        if s is None or s.empty or i >= len(s):
            return 0.0
        v = s.iloc[i]
        return float(v) if pd.notna(v) and np.isfinite(v) else 0.0

    ib_debt_l = _get(st_borr) + _get(lt_borr) + _get(bond_payable)
    cash_l = _get(money_cap) + _get(trad_asset)
    inv_l = _get(inv)

    # 利息费用：优先 int_exp，否则 fin_exp
    int_exp_l = _get(int_exp_s) if not int_exp_s.empty else _get(fin_exp_s)
    if int_exp_l == 0 or not np.isfinite(int_exp_l):
        int_exp_l = _get(fin_exp_s)
    ebit_l = _get(ebit_s) if not ebit_s.empty else np.nan
    if not np.isfinite(ebit_l) or ebit_l == 0:
        ebit_l = _get(oprofit)

    # ---------- 第一层 ----------
    if ta_l and ta_l > 0:
        out["interest_bearing_debt_ratio"] = (ib_debt_l / float(ta_l)) * 100
    else:
        out["interest_bearing_debt_ratio"] = np.nan
    if int_exp_l and int_exp_l > 0 and np.isfinite(ebit_l):
        out["interest_coverage"] = float(ebit_l) / int_exp_l
    else:
        out["interest_coverage"] = np.nan
    if ib_debt_l > 0 and np.isfinite(cash_l):
        out["cash_coverage"] = cash_l / ib_debt_l
    else:
        out["cash_coverage"] = np.nan
    # 去重索引（同一报告期可能有多条如 PIT 修正），避免 reindex 报 duplicate labels
    ta = ta[~ta.index.duplicated(keep="first")]
    tl = tl[~tl.index.duplicated(keep="first")]
    common_idx = ta.index.intersection(tl.index)
    debt_ratio_series = (tl.reindex(common_idx).fillna(0) / ta.reindex(common_idx).replace(0, np.nan)).replace([np.inf, -np.inf], np.nan).dropna()
    if len(debt_ratio_series) >= 2:
        dr_arr = debt_ratio_series.iloc[:5].values.astype(float)[::-1]
        out["debt_ratio_trend"] = _linear_slope(dr_arr)
        if DEBT_TREND_NEGATIVE and np.isfinite(out["debt_ratio_trend"]):
            out["debt_ratio_trend"] = -out["debt_ratio_trend"]
    else:
        out["debt_ratio_trend"] = np.nan

    # ---------- 第二层 ----------
    fcf_series = fcf_ts if not fcf_ts.empty else (ocf - capex).reindex(ocf.index).dropna()
    if fcf_series.empty and not ocf.empty and not capex.empty:
        fcf_series = (ocf - capex).reindex(ocf.index).dropna()
    fcf_arr = _year_end_only(fcf_series)
    if not fcf_arr.empty:
        fcf_arr = fcf_arr.iloc[:5]
        out["fcf_positive_years"] = float(np.sum(fcf_arr > 0))
        if len(fcf_arr) >= 2:
            mean_fcf = np.nanmean(fcf_arr.values)
            if mean_fcf and np.isfinite(mean_fcf) and mean_fcf != 0:
                std_fcf = np.nanstd(fcf_arr.values)
                out["fcf_volatility"] = (std_fcf / abs(mean_fcf)) * 100 if std_fcf and np.isfinite(std_fcf) else np.nan
            else:
                out["fcf_volatility"] = np.nan
            g0, g1 = fcf_arr.iloc[-1], fcf_arr.iloc[0]
            if g0 and g0 > 0 and g1 and np.isfinite(g1):
                out["fcf_growth"] = ((float(g1) / float(g0)) - 1) * 100
            else:
                out["fcf_growth"] = np.nan
        else:
            out["fcf_volatility"] = np.nan
            out["fcf_growth"] = np.nan
    else:
        out["fcf_positive_years"] = np.nan
        out["fcf_volatility"] = np.nan
        out["fcf_growth"] = np.nan

    ni_for_ocf = ni
    if not cf_net_profit.empty:
        ni_for_ocf = cf_net_profit
    if not ocf.empty and not ni_for_ocf.empty:
        ocf_l = ocf.iloc[0]
        ni_ocf_l = ni_for_ocf.iloc[0]
        if ni_ocf_l and np.isfinite(ni_ocf_l) and ni_ocf_l != 0 and np.isfinite(ocf_l):
            out["ocf_ni_ratio"] = float(ocf_l) / float(ni_ocf_l)
        else:
            out["ocf_ni_ratio"] = np.nan
    else:
        out["ocf_ni_ratio"] = np.nan

    # ---------- 第三层 ----------
    if eq_l and eq_l != 0 and np.isfinite(ni_l):
        out["roe"] = (float(ni_l) / float(eq_l)) * 100
    else:
        out["roe"] = np.nan
    if ta_l and ta_l != 0 and np.isfinite(ni_l):
        out["roa"] = (float(ni_l) / float(ta_l)) * 100
    else:
        out["roa"] = np.nan
    if rev_l and rev_l != 0 and np.isfinite(cogs_l):
        out["gross_margin"] = (float(rev_l) - float(cogs_l)) / float(rev_l) * 100
    else:
        out["gross_margin"] = np.nan
    gm_series = (rev - cogs) / rev.replace(0, np.nan) * 100
    gm_series = _year_end_only(gm_series).iloc[:5]
    if len(gm_series) >= 2:
        out["gross_margin_std_5y"] = float(np.nanstd(gm_series.values))
        out["gross_margin_trend"] = _linear_slope(gm_series.values.astype(float))
    else:
        out["gross_margin_std_5y"] = np.nan
        out["gross_margin_trend"] = np.nan
    if np.isfinite(out.get("gross_margin")) and np.isfinite(industry_avg_gm):
        out["gross_margin_vs_industry"] = out["gross_margin"] - industry_avg_gm
    else:
        out["gross_margin_vs_industry"] = np.nan

    # ---------- 第四层 ----------
    cogs_series = _year_end_only(cogs).iloc[:5]
    inv_series = _year_end_only(inv).iloc[:5]
    rev_series = _year_end_only(rev).iloc[:5]
    if not inv_series.empty and len(inv_series) >= 1 and inv_l and inv_l > 0:
        if len(inv_series) >= 2:
            inv_prev = inv_series.iloc[1] if len(inv_series) > 1 else inv_l
            avg_inv = (float(inv_l) + float(inv_prev)) / 2
        else:
            avg_inv = float(inv_l)
        cogs_0 = cogs_series.iloc[0] if not cogs_series.empty else np.nan
        if avg_inv and np.isfinite(cogs_0) and cogs_0 and cogs_0 > 0:
            out["inventory_turnover"] = float(cogs_0) / avg_inv
        else:
            out["inventory_turnover"] = np.nan
    else:
        out["inventory_turnover"] = np.nan
    if len(rev_series) >= 2 and len(inv_series) >= 2:
        r0, r1 = rev_series.iloc[-1], rev_series.iloc[0]
        i0, i1 = inv_series.iloc[-1], inv_series.iloc[0]
        if r0 and r0 > 0 and r1 and r1 > 0 and i0 and i0 > 0 and i1 and i1 > 0:
            rev_cagr = ((float(r1) / float(r0)) ** (1 / (len(rev_series) - 1)) - 1) * 100
            inv_cagr = ((float(i1) / float(i0)) ** (1 / (len(inv_series) - 1)) - 1) * 100
            out["inventory_minus_revenue_growth"] = inv_cagr - rev_cagr
        else:
            out["inventory_minus_revenue_growth"] = np.nan
    else:
        out["inventory_minus_revenue_growth"] = np.nan

    return out


def _layer_score(
    df: pd.DataFrame,
    cols: List[str],
    weights: Dict[str, float],
    negative: set,
) -> pd.Series:
    """对指定列做 Z-score 标准化后加权得分。"""
    s = pd.Series(0.0, index=df.index)
    total_w = sum(weights.values())
    if total_w <= 0:
        return s
    for col in cols:
        if col not in df.columns or col not in weights:
            continue
        w = weights[col] / total_w
        mu, sigma = df[col].mean(), df[col].std()
        if sigma == 0 or not np.isfinite(sigma):
            z = pd.Series(0.0, index=df.index)
        else:
            z = (df[col] - mu) / sigma
            if col in negative:
                z = -z
            z = z.fillna(0)
        s = s + w * z
    return s


def build_steady_quality_scores(
    symbols: List[str],
    min_valid_indicators: int = 5,
) -> Tuple[pd.DataFrame, List[str], Dict[str, Dict]]:
    """
    计算四层稳健高质量得分，返回 (df_scores, top_10_pct_list, factor_details)。
    factor_details[symbol] 含：各原始指标、layer1_score~layer4_score、total_score。
    """
    bulk = fetch_tushare_bulk(symbols, years=YEARS)
    n_bulk = len([s for s in symbols if bulk.get(s)])
    rows: List[Dict] = []
    for sym in symbols:
        raw = bulk.get(sym)
        if not raw:
            continue
        ind = _raw_to_steady_indicators(raw, sym, "", np.nan)
        valid = sum(1 for v in ind.values() if pd.notna(v) and np.isfinite(v))
        if valid < min_valid_indicators:
            continue
        rows.append({"symbol": sym, **ind})
    # 若严格按 min_valid_indicators 无股票通过，则放宽一档重试一次并打日志
    if not rows and n_bulk > 0 and min_valid_indicators >= 4:
        fallback = min_valid_indicators - 1
        for sym in symbols:
            raw = bulk.get(sym)
            if not raw:
                continue
            ind = _raw_to_steady_indicators(raw, sym, "", np.nan)
            valid = sum(1 for v in ind.values() if pd.notna(v) and np.isfinite(v))
            if valid < fallback:
                continue
            rows.append({"symbol": sym, **ind})
        if rows:
            print(f"  有效指标>={min_valid_indicators} 的 0 只，已放宽为 >={fallback} 后通过 {len(rows)} 只")
    if not rows:
        if n_bulk == 0:
            print("  未获取到任何股票财务数据，请检查 Tushare token 或 VIP 权限")
        else:
            print(f"  获取到 {n_bulk} 只财务数据，但有效指标数均不足 {min_valid_indicators}，请检查接口字段或放宽 min_valid_indicators")
        return pd.DataFrame(), [], {}

    print(f"  获取到 {n_bulk} 只财务数据，有效指标>={min_valid_indicators} 的 {len(rows)} 只进入评分")
    df = pd.DataFrame(rows)
    symbol_gm = df.set_index("symbol")["gross_margin"].to_dict()
    industries, industry_avg_gm = get_industry_and_gross_margin_by_symbol(symbols, symbol_gm)
    industry_avg_by_sym = {}
    for sym in df["symbol"]:
        ind = industries.get(sym, "")
        industry_avg_by_sym[sym] = industry_avg_gm.get(ind, np.nan)
    df["gross_margin_vs_industry"] = df.apply(
        lambda r: r["gross_margin"] - industry_avg_by_sym.get(r["symbol"], np.nan)
        if np.isfinite(r.get("gross_margin", np.nan)) and np.isfinite(industry_avg_by_sym.get(r["symbol"], np.nan))
        else np.nan,
        axis=1,
    )

    layer1_cols = list(LAYER1_WEIGHTS.keys())
    layer2_cols = list(LAYER2_WEIGHTS.keys())
    layer3_cols = list(LAYER3_WEIGHTS.keys())
    layer4_cols = list(LAYER4_WEIGHTS.keys())
    all_ind_cols = layer1_cols + layer2_cols + layer3_cols + layer4_cols
    all_ind_cols = [c for c in all_ind_cols if c in df.columns]
    df = df.copy()
    for col in all_ind_cols:
        if col not in df.columns:
            continue
        mu, sigma = df[col].mean(), df[col].std()
        if sigma == 0 or not np.isfinite(sigma):
            df[col + "_z"] = 0.0
        else:
            z = (df[col] - mu) / sigma
            if col in NEGATIVE_INDICATORS or (col == "debt_ratio_trend" and DEBT_TREND_NEGATIVE):
                z = -z
            df[col + "_z"] = z.fillna(0)

    df["layer1_score"] = _layer_score(df, layer1_cols, LAYER1_WEIGHTS, NEGATIVE_INDICATORS)
    df["layer2_score"] = _layer_score(df, layer2_cols, LAYER2_WEIGHTS, NEGATIVE_INDICATORS)
    df["layer3_score"] = _layer_score(df, layer3_cols, LAYER3_WEIGHTS, NEGATIVE_INDICATORS)
    df["layer4_score"] = _layer_score(df, layer4_cols, LAYER4_WEIGHTS, NEGATIVE_INDICATORS)
    df["total_score"] = (
        df["layer1_score"] * 0.25
        + df["layer2_score"] * 0.30
        + df["layer3_score"] * 0.30
        + df["layer4_score"] * 0.15
    )
    df = df.sort_values("total_score", ascending=False).reset_index(drop=True)
    n = len(df)
    k = max(1, int(np.ceil(n * 0.1)))
    top_10_pct = df.head(k)["symbol"].tolist()

    factor_details: Dict[str, Dict] = {}
    for _, r in df.iterrows():
        sym = r["symbol"]
        factor_details[sym] = {
            "layer1_score": float(r["layer1_score"]),
            "layer2_score": float(r["layer2_score"]),
            "layer3_score": float(r["layer3_score"]),
            "layer4_score": float(r["layer4_score"]),
            "total_score": float(r["total_score"]),
        }
        for c in all_ind_cols:
            if c in r:
                factor_details[sym][c] = r[c]
        factor_details[sym]["industry"] = industries.get(sym, "")
        factor_details[sym]["gross_margin_vs_industry"] = (
            float(r["gross_margin_vs_industry"]) if "gross_margin_vs_industry" in r and np.isfinite(r.get("gross_margin_vs_industry", np.nan)) else np.nan
        )

    return df, top_10_pct, factor_details
