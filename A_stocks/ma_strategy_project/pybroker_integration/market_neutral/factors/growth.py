# -*- coding: utf-8 -*-
"""回测组别 G：增长因子。营收同比与净利润同比各一半，公告日不晚于调仓日。

不使用四层稳健质量分。该分数仍由 steady_quality_financial / 成长因子排序步骤单独计算。
"""
from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence

import pandas as pd

from market_neutral.config import ensure_sys_path


def _sleep(sec: float = 0.12) -> None:
    time.sleep(sec)


def fetch_growth_fina(
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    *,
    sleep_sec: float = 0.12,
) -> pd.DataFrame:
    """fina_indicator：or_yoy、netprofit_yoy。用 ann_date 做点-in-time。"""
    ensure_sys_path()
    from backtest_sy_002028_threshold import six_digit_to_ts_code
    from trend_pullback_chips import get_tushare_pro

    pro = get_tushare_pro()
    e = str(end_date).replace("-", "")[:8]
    s_ext = (pd.Timestamp(start_date) - pd.Timedelta(days=800)).strftime("%Y%m%d")
    rows: List[pd.DataFrame] = []
    n = len(list(symbols))
    for i, sym in enumerate(symbols):
        code = "".join(c for c in str(sym) if c.isdigit()).zfill(6)
        try:
            df = pro.fina_indicator(
                ts_code=six_digit_to_ts_code(code),
                start_date=s_ext,
                end_date=e,
                fields="ts_code,ann_date,end_date,or_yoy,netprofit_yoy",
            )
        except Exception as exc:
            print(f"  [growth] {code} 跳过: {exc}", flush=True)
            df = None
        if df is not None and not df.empty:
            d = df.copy()
            d["symbol"] = code
            d["ann_date"] = pd.to_datetime(d["ann_date"], errors="coerce")
            d["or_yoy"] = pd.to_numeric(d["or_yoy"], errors="coerce")
            d["netprofit_yoy"] = pd.to_numeric(d["netprofit_yoy"], errors="coerce")
            rows.append(d[["symbol", "ann_date", "or_yoy", "netprofit_yoy"]])
        if (i + 1) % 10 == 0 or i + 1 == n:
            print(f"  [growth] {i + 1}/{n}", flush=True)
        _sleep(sleep_sec)
    if not rows:
        return pd.DataFrame(columns=["symbol", "ann_date", "or_yoy", "netprofit_yoy"])
    out = pd.concat(rows, ignore_index=True)
    return out.dropna(subset=["ann_date"])


def _score_asof(fina: pd.DataFrame, symbols: Sequence[str], asof: pd.Timestamp) -> pd.DataFrame:
    syms = [str(s).zfill(6) for s in symbols]
    sub = fina[(fina["symbol"].isin(syms)) & (fina["ann_date"] <= asof)]
    if sub.empty:
        return pd.DataFrame(columns=["symbol", "growth_score"])
    last = sub.sort_values(["symbol", "ann_date"]).groupby("symbol", as_index=False).tail(1)
    last = last[(last["or_yoy"].notna()) | (last["netprofit_yoy"].notna())].copy()
    if last.empty:
        return pd.DataFrame(columns=["symbol", "growth_score"])
    last["growth_score"] = (
        0.5 * last["or_yoy"].rank(method="average", pct=True).fillna(0.5)
        + 0.5 * last["netprofit_yoy"].rank(method="average", pct=True).fillna(0.5)
    )
    return last[["symbol", "growth_score"]]


def build_growth_panel(
    symbols: Sequence[str],
    rebal_dates: Sequence[pd.Timestamp],
    name_map: Optional[Dict[str, str]] = None,
    *,
    start_date: str = "",
    end_date: str = "",
) -> pd.DataFrame:
    """每个调仓日一张增长因子截面。列名仍为 growth_score，供回测 G / G_L 使用。"""
    syms = [str(s).zfill(6) for s in symbols]
    dates = sorted({pd.Timestamp(d).normalize() for d in rebal_dates})
    if not syms or not dates:
        return pd.DataFrame()
    start = start_date or str(dates[0].date())
    end = end_date or str(dates[-1].date())
    fina = fetch_growth_fina(syms, start, end)
    if fina.empty:
        return pd.DataFrame()
    nm = name_map or {}
    frames = []
    for dt in dates:
        scored = _score_asof(fina, syms, dt)
        if scored.empty:
            continue
        part = scored.copy()
        part["date"] = dt
        part["stock_name"] = part["symbol"].map(lambda s: nm.get(s, nm.get(str(s), "")))
        frames.append(part)
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["symbol"] = out["symbol"].astype(str).str.zfill(6)
    return out


def write_yoy_rank_csv(
    symbols: Sequence[str],
    *,
    asof: str,
    path: str,
    group_name: str,
    name_map: Optional[Dict[str, str]] = None,
) -> List[str]:
    """观察池按增长因子排序写 CSV。列含分组/排名/代码，供市场雷达取前 3。"""
    import os

    notes: List[str] = []
    syms: List[str] = []
    seen = set()
    for raw in symbols:
        code = "".join(c for c in str(raw) if c.isdigit()).zfill(6)
        if len(code) == 6 and code not in seen:
            seen.add(code)
            syms.append(code)
    dt = pd.Timestamp(asof).normalize()
    names = {str(k).zfill(6): str(v) for k, v in (name_map or {}).items()}
    columns = ["分组", "排名", "股票代码", "股票名称", "行业", "营收同比", "净利润同比", "增长分"]
    out_path = os.path.abspath(path)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    def _dump(rows: List[dict]) -> None:
        pd.DataFrame(rows, columns=columns).to_csv(out_path, index=False, encoding="utf-8-sig")

    if not syms:
        _dump([])
        notes.append(f"「{group_name}」观察池为空，已写空表 → {out_path}")
        return notes

    fina = fetch_growth_fina(syms, str(dt.date()), str(dt.date()))
    latest = fina[(fina["symbol"].isin(syms)) & (fina["ann_date"] <= dt)] if not fina.empty else fina
    detail = pd.DataFrame(columns=["symbol", "or_yoy", "netprofit_yoy"])
    if latest is not None and not latest.empty:
        detail = latest.sort_values(["symbol", "ann_date"]).groupby("symbol", as_index=False).tail(1)
    scored = _score_asof(fina, syms, dt) if not fina.empty else pd.DataFrame(columns=["symbol", "growth_score"])
    if scored is None or scored.empty:
        _dump([])
        notes.append(f"「{group_name}」无可用营收/净利润同比，已写空表 → {out_path}")
        return notes

    scored = scored.sort_values(["growth_score", "symbol"], ascending=[False, True]).reset_index(drop=True)
    yoy = detail.set_index("symbol") if not detail.empty else pd.DataFrame()
    industries: Dict[str, str] = {}
    try:
        from factor_growthT_indicator import get_stock_industries, get_stock_names

        missing = [s for s in scored["symbol"].tolist() if not str(names.get(s) or "").strip()]
        if missing:
            names.update(get_stock_names(missing))
        industries = get_stock_industries(scored["symbol"].astype(str).tolist())
    except Exception as exc:
        notes.append(f"「{group_name}」补名称/行业失败: {exc}")

    rows = []
    for rank, (_, r) in enumerate(scored.iterrows(), start=1):
        sym = str(r["symbol"]).zfill(6)
        or_yoy = yoy.at[sym, "or_yoy"] if sym in getattr(yoy, "index", []) and "or_yoy" in yoy.columns else None
        np_yoy = (
            yoy.at[sym, "netprofit_yoy"]
            if sym in getattr(yoy, "index", []) and "netprofit_yoy" in yoy.columns
            else None
        )
        rows.append(
            {
                "分组": group_name,
                "排名": rank,
                "股票代码": sym,
                "股票名称": names.get(sym, ""),
                "行业": industries.get(sym, ""),
                "营收同比": None if or_yoy is None or pd.isna(or_yoy) else round(float(or_yoy), 4),
                "净利润同比": None if np_yoy is None or pd.isna(np_yoy) else round(float(np_yoy), 4),
                "增长分": round(float(r["growth_score"]), 4),
            }
        )
    _dump(rows)
    notes.append(f"「{group_name}」增长因子排序 {len(rows)}/{len(syms)} 只 → {out_path}")
    return notes
