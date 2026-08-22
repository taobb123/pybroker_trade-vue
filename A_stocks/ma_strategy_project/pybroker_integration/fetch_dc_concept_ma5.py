#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东财概念板块「低位启动 × 资金热门」扫描（抓市场热点）。

数据源（Tushare Pro，需约 6000 积分）：
- dc_index：概念列表、涨跌家数、领涨股等
- dc_daily：概念指数 OHLCV（历史自 2020 年起）
- moneyflow_ind_dc：东财概念板块资金流向（预筛 + 资金分）
- top_list / top_inst / margin_detail / fund_share：资金热门子项
- dc_member：概念成分股 → 资金聚合 / dc_concept_ma5_members.csv / stocks_pool.txt

默认预筛（未指定 --codes 时）= 资金宇宙层（软打分排序，非硬砍）：
用当日涨幅带、昨日资金流入、阳线、量价、60 日位置等软打分，取 TopN 进入评估。

漏斗选股（量化分层）：
1) 资金宇宙：预筛排序 TopN；
2) 低位硬筛：箱体/距低点/启动量价等，过/不过（「命中」只认这一层）；
3) 排序：仅在低位通过者中按资金分（再综合分）排序写池，默认取 Top3；
无低位命中则轮空：不向下游传递股票名单（清空 stocks_pool.txt；成分表写空表）。
可选 --pool-top-n N（N>0）恢复按资金分 TopN 兜底。
综合分 = 低位(0–50) + 资金(0–50)，仅作展示与辅助排序，不作双门槛否决。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/fetch_dc_concept_ma5.py
    python pybroker_integration/fetch_dc_concept_ma5.py --with-members
    python pybroker_integration/fetch_dc_concept_ma5.py --pool-merge   # 与旧池合并去重
    python pybroker_integration/fetch_dc_concept_ma5.py --codes BK1184.DC --diagnose
    python pybroker_integration/fetch_dc_concept_ma5.py --no-prefilter --all-rows
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from concept_capital_factors import (  # noqa: E402
    DEFAULT_MIN_CAPITAL_SCORE,
    ConceptCapitalScore,
    score_concepts_capital,
)
from fetch_a_low_ma5 import (  # noqa: E402
    DEFAULT_STOCKS_POOL_TXT,
    _calendar_start,
    _eval_ma5_trend,
    _volume_up_down_means,
    _yang_yin_counts,
    load_stocks_pool_txt,
)

DEFAULT_OUT_CSV = os.path.join(_SCRIPT_DIR, "dc_concept_ma5_scan.csv")
DEFAULT_MEMBERS_CSV = os.path.join(_SCRIPT_DIR, "dc_concept_ma5_members.csv")
DEFAULT_POOL_TOP_N = 0
DEFAULT_HIT_TOP_N = 3
DC_IDX_TYPE = "概念板块"
REQUEST_SLEEP_SEC = 0.13

CONCEPT_LAUNCH_CONFIG = {
    "history_calendar_days": 200,
    "min_bars": 75,
    "box_bars": 30,
    "launch_bars": 10,
    "low_lookback_bars": 60,
    "box_range_min_pct": 8.0,
    "box_range_max_pct": 25.0,
    "box_position_max": 0.55,
    "launch_min_pct_5d": 3.0,
    "max_dist_from_60d_low_pct": 20.0,
    "prefilter_max_pct_60d": 15.0,
    "prefilter_today_pct_min": 0.0,
    "prefilter_today_pct_max": 3.0,
    "prefilter_min_net_amount": 5_000_000.0,
    "prefilter_min_net_amount_rate": 0.3,
    "prefilter_yesterday_vol_bars": 5,
    # 预筛排序：先按资金软分取 OHLC 复核候选，再按总分取进入评估的 TopN
    "prefilter_top_n": 40,
    "prefilter_ohlc_top_n": 80,
    # 低位半区内 MA5 小加分：min(5, round(ma5_raw * scale / 6))，scale=0.3 → 满分约 5
    "ma5_bonus_scale": 0.3,
    "min_capital_score": DEFAULT_MIN_CAPITAL_SCORE,
}


@dataclass(frozen=True)
class ConceptLaunchSnapshot:
    concept_code: str
    concept_name: str
    signal_date: str
    close: float
    signal: bool
    signal_low: bool
    capital_ok: bool
    score_total: int
    score_low: int
    score_capital: int
    score_launch: int
    score_ma5_bonus: int
    score_mf: int
    score_lhb: int
    score_margin: int
    score_etf: int
    score_inst: int
    box_range_pct: float
    box_avg_position: float
    box_consolidation_ok: bool
    dist_from_60d_low_pct: float
    dist_from_low_ok: bool
    pct_5d: float
    pct_60d: float
    launch_min_pct_ok: bool
    vol_up_gt_down: bool
    yang_gt_yin: bool
    vol_up_down_ratio: float
    yang_days: int
    yin_days: int
    ma5: float
    ma10: float
    ma20: float
    close_ge_ma5: bool
    ma5_up: bool
    ma10_up: bool
    ma5_score_raw: int


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


def _compact(d: str) -> str:
    return pd.Timestamp(d).strftime("%Y%m%d")


def _resolve_trade_date(pro, end_date: str) -> str:
    end_c = _compact(end_date)
    try:
        cal = pro.trade_cal(
            exchange="SSE",
            start_date=(pd.Timestamp(end_date) - pd.Timedelta(days=14)).strftime("%Y%m%d"),
            end_date=end_c,
            is_open="1",
        )
    except Exception:
        return end_c
    if cal is None or cal.empty:
        return end_c
    dates = sorted(cal["cal_date"].astype(str).tolist())
    if not dates:
        return end_c
    if end_c in dates:
        return end_c
    prior = [x for x in dates if x <= end_c]
    return prior[-1] if prior else dates[-1]


def _fetch_open_trade_dates(pro, start_compact: str, end_compact: str) -> List[str]:
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start_compact, end_date=end_compact, is_open="1")
    except Exception:
        return []
    if cal is None or cal.empty:
        return []
    return sorted(cal["cal_date"].astype(str).tolist())


def _prev_trade_date(pro, trade_date_compact: str) -> Optional[str]:
    start = (pd.Timestamp(trade_date_compact) - pd.Timedelta(days=30)).strftime("%Y%m%d")
    days = _fetch_open_trade_dates(pro, start, trade_date_compact)
    if not days:
        return None
    if trade_date_compact not in days:
        prior = [d for d in days if d <= trade_date_compact]
        if not prior:
            return None
        trade_date_compact = prior[-1]
    idx = days.index(trade_date_compact)
    if idx <= 0:
        return None
    return days[idx - 1]


def fetch_moneyflow_ind_dc_day(pro, trade_date_compact: str) -> pd.DataFrame:
    """东财概念板块单日资金流向横截面。"""
    try:
        df = pro.moneyflow_ind_dc(trade_date=trade_date_compact, content_type="概念")
    except Exception:
        df = None
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["ts_code"] = out["ts_code"].astype(str).str.strip()
    if "name" in out.columns:
        out["name"] = out["name"].astype(str).str.strip()
    for col in ("pct_change", "net_amount", "net_amount_rate", "close"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    return out.drop_duplicates(subset=["ts_code"], keep="last")


def _moneyflow_row(mf_df: pd.DataFrame, ts_code: str) -> Dict[str, Any]:
    if mf_df is None or mf_df.empty:
        return {}
    sub = mf_df[mf_df["ts_code"].astype(str) == str(ts_code)]
    if sub.empty:
        return {}
    row = sub.iloc[-1]
    return {k: row[k] for k in row.index}


def _is_yang_bar(row: pd.Series) -> bool:
    o = float(row.get("open", float("nan")))
    c = float(row.get("close", float("nan")))
    return o == o and c == c and c > o


def _yesterday_vol_structure_ok(
    ohlc: pd.DataFrame,
    prev_date_compact: str,
    vol_bars: int,
) -> Tuple[bool, float]:
    """截至昨日（含）近 vol_bars 日：上涨日均量 > 下跌日均量。"""
    if ohlc.empty or vol_bars < 2:
        return False, float("nan")
    d = ohlc.copy()
    d["_dkey"] = d["date"].dt.strftime("%Y%m%d")
    sub = d[d["_dkey"] <= prev_date_compact]
    if len(sub) < vol_bars:
        return False, float("nan")
    seg = sub.iloc[-int(vol_bars):].copy()
    vu, vd, ratio = _volume_up_down_means(seg, int(vol_bars))
    ok = (vu == vu) and (vd == vd) and vd > 0 and vu > vd
    return bool(ok), ratio if ratio == ratio else float("nan")


def _yesterday_yang_ok(ohlc: pd.DataFrame, prev_date_compact: str) -> bool:
    if ohlc.empty:
        return False
    d = ohlc.copy()
    d["_dkey"] = d["date"].dt.strftime("%Y%m%d")
    sub = d[d["_dkey"] == prev_date_compact]
    if sub.empty:
        return False
    return _is_yang_bar(sub.iloc[-1])


def _clip01(x: float) -> float:
    if x != x:
        return 0.0
    return max(0.0, min(1.0, float(x)))


def _score_today_pct_soft(pct_today: float, pct_min: float, pct_max: float) -> int:
    """当日涨幅软分 0–25：理想带内满分，略偏带衰减，不否决。"""
    if pct_today != pct_today:
        return 0
    lo, hi = float(pct_min), float(pct_max)
    if lo < pct_today <= hi:
        return 25
    if pct_today <= lo:
        # 越接近 0 分越高；跌幅过大给 0
        return int(round(12 * _clip01(1.0 + pct_today / max(hi, 1.0))))
    # 高于上限：最多给到 hi*2.5 附近衰减为 0
    over = pct_today - hi
    span = max(hi * 1.5, 1.0)
    return int(round(18 * _clip01(1.0 - over / span)))


def _score_net_inflow_soft(
    net_amt: float,
    net_rate: float,
    min_net_amount: float,
    min_net_amount_rate: float,
) -> int:
    """昨日主力净流入软分 0–30。"""
    if net_amt != net_amt or net_amt <= 0:
        return 0
    amt_t = max(float(min_net_amount), 1.0)
    rate_t = max(float(min_net_amount_rate), 1e-6)
    amt_ok = net_amt >= amt_t
    rate_ok = net_rate == net_rate and net_rate >= rate_t
    if amt_ok and rate_ok:
        return 30
    if amt_ok or rate_ok:
        return 22
    amt_part = _clip01(net_amt / amt_t)
    rate_part = _clip01(net_rate / rate_t) if net_rate == net_rate else 0.0
    return int(round(8 + 12 * max(amt_part, rate_part)))


def _score_vol_structure_soft(vol_ok: bool, vol_ratio: float) -> int:
    """量价结构软分 0–15。"""
    if vol_ok:
        return 15
    if vol_ratio != vol_ratio or vol_ratio <= 0:
        return 0
    # ratio>=1 才理想；0.7~1 给部分分
    return int(round(12 * _clip01((vol_ratio - 0.7) / 0.3)))


def _score_pct60_soft(roc60: float, max_pct_60d: float) -> int:
    """60 日位置软分 0–15：越低位越高。"""
    if roc60 != roc60:
        return 0
    cap = max(float(max_pct_60d), 1.0)
    if roc60 < cap:
        return 15
    if roc60 < cap * 1.8:
        return int(round(15 * _clip01(1.0 - (roc60 - cap) / (cap * 0.8))))
    return 0


def prefilter_fund_flow_launch(
    pro,
    concepts: List[Tuple[str, str]],
    *,
    signal_date_compact: str,
    end_date: str,
    history_calendar_days: int,
    today_pct_min: float,
    today_pct_max: float,
    min_net_amount: float,
    min_net_amount_rate: float,
    yesterday_vol_bars: int,
    max_pct_60d: float,
    sleep_sec: float,
    prefilter_top_n: int = 40,
    prefilter_ohlc_top_n: int = 80,
) -> Tuple[List[Tuple[str, str]], Dict[str, pd.DataFrame], Dict[str, Dict[str, Any]]]:
    """
    预筛 = 板块强弱排序预备（软打分，不硬砍）：
    1) 全候选按当日涨幅带 + 昨日资金流入软分排序；
    2) 取前 ohlc_top_n 拉日线，叠加阳线/量价/60日位置软分；
    3) 按预筛总分取 top_n 进入后续低位×资金评估。
    """
    prev_compact = _prev_trade_date(pro, signal_date_compact)
    if not prev_compact:
        return [], {}, {}

    mf_today = fetch_moneyflow_ind_dc_day(pro, signal_date_compact)
    time.sleep(sleep_sec)
    mf_yesterday = fetch_moneyflow_ind_dc_day(pro, prev_compact)
    time.sleep(sleep_sec)

    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_c = start_dt.strftime("%Y%m%d")
    end_c = _compact(end_date)

    phase1: List[Dict[str, Any]] = []
    for code, name in concepts:
        today_mf = _moneyflow_row(mf_today, code)
        yest_mf = _moneyflow_row(mf_yesterday, code)
        pct_today = float(today_mf.get("pct_change", float("nan")))
        if pct_today != pct_today:
            continue
        net_amt = float(yest_mf.get("net_amount", float("nan")))
        net_rate = float(yest_mf.get("net_amount_rate", float("nan")))
        score_pct = _score_today_pct_soft(pct_today, today_pct_min, today_pct_max)
        score_net = _score_net_inflow_soft(
            net_amt, net_rate, min_net_amount, min_net_amount_rate
        )
        phase1.append(
            {
                "code": code,
                "name": name,
                "pct_today": pct_today,
                "net_amt": net_amt,
                "net_rate": net_rate,
                "score_pct": score_pct,
                "score_net": score_net,
                "score_mf": score_pct + score_net,
            }
        )

    if not phase1:
        return [], {}, {}

    phase1.sort(key=lambda x: (-int(x["score_mf"]), -float(x["pct_today"]), x["code"]))
    ohlc_n = max(1, int(prefilter_ohlc_top_n))
    top_n = max(1, int(prefilter_top_n))
    ohlc_candidates = phase1[: max(ohlc_n, top_n)]

    cache: Dict[str, pd.DataFrame] = {}
    scored: List[Dict[str, Any]] = []
    for row in ohlc_candidates:
        code = str(row["code"])
        name = str(row["name"])
        ohlc = fetch_dc_concept_ohlc(pro, code, start_c, end_c)
        time.sleep(sleep_sec)

        score_yang = 0
        score_vol = 0
        score_pct60 = 0
        vol_ratio = float("nan")
        yang_ok = False
        roc60 = float("nan")
        if not ohlc.empty and len(ohlc) >= max(65, yesterday_vol_bars + 5):
            cache[code] = ohlc
            yang_ok = _yesterday_yang_ok(ohlc, prev_compact)
            score_yang = 15 if yang_ok else 0
            vol_ok, vol_ratio = _yesterday_vol_structure_ok(
                ohlc, prev_compact, yesterday_vol_bars
            )
            score_vol = _score_vol_structure_soft(vol_ok, vol_ratio)
            roc60 = _roc_pct(ohlc["close"], 60)
            score_pct60 = _score_pct60_soft(roc60, max_pct_60d)

        score_prefilter = (
            int(row["score_mf"]) + score_yang + score_vol + score_pct60
        )
        scored.append(
            {
                **row,
                "score_yang": score_yang,
                "score_vol": score_vol,
                "score_pct60": score_pct60,
                "score_prefilter": score_prefilter,
                "vol_ratio": vol_ratio,
                "yang_ok": yang_ok,
                "roc60": roc60,
            }
        )

    scored.sort(
        key=lambda x: (
            -int(x["score_prefilter"]),
            -int(x["score_mf"]),
            -float(x["pct_today"]),
            x["code"],
        )
    )
    kept_rows = scored[:top_n]
    kept: List[Tuple[str, str]] = [(str(r["code"]), str(r["name"])) for r in kept_rows]
    pre_meta: Dict[str, Dict[str, Any]] = {}
    for rank, r in enumerate(kept_rows, start=1):
        code = str(r["code"])
        net_amt = float(r["net_amt"])
        net_rate = float(r["net_rate"])
        vol_ratio = float(r["vol_ratio"])
        roc60 = float(r["roc60"])
        pre_meta[code] = {
            "today_pct_change": round(float(r["pct_today"]), 4),
            "yesterday_net_amount": round(net_amt, 2) if net_amt == net_amt else "",
            "yesterday_net_amount_rate": round(net_rate, 4) if net_rate == net_rate else "",
            "yesterday_vol_ratio": round(vol_ratio, 4) if vol_ratio == vol_ratio else "",
            "yesterday_yang": bool(r["yang_ok"]),
            "prefilter_pct60": round(roc60, 4) if roc60 == roc60 else "",
            "score_prefilter": int(r["score_prefilter"]),
            "score_prefilter_pct": int(r["score_pct"]),
            "score_prefilter_net": int(r["score_net"]),
            "score_prefilter_yang": int(r["score_yang"]),
            "score_prefilter_vol": int(r["score_vol"]),
            "score_prefilter_pct60": int(r["score_pct60"]),
            "prefilter_trade_date": signal_date_compact,
            "prefilter_prev_date": prev_compact,
            "prefilter_rank": rank,
        }

    return kept, cache, pre_meta


def fetch_dc_concept_index(pro, trade_date_compact: str) -> pd.DataFrame:
    df = pro.dc_index(trade_date=trade_date_compact, idx_type=DC_IDX_TYPE)
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["ts_code"] = out["ts_code"].astype(str).str.strip()
    if "name" in out.columns:
        out["name"] = out["name"].astype(str).str.strip()
    return out.drop_duplicates(subset=["ts_code"], keep="last")


def resolve_dc_index_trade_date(pro, end_date: str, *, max_back_sessions: int = 8) -> Tuple[str, pd.DataFrame]:
    anchor = _resolve_trade_date(pro, end_date)
    try:
        cal = pro.trade_cal(
            exchange="SSE",
            start_date=(pd.Timestamp(anchor) - pd.Timedelta(days=60)).strftime("%Y%m%d"),
            end_date=anchor,
            is_open="1",
        )
    except Exception:
        cal = None
    candidates: List[str] = [anchor]
    if cal is not None and not cal.empty:
        open_days = sorted(cal["cal_date"].astype(str).tolist())
        prior = [d for d in open_days if d <= anchor]
        for d in reversed(prior[:-1]):
            if d not in candidates:
                candidates.append(d)
            if len(candidates) >= max_back_sessions:
                break
    for td in candidates:
        df = fetch_dc_concept_index(pro, td)
        if not df.empty:
            return td, df
    return anchor, pd.DataFrame()


def fetch_dc_concept_ohlc(
    pro,
    ts_code: str,
    start_compact: str,
    end_compact: str,
) -> pd.DataFrame:
    try:
        raw = pro.dc_daily(
            ts_code=ts_code,
            start_date=start_compact,
            end_date=end_compact,
            idx_type=DC_IDX_TYPE,
        )
    except Exception:
        raw = None
    if raw is None or raw.empty:
        return pd.DataFrame()
    d = raw.copy()
    d["date"] = pd.to_datetime(d["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    d = d.dropna(subset=["date"]).sort_values("date")
    for col in ("open", "high", "low", "close"):
        d[col] = pd.to_numeric(d.get(col), errors="coerce")
    vol_col = "vol" if "vol" in d.columns else "volume"
    d["volume"] = pd.to_numeric(d.get(vol_col), errors="coerce")
    d = d.dropna(subset=["close"])
    return d[["date", "open", "high", "low", "close", "volume"]].reset_index(drop=True)


def _roc_pct(close: pd.Series, n: int) -> float:
    if close is None or len(close) <= n:
        return float("nan")
    c0 = float(close.iloc[-1 - n])
    c1 = float(close.iloc[-1])
    if c0 != c0 or c1 != c1 or c0 <= 0:
        return float("nan")
    return (c1 / c0 - 1.0) * 100.0


def _box_consolidation_stats(
    d: pd.DataFrame,
    *,
    box_bars: int,
    launch_bars: int,
) -> Tuple[float, float, bool]:
    """横盘段：信号日前 launch_bars 根之前的 box_bars 日箱体统计。"""
    need = int(box_bars) + int(launch_bars)
    if len(d) < need:
        return float("nan"), float("nan"), False
    seg = d.iloc[-(need):-int(launch_bars)]
    hh = float(seg["high"].max())
    ll = float(seg["low"].min())
    mid = (hh + ll) / 2.0
    span = hh - ll
    if span <= 1e-12 or mid <= 1e-12:
        return float("nan"), float("nan"), False
    range_pct = span / mid * 100.0
    positions = (pd.to_numeric(seg["close"], errors="coerce") - ll) / span
    avg_pos = float(positions.mean()) if positions.notna().any() else float("nan")
    return range_pct, avg_pos, True


def _dist_from_n_day_low_pct(d: pd.DataFrame, n: int) -> float:
    if len(d) < n:
        return float("nan")
    seg = d.iloc[-n:]
    ll = float(seg["low"].min())
    c = float(d.iloc[-1]["close"])
    if ll <= 1e-12 or c != c:
        return float("nan")
    return (c / ll - 1.0) * 100.0


def _score_launch_structure(
    *,
    box_range_pct: float,
    box_avg_position: float,
    box_ok: bool,
    vol_ratio: float,
    yang_days: int,
    yin_days: int,
    dist_pct: float,
    max_dist: float,
) -> int:
    """低位启动结构分（0–70，不含 MA5）。"""
    if not box_ok:
        return 0
    s = 0
    if box_range_pct == box_range_pct:
        if 10.0 <= box_range_pct <= 18.0:
            s += 20
        elif 8.0 <= box_range_pct <= 25.0:
            s += 12
    if box_avg_position == box_avg_position:
        if box_avg_position <= 0.35:
            s += 15
        elif box_avg_position <= 0.55:
            s += 8
    if vol_ratio == vol_ratio:
        if vol_ratio >= 1.5:
            s += 20
        elif vol_ratio >= 1.0:
            s += 10
    if yang_days > yin_days:
        margin = yang_days - yin_days
        s += min(10, margin * 2)
    if dist_pct == dist_pct and max_dist > 0:
        if dist_pct <= max_dist * 0.5:
            s += 5
        elif dist_pct <= max_dist:
            s += 2
    return int(max(0, min(70, s)))


def _eval_concept_launch(
    df: pd.DataFrame,
    *,
    concept_code: str,
    concept_name: str,
    min_bars: int,
    box_bars: int,
    launch_bars: int,
    low_lookback_bars: int,
    box_range_min_pct: float,
    box_range_max_pct: float,
    box_position_max: float,
    launch_min_pct_5d: float,
    max_dist_from_60d_low_pct: float,
    ma5_bonus_scale: float,
) -> Optional[ConceptLaunchSnapshot]:
    need = max(
        int(min_bars),
        int(box_bars) + int(launch_bars) + 5,
        int(low_lookback_bars) + 5,
        25,
    )
    if df is None or len(df) < need:
        return None

    d = df.sort_values("date").reset_index(drop=True).copy()
    last = d.iloc[-1]
    c1 = float(last["close"])
    if c1 != c1:
        return None

    box_range_pct, box_avg_pos, box_seg_ok = _box_consolidation_stats(
        d, box_bars=box_bars, launch_bars=launch_bars
    )
    box_consolidation_ok = bool(
        box_seg_ok
        and box_range_pct == box_range_pct
        and box_range_min_pct <= box_range_pct <= box_range_max_pct
        and box_avg_pos == box_avg_pos
        and box_avg_pos <= box_position_max
    )

    dist_pct = _dist_from_n_day_low_pct(d, low_lookback_bars)
    dist_from_low_ok = dist_pct == dist_pct and dist_pct <= max_dist_from_60d_low_pct

    pct_5d = _roc_pct(d["close"], 5)
    pct_60d = _roc_pct(d["close"], 60)
    launch_min_pct_ok = pct_5d == pct_5d and pct_5d >= launch_min_pct_5d

    launch_seg = d.iloc[-int(launch_bars):].copy()
    launch_seg["ma5"] = launch_seg["close"].rolling(5, min_periods=5).mean()
    vu, vd, v_ratio = _volume_up_down_means(launch_seg, int(launch_bars))
    yang_n, yin_n = _yang_yin_counts(launch_seg, int(launch_bars))
    vol_up_gt_down = (vu == vu) and (vd == vd) and vd > 0 and vu > vd
    yang_gt_yin = yang_n > yin_n

    signal_low = bool(
        box_consolidation_ok
        and dist_from_low_ok
        and launch_min_pct_ok
        and vol_up_gt_down
        and yang_gt_yin
    )

    score_launch = _score_launch_structure(
        box_range_pct=box_range_pct,
        box_avg_position=box_avg_pos,
        box_ok=box_consolidation_ok,
        vol_ratio=v_ratio if v_ratio == v_ratio else float("nan"),
        yang_days=yang_n,
        yin_days=yin_n,
        dist_pct=dist_pct,
        max_dist=max_dist_from_60d_low_pct,
    )

    ma5_snap = _eval_ma5_trend(
        d.assign(symbol=concept_code, stock_name=concept_name),
        min_bars=25,
        hug_lookback_bars=5,
        volume_lookback_bars=int(launch_bars),
        persist_lookback_bars=5,
        max_deviation_pct=100.0,
    )
    ma5_score_raw = int(ma5_snap.score_total) if ma5_snap else 0
    # 低位半区 0–50：结构缩放到 0–45 + MA5 最多 5
    score_launch_scaled = int(round(score_launch / 70.0 * 45.0)) if score_launch else 0
    score_ma5_bonus = int(
        max(0, min(5, round(ma5_score_raw * float(ma5_bonus_scale) / 6.0)))
    )
    score_low = int(max(0, min(50, score_launch_scaled + score_ma5_bonus)))
    score_capital = 0
    score_total = score_low
    capital_ok = False
    # 命中暂按低位硬筛；资金分在 attach 后仅用于排序，不再二次否决
    signal = bool(signal_low)

    dt = last["date"]
    try:
        ds = pd.Timestamp(dt).strftime("%Y-%m-%d")
    except Exception:
        ds = str(dt)[:10]

    return ConceptLaunchSnapshot(
        concept_code=concept_code,
        concept_name=concept_name,
        signal_date=ds,
        close=round(c1, 4),
        signal=signal,
        signal_low=signal_low,
        capital_ok=capital_ok,
        score_total=score_total,
        score_low=score_low,
        score_capital=score_capital,
        score_launch=score_launch,
        score_ma5_bonus=score_ma5_bonus,
        score_mf=0,
        score_lhb=0,
        score_margin=0,
        score_etf=0,
        score_inst=0,
        box_range_pct=round(box_range_pct, 4) if box_range_pct == box_range_pct else float("nan"),
        box_avg_position=round(box_avg_pos, 4) if box_avg_pos == box_avg_pos else float("nan"),
        box_consolidation_ok=box_consolidation_ok,
        dist_from_60d_low_pct=round(dist_pct, 4) if dist_pct == dist_pct else float("nan"),
        dist_from_low_ok=dist_from_low_ok,
        pct_5d=round(pct_5d, 4) if pct_5d == pct_5d else float("nan"),
        pct_60d=round(pct_60d, 4) if pct_60d == pct_60d else float("nan"),
        launch_min_pct_ok=launch_min_pct_ok,
        vol_up_gt_down=vol_up_gt_down,
        yang_gt_yin=yang_gt_yin,
        vol_up_down_ratio=round(v_ratio, 4) if v_ratio == v_ratio else float("nan"),
        yang_days=yang_n,
        yin_days=yin_n,
        ma5=round(ma5_snap.ma5, 4) if ma5_snap else float("nan"),
        ma10=round(ma5_snap.ma10, 4) if ma5_snap else float("nan"),
        ma20=round(ma5_snap.ma20, 4) if ma5_snap else float("nan"),
        close_ge_ma5=bool(ma5_snap.close_ge_ma5) if ma5_snap else False,
        ma5_up=bool(ma5_snap.ma5_up) if ma5_snap else False,
        ma10_up=bool(ma5_snap.ma10_up) if ma5_snap else False,
        ma5_score_raw=ma5_score_raw,
    )


def _index_meta_row(index_df: pd.DataFrame, ts_code: str) -> Dict[str, Any]:
    if index_df is None or index_df.empty:
        return {}
    sub = index_df[index_df["ts_code"].astype(str) == str(ts_code)]
    if sub.empty:
        return {}
    row = sub.iloc[-1]
    keys = (
        "pct_change",
        "turnover_rate",
        "up_num",
        "down_num",
        "leading",
        "leading_code",
        "leading_pct",
        "total_mv",
    )
    return {k: row[k] for k in keys if k in row.index}


def scan_dc_concept_launch(
    concepts: List[Tuple[str, str]],
    *,
    pro,
    end_date: str,
    history_calendar_days: int,
    ohlc_cache: Optional[Dict[str, pd.DataFrame]],
    pre_meta: Optional[Dict[str, Dict[str, Any]]],
    index_df: pd.DataFrame,
    sleep_sec: float,
    eval_kwargs: Dict[str, Any],
) -> Tuple[List[ConceptLaunchSnapshot], List[str], List[ConceptLaunchSnapshot], Dict[str, Dict[str, Any]]]:
    end_dt = pd.to_datetime(end_date).to_pydatetime()
    start_dt = _calendar_start(end_dt, history_calendar_days)
    start_c = start_dt.strftime("%Y%m%d")
    end_c = _compact(end_date)
    cache = ohlc_cache or {}
    pre = pre_meta or {}

    hits: List[ConceptLaunchSnapshot] = []
    evaluated: List[ConceptLaunchSnapshot] = []
    skipped: List[str] = []
    extras: Dict[str, Dict[str, Any]] = {}

    for code, name in concepts:
        if code in cache:
            ohlc = cache[code]
        else:
            ohlc = fetch_dc_concept_ohlc(pro, code, start_c, end_c)
            time.sleep(sleep_sec)
        if ohlc.empty:
            skipped.append(f"{name}({code})(无日线)")
            continue

        meta = _index_meta_row(index_df, code)
        extras[code] = {
            "index_pct_change": meta.get("pct_change", ""),
            "turnover_rate": meta.get("turnover_rate", ""),
            "up_num": meta.get("up_num", ""),
            "down_num": meta.get("down_num", ""),
            "leading": meta.get("leading", ""),
            "leading_code": meta.get("leading_code", ""),
            "leading_pct": meta.get("leading_pct", ""),
            **pre.get(code, {}),
        }

        snap = _eval_concept_launch(
            ohlc,
            concept_code=code,
            concept_name=name,
            **eval_kwargs,
        )
        if snap is None:
            skipped.append(f"{name}({code})(数据不足)")
            continue
        evaluated.append(snap)
        # 最终命中 = 低位硬筛；资金分在 attach 后用于排序
        if snap.signal_low:
            hits.append(snap)

    hits.sort(key=lambda x: (-x.score_total, -x.pct_5d if x.pct_5d == x.pct_5d else 0, x.concept_code))
    return hits, skipped, evaluated, extras


def members_map_from_df(mem_df: pd.DataFrame) -> Dict[str, List[str]]:
    """concept_code -> 6 位成分代码列表。"""
    out: Dict[str, List[str]] = {}
    if mem_df is None or mem_df.empty:
        return out
    for concept_code, grp in mem_df.groupby("concept_code"):
        syms: List[str] = []
        seen: set[str] = set()
        for raw in grp.get("con_code", pd.Series(dtype=str)).tolist():
            sym = _con_code_to_symbol(raw)
            if sym and sym not in seen:
                seen.add(sym)
                syms.append(sym)
        out[str(concept_code)] = syms
    return out


def _funnel_rank_key(x: ConceptLaunchSnapshot) -> Tuple[Any, ...]:
    """漏斗排序：资金分主序，综合分/5日涨幅辅助。"""
    return (
        -int(x.score_capital),
        -int(x.score_total),
        -(x.pct_5d if x.pct_5d == x.pct_5d else 0),
        x.concept_code,
    )


def attach_capital_scores(
    snaps: List[ConceptLaunchSnapshot],
    capital_by_code: Dict[str, ConceptCapitalScore],
    *,
    min_capital_score: int,
) -> List[ConceptLaunchSnapshot]:
    """合并资金半区；命中仍只看低位硬筛，资金分用于排序与 capital_ok 标注。"""
    merged: List[ConceptLaunchSnapshot] = []
    for s in snaps:
        cap = capital_by_code.get(s.concept_code)
        if cap is None:
            score_capital = 0
            capital_ok = 0 >= int(min_capital_score)
            score_mf = score_lhb = score_margin = score_etf = score_inst = 0
        else:
            score_capital = int(cap.score_capital)
            capital_ok = bool(cap.capital_ok) or score_capital >= int(min_capital_score)
            score_mf = int(cap.score_mf)
            score_lhb = int(cap.score_lhb)
            score_margin = int(cap.score_margin)
            score_etf = int(cap.score_etf)
            score_inst = int(cap.score_inst)
        score_total = int(max(0, min(100, s.score_low + score_capital)))
        signal = bool(s.signal_low)
        merged.append(
            replace(
                s,
                signal=signal,
                capital_ok=capital_ok,
                score_capital=score_capital,
                score_total=score_total,
                score_mf=score_mf,
                score_lhb=score_lhb,
                score_margin=score_margin,
                score_etf=score_etf,
                score_inst=score_inst,
            )
        )
    return merged


def funnel_low_hits(evaluated: List[ConceptLaunchSnapshot]) -> List[ConceptLaunchSnapshot]:
    """低位硬筛通过者，按资金分排序。"""
    hits = [x for x in evaluated if x.signal_low]
    hits.sort(key=_funnel_rank_key)
    return hits


def dual_gate_hits(evaluated: List[ConceptLaunchSnapshot]) -> List[ConceptLaunchSnapshot]:
    """兼容旧名：等价于 funnel_low_hits。"""
    return funnel_low_hits(evaluated)


def _failed_launch_reasons(s: ConceptLaunchSnapshot) -> List[str]:
    failed: List[str] = []
    if not s.box_consolidation_ok:
        failed.append("30日低位横盘不满足")
    if not s.dist_from_low_ok:
        failed.append("距60日低点过远")
    if not s.launch_min_pct_ok:
        failed.append("近5日涨幅未达启动阈值")
    if not s.vol_up_gt_down:
        failed.append("启动段未放量涨/缩量跌")
    if not s.yang_gt_yin:
        failed.append("启动段阳未多于阴")
    return failed


def snapshots_to_dataframe(
    snaps: List[ConceptLaunchSnapshot],
    extras: Dict[str, Dict[str, Any]],
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for s in snaps:
        m = extras.get(s.concept_code, {})
        rows.append(
            {
                "concept_code": s.concept_code,
                "concept_name": s.concept_name,
                "signal_date": s.signal_date,
                "in_trend": s.signal,
                "signal_low": s.signal_low,
                "capital_ok": s.capital_ok,
                "score_total": s.score_total,
                "score_low": s.score_low,
                "score_capital": s.score_capital,
                "score_mf": s.score_mf,
                "score_lhb": s.score_lhb,
                "score_margin": s.score_margin,
                "score_etf": s.score_etf,
                "score_inst": s.score_inst,
                "mf_net_1d": m.get("mf_net_1d", ""),
                "mf_net_3d": m.get("mf_net_3d", ""),
                "lhb_member_count": m.get("lhb_member_count", ""),
                "lhb_net_amount": m.get("lhb_net_amount", ""),
                "margin_rzye_chg_pct": m.get("margin_rzye_chg_pct", ""),
                "etf_share_chg": m.get("etf_share_chg", ""),
                "inst_net_buy": m.get("inst_net_buy", ""),
                "today_pct_change": m.get("today_pct_change", ""),
                "yesterday_net_amount": m.get("yesterday_net_amount", ""),
                "yesterday_net_amount_rate": m.get("yesterday_net_amount_rate", ""),
                "yesterday_vol_ratio": m.get("yesterday_vol_ratio", ""),
                "score_prefilter": m.get("score_prefilter", ""),
                "prefilter_rank": m.get("prefilter_rank", ""),
                "score_launch": s.score_launch,
                "score_ma5_bonus": s.score_ma5_bonus,
                "ma5_score_raw": s.ma5_score_raw,
                "box_range_pct": s.box_range_pct,
                "box_avg_position": s.box_avg_position,
                "box_consolidation_ok": s.box_consolidation_ok,
                "dist_from_60d_low_pct": s.dist_from_60d_low_pct,
                "pct_5d": s.pct_5d,
                "pct_60d": s.pct_60d,
                "vol_up_down_ratio": s.vol_up_down_ratio,
                "yang_days": s.yang_days,
                "yin_days": s.yin_days,
                "close": s.close,
                "ma5": s.ma5,
                "ma10": s.ma10,
                "ma20": s.ma20,
                "close_ge_ma5": s.close_ge_ma5,
                "ma5_up": s.ma5_up,
                "ma10_up": s.ma10_up,
                "index_pct_change": m.get("index_pct_change", ""),
                "turnover_rate": m.get("turnover_rate", ""),
                "up_num": m.get("up_num", ""),
                "down_num": m.get("down_num", ""),
                "leading": m.get("leading", ""),
                "leading_code": m.get("leading_code", ""),
                "leading_pct": m.get("leading_pct", ""),
                "diagnosis_zh": _diagnosis_zh(s),
            }
        )
    return pd.DataFrame(rows)


def _diagnosis_zh(s: ConceptLaunchSnapshot) -> str:
    label = f"{s.concept_name}({s.concept_code})"
    score_s = (
        f"综合分 {s.score_total}（低位 {s.score_low} + 资金 {s.score_capital}；"
        f"资金明细 流入{s.score_mf}/龙虎{s.score_lhb}/融资{s.score_margin}/"
        f"ETF{s.score_etf}/机构{s.score_inst}）。"
    )
    if s.signal:
        parts = [
            f"{label} 截至 {s.signal_date}：漏斗命中（资金宇宙内 + 低位硬筛通过）。",
            f"30日横盘振幅 {s.box_range_pct:.2f}%、均价位置 {s.box_avg_position:.2f}；",
            f"距60日低点 {s.dist_from_60d_low_pct:.2f}%，近5日 {s.pct_5d:.2f}%、近60日 {s.pct_60d:.2f}%。",
            f"启动段量价比约 {s.vol_up_down_ratio:.2f}，阳 {s.yang_days}/阴 {s.yin_days}。",
            score_s,
        ]
        if s.close_ge_ma5 and s.ma5_up:
            parts.append("MA5 呈上翘且收盘站稳，可作辅助确认。")
        return " ".join(parts)
    failed = "；".join(_failed_launch_reasons(s)) or "未满足"
    return (
        f"{label} 截至 {s.signal_date}：未过低位硬筛（{failed}）。 {score_s}"
    )


def _concept_brief_line(s: ConceptLaunchSnapshot, extras: Dict[str, Dict[str, Any]]) -> str:
    m = extras.get(s.concept_code, {})
    tag = "[命中]" if s.signal else "[未中]"
    reason = ""
    if not s.signal:
        reason = "  " + ("；".join(_failed_launch_reasons(s)) or "")
    lead = m.get("leading", "")
    lead_s = f"  领涨:{lead}" if lead else ""
    today_pct = m.get("today_pct_change", "")
    today_s = f"  当日{today_pct}%" if today_pct != "" else ""
    pref = m.get("score_prefilter", "")
    pref_s = f"  预筛{pref}" if pref != "" else ""
    return (
        f"  {tag} {s.concept_name}({s.concept_code})  {s.signal_date}  "
        f"score={s.score_total}(低位{s.score_low}+资金{s.score_capital})  "
        f"5日{s.pct_5d:.2f}%  距低{s.dist_from_60d_low_pct:.2f}%"
        f"{pref_s}{today_s}{reason}{lead_s}"
    )


def _concept_diagnosis_lines(s: ConceptLaunchSnapshot) -> List[str]:
    label = f"{s.concept_name}({s.concept_code})"
    lines = [
        f"—— {label}  截止 {s.signal_date} ——",
        f"  收盘 {s.close:.4f}  MA5 {s.ma5:.4f}  MA10 {s.ma10:.4f}  MA20 {s.ma20:.4f}",
        (
            f"  横盘30日: 振幅 {s.box_range_pct:.2f}%  均价位置 {s.box_avg_position:.2f}  "
            f"{'OK' if s.box_consolidation_ok else 'NG'}"
        ),
        (
            f"  启动: 距60日低 {s.dist_from_60d_low_pct:.2f}%  5日 {s.pct_5d:.2f}%  60日 {s.pct_60d:.2f}%  "
            f"量比 {s.vol_up_down_ratio:.4f}  阳/阴 {s.yang_days}/{s.yin_days}"
        ),
        (
            f"  评分: 合计 {s.score_total}（低位 {s.score_low} + 资金 {s.score_capital}；"
            f"结构原始 {s.score_launch} MA5加分 {s.score_ma5_bonus}；"
            f"资金 流入{s.score_mf}/龙虎{s.score_lhb}/融资{s.score_margin}/"
            f"ETF{s.score_etf}/机构{s.score_inst}）"
        ),
        (
            f"  门槛: 低位硬筛={'OK' if s.signal_low else 'NG'}  "
            f"资金标注={'OK' if s.capital_ok else 'NG'}  "
            f"漏斗命中={'OK' if s.signal else 'NG'}"
        ),
    ]
    if s.signal:
        lines.append("  **结论: 漏斗命中（资金宇宙内 + 低位硬筛通过）。**")
    else:
        lines.append("  **结论: 未过低位硬筛。** " + "；".join(_failed_launch_reasons(s)))
    lines.append("")
    return lines


def fetch_members_for_concepts(
    pro,
    concept_codes: List[str],
    trade_date_compact: str,
    sleep_sec: float,
) -> pd.DataFrame:
    rows: List[Dict[str, Any]] = []
    for code in concept_codes:
        try:
            df = pro.dc_member(trade_date=trade_date_compact, ts_code=code)
        except Exception:
            df = None
        time.sleep(sleep_sec)
        if df is None or df.empty:
            continue
        for _, r in df.iterrows():
            rows.append(
                {
                    "trade_date": trade_date_compact,
                    "concept_code": code,
                    "con_code": str(r.get("con_code", "")).strip(),
                    "con_name": str(r.get("name", "")).strip(),
                }
            )
    return pd.DataFrame(rows)


def _con_code_to_symbol(con_code: str) -> Optional[str]:
    """东财成分代码 → 6 位 A 股代码。"""
    s = str(con_code or "").strip().upper()
    if not s:
        return None
    digits = "".join(c for c in s.split(".")[0] if c.isdigit())
    if len(digits) < 6:
        return None
    return digits[-6:].zfill(6)


def symbols_from_members_df(mem_df: pd.DataFrame) -> List[str]:
    if mem_df is None or mem_df.empty or "con_code" not in mem_df.columns:
        return []
    out: List[str] = []
    seen: set[str] = set()
    for raw in mem_df["con_code"].tolist():
        sym = _con_code_to_symbol(raw)
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


def write_stocks_pool_txt(
    path: str,
    symbols: List[str],
    *,
    merge: bool = False,
) -> Tuple[int, int]:
    """
    写入 stocks_pool.txt（每行一个 6 位代码）。
    默认 merge=False：仅保留本次 symbols，覆盖旧池。
    merge=True 时在原有池基础上去重追加。
    返回 (写入后总数, 本次新增数)。
    """
    p = os.path.abspath(path)
    base = load_stocks_pool_txt(p) if merge and os.path.isfile(p) else []
    seen = set(base)
    added = 0
    for sym in symbols:
        s = "".join(filter(str.isdigit, str(sym))).zfill(6)
        if len(s) != 6 or s in seen:
            continue
        seen.add(s)
        base.append(s)
        added += 1
    d = os.path.dirname(p)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("\n".join(base))
        if base:
            f.write("\n")
    return len(base), added


def concepts_for_member_fetch(
    hits: List[ConceptLaunchSnapshot],
    evaluated: List[ConceptLaunchSnapshot],
    *,
    pool_top_n: int,
    hit_top_n: int = DEFAULT_HIT_TOP_N,
) -> List[ConceptLaunchSnapshot]:
    """有低位硬筛命中取资金分 Top hit_top_n；否则仅当 pool_top_n>0 时按资金分兜底，默认轮空。"""
    if hits:
        n = int(hit_top_n)
        if n <= 0:
            return []
        return list(hits)[:n]
    n = int(pool_top_n)
    if n <= 0 or not evaluated:
        return []
    return sorted(evaluated, key=_funnel_rank_key)[:n]


def main() -> None:
    cfg = CONCEPT_LAUNCH_CONFIG
    parser = argparse.ArgumentParser(
        description="东财概念扫描：资金宇宙→低位硬筛→资金分排序；命中只认低位硬筛，无命中则轮空不传股票名单"
    )
    parser.add_argument("--codes", default="", help="逗号分隔概念代码；为空则扫全市场（可预筛）")
    parser.add_argument(
        "--no-prefilter",
        action="store_true",
        help="关闭预筛排序（默认：软打分排序后取 TopN 进入评估）",
    )
    parser.add_argument(
        "--prefilter-top-n",
        type=int,
        default=int(cfg["prefilter_top_n"]),
        help="预筛排序后进入低位×资金评估的概念数，默认 40",
    )
    parser.add_argument(
        "--prefilter-ohlc-top-n",
        type=int,
        default=int(cfg["prefilter_ohlc_top_n"]),
        help="预筛阶段拉日线做结构软分的候选数，默认 80",
    )
    parser.add_argument(
        "--prefilter-today-pct-max",
        type=float,
        default=float(cfg["prefilter_today_pct_max"]),
        help="预筛当日涨幅理想上限（%%，软评分锚点），默认 3",
    )
    parser.add_argument(
        "--prefilter-min-net-amount",
        type=float,
        default=float(cfg["prefilter_min_net_amount"]),
        help="预筛昨日主力净流入理想锚点（元），默认 500万",
    )
    parser.add_argument(
        "--prefilter-min-net-rate",
        type=float,
        default=float(cfg["prefilter_min_net_amount_rate"]),
        help="预筛昨日主力净流入占比理想锚点（%%），默认 0.3",
    )
    parser.add_argument(
        "--prefilter-yesterday-vol-bars",
        type=int,
        default=int(cfg["prefilter_yesterday_vol_bars"]),
        help="预筛量价结构回看根数，默认 5",
    )
    parser.add_argument(
        "--prefilter-max-pct-60d",
        type=float,
        default=float(cfg["prefilter_max_pct_60d"]),
        help="预筛60日涨幅理想上限（%%，软评分锚点），默认 15",
    )
    parser.add_argument("--diagnose", action="store_true")
    parser.add_argument("--end-date", default=datetime.now().strftime("%Y-%m-%d"))
    parser.add_argument("--days", type=int, default=int(cfg["history_calendar_days"]))
    parser.add_argument("--min-bars", type=int, default=int(cfg["min_bars"]))
    parser.add_argument("--box-bars", type=int, default=int(cfg["box_bars"]))
    parser.add_argument("--launch-bars", type=int, default=int(cfg["launch_bars"]))
    parser.add_argument("--low-lookback", type=int, default=int(cfg["low_lookback_bars"]))
    parser.add_argument("--box-range-min", type=float, default=float(cfg["box_range_min_pct"]))
    parser.add_argument("--box-range-max", type=float, default=float(cfg["box_range_max_pct"]))
    parser.add_argument("--box-position-max", type=float, default=float(cfg["box_position_max"]))
    parser.add_argument("--launch-min-pct-5d", type=float, default=float(cfg["launch_min_pct_5d"]))
    parser.add_argument("--max-dist-from-low", type=float, default=float(cfg["max_dist_from_60d_low_pct"]))
    parser.add_argument("--ma5-bonus-scale", type=float, default=float(cfg["ma5_bonus_scale"]))
    parser.add_argument(
        "--min-capital-score",
        type=int,
        default=int(cfg["min_capital_score"]),
        help="资金分标注门槛 capital_ok（0–50），默认 25；不参与命中硬筛，仅展示/诊断",
    )
    parser.add_argument(
        "--no-etf-factor",
        action="store_true",
        help="关闭 ETF 份额加分（减少接口调用）",
    )
    parser.add_argument("--sleep", type=float, default=REQUEST_SLEEP_SEC)
    parser.add_argument("--all-rows", action="store_true")
    parser.add_argument("--with-members", action="store_true")
    parser.add_argument(
        "--write-stocks-pool",
        default=DEFAULT_STOCKS_POOL_TXT,
        help=f"将命中成分股写入股票池（默认 {DEFAULT_STOCKS_POOL_TXT}；传空字符串关闭）",
    )
    parser.add_argument(
        "--no-write-stocks-pool",
        action="store_true",
        help="不写入 stocks_pool.txt",
    )
    parser.add_argument(
        "--hit-top-n",
        type=int,
        default=DEFAULT_HIT_TOP_N,
        help="低位硬筛命中时，取资金分前 N 个概念拉成分股，默认 3；传 0 关闭写成分",
    )
    parser.add_argument(
        "--pool-top-n",
        type=int,
        default=DEFAULT_POOL_TOP_N,
        help="无低位硬筛命中时：0=轮空不传股票名单（默认）；N>0 则按资金分 TopN 兜底",
    )
    parser.add_argument(
        "--pool-merge",
        action="store_true",
        help="股票池与原有池合并去重（默认覆盖旧池，仅保留本次命中概念成分；轮空时写空池）",
    )
    parser.add_argument("--out-csv", default=DEFAULT_OUT_CSV)
    parser.add_argument("--out-members-csv", default=DEFAULT_MEMBERS_CSV)
    args = parser.parse_args()

    eval_kwargs = {
        "min_bars": int(args.min_bars),
        "box_bars": int(args.box_bars),
        "launch_bars": int(args.launch_bars),
        "low_lookback_bars": int(args.low_lookback),
        "box_range_min_pct": float(args.box_range_min),
        "box_range_max_pct": float(args.box_range_max),
        "box_position_max": float(args.box_position_max),
        "launch_min_pct_5d": float(args.launch_min_pct_5d),
        "max_dist_from_60d_low_pct": float(args.max_dist_from_low),
        "ma5_bonus_scale": float(args.ma5_bonus_scale),
    }

    pro = _get_tushare_pro()
    trade_date_compact, index_df = resolve_dc_index_trade_date(pro, str(args.end_date))
    time.sleep(float(args.sleep))
    if index_df.empty:
        print(f"dc_index 无数据（已回退至 {trade_date_compact}），请检查权限或 --end-date。")
        sys.exit(2)

    trade_date_show = pd.Timestamp(trade_date_compact).strftime("%Y-%m-%d")
    code_arg = str(args.codes).strip()
    if code_arg:
        wanted = {x.strip().upper() for x in code_arg.split(",") if x.strip()}
        sub = index_df[index_df["ts_code"].astype(str).str.upper().isin(wanted)]
        concepts = [(str(r["ts_code"]), str(r.get("name", "") or "").strip()) for _, r in sub.iterrows()]
        ohlc_cache: Dict[str, pd.DataFrame] = {}
        pre_meta: Dict[str, Dict[str, Any]] = {}
    else:
        concepts = [
            (str(r["ts_code"]), str(r.get("name", "") or "").strip())
            for _, r in index_df.iterrows()
            if str(r.get("ts_code", "")).strip()
        ]
        ohlc_cache = {}
        pre_meta = {}
        if not bool(args.no_prefilter):
            print(
                f"预筛排序：涨幅带/资金/阳线/量价/60日位置软打分，"
                f"取 Top{int(args.prefilter_top_n)} 进入评估"
                f"（OHLC 复核 Top{int(args.prefilter_ohlc_top_n)}）…"
            )
            concepts, ohlc_cache, pre_meta = prefilter_fund_flow_launch(
                pro,
                concepts,
                signal_date_compact=trade_date_compact,
                end_date=str(args.end_date),
                history_calendar_days=int(args.days),
                today_pct_min=float(cfg["prefilter_today_pct_min"]),
                today_pct_max=float(args.prefilter_today_pct_max),
                min_net_amount=float(args.prefilter_min_net_amount),
                min_net_amount_rate=float(args.prefilter_min_net_rate),
                yesterday_vol_bars=int(args.prefilter_yesterday_vol_bars),
                max_pct_60d=float(args.prefilter_max_pct_60d),
                sleep_sec=float(args.sleep),
                prefilter_top_n=int(args.prefilter_top_n),
                prefilter_ohlc_top_n=int(args.prefilter_ohlc_top_n),
            )
            print(f"预筛排序完成：进入评估 {len(concepts)} 个概念。")

    if not concepts:
        print("概念列表为空（无可用资金横截面数据，可试 --no-prefilter 或检查权限/交易日）。")
        sys.exit(2)

    _low_hits, skipped, evaluated, extras = scan_dc_concept_launch(
        concepts,
        pro=pro,
        end_date=str(args.end_date),
        history_calendar_days=int(args.days),
        ohlc_cache=ohlc_cache,
        pre_meta=pre_meta,
        index_df=index_df,
        sleep_sec=float(args.sleep),
        eval_kwargs=eval_kwargs,
    )

    # 资金聚合需要成分股：先拉评估宇宙成分，再打资金分
    capital_by_code: Dict[str, ConceptCapitalScore] = {}
    mem_all = pd.DataFrame()
    if evaluated:
        print(f"资金热门评分：拉取 {len(evaluated)} 个概念成分并聚合龙虎榜/融资/ETF/机构 …")
        eval_codes = [s.concept_code for s in evaluated]
        mem_all = fetch_members_for_concepts(
            pro, eval_codes, trade_date_compact, float(args.sleep)
        )
        concept_members = members_map_from_df(mem_all)
        capital_by_code = score_concepts_capital(
            pro,
            concepts=[(s.concept_code, s.concept_name) for s in evaluated],
            concept_members=concept_members,
            trade_date_compact=trade_date_compact,
            min_capital_score=int(args.min_capital_score),
            sleep_sec=float(args.sleep),
            enable_etf=not bool(args.no_etf_factor),
        )
        for code, cap in capital_by_code.items():
            extras.setdefault(code, {})
            extras[code].update(
                {
                    "mf_net_1d": round(cap.mf_net_1d, 2) if cap.mf_net_1d == cap.mf_net_1d else "",
                    "mf_net_3d": round(cap.mf_net_3d, 2) if cap.mf_net_3d == cap.mf_net_3d else "",
                    "lhb_member_count": cap.lhb_member_count,
                    "lhb_net_amount": round(cap.lhb_net_amount, 2),
                    "margin_rzye_chg_pct": (
                        round(cap.margin_rzye_chg_pct, 4)
                        if cap.margin_rzye_chg_pct == cap.margin_rzye_chg_pct
                        else ""
                    ),
                    "etf_share_chg": round(cap.etf_share_chg, 4),
                    "inst_net_buy": round(cap.inst_net_buy, 2),
                }
            )

    evaluated = attach_capital_scores(
        evaluated,
        capital_by_code,
        min_capital_score=int(args.min_capital_score),
    )
    hits = funnel_low_hits(evaluated)

    out_snaps = (
        sorted(evaluated, key=lambda x: (-int(x.signal),) + _funnel_rank_key(x))
        if bool(args.all_rows)
        else hits
    )
    out_df = snapshots_to_dataframe(out_snaps, extras)
    out_path = os.path.abspath(args.out_csv)
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    out_df.to_csv(out_path, index=False, encoding="utf-8-sig")

    print(
        f"东财概念漏斗 | 锚定 {trade_date_show} | 评估 {len(concepts)} | "
        f"低位通过 {sum(1 for x in evaluated if x.signal_low)} | "
        f"漏斗命中 {len(hits)} | 资金标注 "
        f"{sum(1 for x in evaluated if x.capital_ok)} | CSV {len(out_snaps)} 行"
    )
    print(f"已写入: {out_path}")

    member_snaps = concepts_for_member_fetch(
        hits,
        evaluated,
        pool_top_n=int(args.pool_top_n),
        hit_top_n=int(args.hit_top_n),
    )
    used_topn_fallback = bool(not hits and member_snaps)
    used_hit_topn = bool(hits and member_snaps and len(member_snaps) < len(hits))
    write_pool = (
        not bool(args.no_write_stocks_pool)
        and str(args.write_stocks_pool or "").strip() != ""
    )
    need_members = bool(args.with_members) or write_pool

    if need_members and member_snaps:
        if used_topn_fallback:
            print(
                f"无低位硬筛通过，启用资金分 Top{int(args.pool_top_n)} 兜底"
                f"（{len(member_snaps)} 个概念）。",
                file=sys.stderr,
            )
        elif used_hit_topn or (hits and len(hits) > int(args.hit_top_n)):
            print(
                f"低位命中 {len(hits)}，成分/股票池仅取资金分 Top{int(args.hit_top_n)}"
                f"（{len(member_snaps)} 个概念）。",
                file=sys.stderr,
            )
        hit_codes = {s.concept_code for s in member_snaps}
        name_map = {s.concept_code: s.concept_name for s in member_snaps}
        if not mem_all.empty:
            mem_df = mem_all[mem_all["concept_code"].isin(hit_codes)].copy()
        else:
            mem_df = fetch_members_for_concepts(
                pro, list(hit_codes), trade_date_compact, float(args.sleep)
            )
        if not mem_df.empty:
            if "concept_name" not in mem_df.columns:
                mem_df.insert(1, "concept_name", mem_df["concept_code"].map(name_map))
            else:
                mem_df["concept_name"] = mem_df["concept_code"].map(name_map)
            if bool(args.with_members):
                mem_path = os.path.abspath(args.out_members_csv)
                mem_df.to_csv(mem_path, index=False, encoding="utf-8-sig")
                print(f"成分股已写入: {mem_path}（{len(mem_df)} 行）")
            if write_pool:
                syms = symbols_from_members_df(mem_df)
                pool_path = os.path.abspath(str(args.write_stocks_pool))
                total, added = write_stocks_pool_txt(
                    pool_path,
                    syms,
                    merge=bool(args.pool_merge),
                )
                src = (
                    f"命中Top{int(args.hit_top_n)}"
                    if hits
                    else f"Top{int(args.pool_top_n)}"
                )
                mode = "合并" if bool(args.pool_merge) else "覆盖"
                print(
                    f"股票池已更新({mode}): {pool_path}（来源{src} {len(member_snaps)} 概念，"
                    f"成分 {len(syms)} 只，写入 {total} 只）"
                )
        elif need_members:
            print("提示: 未拉取到成分股（dc_member 为空），跳过 CSV/股票池写入。", file=sys.stderr)
    elif need_members and not member_snaps:
        print(
            "轮空: 无低位硬筛命中，不向下游传递股票名单。",
            file=sys.stderr,
        )
        if bool(args.with_members):
            mem_path = os.path.abspath(args.out_members_csv)
            empty_mem = pd.DataFrame(
                columns=["trade_date", "concept_name", "concept_code", "con_code", "con_name"]
            )
            empty_mem.to_csv(mem_path, index=False, encoding="utf-8-sig")
            print(f"成分股已清空(轮空): {mem_path}（0 行）")
        if write_pool and not bool(args.pool_merge):
            pool_path = os.path.abspath(str(args.write_stocks_pool))
            total, _ = write_stocks_pool_txt(pool_path, [], merge=False)
            print(f"股票池已清空(轮空): {pool_path}（{total} 只）")

    print("=" * 72)
    print("【漏斗命中 · 资金宇宙 → 低位硬筛 → 资金分排序】")
    if hits:
        if len(hits) > int(args.hit_top_n):
            print(
                f"  （低位命中 {len(hits)}，下列为写入成分的资金分 Top{int(args.hit_top_n)}）"
            )
        for s in member_snaps if member_snaps else hits[: max(0, int(args.hit_top_n))]:
            print(_concept_brief_line(s, extras))
    elif used_topn_fallback:
        print(f"  （无低位通过，已按资金分 Top{int(args.pool_top_n)} 兜底）")
        for s in member_snaps:
            print(_concept_brief_line(s, extras))
    else:
        print("  （无命中，今日轮空）")

    misses = [x for x in evaluated if not x.signal]
    if misses and not used_topn_fallback:
        print("—— 未过低位硬筛（按资金分 Top10 仅展示）——")
        for snap in sorted(misses, key=_funnel_rank_key)[:10]:
            print(_concept_brief_line(snap, extras))

    if skipped:
        print("跳过: " + ", ".join(skipped[:15]) + (" ..." if len(skipped) > 15 else ""))

    if bool(args.diagnose) and evaluated:
        print("=" * 72)
        print("【逐概念诊断】")
        for snap in sorted(evaluated, key=lambda x: (-int(x.signal),) + _funnel_rank_key(x)):
            for line in _concept_diagnosis_lines(snap):
                print(line)


if __name__ == "__main__":
    main()
