#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 AkShare 同源数据源（东方财富 np-anotice-stock）拉取沪深京 A 股公告。

实现说明：
- 接口与 akshare.stock_notice_report 一致，但支持按自然月设置 begin_time/end_time，
  分页拉取后在本地按 6 位股票代码过滤，减少按日循环次数。
- 可选 --use-akshare-daily：逐日调用 ak.stock_notice_report，与官方示例完全一致（较慢）。

依赖：pip install akshare pandas requests

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_stock_announcements_akshare.py
    python pybroker_integration/fetch_stock_announcements_akshare.py --symbol 603228 --start-date 20200101 --out jw_ann.csv
    python pybroker_integration/fetch_stock_announcements_akshare.py --no-env-proxy
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import pandas as pd
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

DEFAULT_SYMBOL_6 = "603228"  # 景旺电子
ANN_URL = "https://np-anotice-stock.eastmoney.com/api/security/ann"
REPORT_MAP = {
    "全部": "0",
    "财务报告": "1",
    "融资公告": "2",
    "风险提示": "3",
    "信息变更": "4",
    "重大事项": "5",
    "资产重组": "6",
    "持股变动": "7",
}
DEFAULT_SLEEP = 0.25
MAX_RETRIES = 4


def normalize_symbol_6(symbol: str) -> str:
    s = symbol.strip().upper()
    if "." in s:
        s = s.split(".")[0]
    s = "".join(c for c in s if c.isdigit()) or s
    if len(s) < 6:
        s = s.zfill(6)
    return s[-6:]


def _month_starts(start: datetime, end: datetime) -> list[datetime]:
    out: list[datetime] = []
    cur = start.replace(day=1)
    last = end.replace(day=1)
    while cur <= last:
        out.append(cur)
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return out


def _month_end(d: datetime) -> datetime:
    if d.month == 12:
        nxt = d.replace(year=d.year + 1, month=1, day=1)
    else:
        nxt = d.replace(month=d.month + 1, day=1)
    return nxt - timedelta(days=1)


def _session(no_env_proxy: bool) -> requests.Session:
    s = requests.Session()
    if no_env_proxy:
        s.trust_env = False
    s.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://data.eastmoney.com/",
        }
    )
    return s


def _get_json_with_retry(sess: requests.Session, params: dict) -> dict[str, Any]:
    last_err: Optional[BaseException] = None
    for attempt in range(MAX_RETRIES):
        try:
            r = sess.get(ANN_URL, params=params, timeout=45)
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, json.JSONDecodeError) as e:
            last_err = e
            time.sleep(min(2.0 ** attempt, 8.0))
    raise RuntimeError(f"东方财富公告接口连续失败: {last_err}") from last_err


def _parse_ann_page_items(data_json: dict[str, Any]) -> pd.DataFrame:
    """将单页 list 转为与 akshare.stock_notice_report 相近的列。"""
    items = (data_json.get("data") or {}).get("list") or []
    if not items:
        return pd.DataFrame(columns=["代码", "名称", "公告标题", "公告类型", "公告日期", "网址"])

    rows: list[dict[str, Any]] = []
    for item in items:
        try:
            c0 = (item.get("codes") or [None])[0]
            col0 = (item.get("columns") or [None])[0]
            if not c0:
                continue
            stock_code = str(c0.get("stock_code", "")).strip()
            short_name = str(c0.get("short_name", "")).strip()
            title = str(item.get("title", "")).strip()
            col_name = str((col0 or {}).get("column_name", "")).strip()
            art_code = str(item.get("art_code", "")).strip()
            notice_date = item.get("notice_date")
        except (TypeError, KeyError, IndexError):
            continue
        detail = f"https://data.eastmoney.com/notices/detail/{stock_code}/{art_code}.html"
        rows.append(
            {
                "代码": stock_code,
                "名称": short_name,
                "公告标题": title,
                "公告类型": col_name,
                "公告日期": notice_date,
                "网址": detail,
                "编码": art_code,
            }
        )
    return pd.DataFrame(rows)


def fetch_notices_month_range_em(
    sess: requests.Session,
    symbol_6: str,
    category: str,
    begin: datetime,
    end: datetime,
    sleep_sec: float,
) -> pd.DataFrame:
    """按东方财富接口拉取 [begin, end] 区间内、指定类别下的全市场公告，再过滤个股。"""
    if category not in REPORT_MAP:
        raise ValueError(f"类别必须是: {', '.join(REPORT_MAP)}")
    begin_s = begin.strftime("%Y-%m-%d")
    end_s = end.strftime("%Y-%m-%d")
    params = {
        "sr": "-1",
        "page_size": "100",
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "f_node": REPORT_MAP[category],
        "s_node": "0",
        "begin_time": begin_s,
        "end_time": end_s,
    }
    params["page_index"] = "1"
    first = _get_json_with_retry(sess, params)
    if first.get("success") is False:
        raise RuntimeError(str(first.get("message") or first.get("error") or "接口返回失败"))
    data0 = first.get("data") or {}
    total = int(data0.get("total_hits") or 0)
    if total <= 0:
        return pd.DataFrame(columns=["代码", "名称", "公告标题", "公告类型", "公告日期", "网址"])

    total_page = max(1, math.ceil(total / 100))
    frames: list[pd.DataFrame] = []
    for page in range(1, total_page + 1):
        if page == 1:
            data_json = first
        else:
            params["page_index"] = str(page)
            data_json = _get_json_with_retry(sess, params)
            time.sleep(sleep_sec)
        chunk = _parse_ann_page_items(data_json)
        if not chunk.empty:
            frames.append(chunk)

    if not frames:
        return pd.DataFrame(columns=["代码", "名称", "公告标题", "公告类型", "公告日期", "网址"])
    big = pd.concat(frames, ignore_index=True)
    code_norm = big["代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip().str.zfill(6)
    out = big.loc[code_norm == symbol_6].copy()
    out["公告日期"] = pd.to_datetime(out["公告日期"], errors="coerce").dt.date
    return out[
        ["代码", "名称", "公告标题", "公告类型", "公告日期", "网址"]
    ]


def fetch_by_months_default(
    sess: requests.Session,
    symbol_6: str,
    category: str,
    start: datetime,
    end: datetime,
    sleep_sec: float,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for m0 in _month_starts(start, end):
        seg_start = max(m0, start)
        seg_end = min(_month_end(m0), end)
        df = fetch_notices_month_range_em(sess, symbol_6, category, seg_start, seg_end, sleep_sec)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["代码", "名称", "公告标题", "公告类型", "公告日期", "网址"])
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["网址"], keep="first")
    out = out.sort_values(["公告日期", "公告标题"], ascending=[True, True]).reset_index(drop=True)
    return out


def fetch_by_akshare_daily(symbol_6: str, category: str, start: datetime, end: datetime, sleep_sec: float) -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as e:
        raise RuntimeError("未安装 akshare，请执行: pip install akshare") from e

    frames: list[pd.DataFrame] = []
    d = start.date()
    last = end.date()
    while d <= last:
        ds = d.strftime("%Y%m%d")
        try:
            df = ak.stock_notice_report(symbol=category, date=ds)
        except Exception as e:
            raise RuntimeError(f"ak.stock_notice_report 失败 date={ds}: {e}") from e
        time.sleep(sleep_sec)
        if df is not None and not df.empty:
            codes = df["代码"].astype(str).str.replace(r"\.0$", "", regex=True).str.strip().str.zfill(6)
            sub = df.loc[codes == symbol_6].copy()
            if not sub.empty:
                frames.append(sub)
        d += timedelta(days=1)

    if not frames:
        return pd.DataFrame(columns=["代码", "名称", "公告标题", "公告类型", "公告日期", "网址"])
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(subset=["网址"], keep="first")
    out = out.sort_values(["公告日期", "公告标题"], ascending=[True, True]).reset_index(drop=True)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="东方财富公告（AkShare 同源）单股拉取，默认景旺电子 603228")
    p.add_argument("--symbol", default=DEFAULT_SYMBOL_6, help="6 位股票代码或 603228.SH，默认 603228")
    p.add_argument("--category", default="全部", choices=list(REPORT_MAP.keys()), help="公告大类，默认全部")
    p.add_argument("--start-date", default="20200101", help="开始日期 yyyymmdd")
    p.add_argument("--end-date", default="", help="结束日期 yyyymmdd，默认今天")
    p.add_argument("--out", default="", help="输出 CSV；默认当前目录 announcements_ak_<code>_<start>_<end>.csv")
    p.add_argument("--sleep", type=float, default=DEFAULT_SLEEP, help="分页请求间隔秒，默认 0.25")
    p.add_argument(
        "--no-env-proxy",
        action="store_true",
        help="requests 不使用系统环境变量中的代理（trust_env=False），缓解错误代理导致的断连",
    )
    p.add_argument(
        "--use-akshare-daily",
        action="store_true",
        help="逐日调用 akshare.stock_notice_report（更慢，与官方示例一致）",
    )
    args = p.parse_args(argv)

    end_s = (args.end_date or "").strip() or datetime.now().strftime("%Y%m%d")
    start_s = args.start_date.strip()
    start_dt = datetime.strptime(start_s, "%Y%m%d")
    end_dt = datetime.strptime(end_s, "%Y%m%d")
    if start_dt > end_dt:
        print("错误: start-date 不能晚于 end-date", file=sys.stderr)
        return 1

    sym6 = normalize_symbol_6(args.symbol)

    if args.use_akshare_daily:
        df = fetch_by_akshare_daily(sym6, args.category, start_dt, end_dt, max(args.sleep, 0.05))
    else:
        sess = _session(args.no_env_proxy)
        df = fetch_by_months_default(sess, sym6, args.category, start_dt, end_dt, max(args.sleep, 0.05))

    if df.empty:
        print(
            f"未获取到 {sym6} 在 {start_s}–{end_s} 的公告（或网络/代理失败）。可尝试 --no-env-proxy 或 --use-akshare-daily。",
            file=sys.stderr,
        )
        return 2

    out_path = (args.out or "").strip()
    if not out_path:
        out_path = os.path.join(
            os.getcwd(),
            f"announcements_ak_{sym6}_{start_s}_{end_s}.csv",
        )
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"共 {len(df)} 条，已写入: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
