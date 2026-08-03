#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全边际估值模型（DCF + 安全边际）

核心逻辑：
1. 用自由现金流折现（DCF）计算企业内在价值：
   IntrinsicValue = sum_{t=1}^{5} FCF_t/(1+r)^t + TV/(1+r)^5
   其中终值 TV = FCF_5 * (1+g) / (r-g)（戈登模型）
2. 每股内在价值 = IntrinsicValue / 总股本
3. 安全边际买入价 = 每股内在价值 * (1 - 安全边际)

数据来源：TuShare Pro（cashflow 表：n_cashflow_act、c_pay_acq_const_fiolta；daily_basic：total_share）
FCF = 经营现金流(OCF) - 资本支出(CAPEX)
"""
import os
import sys
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any

# 项目根目录（当前脚本所在目录）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# 上级目录为 ma_strategy_project，config.settings 在其下，需加入 path 才能导入
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)


def _get_tushare_token() -> str:
    try:
        from config.settings import DATA_CONFIG
        return (DATA_CONFIG or {}).get("tushare_token", "") or ""
    except Exception:
        return os.environ.get("TUSHARE_TOKEN", "")


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


def _get_tushare_pro():
    """获取 TuShare Pro API，未配置 token 时返回 None。"""
    token = _get_tushare_token()
    if not token:
        return None
    try:
        import tushare as ts
        ts.set_token(token)
        return ts.pro_api()
    except Exception:
        return None


def get_stock_names(ts_codes: List[str]) -> Dict[str, str]:
    """用 TuShare stock_basic 批量获取股票名称，返回 {ts_code: name}。"""
    result = {c: c for c in ts_codes if c}
    pro = _get_tushare_pro()
    if pro is None or not ts_codes:
        return result
    try:
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        if df is None or df.empty or "name" not in df.columns:
            return result
        for _, row in df.iterrows():
            result[str(row["ts_code"])] = str(row["name"]).strip()
        return result
    except Exception:
        return result


def fetch_cashflow(ts_code: str, limit: int = 5) -> Optional[pd.DataFrame]:
    """获取现金流量表（按 end_date 升序，取最近 limit 期）。TuShare 需传 start_date/end_date。"""
    pro = _get_tushare_pro()
    if pro is None:
        return None
    try:
        import time
        end_date = time.strftime("%Y%m%d", time.localtime())
        start_date = f"{int(end_date[:4]) - 6}0101"
        df = pro.cashflow(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            report_type="1",
            fields="end_date,n_cashflow_act,c_pay_acq_const_fiolta",
        )
        if df is None or df.empty or "n_cashflow_act" not in df.columns:
            return None
        df = df.sort_values("end_date", ascending=True).tail(limit)
        return df.reset_index(drop=True)
    except Exception:
        return None


def fetch_total_share(ts_code: str) -> Optional[float]:
    """获取总股本（万股 -> 股）。daily_basic 的 total_share 单位为万股；无交易日时用 stk_holdertrade 或 stock_basic 兜底。"""
    pro = _get_tushare_pro()
    if pro is None:
        return None
    try:
        import time
        trade_date = time.strftime("%Y%m%d", time.localtime())
        df = pro.daily_basic(ts_code=ts_code, trade_date=trade_date)
        if df is not None and not df.empty and "total_share" in df.columns:
            val = df["total_share"].iloc[0]
            if not (pd.isna(val) or val <= 0):
                return float(val) * 10000.0
        df = pro.daily_basic(ts_code=ts_code, limit=1)
        if df is not None and not df.empty and "total_share" in df.columns:
            val = df["total_share"].iloc[0]
            if not (pd.isna(val) or val <= 0):
                return float(val) * 10000.0
        return None
    except Exception:
        return None


def compute_fcf_and_growth(cashflow: pd.DataFrame) -> tuple:
    """
    从现金流量表计算 FCF 序列与增长率。
    FCF = n_cashflow_act - |c_pay_acq_const_fiolta|
    增长率 = 过去 5 年 FCF 的 CAGR，并做保守上限 15%。
    返回 (current_fcf, growth_rate) 或 (None, None) 表示无效。
    """
    if cashflow is None or cashflow.empty or len(cashflow) < 2:
        return None, None
    ocf = pd.to_numeric(cashflow["n_cashflow_act"], errors="coerce")
    capex_col = "c_pay_acq_const_fiolta"
    if capex_col not in cashflow.columns:
        return None, None
    capex = pd.to_numeric(cashflow[capex_col], errors="coerce").fillna(0).abs()
    fcf = ocf - capex
    fcf = fcf.dropna()
    if len(fcf) < 2:
        return None, None
    fcf = fcf.values
    start_val, end_val = float(fcf[0]), float(fcf[-1])
    if start_val <= 0 or end_val <= 0:
        return None, None
    n = len(fcf) - 1
    if n <= 0:
        return None, None
    growth_rate = (end_val / start_val) ** (1 / n) - 1
    growth_rate = min(growth_rate, 0.15)
    return end_val, growth_rate


def dcf_intrinsic_value(
    current_fcf: float,
    growth_rate: float,
    r: float = 0.10,
    g: float = 0.03,
    years: int = 5,
) -> float:
    """
    5 年 FCF 增长 + 永续终值，折现到当前的企业价值。
    FCF_t = current_fcf * (1+growth_rate)^t，t=1..years
    TV = FCF_years * (1+g) / (r-g)，折现到当前为 TV/(1+r)^years
    """
    if r <= g or current_fcf <= 0:
        return 0.0
    pv = 0.0
    for t in range(1, years + 1):
        fcf_t = current_fcf * ((1 + growth_rate) ** t)
        pv += fcf_t / ((1 + r) ** t)
    fcf_n = current_fcf * ((1 + growth_rate) ** years)
    terminal_value = fcf_n * (1 + g) / (r - g)
    pv += terminal_value / ((1 + r) ** years)
    return pv


def value_one_stock(
    ts_code: str,
    r: float = 0.10,
    g: float = 0.03,
    margin: float = 0.30,
    growth_cap: float = 0.15,
) -> Dict[str, Any]:
    """
    对单只股票做 DCF 安全边际估值。
    ts_code: TuShare 代码（如 000975.SZ）
    r: 折现率；g: 永续增长率；margin: 安全边际比例；growth_cap: FCF 增长率上限。
    返回 dict：intrinsic_value_enterprise, intrinsic_per_share, buy_price, current_fcf, growth_rate, total_share, success, error
    """
    out = {
        "intrinsic_value_enterprise": None,
        "intrinsic_per_share": None,
        "buy_price": None,
        "current_fcf": None,
        "growth_rate": None,
        "total_share": None,
        "success": False,
        "error": None,
    }
    cashflow = fetch_cashflow(ts_code, limit=5)
    if cashflow is None or cashflow.empty:
        out["error"] = "无法获取现金流量表"
        return out
    current_fcf, growth_rate = compute_fcf_and_growth(cashflow)
    if current_fcf is None:
        out["error"] = "FCF 或增长率无效"
        return out
    total_share = fetch_total_share(ts_code)
    if total_share is None or total_share <= 0:
        out["error"] = "无法获取总股本"
        return out
    growth_rate = min(growth_rate, growth_cap)
    enterprise_value = dcf_intrinsic_value(current_fcf, growth_rate, r=r, g=g, years=5)
    if enterprise_value <= 0:
        out["error"] = "DCF 估值无效"
        return out
    intrinsic_per_share = enterprise_value / total_share
    buy_price = intrinsic_per_share * (1 - margin)
    out["intrinsic_value_enterprise"] = enterprise_value
    out["intrinsic_per_share"] = intrinsic_per_share
    out["buy_price"] = buy_price
    out["current_fcf"] = current_fcf
    out["growth_rate"] = growth_rate
    out["total_share"] = total_share
    out["success"] = True
    return out


def batch_valuation(
    symbols: List[str],
    r: float = 0.10,
    g: float = 0.03,
    margin: float = 0.30,
    growth_cap: float = 0.15,
) -> pd.DataFrame:
    """
    批量 DCF 安全边际估值。
    symbols: 股票代码列表（支持 6 位或 ts_code 格式）。
    返回 DataFrame：symbol, ts_code, intrinsic_per_share, buy_price, current_fcf, growth_rate, success, error
    """
    rows = []
    for sym in symbols:
        ts_code = sym if "." in str(sym) else _to_ts_code(str(sym))
        if not ts_code:
            rows.append({
                "symbol": sym,
                "ts_code": "",
                "intrinsic_per_share": np.nan,
                "buy_price": np.nan,
                "current_fcf": np.nan,
                "growth_rate": np.nan,
                "success": False,
                "error": "无效代码",
            })
            continue
        res = value_one_stock(ts_code, r=r, g=g, margin=margin, growth_cap=growth_cap)
        rows.append({
            "symbol": sym,
            "ts_code": ts_code,
            "intrinsic_per_share": res["intrinsic_per_share"],
            "buy_price": res["buy_price"],
            "current_fcf": res["current_fcf"],
            "growth_rate": res["growth_rate"],
            "success": res["success"],
            "error": res["error"],
        })
    return pd.DataFrame(rows)


def load_stock_pool(file_path: str) -> List[str]:
    """从文件加载股票池（每行或空格分隔的代码）。"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        symbols = [s.strip() for s in content.replace("\n", " ").split() if s.strip()]
        return symbols
    except Exception as e:
        print(f"加载股票池失败: {e}")
        return []


def main():
    """主入口：从股票池加载代码 -> 批量 DCF 安全边际估值 -> 打印并保存 CSV。"""
    print("=" * 60)
    print("安全边际估值模型（DCF + 单一情景）")
    print("=" * 60)

    if not _get_tushare_token():
        print("未配置 TuShare token。请在 config.settings 中设置 DATA_CONFIG['tushare_token'] 或环境变量 TUSHARE_TOKEN")
        return

    pool_path = os.path.join(_SCRIPT_DIR, "stocks_pool.txt")
    symbols = load_stock_pool(pool_path)
    if not symbols:
        print("股票池为空，请检查 stocks_pool.txt")
        return

    print(f"股票池数量: {len(symbols)}")
    print("参数: 折现率 r=10%, 永续增长 g=3%, 安全边际 30%")
    print()

    df = batch_valuation(symbols, r=0.10, g=0.03, margin=0.30, growth_cap=0.15)
    ok = int(df["success"].sum())
    print(f"有效估值: {ok} / {len(symbols)}")

    if ok > 0:
        ts_codes = df["ts_code"].dropna().astype(str).unique().tolist()
        name_map = get_stock_names(ts_codes)
        df["name"] = df["ts_code"].astype(str).map(lambda c: name_map.get(c, "") if c else "")

        valid = df[df["success"]].copy()
        valid = valid.sort_values("buy_price", ascending=False)
        valid["intrinsic_per_share"] = valid["intrinsic_per_share"].round(4)
        valid["buy_price"] = valid["buy_price"].round(4)
        valid["growth_rate"] = (valid["growth_rate"] * 100).round(2)
        print("\n估值结果（按安全边际买入价从高到低）:")
        print(valid[["name", "ts_code", "intrinsic_per_share", "buy_price", "growth_rate"]].to_string(index=False))

        out_csv = os.path.join(_SCRIPT_DIR, "safety_margin_valuation.csv")
        df_save = df.copy()
        for col in ("intrinsic_per_share", "buy_price", "current_fcf", "growth_rate"):
            if col in df_save.columns and pd.api.types.is_numeric_dtype(df_save[col]):
                df_save[col] = df_save[col].round(2)
        df_save.to_csv(out_csv, index=False, encoding="utf-8-sig")
        print(f"\n结果已保存: {out_csv}")
    else:
        print("无有效估值结果。失败原因统计:")
        err_counts = df["error"].value_counts()
        for err, cnt in err_counts.items():
            print(f"  - {err}: {cnt} 只")
        first_ts = df["ts_code"].iloc[0] if not df.empty and pd.notna(df["ts_code"].iloc[0]) else ( _to_ts_code(symbols[0]) if symbols else "")
        if first_ts:
            print(f"\n首只诊断 {first_ts}:")
            cf = fetch_cashflow(first_ts, limit=5)
            print(f"  现金流量表: {'共 %d 期' % len(cf) if cf is not None and not cf.empty else '未获取到'}")
            if cf is not None and not cf.empty:
                print(f"  列: {list(cf.columns)}")
            sh = fetch_total_share(first_ts)
            print(f"  总股本: {sh} 股" if sh else "  总股本: 未获取到")

    print("=" * 60)


if __name__ == "__main__":
    main()
