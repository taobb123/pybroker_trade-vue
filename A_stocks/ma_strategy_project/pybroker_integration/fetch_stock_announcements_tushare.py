#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
使用 Tushare Pro「上市公司全量公告」接口 anns_d 拉取单只 A 股公告列表。

默认：景旺电子（603228.SH），起始 2020-01-01，导出 CSV。

依赖：
- pip install tushare pandas
- 账号需开通 anns_d 单独权限；Token 见环境变量 TUSHARE_TOKEN 或 config.settings.DATA_CONFIG['tushare_token']

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_stock_announcements_tushare.py
    python pybroker_integration/fetch_stock_announcements_tushare.py --start-date 20200101 --out announcements_603228.csv
    python pybroker_integration/fetch_stock_announcements_tushare.py --ts-code 000001.SZ --start-date 20200101
    python pybroker_integration/fetch_stock_announcements_tushare.py --daily
默认先按月请求；若失败且非权限类错误，会自动改为按日 ann_date 重试。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 景旺电子 — 深圳市景旺电子股份有限公司，上交所
DEFAULT_TS_CODE = "603228.SH"
ANN_MAX_ROWS = 2000
REQUEST_SLEEP_SEC = 0.35


def _tushare_error_is_fatal(msg: str) -> bool:
    """权限 / Token 等问题，按日重试也不会好，直接退出。"""
    m = (msg or "").lower()
    keys = (
        "权限",
        "积分",
        "token",
        "登陆",
        "登录",
        "无权",
        "没有访问",
        "permission",
        "unauthorized",
    )
    return any(k in (msg or "") for k in keys) or "token" in m


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


def _ymd(d: datetime) -> str:
    return d.strftime("%Y%m%d")


def _month_starts(start: datetime, end: datetime) -> list[datetime]:
    """含首尾月份：每月 1 日。"""
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


def _fetch_ann_window(pro, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        df = pro.anns_d(ts_code=ts_code, start_date=start_date, end_date=end_date)
    except Exception as e:
        raise RuntimeError(
            f"anns_d 请求失败 ts_code={ts_code} start_date={start_date} end_date={end_date}: {e}"
        ) from e
    time.sleep(REQUEST_SLEEP_SEC)
    if df is None:
        return pd.DataFrame()
    return df


def _fetch_ann_single_day(pro, ts_code: str, ann_date: str) -> pd.DataFrame:
    """与官方示例一致：按公告日 ann_date 查询（单股单日通常远小于 2000 条）。"""
    try:
        df = pro.anns_d(ts_code=ts_code, ann_date=ann_date)
    except Exception as e:
        raise RuntimeError(f"anns_d 请求失败 ts_code={ts_code} ann_date={ann_date}: {e}") from e
    time.sleep(REQUEST_SLEEP_SEC)
    if df is None:
        return pd.DataFrame()
    if len(df) >= ANN_MAX_ROWS:
        raise RuntimeError(
            f"单日 {ann_date} 返回 {len(df)} 条（已达 {ANN_MAX_ROWS} 上限），请缩小标的或联系 Tushare。"
        )
    return df


def _fetch_ann_range_split_if_needed(pro, ts_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    若区间返回达到 2000 条，按日期二分递归，避免截断。
    """
    df = _fetch_ann_window(pro, ts_code, start_date, end_date)
    if df.empty or len(df) < ANN_MAX_ROWS:
        return df
    if start_date >= end_date:
        raise RuntimeError(
            f"单日 {start_date} 公告仍达到 {ANN_MAX_ROWS} 条上限，请改用手动更细粒度或联系 Tushare。"
        )
    s = datetime.strptime(start_date, "%Y%m%d")
    e = datetime.strptime(end_date, "%Y%m%d")
    mid = s + (e - s) // 2
    mid_s = _ymd(mid)
    left = _fetch_ann_range_split_if_needed(pro, ts_code, start_date, mid_s)
    mid_next = mid + timedelta(days=1)
    if mid_next > e:
        return left
    right = _fetch_ann_range_split_if_needed(pro, ts_code, _ymd(mid_next), end_date)
    return pd.concat([left, right], ignore_index=True)


def _concat_sort_dedupe(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    subset = [c for c in ("ann_date", "title", "url", "ts_code") if c in out.columns]
    if subset:
        out = out.drop_duplicates(subset=subset, keep="first")
    sort_cols = [c for c in ("ann_date", "rec_time") if c in out.columns]
    if sort_cols:
        out = out.sort_values(sort_cols, ascending=[True] * len(sort_cols)).reset_index(drop=True)
    return out


def fetch_announcements_by_month_ranges(
    pro,
    ts_code: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """按月用 start_date/end_date 分段请求（调用次数少）。"""
    frames: list[pd.DataFrame] = []
    for m0 in _month_starts(start, end):
        seg_start = max(m0, start)
        seg_end = min(_month_end(m0), end)
        chunk = _fetch_ann_range_split_if_needed(pro, ts_code, _ymd(seg_start), _ymd(seg_end))
        if not chunk.empty:
            frames.append(chunk)
    return _concat_sort_dedupe(frames)


def fetch_announcements_by_calendar_days(
    pro,
    ts_code: str,
    start: datetime,
    end: datetime,
) -> pd.DataFrame:
    """按自然日 ann_date 循环（与文档示例一致，兼容性通常更好，耗时更长）。"""
    frames: list[pd.DataFrame] = []
    d = start.date()
    last = end.date()
    while d <= last:
        chunk = _fetch_ann_single_day(pro, ts_code, d.strftime("%Y%m%d"))
        if not chunk.empty:
            frames.append(chunk)
        d += timedelta(days=1)
    return _concat_sort_dedupe(frames)


def fetch_announcements_since(
    pro,
    ts_code: str,
    start: datetime,
    end: datetime,
    *,
    daily_only: bool,
    monthly_only: bool,
) -> pd.DataFrame:
    if daily_only and monthly_only:
        raise ValueError("不能同时指定 daily_only 与 monthly_only")
    if daily_only:
        return fetch_announcements_by_calendar_days(pro, ts_code, start, end)
    if monthly_only:
        return fetch_announcements_by_month_ranges(pro, ts_code, start, end)
    try:
        return fetch_announcements_by_month_ranges(pro, ts_code, start, end)
    except RuntimeError as e:
        msg = str(e)
        if _tushare_error_is_fatal(msg):
            raise
        print(
            "按月区间请求失败，将改用按日 ann_date 拉取（更慢但更稳）。原因：",
            msg,
            file=sys.stderr,
        )
        return fetch_announcements_by_calendar_days(pro, ts_code, start, end)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Tushare anns_d 拉取单股 A 股公告（默认景旺电子 2020 起）")
    p.add_argument("--ts-code", default=DEFAULT_TS_CODE, help="Tushare 证券代码，默认 603228.SH（景旺电子）")
    p.add_argument(
        "--start-date",
        default="20200101",
        help="公告开始日期 yyyymmdd，默认 20200101",
    )
    p.add_argument(
        "--end-date",
        default="",
        help="公告结束日期 yyyymmdd，默认今天",
    )
    p.add_argument(
        "--out",
        default="",
        help="输出 CSV 路径；默认当前目录 announcements_<ts_code>_<start>_<end>.csv",
    )
    p.add_argument(
        "--daily",
        action="store_true",
        help="仅按日 ann_date 请求（最稳，日期跨度大时较慢）",
    )
    p.add_argument(
        "--monthly-only",
        action="store_true",
        help="仅按月 start_date/end_date 请求；失败时不自动改按日",
    )
    args = p.parse_args(argv)
    if args.daily and args.monthly_only:
        print("错误: 不能同时使用 --daily 与 --monthly-only", file=sys.stderr)
        return 1

    end_s = (args.end_date or "").strip() or _ymd(datetime.now())
    start_s = args.start_date.strip()
    start_dt = datetime.strptime(start_s, "%Y%m%d")
    end_dt = datetime.strptime(end_s, "%Y%m%d")
    if start_dt > end_dt:
        print("错误: start-date 不能晚于 end-date", file=sys.stderr)
        return 1

    pro = _get_tushare_pro()
    try:
        df = fetch_announcements_since(
            pro,
            args.ts_code.strip().upper(),
            start_dt,
            end_dt,
            daily_only=bool(args.daily),
            monthly_only=bool(args.monthly_only),
        )
    except Exception as e:
        msg = str(e)
        if _tushare_error_is_fatal(msg):
            print("Tushare 拒绝访问（与日期/股票参数无关，需账号具备相应接口权限）：", file=sys.stderr)
            print(msg, file=sys.stderr)
            if "anns_d" in msg:
                print(
                    "\n本脚本依赖「上市公司全量公告」接口 anns_d："
                    "https://tushare.pro/document/2?doc_id=176\n"
                    "权限与积分说明：https://tushare.pro/document/1?doc_id=108",
                    file=sys.stderr,
                )
            return 3
        raise

    if df.empty:
        print("未获取到任何公告（请检查 ts_code、日期区间、anns_d 权限与网络）。", file=sys.stderr)
        return 2

    out_path = (args.out or "").strip()
    if not out_path:
        safe = args.ts_code.replace(".", "_")
        out_path = os.path.join(
            os.getcwd(),
            f"announcements_{safe}_{start_s}_{end_s}.csv",
        )
    df.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"共 {len(df)} 条，已写入: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
