#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取「早间涨停」与「财经快讯」，并做简单名称匹配。

功能：
1) 拉取目标交易日涨停明细（优先 limit_list_d）。
2) 过滤早间首封涨停（默认首封时间 <= 10:30:00）。
3) 拉取同日早间财经快讯（默认 07:00:00 - 截止时间；优先东方财富 7×24，失败回退新浪 7×24）。
4) 使用股票简称在新闻标题+正文中做关键词匹配。
5) 导出两个 CSV：
   - morning_limit_up_<trade_date>.csv
   - morning_limit_up_news_match_<trade_date>.csv

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/morning_limit_up_news.py
    python pybroker_integration/morning_limit_up_news.py --trade-date 20260421
    python pybroker_integration/morning_limit_up_news.py --cutoff 10:00:00 --out-dir pybroker_integration
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from datetime import datetime
from typing import Optional

import pandas as pd
import requests

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
}
_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _clear_proxy_env() -> None:
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)


def _get_tushare_pro():
    token = (os.getenv("TUSHARE_TOKEN") or "").strip()
    if not token:
        try:
            from config.settings import DATA_CONFIG

            token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
        except Exception:
            token = ""
    if not token:
        raise RuntimeError("未找到 Tushare Token，请设置环境变量 TUSHARE_TOKEN 或配置 config.settings.DATA_CONFIG['tushare_token']")
    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()


def _normalize_trade_date(s: Optional[str]) -> str:
    if not s:
        return datetime.now().strftime("%Y%m%d")
    s = str(s).strip().replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError("trade_date 格式应为 YYYYMMDD 或 YYYY-MM-DD")
    return s


def _compact_to_dash(d: str) -> str:
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def _normalize_hms(raw: object) -> Optional[str]:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() == "nan":
        return None
    s = s.replace(":", "")
    if not s.isdigit():
        return None
    if len(s) == 5:
        s = f"0{s}"
    if len(s) == 4:
        s = f"{s}00"
    if len(s) < 6:
        s = s.rjust(6, "0")
    if len(s) > 6:
        s = s[:6]
    return f"{s[0:2]}:{s[2:4]}:{s[4:6]}"


def _fetch_limit_list(pro, trade_date: str) -> pd.DataFrame:
    for fn_name in ("limit_list_d", "limit_list"):
        try:
            fn = getattr(pro, fn_name)
        except AttributeError:
            continue
        try:
            df = fn(trade_date=trade_date)
            if df is not None and not df.empty:
                return df.copy()
        except Exception:
            continue
    return pd.DataFrame()


def _recent_open_days(pro, end_trade_date: str, lookback_days: int = 20) -> list[str]:
    end_dt = datetime.strptime(end_trade_date, "%Y%m%d")
    start_dt = end_dt - pd.Timedelta(days=max(lookback_days, 5) * 2)
    try:
        cal = pro.trade_cal(
            exchange="SSE",
            start_date=start_dt.strftime("%Y%m%d"),
            end_date=end_trade_date,
            is_open="1",
        )
    except Exception:
        return [end_trade_date]
    if cal is None or cal.empty or "cal_date" not in cal.columns:
        return [end_trade_date]
    days = sorted(cal["cal_date"].astype(str).tolist())
    return days[-lookback_days:] if days else [end_trade_date]


def _resolve_trade_date_with_data(pro, requested_trade_date: str) -> tuple[str, pd.DataFrame]:
    candidates = list(reversed(_recent_open_days(pro, requested_trade_date, lookback_days=20)))
    if requested_trade_date not in candidates:
        candidates = [requested_trade_date] + candidates
    seen = set()
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        df = _fetch_limit_list(pro, d)
        if df is not None and not df.empty:
            return d, df
    return requested_trade_date, pd.DataFrame()


def _to_morning_limit_up(df: pd.DataFrame, cutoff_hms: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if "first_time" not in out.columns:
        out["first_time"] = None
    out["first_time_hms"] = out["first_time"].map(_normalize_hms)

    if "limit" in out.columns:
        out = out[out["limit"].astype(str).str.upper() == "U"]
    elif "pct_chg" in out.columns:
        pct = pd.to_numeric(out["pct_chg"], errors="coerce")
        out = out[pct >= 9.5]

    out = out[out["first_time_hms"].notna()]
    out = out[out["first_time_hms"] <= cutoff_hms]
    if out.empty:
        return out

    if "ts_code" in out.columns:
        out["code6"] = out["ts_code"].astype(str).str.split(".").str[0].str.zfill(6)
    elif "symbol" in out.columns:
        out["code6"] = out["symbol"].astype(str).str.zfill(6)
    else:
        out["code6"] = ""
    return out


def _fetch_stock_basic_name(pro) -> pd.DataFrame:
    try:
        return pro.stock_basic(exchange="", list_status="L", fields="ts_code,symbol,name")
    except Exception:
        return pd.DataFrame(columns=["ts_code", "symbol", "name"])


def _enrich_stock_name(limit_df: pd.DataFrame, basic_df: pd.DataFrame) -> pd.DataFrame:
    if limit_df.empty:
        return limit_df
    out = limit_df.copy()
    if "name" in out.columns:
        out["stock_name"] = out["name"].astype(str).str.strip()
    else:
        out["stock_name"] = ""
    basic_map = {}
    if basic_df is not None and not basic_df.empty and "ts_code" in basic_df.columns:
        basic_map = {
            str(r["ts_code"]): str(r["name"]).strip()
            for _, r in basic_df.iterrows()
            if str(r.get("name", "")).strip()
        }
    if "ts_code" in out.columns and basic_map:
        out.loc[out["stock_name"].eq(""), "stock_name"] = out["ts_code"].map(basic_map).fillna("")
    return out


def _empty_news_df() -> pd.DataFrame:
    return pd.DataFrame(columns=["datetime", "title", "content", "channels"])


def _strip_html(text: object) -> str:
    s = str(text or "")
    s = _HTML_TAG_RE.sub("", s)
    return s.replace("\u3000", " ").strip()


def _filter_news_window(
    rows: list[dict[str, str]], trade_date: str, cutoff_hms: str
) -> pd.DataFrame:
    dash_day = _compact_to_dash(trade_date)
    window_start = f"{dash_day} 07:00:00"
    window_end = f"{dash_day} {cutoff_hms}"
    kept = [
        row
        for row in rows
        if window_start <= str(row.get("datetime", "")) <= window_end
    ]
    if not kept:
        return _empty_news_df()
    return pd.DataFrame(kept)[["datetime", "title", "content", "channels"]].copy()


def _fetch_eastmoney_724(trade_date: str, cutoff_hms: str, max_pages: int = 20) -> pd.DataFrame:
    """东方财富 7×24 全球财经快讯（免费，无需 Tushare news 权限）。"""
    dash_day = _compact_to_dash(trade_date)
    window_start = f"{dash_day} 07:00:00"
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList"
    rows: list[dict[str, str]] = []
    sort_end = ""
    session = requests.Session()
    session.trust_env = False

    for _ in range(max_pages):
        params = {
            "client": "web",
            "biz": "web_724",
            "fastColumn": "102",
            "sortEnd": sort_end,
            "pageSize": "200",
            "req_trace": str(int(time.time() * 1000)),
        }
        resp = session.get(url, params=params, headers=_HTTP_HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        code = str(payload.get("code", ""))
        if code != "1" or not payload.get("data"):
            raise RuntimeError(f"东方财富快讯接口异常: {payload.get('message') or payload}")
        batch = payload["data"].get("fastNewsList") or []
        if not batch:
            break
        for item in batch:
            show_time = str(item.get("showTime", "")).strip()
            title = _strip_html(item.get("title"))
            summary = _strip_html(item.get("summary"))
            rows.append(
                {
                    "datetime": show_time,
                    "title": title,
                    "content": summary or title,
                    "channels": "eastmoney_724",
                }
            )
        sort_end = str(batch[-1].get("realSort") or "")
        if not sort_end or str(batch[-1].get("showTime", "")) < window_start:
            break

    return _filter_news_window(rows, trade_date, cutoff_hms)


def _fetch_sina_724(trade_date: str, cutoff_hms: str, max_pages: int = 30) -> pd.DataFrame:
    """新浪财经 7×24 快讯（东方财富不可用时的回退）。"""
    dash_day = _compact_to_dash(trade_date)
    window_start = f"{dash_day} 07:00:00"
    url = "https://zhibo.sina.com.cn/api/zhibo/feed"
    rows: list[dict[str, str]] = []
    session = requests.Session()
    session.trust_env = False

    for page in range(1, max_pages + 1):
        params = {
            "page": str(page),
            "page_size": "50",
            "zhibo_id": "152",
            "tag_id": "0",
            "dire": "f",
            "dpc": "1",
            "pagesize": "50",
            "type": "1",
        }
        resp = session.get(url, params=params, headers=_HTTP_HEADERS, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        batch = payload.get("result", {}).get("data", {}).get("feed", {}).get("list") or []
        if not batch:
            break
        for item in batch:
            show_time = str(item.get("create_time", "")).strip()
            text = _strip_html(item.get("rich_text"))
            rows.append(
                {
                    "datetime": show_time,
                    "title": "",
                    "content": text,
                    "channels": "sina_724",
                }
            )
        if str(batch[-1].get("create_time", "")) < window_start:
            break

    return _filter_news_window(rows, trade_date, cutoff_hms)


def _fetch_morning_news(trade_date: str, cutoff_hms: str) -> tuple[pd.DataFrame, str]:
    _clear_proxy_env()
    errors: list[str] = []
    for source_name, fetcher in (
        ("eastmoney_724", _fetch_eastmoney_724),
        ("sina_724", _fetch_sina_724),
    ):
        try:
            df = fetcher(trade_date, cutoff_hms)
            if df is not None and not df.empty:
                return df, source_name
            errors.append(f"{source_name}: 返回空结果")
        except Exception as exc:
            errors.append(f"{source_name}: {exc}")
    raise RuntimeError("早间财经快讯拉取失败：" + "；".join(errors))


def _match_news(morning_df: pd.DataFrame, news_df: pd.DataFrame) -> pd.DataFrame:
    if morning_df.empty:
        return pd.DataFrame()
    if news_df.empty:
        base = morning_df[["ts_code", "code6", "stock_name", "first_time_hms"]].copy()
        base["news_datetime"] = ""
        base["news_title"] = ""
        base["news_content"] = ""
        base["channels"] = ""
        base["match_hit"] = 0
        return base

    merged = []
    news = news_df.copy()
    news["text"] = (news["title"].fillna("") + " " + news["content"].fillna("")).astype(str)

    for _, r in morning_df.iterrows():
        ts_code = str(r.get("ts_code", ""))
        code6 = str(r.get("code6", ""))
        stock_name = str(r.get("stock_name", "")).strip()
        first_time_hms = str(r.get("first_time_hms", ""))
        if not stock_name:
            row = {
                "ts_code": ts_code,
                "code6": code6,
                "stock_name": stock_name,
                "first_time_hms": first_time_hms,
                "news_datetime": "",
                "news_title": "",
                "news_content": "",
                "channels": "",
                "match_hit": 0,
            }
            merged.append(row)
            continue

        hit = news[news["text"].str.contains(stock_name, case=False, regex=False)]
        if hit.empty:
            row = {
                "ts_code": ts_code,
                "code6": code6,
                "stock_name": stock_name,
                "first_time_hms": first_time_hms,
                "news_datetime": "",
                "news_title": "",
                "news_content": "",
                "channels": "",
                "match_hit": 0,
            }
            merged.append(row)
            continue

        for _, n in hit.iterrows():
            row = {
                "ts_code": ts_code,
                "code6": code6,
                "stock_name": stock_name,
                "first_time_hms": first_time_hms,
                "news_datetime": str(n.get("datetime", "")),
                "news_title": str(n.get("title", "")),
                "news_content": str(n.get("content", "")),
                "channels": str(n.get("channels", "")),
                "match_hit": 1,
            }
            merged.append(row)
    return pd.DataFrame(merged)


def run(trade_date: str, cutoff_hms: str, out_dir: str) -> None:
    pro = _get_tushare_pro()
    os.makedirs(out_dir, exist_ok=True)

    effective_trade_date, all_limit = _resolve_trade_date_with_data(pro, trade_date)
    if all_limit.empty:
        raise RuntimeError(f"未获取到涨停明细，trade_date={trade_date}")

    morning = _to_morning_limit_up(all_limit, cutoff_hms=cutoff_hms)
    basic = _fetch_stock_basic_name(pro)
    morning = _enrich_stock_name(morning, basic)

    news, news_source = _fetch_morning_news(effective_trade_date, cutoff_hms)
    matched = _match_news(morning, news)

    morning_path = os.path.join(out_dir, f"morning_limit_up_{effective_trade_date}.csv")
    match_path = os.path.join(out_dir, f"morning_limit_up_news_match_{effective_trade_date}.csv")

    morning.to_csv(morning_path, index=False, encoding="utf-8-sig")
    matched.to_csv(match_path, index=False, encoding="utf-8-sig")

    print(f"requested_trade_date={trade_date}, effective_trade_date={effective_trade_date}, cutoff={cutoff_hms}")
    print(f"早间涨停数量: {len(morning)}")
    print(f"早间快讯来源: {news_source}")
    print(f"早间财经快讯数量: {len(news)}")
    print(f"匹配结果行数: {len(matched)}")
    print(f"已导出: {morning_path}")
    print(f"已导出: {match_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="抓取早间涨停并匹配财经快讯")
    parser.add_argument("--trade-date", default="", help="交易日 YYYYMMDD 或 YYYY-MM-DD，默认今天")
    parser.add_argument("--cutoff", default="10:30:00", help="早间截止时间，默认 10:30:00")
    parser.add_argument(
        "--out-dir",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="输出目录，默认脚本所在目录",
    )
    args = parser.parse_args()

    trade_date = _normalize_trade_date(args.trade_date)
    cutoff_hms = _normalize_hms(args.cutoff) or "10:30:00"
    run(trade_date=trade_date, cutoff_hms=cutoff_hms, out_dir=args.out_dir)


if __name__ == "__main__":
    main()
