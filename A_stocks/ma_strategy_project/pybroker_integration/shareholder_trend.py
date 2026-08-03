#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
近三季股东变化 + 四维筛选 + 近一周涨幅（仅展示）。

读取 stocks_pool.txt，调用 Tushare Pro / 本地行情：
- stk_holdernumber、top10_floatholders：户数与北向
- fina_indicator.yoy_net_profit：净利润同比（%）
- 日线：距 MA120（%）、近 5 交易日涨幅（%）（补充列，不参与筛选）

入选（AND，列「是否入选」）：
  户数三季变化率 < -5%、北向三季变动 > 0、净利润同比增速 > 20%、|距 MA120| < 10%

输出 shareholder_trend.csv；入选优先，再按户数三季变化率升序。

用法（pybroker_integration 目录）：
    python shareholder_trend.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

REQUEST_SLEEP_SEC = 0.35
QUARTERS = 3
NORTHBOUND_KEY = "香港中央结算"
OUTPUT_FILE = "shareholder_trend.csv"

# 主筛选阈值
HOLDER_DROP_PCT_MAX = -5.0  # 户数三季变化率须 < -5%
NORTHBOUND_CHANGE_MIN = 0.0
PROFIT_YOY_MIN_PCT = 20.0
MA120_DIST_MAX_PCT = 10.0

# 行情：近 5 个交易日涨幅（补充展示，不筛选）
WEEK_TRADING_DAYS = 5
MA_WINDOW = 120
LOOKBACK_CALENDAR_DAYS = 200


def _normalize_code(code: str) -> str:
    if not code or pd.isna(code):
        return ""
    s = str(code).strip().upper().replace("SZ", "").replace("SH", "")
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
    token = (os.getenv("TUSHARE_TOKEN") or "").strip()
    if not token:
        try:
            from config.settings import DATA_CONFIG

            token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
        except Exception:
            token = ""
    if not token:
        raise RuntimeError(
            "未找到 Tushare Token：请设置环境变量 TUSHARE_TOKEN 或 "
            "config.settings.DATA_CONFIG['tushare_token']"
        )
    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()


def load_stock_pool(file_path: str) -> List[str]:
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
            return [s.strip() for s in content.replace("\n", " ").split() if s.strip()]
    except Exception as e:
        print(f"✗ 加载股票池失败: {e}")
        return []


def get_stock_names(symbols: List[str]) -> Dict[str, str]:
    result = {s: s for s in symbols}
    try:
        pro = _get_tushare_pro()
        df = pro.stock_basic(exchange="", list_status="L", fields="ts_code,name")
        if df is None or df.empty:
            return result
        code_to_name: Dict[str, str] = {}
        for _, row in df.iterrows():
            ts_code = str(row["ts_code"])
            name = str(row["name"])
            code = ts_code.split(".")[0]
            code_to_name[code] = name
            code_to_name[ts_code] = name
        for sym in symbols:
            code = _normalize_code(sym)
            result[sym] = code_to_name.get(code, sym)
    except Exception as e:
        print(f"⚠ 获取股票名称失败: {e}")
    return result


def _recent_quarter_rows(df: pd.DataFrame, n: int = QUARTERS) -> pd.DataFrame:
    """按 end_date 去重，取最近 n 个报告期，按时间升序返回。"""
    if df is None or df.empty or "end_date" not in df.columns:
        return pd.DataFrame()
    sub = df.drop_duplicates(subset=["end_date"]).sort_values("end_date", ascending=False).head(n)
    return sub.sort_values("end_date").reset_index(drop=True)


def _latest_net_profit_yoy(pro, ts_code: str) -> Optional[float]:
    """最新报告期净利润同比增速（%，Tushare fina_indicator.yoy_net_profit）。"""
    try:
        fi = pro.fina_indicator(
            ts_code=ts_code,
            fields="end_date,ann_date,yoy_net_profit",
        )
        time.sleep(REQUEST_SLEEP_SEC)
    except Exception:
        return None
    if fi is None or fi.empty or "yoy_net_profit" not in fi.columns:
        return None
    sub = fi.dropna(subset=["yoy_net_profit"]).sort_values("end_date", ascending=False)
    if sub.empty:
        return None
    val = sub["yoy_net_profit"].iloc[0]
    return float(val) if pd.notna(val) else None


def _price_metrics_from_bars(g: pd.DataFrame, asof_ts: pd.Timestamp) -> Optional[dict]:
    """统一截面日：近 5 日涨幅、距 MA120 偏离（%）。"""
    g = g.sort_values("date").reset_index(drop=True)
    if g.empty:
        return None
    last = pd.Timestamp(g["date"].iloc[-1]).normalize()
    if last != asof_ts.normalize():
        return None
    close = g["close"].astype(float)
    if len(close) < MA_WINDOW + 1:
        return None
    c = float(close.iloc[-1])
    ma120 = float(close.rolling(MA_WINDOW).mean().iloc[-1])
    if not np.isfinite(ma120) or ma120 <= 0:
        return None
    dist_pct = (c / ma120 - 1) * 100.0
    week_pct = np.nan
    if len(close) >= WEEK_TRADING_DAYS + 1:
        c0 = float(close.iloc[-(WEEK_TRADING_DAYS + 1)])
        if c0 > 0:
            week_pct = (c / c0 - 1) * 100.0
    return {
        "收盘价": round(c, 2),
        "距MA120(%)": round(dist_pct, 2),
        "近一周涨幅(%)": round(week_pct, 2) if pd.notna(week_pct) else np.nan,
    }


def fetch_price_metrics_batch(symbols: List[str]) -> Tuple[Optional[pd.Timestamp], Dict[str, dict]]:
    """批量拉日线，按 6 位代码返回行情指标。"""
    try:
        from pybroker_integration.custom_data_source import create_custom_data_source
    except ImportError:
        print("⚠ 无法导入行情数据源，跳过 MA120 / 近一周涨幅")
        return None, {}

    end = datetime.now()
    start = end - timedelta(days=LOOKBACK_CALENDAR_DAYS)
    data_source = create_custom_data_source()
    df = data_source._fetch_data(frozenset(symbols), start, end)
    if df is None or df.empty:
        print("⚠ 未获取到行情数据")
        return None, {}

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    asof_ts = pd.Timestamp(df["date"].max()).normalize()

    out: Dict[str, dict] = {}
    for sym, g in df.groupby("symbol"):
        code = _normalize_code(sym)
        if not code:
            continue
        m = _price_metrics_from_bars(g, asof_ts)
        if m:
            out[code] = m
    return asof_ts, out


def _passes_screen(row: pd.Series) -> bool:
    hc = row.get("户数三季变化率")
    if pd.isna(hc) or hc >= HOLDER_DROP_PCT_MAX:
        return False
    nb = row.get("北向三季变动")
    if pd.isna(nb) or nb <= NORTHBOUND_CHANGE_MIN:
        return False
    yoy = row.get("净利润同比增速(%)")
    if pd.isna(yoy) or yoy <= PROFIT_YOY_MIN_PCT:
        return False
    dist = row.get("距MA120(%)")
    if pd.isna(dist) or abs(float(dist)) >= MA120_DIST_MAX_PCT:
        return False
    return True


def _northbound_ratio(holders: pd.DataFrame, end_date: str) -> Optional[float]:
    if holders is None or holders.empty:
        return None
    sub = holders[holders["end_date"] == end_date]
    if sub.empty:
        return None
    mask = sub["holder_name"].astype(str).str.contains(NORTHBOUND_KEY, na=False)
    row = sub[mask]
    if row.empty or "hold_ratio" not in row.columns:
        return None
    val = row["hold_ratio"].iloc[0]
    return float(val) if pd.notna(val) else None


def analyze_one(pro, ts_code: str) -> Optional[dict]:
    try:
        hn = pro.stk_holdernumber(ts_code=ts_code)
        time.sleep(REQUEST_SLEEP_SEC)
        fh = pro.top10_floatholders(ts_code=ts_code)
        time.sleep(REQUEST_SLEEP_SEC)
        profit_yoy = _latest_net_profit_yoy(pro, ts_code)
    except Exception as e:
        print(f"  ⚠ {ts_code} 拉取失败: {e}")
        return None

    hn_q = _recent_quarter_rows(hn, QUARTERS)
    if len(hn_q) < 2:
        return None

    oldest = hn_q.iloc[0]
    latest = hn_q.iloc[-1]
    start_num = int(oldest["holder_num"])
    end_num = int(latest["holder_num"])
    if start_num <= 0:
        return None
    change_pct = (end_num - start_num) / start_num * 100.0

    periods = hn_q["end_date"].tolist()
    nb_start = _northbound_ratio(fh, periods[0])
    nb_end = _northbound_ratio(fh, periods[-1])
    nb_change_pp = (nb_end - nb_start) if nb_start is not None and nb_end is not None else np.nan

    row = {
        "起始报告期": periods[0],
        "最新报告期": periods[-1],
        "起始户数": start_num,
        "最新户数": end_num,
        "户数三季变化率": round(change_pct, 2),
        "北向起始占比": round(nb_start, 4) if nb_start is not None else np.nan,
        "北向最新占比": round(nb_end, 4) if nb_end is not None else np.nan,
        "北向三季变动": round(nb_change_pp, 4) if pd.notna(nb_change_pp) else np.nan,
        "净利润同比增速(%)": round(profit_yoy, 2) if profit_yoy is not None else np.nan,
    }
    for i, p in enumerate(periods, 1):
        h = hn_q[hn_q["end_date"] == p]
        if not h.empty:
            row[f"Q{i}报告期"] = p
            row[f"Q{i}户数"] = int(h["holder_num"].iloc[0])
        nb = _northbound_ratio(fh, p)
        row[f"Q{i}北向占比"] = round(nb, 4) if nb is not None else np.nan
    return row


def _save_csv(df: pd.DataFrame, out_path: str) -> None:
    tmp = out_path + ".tmp"
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    try:
        os.replace(tmp, out_path)
        print(f"✓ 已保存: {out_path}")
    except OSError:
        print(f"✓ 已写入: {tmp}")
        print(f"  若 {os.path.basename(out_path)} 被占用，请关闭后手动将 .tmp 重命名。")


def main() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pool_file = os.path.join(script_dir, "stocks_pool.txt")
    out_file = os.path.join(script_dir, OUTPUT_FILE)

    print("=" * 72)
    print("股东筛选 — 户数/北向/利润同比/MA120 + 近一周涨幅（展示）")
    print("=" * 72)

    symbols = load_stock_pool(pool_file)
    if not symbols:
        print("✗ 股票池为空")
        return

    print(f"✓ 股票池: {len(symbols)} 只")
    pro = _get_tushare_pro()
    names = get_stock_names(symbols)

    print("拉取行情（MA120、近 5 交易日涨幅）...")
    asof_ts, price_by_code = fetch_price_metrics_batch(symbols)
    if asof_ts is not None:
        print(f"✓ 行情截面日: {asof_ts.date()}，有效 {len(price_by_code)} 只")

    rows = []
    for i, sym in enumerate(symbols, 1):
        ts_code = _to_ts_code(sym)
        if not ts_code:
            continue
        print(f"  [{i}/{len(symbols)}] {sym} ({ts_code})")
        metrics = analyze_one(pro, ts_code)
        if metrics is None:
            print(f"    跳过（数据不足）")
            continue
        code = _normalize_code(sym)
        row = {"股票代码": code, "股票名称": names.get(sym, sym), **metrics}
        row.update(price_by_code.get(code, {}))
        rows.append(row)

    if not rows:
        print("✗ 无有效结果")
        return

    df = pd.DataFrame(rows)
    df["是否入选"] = df.apply(_passes_screen, axis=1)
    df = df.sort_values(["是否入选", "户数三季变化率"], ascending=[False, True]).reset_index(drop=True)
    df.insert(0, "排名", range(1, len(df) + 1))

    num_cols = [c for c in df.columns if "户数" in c and c != "户数三季变化率"]
    for c in num_cols:
        if c in df.columns:
            df[c] = df[c].apply(lambda x: int(x) if pd.notna(x) else x)

    n_pass = int(df["是否入选"].sum())
    print("\n" + "-" * 72)
    print(
        f"有效 {len(df)} 只，入选 {n_pass} 只 "
        f"(户数三季<-5%、北向>0、净利同比>{PROFIT_YOY_MIN_PCT}%、|距MA120|<{MA120_DIST_MAX_PCT}%)"
    )
    preview_cols = [
        "排名",
        "是否入选",
        "股票代码",
        "股票名称",
        "户数三季变化率",
        "北向三季变动",
        "净利润同比增速(%)",
        "距MA120(%)",
        "近一周涨幅(%)",
    ]
    preview_cols = [c for c in preview_cols if c in df.columns]
    print(df[preview_cols].head(min(10, len(df))).to_string(index=False))

    _save_csv(df, out_file)
    print("=" * 72)


if __name__ == "__main__":
    main()
