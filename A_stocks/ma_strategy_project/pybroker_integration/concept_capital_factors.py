#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东财概念「资金热门」评分（0–50）。

日频主因子：
  - 主力净流入（概念 moneyflow_ind_dc）~35% → 最高 18 分
  - 龙虎榜成分聚合（top_list）~25% → 最高 12 分
  - 融资余额变化（margin_detail）~20% → 最高 10 分
确认加分：
  - ETF 份额粗映射（fund_basic 名称包含概念名 + fund_share）~10% → 最高 5 分
  - 机构席位（top_inst / 龙虎榜理由含「机构」）~10% → 最高 5 分

缺数据时该项为 0，不否决；调用方用 score_capital 做漏斗排序与 capital_ok 标注（不再作双门槛否决）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

import pandas as pd

# 资金半区满分 50；子项上限合计 50
CAPITAL_POINTS = {
    "moneyflow": 18,
    "lhb": 12,
    "margin": 10,
    "etf": 5,
    "inst": 5,
}

DEFAULT_MIN_CAPITAL_SCORE = 25
MF_LOOKBACK_DAYS = 3
REQUEST_SLEEP_SEC = 0.13


@dataclass(frozen=True)
class ConceptCapitalScore:
    concept_code: str
    score_capital: int
    score_mf: int
    score_lhb: int
    score_margin: int
    score_etf: int
    score_inst: int
    capital_ok: bool
    mf_net_1d: float
    mf_net_3d: float
    mf_rate_1d: float
    lhb_member_count: int
    lhb_net_amount: float
    margin_rzye_chg_pct: float
    etf_share_chg: float
    inst_net_buy: float
    detail: Dict[str, Any]


def _safe_float(v: Any, default: float = float("nan")) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def _norm_symbol6(ts_code: str) -> Optional[str]:
    s = str(ts_code or "").strip().upper()
    if not s:
        return None
    digits = "".join(c for c in s.split(".")[0] if c.isdigit())
    if len(digits) < 6:
        return None
    return digits[-6:].zfill(6)


def fetch_moneyflow_days(
    pro,
    trade_dates: List[str],
    *,
    sleep_sec: float = REQUEST_SLEEP_SEC,
) -> Dict[str, pd.DataFrame]:
    """trade_date -> moneyflow_ind_dc 概念横截面。"""
    out: Dict[str, pd.DataFrame] = {}
    for td in trade_dates:
        try:
            df = pro.moneyflow_ind_dc(trade_date=td, content_type="概念")
        except Exception:
            df = None
        time.sleep(sleep_sec)
        if df is None or df.empty:
            out[td] = pd.DataFrame()
            continue
        d = df.copy()
        d["ts_code"] = d["ts_code"].astype(str).str.strip()
        for col in ("net_amount", "net_amount_rate", "pct_change"):
            if col in d.columns:
                d[col] = pd.to_numeric(d[col], errors="coerce")
        out[td] = d.drop_duplicates(subset=["ts_code"], keep="last")
    return out


def fetch_top_list_day(pro, trade_date: str, *, sleep_sec: float = REQUEST_SLEEP_SEC) -> pd.DataFrame:
    try:
        df = pro.top_list(trade_date=trade_date)
    except Exception:
        df = None
    time.sleep(sleep_sec)
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["ts_code"] = d["ts_code"].astype(str).str.strip().str.upper()
    d["sym6"] = d["ts_code"].map(_norm_symbol6)
    for col in ("net_amount", "l_buy", "l_sell", "amount"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    if "reason" in d.columns:
        d["reason"] = d["reason"].astype(str)
    return d


def fetch_top_inst_day(pro, trade_date: str, *, sleep_sec: float = REQUEST_SLEEP_SEC) -> pd.DataFrame:
    try:
        df = pro.top_inst(trade_date=trade_date)
    except Exception:
        df = None
    time.sleep(sleep_sec)
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["ts_code"] = d["ts_code"].astype(str).str.strip().str.upper()
    d["sym6"] = d["ts_code"].map(_norm_symbol6)
    for col in ("buy", "sell", "net_buy"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
        elif col == "net_buy" and "exalter" not in d.columns:
            # 部分版本用 buy/sell
            pass
    if "net_buy" not in d.columns and "buy" in d.columns and "sell" in d.columns:
        d["net_buy"] = d["buy"].fillna(0) - d["sell"].fillna(0)
    return d


def fetch_margin_detail_day(
    pro,
    trade_date: str,
    *,
    sleep_sec: float = REQUEST_SLEEP_SEC,
) -> pd.DataFrame:
    try:
        df = pro.margin_detail(trade_date=trade_date)
    except Exception:
        df = None
    time.sleep(sleep_sec)
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["ts_code"] = d["ts_code"].astype(str).str.strip().str.upper()
    d["sym6"] = d["ts_code"].map(_norm_symbol6)
    for col in ("rzye", "rzmre", "rqye"):
        if col in d.columns:
            d[col] = pd.to_numeric(d[col], errors="coerce")
    return d.drop_duplicates(subset=["sym6"], keep="last")


def _recent_trade_dates(pro, end_compact: str, n: int) -> List[str]:
    start = (pd.Timestamp(end_compact) - pd.Timedelta(days=max(40, n * 3))).strftime("%Y%m%d")
    try:
        cal = pro.trade_cal(exchange="SSE", start_date=start, end_date=end_compact, is_open="1")
    except Exception:
        return [end_compact]
    if cal is None or cal.empty:
        return [end_compact]
    days = sorted(cal["cal_date"].astype(str).tolist())
    days = [d for d in days if d <= end_compact]
    return days[-n:] if days else [end_compact]


def _member_sym_set(members: List[str]) -> Set[str]:
    out: Set[str] = set()
    for m in members or []:
        s = _norm_symbol6(m) or "".join(c for c in str(m) if c.isdigit()).zfill(6)[-6:]
        if len(s) == 6 and s.isdigit():
            out.add(s)
    return out


def _score_moneyflow_row(
    code: str,
    mf_by_day: Dict[str, pd.DataFrame],
    dates_asc: List[str],
) -> Tuple[int, float, float, float]:
    """返回 (分, 1日净流入, 3日净流入, 1日净占比)。"""
    nets: List[float] = []
    rate_1d = float("nan")
    for i, td in enumerate(reversed(dates_asc)):  # 从近到远
        df = mf_by_day.get(td)
        if df is None or df.empty:
            nets.append(float("nan"))
            continue
        sub = df[df["ts_code"].astype(str) == str(code)]
        if sub.empty:
            nets.append(float("nan"))
            continue
        net = _safe_float(sub.iloc[-1].get("net_amount"))
        nets.append(net)
        if i == 0:
            rate_1d = _safe_float(sub.iloc[-1].get("net_amount_rate"))
    net_1d = nets[0] if nets else float("nan")
    valid = [x for x in nets if x == x]
    net_3d = float(sum(valid)) if valid else float("nan")

    pts = 0
    max_pts = CAPITAL_POINTS["moneyflow"]
    if net_1d == net_1d and net_1d > 0:
        pts += 6
        if net_1d >= 50_000_000:
            pts += 4
        elif net_1d >= 20_000_000:
            pts += 2
        elif net_1d >= 5_000_000:
            pts += 1
    if rate_1d == rate_1d and rate_1d >= 0.3:
        pts += 2
        if rate_1d >= 1.0:
            pts += 2
    if net_3d == net_3d and net_3d > 0:
        pts += 2
        if net_3d >= 100_000_000:
            pts += 2
        elif net_3d >= net_1d * 1.5 if net_1d == net_1d and net_1d > 0 else False:
            pts += 1
    return int(max(0, min(max_pts, pts))), net_1d, net_3d, rate_1d


def _score_lhb_for_members(
    members: Set[str],
    top_df: pd.DataFrame,
) -> Tuple[int, int, float]:
    max_pts = CAPITAL_POINTS["lhb"]
    if not members or top_df is None or top_df.empty or "sym6" not in top_df.columns:
        return 0, 0, 0.0
    sub = top_df[top_df["sym6"].isin(members)]
    if sub.empty:
        return 0, 0, 0.0
    # 同一股票可能多理由重复，按代码聚合净买
    g = sub.groupby("sym6", as_index=False)["net_amount"].sum()
    cnt = int(len(g))
    net = float(g["net_amount"].fillna(0).sum())
    pts = 0
    if cnt >= 1:
        pts += 4
    if cnt >= 2:
        pts += 3
    if cnt >= 3:
        pts += 2
    if net > 0:
        pts += 2
        if net >= 100_000_000:
            pts += 1
    return int(max(0, min(max_pts, pts))), cnt, net


def _score_margin_for_members(
    members: Set[str],
    margin_today: pd.DataFrame,
    margin_prev: pd.DataFrame,
) -> Tuple[int, float]:
    max_pts = CAPITAL_POINTS["margin"]
    if not members or margin_today is None or margin_today.empty:
        return 0, float("nan")
    t = margin_today[margin_today["sym6"].isin(members)]
    if t.empty or "rzye" not in t.columns:
        return 0, float("nan")
    rzye_t = float(t["rzye"].fillna(0).sum())
    rzye_p = float("nan")
    if margin_prev is not None and not margin_prev.empty and "rzye" in margin_prev.columns:
        p = margin_prev[margin_prev["sym6"].isin(members)]
        if not p.empty:
            rzye_p = float(p["rzye"].fillna(0).sum())
    chg_pct = float("nan")
    if rzye_p == rzye_p and rzye_p > 0:
        chg_pct = (rzye_t - rzye_p) / rzye_p * 100.0
    pts = 0
    rzmre = float(t["rzmre"].fillna(0).sum()) if "rzmre" in t.columns else 0.0
    if chg_pct == chg_pct and chg_pct > 0:
        pts += 4
        if chg_pct >= 3.0:
            pts += 3
        elif chg_pct >= 1.0:
            pts += 2
        elif chg_pct >= 0.3:
            pts += 1
    if rzmre > 0:
        pts += 1
        if rzmre >= 50_000_000:
            pts += 2
    return int(max(0, min(max_pts, pts))), chg_pct


def _load_etf_name_map(pro, *, sleep_sec: float) -> pd.DataFrame:
    """ETF 列表：ts_code, name。失败返回空表。"""
    try:
        df = pro.fund_basic(market="E", status="L")
    except Exception:
        try:
            df = pro.fund_basic(market="E")
        except Exception:
            df = None
    time.sleep(sleep_sec)
    if df is None or df.empty:
        return pd.DataFrame()
    d = df.copy()
    d["ts_code"] = d["ts_code"].astype(str).str.strip()
    d["name"] = d["name"].astype(str)
    # 尽量只留 ETF
    mask = d["name"].str.contains("ETF", case=False, na=False)
    if "fund_type" in d.columns:
        mask = mask | d["fund_type"].astype(str).str.contains("ETF", case=False, na=False)
    d = d.loc[mask, ["ts_code", "name"]].drop_duplicates(subset=["ts_code"])
    return d


def _score_etf_for_concept(
    concept_name: str,
    etf_df: pd.DataFrame,
    share_chg_by_code: Dict[str, float],
) -> Tuple[int, float]:
    max_pts = CAPITAL_POINTS["etf"]
    name = str(concept_name or "").strip()
    if not name or etf_df is None or etf_df.empty:
        return 0, 0.0
    # 去掉常见后缀噪声，取较短核心名做包含匹配
    core = name.replace("概念", "").replace("板块", "").strip()
    if len(core) < 2:
        return 0, 0.0
    hit = etf_df[etf_df["name"].str.contains(core, regex=False, na=False)]
    if hit.empty and len(core) >= 4:
        hit = etf_df[etf_df["name"].str.contains(core[:2], regex=False, na=False)]
    if hit.empty:
        return 0, 0.0
    total_chg = 0.0
    matched = 0
    for code in hit["ts_code"].tolist():
        chg = share_chg_by_code.get(str(code))
        if chg is None or chg != chg:
            continue
        total_chg += float(chg)
        matched += 1
    if matched == 0:
        # 有映射但无份额数据：给微弱确认分
        return 1, 0.0
    pts = 1
    if total_chg > 0:
        pts += 2
        if total_chg >= 1e7:
            pts += 2
        elif total_chg >= 1e6:
            pts += 1
    return int(max(0, min(max_pts, pts))), total_chg


def _fetch_etf_share_chg(
    pro,
    etf_codes: List[str],
    trade_date: str,
    prev_date: Optional[str],
    *,
    sleep_sec: float,
) -> Dict[str, float]:
    """ETF 最新份额相对前一交易日变化（fd_share，万份等单位随接口，只比方向/相对）。"""
    out: Dict[str, float] = {}
    if not etf_codes or not prev_date:
        return out
    # 接口常按 ts_code 查询；批量控制调用次数
    for code in etf_codes[:80]:
        try:
            df = pro.fund_share(ts_code=code, start_date=prev_date, end_date=trade_date)
        except Exception:
            df = None
        time.sleep(sleep_sec)
        if df is None or df.empty or "fd_share" not in df.columns:
            continue
        d = df.copy()
        d["trade_date"] = d["trade_date"].astype(str)
        d["fd_share"] = pd.to_numeric(d["fd_share"], errors="coerce")
        d = d.sort_values("trade_date")
        row_t = d[d["trade_date"] == trade_date]
        row_p = d[d["trade_date"] == prev_date]
        if row_t.empty or row_p.empty:
            if len(d) >= 2:
                out[code] = float(d.iloc[-1]["fd_share"] - d.iloc[-2]["fd_share"])
            continue
        out[code] = float(row_t.iloc[-1]["fd_share"] - row_p.iloc[-1]["fd_share"])
    return out


def _score_inst_for_members(
    members: Set[str],
    top_df: pd.DataFrame,
    inst_df: pd.DataFrame,
) -> Tuple[int, float]:
    max_pts = CAPITAL_POINTS["inst"]
    net = 0.0
    if inst_df is not None and not inst_df.empty and "sym6" in inst_df.columns:
        sub = inst_df[inst_df["sym6"].isin(members)]
        if not sub.empty and "net_buy" in sub.columns:
            net = float(sub["net_buy"].fillna(0).sum())
    # 龙虎榜理由含机构
    reason_hit = 0
    if top_df is not None and not top_df.empty and "reason" in top_df.columns:
        sub2 = top_df[top_df["sym6"].isin(members)]
        if not sub2.empty:
            reason_hit = int(sub2["reason"].str.contains("机构", na=False).sum())
    pts = 0
    if net > 0:
        pts += 2
        if net >= 50_000_000:
            pts += 2
        elif net >= 10_000_000:
            pts += 1
    if reason_hit >= 1:
        pts += 1
    return int(max(0, min(max_pts, pts))), net


def score_concepts_capital(
    pro,
    *,
    concepts: List[Tuple[str, str]],
    concept_members: Dict[str, List[str]],
    trade_date_compact: str,
    min_capital_score: int = DEFAULT_MIN_CAPITAL_SCORE,
    sleep_sec: float = REQUEST_SLEEP_SEC,
    enable_etf: bool = True,
) -> Dict[str, ConceptCapitalScore]:
    """
    对概念列表打资金分。

    concept_members: concept_code -> 6 位代码列表（可空，则龙虎榜/融资/机构为 0）。
    """
    dates = _recent_trade_dates(pro, trade_date_compact, MF_LOOKBACK_DAYS)
    prev = dates[-2] if len(dates) >= 2 else None
    mf_by_day = fetch_moneyflow_days(pro, dates, sleep_sec=sleep_sec)
    top_df = fetch_top_list_day(pro, trade_date_compact, sleep_sec=sleep_sec)
    inst_df = fetch_top_inst_day(pro, trade_date_compact, sleep_sec=sleep_sec)
    margin_t = fetch_margin_detail_day(pro, trade_date_compact, sleep_sec=sleep_sec)
    margin_p = (
        fetch_margin_detail_day(pro, prev, sleep_sec=sleep_sec) if prev else pd.DataFrame()
    )

    etf_df = pd.DataFrame()
    share_chg: Dict[str, float] = {}
    if enable_etf:
        etf_df = _load_etf_name_map(pro, sleep_sec=sleep_sec)
        # 仅对可能匹配的 ETF 拉份额，控制调用量
        names = [n for _, n in concepts if n]
        cand_codes: List[str] = []
        if not etf_df.empty and names:
            mask = False
            for n in names:
                core = str(n).replace("概念", "").replace("板块", "").strip()
                if len(core) >= 2:
                    mask = mask | etf_df["name"].str.contains(core, regex=False, na=False)
            if isinstance(mask, pd.Series) and mask.any():
                cand_codes = etf_df.loc[mask, "ts_code"].astype(str).tolist()
        if cand_codes and prev:
            share_chg = _fetch_etf_share_chg(
                pro, cand_codes, trade_date_compact, prev, sleep_sec=sleep_sec
            )

    results: Dict[str, ConceptCapitalScore] = {}
    for code, name in concepts:
        members = _member_sym_set(concept_members.get(code, []))
        smf, net1, net3, rate1 = _score_moneyflow_row(code, mf_by_day, dates)
        slhb, lhb_cnt, lhb_net = _score_lhb_for_members(members, top_df)
        smargin, m_chg = _score_margin_for_members(members, margin_t, margin_p)
        setf, etf_chg = _score_etf_for_concept(name, etf_df, share_chg)
        sinst, inst_net = _score_inst_for_members(members, top_df, inst_df)
        total = int(max(0, min(50, smf + slhb + smargin + setf + sinst)))
        results[code] = ConceptCapitalScore(
            concept_code=code,
            score_capital=total,
            score_mf=smf,
            score_lhb=slhb,
            score_margin=smargin,
            score_etf=setf,
            score_inst=sinst,
            capital_ok=total >= int(min_capital_score),
            mf_net_1d=net1 if net1 == net1 else float("nan"),
            mf_net_3d=net3 if net3 == net3 else float("nan"),
            mf_rate_1d=rate1 if rate1 == rate1 else float("nan"),
            lhb_member_count=lhb_cnt,
            lhb_net_amount=lhb_net,
            margin_rzye_chg_pct=m_chg if m_chg == m_chg else float("nan"),
            etf_share_chg=etf_chg,
            inst_net_buy=inst_net,
            detail={
                "mf_dates": ",".join(dates),
                "member_count": len(members),
            },
        )
    return results
