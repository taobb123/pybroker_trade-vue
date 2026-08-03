#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票池波峰分析：过去三周内日涨幅>1.5%视为一个波峰，统计波峰次数并展示各波峰涨幅，辅助判断买入价值。

- 股票池：脚本同目录 stocks_pool.txt（每行或空白分隔的 6 位代码）
- 时间范围：自然日 3 周
- 排序：波峰数量降序，同分按波峰总涨幅、最大单日涨幅
- 名称：Tushare stock_basic 批量映射
- 日线：优先 pro.daily（含 pct_chg），失败则 pro_bar 并推算日涨幅
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
import numpy as np


def load_stock_pool(file_path: str) -> List[str]:
    """从 stocks_pool.txt 读取代码列表（与 factor_investing_20Roc 一致）。"""
    path = os.path.abspath(file_path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"股票池文件不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read().strip()
    return [s.strip() for s in content.replace("\n", " ").split() if s.strip()]


def _code_name_map_from_pro(pro) -> Dict[str, str]:
    """ts_code / 6 位代码 -> 简称。"""
    df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
    m: Dict[str, str] = {}
    for _, row in df.iterrows():
        ts_code = row["ts_code"]
        name = row["name"]
        m[ts_code.split(".")[0]] = name
        m[ts_code] = name
    return m


def resolve_stock_name(code_to_name: Dict[str, str], code: str) -> str:
    if code in code_to_name:
        return code_to_name[code]
    if len(code) == 6 and code.isdigit():
        suf = (
            f"{code}.SH"
            if code.startswith(("60", "68"))
            else (f"{code}.SZ" if code.startswith(("00", "30", "1")) else code)
        )
        return code_to_name.get(suf, code)
    return code


def get_tushare_pro():
    """获取 Tushare pro 实例（使用 config.settings 或环境变量）。"""
    token = ""
    try:
        from config.settings import DATA_CONFIG
        token = (DATA_CONFIG or {}).get("tushare_token", "") or ""
    except Exception:
        pass
    if not token:
        token = os.environ.get("TUSHARE_TOKEN", "")
    if not token:
        raise RuntimeError(
            "未配置 Tushare token：请在 config.settings 中设置 DATA_CONFIG['tushare_token'] 或环境变量 TUSHARE_TOKEN"
        )
    import tushare as ts
    ts.set_token(token)
    return ts.pro_api()


def to_ts_code(code: str) -> str:
    """6位代码转 tushare 代码。"""
    if code.startswith(("0", "3", "1")):
        return f"{code}.SZ"
    return f"{code}.SH"


def fetch_daily(pro, ts_code: str, start_date: str, end_date: str):
    """拉取日线。优先使用 pro.daily（含 pct_chg），失败则用 pro_bar 并计算日涨幅。"""
    start = start_date.replace("-", "")
    end = end_date.replace("-", "")
    df = None
    try:
        df = pro.daily(ts_code=ts_code, start_date=start, end_date=end)
    except Exception:
        try:
            import tushare as ts
            df = ts.pro_bar(
                ts_code=ts_code,
                start_date=start,
                end_date=end,
                adj="qfq",
                freq="D",
                asset="E",
            )
        except Exception:
            return None
    if df is None or df.empty:
        return None
    df = df.sort_values("trade_date").reset_index(drop=True)
    if "pct_chg" not in df.columns and "close" in df.columns:
        close = df["close"].astype(float)
        df["pct_chg"] = (close - close.shift(1)) / close.shift(1) * 100
    return df


def analyze_peaks(pool_path: str, peak_threshold_pct: float = 1.5, weeks: int = 3):
    """
    对股票池中股票做波峰分析。
    波峰：当日涨幅 > peak_threshold_pct（默认 1.5%）
    时间：过去 weeks 周（自然日）
    """
    codes = load_stock_pool(pool_path)
    if not codes:
        return pd.DataFrame()

    pro = get_tushare_pro()
    code_to_name = _code_name_map_from_pro(pro)

    end_date = datetime.now()
    start_date = end_date - timedelta(days=weeks * 7)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    rows = []
    for code in codes:
        name = resolve_stock_name(code_to_name, code)
        ts_code = to_ts_code(code)
        df = fetch_daily(pro, ts_code, start_str, end_str)
        if df is None or df.empty:
            rows.append({
                "code": code,
                "name": name,
                "peak_count": 0,
                "peak_dates": "",
                "peak_pcts": "",
                "total_peak_pct": np.nan,
                "max_peak_pct": np.nan,
            })
            continue
        if "pct_chg" not in df.columns:
            rows.append({
                "code": code,
                "name": name,
                "peak_count": 0,
                "peak_dates": "",
                "peak_pcts": "",
                "total_peak_pct": np.nan,
                "max_peak_pct": np.nan,
            })
            continue
        pct = pd.to_numeric(df["pct_chg"], errors="coerce").fillna(0)
        is_peak = pct > peak_threshold_pct
        peak_dates = df.loc[is_peak, "trade_date"].astype(str).tolist()
        peak_pcts = pct.loc[is_peak].round(2).tolist()
        total_peak_pct = float(pct.loc[is_peak].sum()) if is_peak.any() else np.nan
        max_peak_pct = float(pct.loc[is_peak].max()) if is_peak.any() else np.nan
        rows.append({
            "code": code,
            "name": name,
            "peak_count": int(is_peak.sum()),
            "peak_dates": "; ".join(peak_dates),
            "peak_pcts": "; ".join(f"{x}%" for x in peak_pcts),
            "total_peak_pct": total_peak_pct,
            "max_peak_pct": max_peak_pct,
        })

    result = pd.DataFrame(rows)
    result = result.sort_values(
        ["peak_count", "total_peak_pct", "max_peak_pct"],
        ascending=[False, False, False],
        na_position="last",
    ).reset_index(drop=True)
    return result


def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pool_path = os.path.join(script_dir, "stocks_pool.txt")
    peak_pct = 1.5
    weeks = 3

    print("股票池波峰分析（stocks_pool.txt | 过去三周自然日，日涨幅>1.5% 计为波峰）")
    print("排序：波峰数 > 波峰总涨幅 > 最大单日涨幅")
    print(f"股票池: {pool_path}")
    print("=" * 60)
    try:
        df = analyze_peaks(pool_path, peak_threshold_pct=peak_pct, weeks=weeks)
    except FileNotFoundError as e:
        print(e)
        return
    if df.empty:
        print("无有效数据或股票池为空。")
        return

    print(df.to_string(index=False))
    print()
    print("--- 最有买入价值（按波峰数+波峰总涨幅/最大单日涨幅）---")
    for _, r in df.head(10).iterrows():
        total_str = f"{r['total_peak_pct']:.2f}%" if pd.notna(r["total_peak_pct"]) else "-"
        max_str = f"{r['max_peak_pct']:.2f}%" if pd.notna(r["max_peak_pct"]) else "-"
        nm = r["name"] if pd.notna(r["name"]) and str(r["name"]).strip() else r["code"]
        print(f"  {r['code']} [{nm}] 波峰数={r['peak_count']}, 波峰总涨幅={total_str}, 最大单日涨幅={max_str}")
        print(f"    波峰日及涨幅: {r['peak_pcts']} | 日期: {r['peak_dates']}")

    out_dir = script_dir
    out_csv = os.path.join(out_dir, "买入价值_波峰分析.csv")
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    out_txt = os.path.join(out_dir, "买入价值_波峰分析.txt")
    with open(out_txt, "w", encoding="utf-8") as f:
        f.write("股票池波峰分析（stocks_pool.txt | 过去三周自然日，日涨幅>1.5% 计为波峰）\n")
        f.write("排序：波峰数 > 波峰总涨幅 > 最大单日涨幅\n")
        f.write("=" * 60 + "\n\n")
        f.write("--- 最有买入价值（按波峰数+波峰总涨幅/最大单日涨幅）---\n")
        for _, r in df.head(10).iterrows():
            total_str = f"{r['total_peak_pct']:.2f}%" if pd.notna(r["total_peak_pct"]) else "-"
            max_str = f"{r['max_peak_pct']:.2f}%" if pd.notna(r["max_peak_pct"]) else "-"
            nm = r["name"] if pd.notna(r["name"]) and str(r["name"]).strip() else r["code"]
            f.write(
                f"  {r['code']} [{nm}] 波峰数={r['peak_count']}, "
                f"波峰总涨幅={total_str}, 最大单日涨幅={max_str}\n"
            )
            f.write(f"    波峰日及涨幅: {r['peak_pcts']} | 日期: {r['peak_dates']}\n")
    print()
    print(f"结果已保存: CSV -> {out_csv}")
    print(f"           文本 -> {out_txt}")


if __name__ == "__main__":
    main()
