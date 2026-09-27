#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
袖子均值—方差第一期。

四条袖子：观察池 W4、观察池 W6、M+ 多头、Q 多头。
样本外比较三种袖子加权：等权、按过去收益加权、收缩后的均值—方差。
λ 与收缩强度事先固定，不在测试段里挑选。
温度 π(S) 只在仓位公式里做总仓位，不再改 λ。

不修改 VP_SIX_CONFIG、PATTERN_ENTRY_CONFIG、config/workflow_runner.yaml。
观察池入池规则保持初始 θ（Phase1）。W2、W3 不进入本期。

输出：output/sleeve_mv/report.md 以及收益、折、权重表。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_SCRIPT_DIR)
for p in (_SCRIPT_DIR, _PROJ):
    if p not in sys.path:
        sys.path.insert(0, p)

from fetch_vp_six_combo import (  # noqa: E402
    DEFAULT_STOCKS_POOL_TXT,
    DEFAULT_SYMBOLS_POOL_TXT,
    VP_SIX_CONFIG,
    _assign_combo_phase1,
    _classify_position,
    _ensure_volume_col,
    load_symbols_pool_txt,
)
from backtest_sy_002028_threshold import fetch_ohlc_qfq  # noqa: E402
from kelly_position import (  # noqa: E402
    HALF_KELLY,
    KELLY_CAP,
    estimate_p_b_from_month_rets,
    half_kelly_capped,
)

OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "sleeve_mv")
FETCH_START = "2023-01-01"
TEMPERATURE_CSV = os.path.join(_SCRIPT_DIR, "market_temperature_latest.csv")

SLEEVES = ("W4", "W6", "M+", "Q")
TOP_N = 2
TRAIN_DAYS = 126
TEST_DAYS = 63
MIN_OBS = 40
HOLDOUT_FRAC = 0.20
LAMBDA = 1.0
SHRINK = 0.5
GRID_STEP = 0.05
MIN_NAMES_TO_ADOPT = 8

BASE_AMP = float(VP_SIX_CONFIG["vol_amplify_ratio"])
BASE_SHR = float(VP_SIX_CONFIG["vol_shrink_ratio"])
BASE_BOT = float(VP_SIX_CONFIG["bottom_range_pct"])
BASE_HIGH = float(VP_SIX_CONFIG["high_range_pct"])
STAGNANT_ABS = float(VP_SIX_CONFIG["stagnant_abs_pct"])
VOL_MA = int(VP_SIX_CONFIG["vol_ma_bars"])
RANGE_N = int(VP_SIX_CONFIG["range_lookback_bars"])
BREAK_N = int(VP_SIX_CONFIG["breakout_lookback_bars"])
MA20_LB = int(VP_SIX_CONFIG["downtrend_ma20_lookback"])
WATCH_DAYS = int(VP_SIX_CONFIG["watch_pool_max_trade_days"])


def resolve_study_symbols() -> Tuple[List[str], str]:
    custom = load_symbols_pool_txt(DEFAULT_SYMBOLS_POOL_TXT)
    if custom:
        return custom, f"自定义列表 {DEFAULT_SYMBOLS_POOL_TXT}（{len(custom)} 只）"
    pool = load_symbols_pool_txt(DEFAULT_STOCKS_POOL_TXT)
    return pool, f"股票池 {DEFAULT_STOCKS_POOL_TXT}（{len(pool)} 只）"


def _finite(x: float) -> bool:
    return x == x and x is not None


def combo_id_row(row: pd.Series) -> int:
    c1 = float(row["close"])
    c0 = float(row["prev_close"])
    vol_ratio = float(row["vol_ratio"])
    pct = (c1 / c0 - 1.0) * 100.0
    pos = _classify_position(
        close=c1,
        ma20=float(row["ma20"]),
        ma60=float(row["ma60"]),
        ma20_prev_n=float(row["ma20_prev"]),
        range_pct=float(row["range_pct"]),
        bottom_range_pct=BASE_BOT,
        high_range_pct=BASE_HIGH,
    )
    cid, _exact = _assign_combo_phase1(
        position_stage=pos,
        vol_amplify=vol_ratio >= BASE_AMP,
        vol_shrink=vol_ratio <= BASE_SHR,
        price_up=c1 > c0,
        price_down=c1 < c0,
        is_breakout=c1 >= float(row["prior_high"]) * 0.998,
        is_stagnant=abs(pct) <= STAGNANT_ABS,
    )
    return int(cid)


def build_panel(symbols: Sequence[str], end: str) -> Tuple[pd.DataFrame, List[str]]:
    notes: List[str] = []
    frames: List[pd.DataFrame] = []
    need = max(65, RANGE_N, VOL_MA + 1, BREAK_N + 1)
    for sym in symbols:
        try:
            raw = fetch_ohlc_qfq(sym, FETCH_START, end)
        except Exception as exc:
            notes.append(f"{sym} 取数失败：{exc}")
            continue
        if raw is None or raw.empty:
            notes.append(f"{sym} 无日线")
            continue
        d = _ensure_volume_col(raw)
        d["close"] = pd.to_numeric(d["close"], errors="coerce")
        d["high"] = pd.to_numeric(d["high"], errors="coerce")
        d["low"] = pd.to_numeric(d["low"], errors="coerce")
        d["volume"] = pd.to_numeric(d["volume"], errors="coerce")
        d = d.sort_values("date").reset_index(drop=True)
        d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
        d["ma60"] = d["close"].rolling(60, min_periods=60).mean()
        d["vol_ma"] = d["volume"].shift(1).rolling(VOL_MA, min_periods=VOL_MA).mean()
        d["range_low"] = d["low"].rolling(RANGE_N, min_periods=RANGE_N).min()
        d["range_high"] = d["high"].rolling(RANGE_N, min_periods=RANGE_N).max()
        d["ma20_prev"] = d["ma20"].shift(MA20_LB)
        d["prior_high"] = d["high"].shift(1).rolling(BREAK_N, min_periods=BREAK_N).max()
        d["prev_close"] = d["close"].shift(1)
        ret = d["close"].pct_change()
        sigma = ret.rolling(20, min_periods=5).std(ddof=0)
        r60 = d["close"] / d["close"].shift(60) - 1.0
        d["mom_adj"] = np.where(
            (sigma > 1e-8) & r60.notna(),
            r60 / sigma,
            r60,
        )
        prior_vol = d["volume"].shift(1).rolling(20, min_periods=20).mean()
        d["mud_vol"] = d["volume"] / prior_vol
        d["symbol"] = sym
        d = d.iloc[need:].copy()
        d = d.dropna(subset=["ma20", "ma60", "vol_ma", "ma20_prev", "prior_high", "prev_close"])
        d = d[(d["vol_ma"] > 0) & (d["prev_close"] > 0) & (d["close"] > 0)]
        if d.empty:
            notes.append(f"{sym} 有效样本为空")
            continue
        span = d["range_high"] - d["range_low"]
        d["range_pct"] = ((d["close"] - d["range_low"]) / span).where(span > 1e-12, 0.5)
        d["range_pct"] = d["range_pct"].clip(0.0, 1.0)
        d["vol_ratio"] = d["volume"] / d["vol_ma"]
        frames.append(
            d[
                [
                    "symbol",
                    "date",
                    "close",
                    "ma20",
                    "ma60",
                    "ma20_prev",
                    "range_pct",
                    "vol_ratio",
                    "prior_high",
                    "prev_close",
                    "mom_adj",
                    "mud_vol",
                ]
            ]
        )
        notes.append(f"{sym} 有效日 {len(d)}")
    if not frames:
        return pd.DataFrame(), notes
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
    print(f"  分类 {len(panel)} 行 …", flush=True)
    panel["combo_id"] = panel.apply(combo_id_row, axis=1).astype(int)
    return panel, notes


def attach_q(panel: pd.DataFrame, symbols: Sequence[str], end: str, notes: List[str]) -> pd.DataFrame:
    panel = panel.copy()
    try:
        from market_neutral.data.prices import fetch_daily_basic_panel, fetch_industry_map
        from market_neutral.factors.company_value import fetch_fina_lite
        from market_neutral.factors.value import build_valuation_panel
    except Exception as exc:
        notes.append(f"Q 模块导入失败：{exc}")
        return panel

    print("  拉取财务与估值 …", flush=True)
    try:
        fina = fetch_fina_lite(symbols, FETCH_START, end)
        notes.append(f"fina 行数 {0 if fina is None else len(fina)}")
    except Exception as exc:
        notes.append(f"fina 拉取失败：{exc}")
        fina = pd.DataFrame()
    try:
        basic = fetch_daily_basic_panel(symbols, FETCH_START, end)
        industry = fetch_industry_map(symbols)
        valuation = build_valuation_panel(basic, industry)
        notes.append(f"估值行数 {0 if valuation is None else len(valuation)}")
    except Exception as exc:
        notes.append(f"估值拉取失败：{exc}")
        valuation = pd.DataFrame()

    out = panel.sort_values(["symbol", "date"]).reset_index(drop=True)
    out["roe"] = np.nan
    out["ocf_to_or"] = np.nan
    out["upside"] = np.nan
    if fina is not None and not fina.empty and "ann_date" in fina.columns:
        f = fina.dropna(subset=["ann_date"]).copy()
        f["symbol"] = f["symbol"].astype(str).str.zfill(6)
        f["date"] = pd.to_datetime(f["ann_date"]).dt.normalize()
        f = f.sort_values(["symbol", "date", "end_date"]).drop_duplicates(
            ["symbol", "date"], keep="last"
        )
        left = out.drop(columns=["roe", "ocf_to_or"])
        parts: List[pd.DataFrame] = []
        for sym, g in left.groupby("symbol", sort=False):
            g = g.sort_values("date")
            sub_f = f.loc[f["symbol"] == sym, ["date", "roe", "ocf_to_or"]].sort_values("date")
            if sub_f.empty:
                g = g.copy()
                g["roe"] = np.nan
                g["ocf_to_or"] = np.nan
                parts.append(g)
            else:
                parts.append(pd.merge_asof(g, sub_f, on="date", direction="backward"))
        out = pd.concat(parts, ignore_index=True)
    if valuation is not None and not valuation.empty and "upside" in valuation.columns:
        v = valuation[["date", "symbol", "upside"]].copy()
        v["date"] = pd.to_datetime(v["date"]).dt.normalize()
        v["symbol"] = v["symbol"].astype(str).str.zfill(6)
        out = out.drop(columns=["upside"], errors="ignore").merge(
            v, on=["date", "symbol"], how="left"
        )
    return out


def _top_mplus(rows: List[dict]) -> List[str]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    df["mom_adj"] = pd.to_numeric(df["mom_adj"], errors="coerce")
    df = df[df["mom_adj"].notna()].copy()
    if df.empty:
        return []
    df["mom_pct"] = df["mom_adj"].rank(method="average", pct=True)
    df["vol_pct"] = pd.to_numeric(df["mud_vol"], errors="coerce").rank(method="average", pct=True)
    df["score"] = 0.7 * df["mom_pct"].fillna(0.5) + 0.3 * df["vol_pct"].fillna(0.5)
    df = df.sort_values(["score", "symbol"], ascending=[False, True])
    return df["symbol"].head(TOP_N).astype(str).tolist()


def _top_q(rows: List[dict]) -> List[str]:
    if not rows:
        return []
    df = pd.DataFrame(rows)
    for col in ("roe", "ocf_to_or", "upside"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    usable = df["roe"].notna() | df["ocf_to_or"].notna() | df["upside"].notna()
    df = df[usable].copy()
    if df.empty:
        return []
    df["score"] = (
        0.4 * df["roe"].rank(method="average", pct=True).fillna(0.5)
        + 0.3 * df["ocf_to_or"].rank(method="average", pct=True).fillna(0.5)
        + 0.3 * df["upside"].rank(method="average", pct=True).fillna(0.5)
    )
    df = df.sort_values(["score", "symbol"], ascending=[False, True])
    return df["symbol"].head(TOP_N).astype(str).tolist()


def _sleeve_return(
    symbols: Sequence[str],
    closes: Dict[Tuple[str, pd.Timestamp], float],
    d: pd.Timestamp,
    nxt: pd.Timestamp,
) -> Tuple[float, int]:
    rets: List[float] = []
    for sym in symbols:
        c0 = closes.get((sym, d))
        c1 = closes.get((sym, nxt))
        if c0 is None or c1 is None or not (c0 > 0 and c1 > 0):
            continue
        rets.append(c1 / c0 - 1.0)
    if not rets:
        return float("nan"), 0
    return float(np.mean(rets)), len(rets)


def build_sleeve_returns(panel: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, List[str]]]:
    """收益日记在次日。持仓用当日收盘时已经知道的观察池与排名。"""
    work = panel.copy()
    work["symbol"] = work["symbol"].astype(str).str.zfill(6)
    work = work.sort_values(["symbol", "date"])
    dates = list(pd.to_datetime(work["date"]).drop_duplicates().sort_values())
    by_sym = {
        sym: g.drop_duplicates("date").set_index("date").sort_index()
        for sym, g in work.groupby("symbol", sort=False)
    }
    closes: Dict[Tuple[str, pd.Timestamp], float] = {}
    for sym, g in by_sym.items():
        for dt, c in g["close"].items():
            if _finite(float(c)) and float(c) > 0:
                closes[(sym, pd.Timestamp(dt))] = float(c)

    rows = []
    last_names: Dict[str, List[str]] = {k: [] for k in SLEEVES}
    last_pnl: Optional[pd.Timestamp] = None
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        start = dates[max(0, i - WATCH_DAYS + 1)]
        w4: List[str] = []
        w6: List[str] = []
        feat: List[dict] = []
        for sym, g in by_sym.items():
            window = g[(g.index >= start) & (g.index <= d)]
            if window.empty:
                continue
            last = window.iloc[-1]
            cid = int(last["combo_id"])
            if cid == 4:
                w4.append(sym)
            elif cid == 6:
                w6.append(sym)
            if cid in (4, 6):
                feat.append(
                    {
                        "symbol": sym,
                        "mom_adj": last.get("mom_adj"),
                        "mud_vol": last.get("mud_vol"),
                        "roe": last.get("roe"),
                        "ocf_to_or": last.get("ocf_to_or"),
                        "upside": last.get("upside"),
                    }
                )
        mplus = _top_mplus(feat)
        qnames = _top_q(feat)
        books = {"W4": w4, "W6": w6, "M+": mplus, "Q": qnames}
        if any(books.values()):
            last_names = books
            last_pnl = pd.Timestamp(nxt)
        rec = {"date": nxt}
        for name, members in books.items():
            ret, n = _sleeve_return(members, closes, d, nxt)
            rec[name] = ret
            rec[f"n_{name}"] = n
        rows.append(rec)
    if not rows:
        return pd.DataFrame(), last_names, last_pnl
    out = pd.DataFrame(rows).set_index("date").sort_index()
    return out, last_names, last_pnl


def _simplex(names: Sequence[str], step: float = GRID_STEP):
    n = len(names)
    units = int(round(1.0 / step))

    def rec(left: int, k: int):
        if k == 1:
            yield (left,)
            return
        for i in range(left + 1):
            yield from ((i,) + tail for tail in rec(left - i, k - 1))

    for comb in rec(units, n):
        yield {names[i]: comb[i] / units for i in range(n)}


def _eligible(hist: pd.DataFrame) -> List[str]:
    out = []
    for name in SLEEVES:
        if name not in hist.columns:
            continue
        if int(hist[name].notna().sum()) >= MIN_OBS:
            out.append(name)
    return out


def _ew(names: Sequence[str]) -> Dict[str, float]:
    if not names:
        return {}
    w = 1.0 / len(names)
    return {n: w for n in names}


def _ret_weights(hist: pd.DataFrame, names: Sequence[str]) -> Dict[str, float]:
    mu = hist[list(names)].mean(skipna=True).clip(lower=0.0)
    total = float(mu.sum())
    if total <= 0:
        return _ew(names)
    return {n: float(mu[n]) / total for n in names}


def _mv_weights(hist: pd.DataFrame, names: Sequence[str]) -> Dict[str, float]:
    cols = list(names)
    sub = hist[cols]
    mu = sub.mean(skipna=True).fillna(0.0).to_numpy(dtype=float)
    cov = sub.cov(min_periods=MIN_OBS).fillna(0.0).to_numpy(dtype=float)
    diag_mean = float(np.mean(np.diag(cov))) if len(cols) else 0.0
    if not _finite(diag_mean):
        diag_mean = 0.0
    target = np.eye(len(cols)) * diag_mean
    shrunk = (1.0 - SHRINK) * cov + SHRINK * target
    mu_a = mu * 252.0
    sig_a = shrunk * 252.0
    best_score = None
    best = _ew(cols)
    for wdict in _simplex(cols):
        w = np.array([wdict[n] for n in cols], dtype=float)
        score = float(w @ mu_a - LAMBDA * (w @ sig_a @ w))
        if best_score is None or score > best_score:
            best_score = score
            best = wdict
    return best


def _apply_weights(row: pd.Series, weights: Dict[str, float]) -> float:
    num = 0.0
    den = 0.0
    for name, w in weights.items():
        val = row.get(name, np.nan)
        if val == val and w > 0:
            num += float(w) * float(val)
            den += float(w)
    if den <= 0:
        return float("nan")
    return num / den


def _perf(rets: pd.Series) -> Dict[str, float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    if len(r) < 5:
        return {"n": float(len(r)), "total": np.nan, "sharpe": np.nan, "vol": np.nan, "mdd": np.nan}
    total = float((1.0 + r).prod() - 1.0)
    vol = float(r.std(ddof=0) * np.sqrt(252.0))
    sharpe = float(r.mean() / r.std(ddof=0) * np.sqrt(252.0)) if r.std(ddof=0) > 1e-12 else np.nan
    eq = (1.0 + r).cumprod()
    mdd = float((eq / eq.cummax() - 1.0).min())
    return {"n": float(len(r)), "total": total, "sharpe": sharpe, "vol": vol, "mdd": mdd}


def walk_forward(wide: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, pd.Series], Dict[str, Dict[str, float]]]:
    dates = list(wide.index)
    n = len(dates)
    hold_start = int(n * (1.0 - HOLDOUT_FRAC))
    hold_start = min(max(hold_start, TRAIN_DAYS + 5), n)
    methods = ("等权", "过去收益", "均值方差")

    def pack(train_idx, test_idx) -> Tuple[Dict[str, Dict[str, float]], Dict[str, pd.Series]]:
        hist = wide.loc[train_idx]
        names = _eligible(hist)
        if len(names) < 2:
            names = [c for c in SLEEVES if c in hist.columns and int(hist[c].notna().sum()) > 0]
            weights = {m: _ew(names) for m in methods}
        else:
            weights = {
                "等权": _ew(names),
                "过去收益": _ret_weights(hist, names),
                "均值方差": _mv_weights(hist, names),
            }
        test = wide.loc[test_idx]
        series = {}
        for m, w in weights.items():
            series[m] = test.apply(lambda row, ww=w: _apply_weights(row, ww), axis=1)
        return weights, series

    fold_rows = []
    stitched = {m: [] for m in methods}
    region = dates[:hold_start]
    i = TRAIN_DAYS
    fold_id = 1
    while i < len(region):
        train_idx = region[i - TRAIN_DAYS : i]
        test_idx = region[i : min(i + TEST_DAYS, len(region))]
        if len(test_idx) < 5:
            break
        weights, series = pack(train_idx, test_idx)
        for m in methods:
            stitched[m].append(series[m])
            p = _perf(series[m])
            fold_rows.append(
                {
                    "fold": fold_id,
                    "method": m,
                    "train_start": pd.Timestamp(train_idx[0]).strftime("%Y-%m-%d"),
                    "train_end": pd.Timestamp(train_idx[-1]).strftime("%Y-%m-%d"),
                    "test_start": pd.Timestamp(test_idx[0]).strftime("%Y-%m-%d"),
                    "test_end": pd.Timestamp(test_idx[-1]).strftime("%Y-%m-%d"),
                    "n": int(p["n"]),
                    "total": p["total"],
                    "sharpe": p["sharpe"],
                    "vol": p["vol"],
                    "mdd": p["mdd"],
                    "weights": "; ".join(f"{k}={v:.2f}" for k, v in weights[m].items()),
                }
            )
        fold_id += 1
        i += TEST_DAYS

    hold_w: Dict[str, Dict[str, float]] = {}
    hold_series: Dict[str, pd.Series] = {}
    if hold_start >= TRAIN_DAYS and hold_start < n:
        train_idx = dates[hold_start - TRAIN_DAYS : hold_start]
        test_idx = dates[hold_start:]
        hold_w, hold_series = pack(train_idx, test_idx)
        for m in methods:
            p = _perf(hold_series[m])
            fold_rows.append(
                {
                    "fold": "holdout",
                    "method": m,
                    "train_start": pd.Timestamp(train_idx[0]).strftime("%Y-%m-%d"),
                    "train_end": pd.Timestamp(train_idx[-1]).strftime("%Y-%m-%d"),
                    "test_start": pd.Timestamp(test_idx[0]).strftime("%Y-%m-%d"),
                    "test_end": pd.Timestamp(test_idx[-1]).strftime("%Y-%m-%d"),
                    "n": int(p["n"]),
                    "total": p["total"],
                    "sharpe": p["sharpe"],
                    "vol": p["vol"],
                    "mdd": p["mdd"],
                    "weights": "; ".join(f"{k}={v:.2f}" for k, v in hold_w[m].items()),
                }
            )

    stitched_s = {}
    for m in methods:
        stitched_s[m] = pd.concat(stitched[m]) if stitched[m] else pd.Series(dtype=float)
    folds = pd.DataFrame(fold_rows)

    latest_w = {m: _ew(list(SLEEVES)) for m in methods}
    if n > TRAIN_DAYS:
        hist = wide.iloc[-(TRAIN_DAYS + 1) : -1]
        names = _eligible(hist)
        if len(names) >= 2:
            latest_w = {
                "等权": _ew(names),
                "过去收益": _ret_weights(hist, names),
                "均值方差": _mv_weights(hist, names),
            }
    return folds, wide, stitched_s, {"holdout": hold_w, "latest": latest_w, "hold_series": hold_series}


def _pct(x: float) -> str:
    if x != x:
        return "—"
    return f"{x * 100:.2f}%"


def _num(x: float) -> str:
    if x != x:
        return "—"
    return f"{x:.2f}"


def _load_pi() -> Tuple[Optional[float], str]:
    if not os.path.isfile(TEMPERATURE_CSV):
        return None, "未找到 market_temperature_latest.csv"
    df = pd.read_csv(TEMPERATURE_CSV)
    if df.empty or "position_pct" not in df.columns:
        return None, "温度文件没有 position_pct"
    row = df.iloc[0]
    pi = float(row["position_pct"]) / 100.0
    trade_date = str(row.get("trade_date", ""))
    score = row.get("total_score", "")
    return pi, f"文件交易日 {trade_date}，温度分 {score}，π(S)={pi:.0%}"


def _kelly_cap(ew_rets: pd.Series) -> Tuple[float, str]:
    r = pd.to_numeric(ew_rets, errors="coerce").dropna()
    if r.empty:
        return KELLY_CAP, "等权日收益为空，半凯利不参与，只留 20% 上限"
    eq = pd.DataFrame({"date": r.index, "day_return": r.to_numpy()})
    eq["date"] = pd.to_datetime(eq["date"])
    eq["ym"] = eq["date"].dt.to_period("M")
    month = eq.groupby("ym")["day_return"].apply(lambda x: float((1.0 + x).prod() - 1.0))
    if len(month) > 1:
        month = month.iloc[:-1]
    p, b, n, n_win, n_loss, note = estimate_p_b_from_month_rets(month)
    if note:
        return KELLY_CAP, f"{note}。半凯利不参与取小，单票只受 20% 上限"
    _full, _half, capped = half_kelly_capped(p, b, half=HALF_KELLY, cap=KELLY_CAP)
    return capped, f"月样本 {n}（胜 {n_win} / 负 {n_loss}），p={p:.2f}，b={b:.2f}，半凯利封顶后 {capped:.0%}"


def write_report(
    *,
    universe: str,
    n_symbols: int,
    notes: List[str],
    wide: pd.DataFrame,
    folds: pd.DataFrame,
    stitched: Dict[str, pd.Series],
    weights_pack: dict,
    last_names: Dict[str, List[str]],
    last_pnl: Optional[pd.Timestamp],
    end: str,
) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    methods = ("等权", "过去收益", "均值方差")
    wf_perf = {m: _perf(stitched[m]) for m in methods}
    hold_series = weights_pack.get("hold_series") or {}
    hold_perf = {m: _perf(hold_series[m]) if m in hold_series else _perf(pd.Series(dtype=float)) for m in methods}

    mv_wf = wf_perf["均值方差"]["sharpe"]
    ew_wf = wf_perf["等权"]["sharpe"]
    mv_h = hold_perf["均值方差"]["sharpe"]
    ew_h = hold_perf["等权"]["sharpe"]
    mv_beats = (
        n_symbols >= MIN_NAMES_TO_ADOPT
        and mv_wf == mv_wf
        and ew_wf == ew_wf
        and mv_wf > ew_wf
        and mv_h == mv_h
        and ew_h == ew_h
        and mv_h > ew_h
        and wf_perf["均值方差"]["total"] > wf_perf["等权"]["total"]
        and hold_perf["均值方差"]["total"] > hold_perf["等权"]["total"]
    )
    numeric_better = (
        mv_wf == mv_wf
        and ew_wf == ew_wf
        and mv_wf > ew_wf
        and mv_h == mv_h
        and ew_h == ew_h
        and mv_h > ew_h
        and wf_perf["均值方差"]["total"] > wf_perf["等权"]["total"]
        and hold_perf["均值方差"]["total"] > hold_perf["等权"]["total"]
    )
    if mv_beats:
        conclusion = (
            "均值—方差在滚动测试和最后一段上都高于等权，且名单不少于 8 只。"
            "本期仍不改线上仓位；若要替换等权，需要另一次确认。"
        )
    elif numeric_better:
        conclusion = (
            f"这 {n_symbols} 只上，均值—方差的滚动夏普、最后一段夏普和两段累计收益都高于等权。"
            f"名单少于 {MIN_NAMES_TO_ADOPT} 只，而且 M+ 与 Q 往往是同一批股票，不能把这个差值当成四条独立袖子的稳定优势。"
            "组合层保持等权，均值—方差留在本报告里。"
        )
    else:
        conclusion = (
            "组合层保持等权。均值—方差留在本报告里，不写入线上仓位。"
            f"替换等权需要：滚动测试与最后一段的夏普和累计收益都更高，且名单不少于 {MIN_NAMES_TO_ADOPT} 只。"
            f"本期名单 {n_symbols} 只。"
        )

    corr = wide[list(SLEEVES)].corr()
    coverage = {name: float(wide[name].notna().mean()) if name in wide.columns else 0.0 for name in SLEEVES}

    pi, pi_note = _load_pi()
    pi_v = 1.0 if pi is None else pi
    ew_book = wide[list(SLEEVES)].mean(axis=1, skipna=True)
    kelly_cap, kelly_note = _kelly_cap(ew_book)
    latest = weights_pack.get("latest") or {}

    lines = [
        "# 袖子均值—方差第一期报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。",
        "",
        "本报告不写回 `VP_SIX_CONFIG` 与 `config/workflow_runner.yaml`。观察池入池规则仍是初始 θ。",
        "",
        f"宇宙：{universe}。",
        f"取数：{FETCH_START} ～ {end}。收益是持仓日收盘到下一交易日收盘。",
        "袖子：W4、W6（滚动 6 个交易日、同票留最新 combo）、M+ 多头、Q 多头。",
        f"M+ 与 Q 都在当日 W4∪W6 里取前 {TOP_N} 名，袖子内部等权。W2、W3 不在本期。",
        "筹码覆写不进入这条收益序列。入池用 Phase1、初始放量 1.50、底部 0.30、高位 0.80。",
        f"均值—方差：λ={LAMBDA:.0f}（年化收益与年化协方差），协方差向对角收缩 {SHRINK:.0%}，权重步长 {GRID_STEP:.2f}，只做多且和为 1。",
        f"估计窗 {TRAIN_DAYS} 个交易日，测试窗 {TEST_DAYS} 个交易日。一条袖子在估计窗里至少 {MIN_OBS} 个有效日才参与加权。",
        "最后约 20% 交易日只评价一次，不用于挑选 λ 或收缩强度。",
        "",
        "## 结论",
        "",
        conclusion,
        "",
        "## 样本外",
        "",
        "| 方法 | 滚动测试累计 | 滚动夏普 | 最后一段累计 | 最后一段夏普 | 最后一段最大回撤 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for m in methods:
        a = wf_perf[m]
        b = hold_perf[m]
        lines.append(
            f"| {m} | {_pct(a['total'])} | {_num(a['sharpe'])} | {_pct(b['total'])} | {_num(b['sharpe'])} | {_pct(b['mdd'])} |"
        )
    lines.append("")
    lines.append("夏普按日收益的均值除以波动。累计收益是复利。波动会吃掉复利，所以夏普为正时，累计仍可以是负的。")
    lines.append("表里的等权，是估计窗里有效日不少于 40 天的那些袖子等权。W4 经常不够 40 天，多数窗口没有 W4。")

    lines += ["", "## 各折", ""]
    if folds.empty:
        lines.append("样本长度不够切开训练与测试。")
    else:
        show = folds.copy()
        for _, r in show.iterrows():
            lines.append(
                f"- {r['fold']} · {r['method']} · 测试 {r['test_start']} ～ {r['test_end']} · "
                f"累计 {_pct(float(r['total']))} · 夏普 {_num(float(r['sharpe']))} · 权重 {r['weights']}"
            )

    lines += [
        "",
        "## 袖子覆盖与相关",
        "",
        "有日收益的交易日占比：",
        "",
    ]
    for name in SLEEVES:
        lines.append(f"- {name}：{coverage[name]:.0%}")
    both = wide["M+"].notna() & wide["Q"].notna()
    n_both = int(both.sum())
    n_same = 0
    if n_both:
        n_same = int((wide.loc[both, "M+"] - wide.loc[both, "Q"]).abs().lt(1e-12).sum())
    lines += [
        "",
        "M+、Q 的候选来自当日观察池，所以它们和 W4、W6 持有的是同一批股票的子集，相关会偏高。",
        f"M+ 与 Q 同时有收益的 {n_both} 天里，日收益完全相同的有 {n_same} 天。名单只有 {n_symbols} 只、又各取前 {TOP_N} 名时，两条袖子经常就是整个观察池。",
        "",
        "|  | " + " | ".join(SLEEVES) + " |",
        "| --- | " + " | ".join("---" for _ in SLEEVES) + " |",
    ]
    for a in SLEEVES:
        cells = []
        for b in SLEEVES:
            val = corr.loc[a, b] if a in corr.index and b in corr.columns else np.nan
            cells.append(_num(float(val)) if val == val else "—")
        lines.append(f"| {a} | " + " | ".join(cells) + " |")

    lines += ["", "## 截至最近的权重（只展示）", ""]
    lines.append(f"温度：{pi_note}。")
    lines.append(f"共用半凯利（按等权组合的月收益估计，不含最后一个月）：{kelly_note}。")
    lines.append("单票仓位 = min( π(S) × 袖子权重 / 袖子内只数 , 半凯利或 20% 上限 )。袖子内等权。")
    lines.append("")
    lines.append("| 方法 | " + " | ".join(SLEEVES) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in SLEEVES) + " |")
    for m in methods:
        w = latest.get(m) or {}
        cells = [f"{w.get(name, 0.0):.0%}" for name in SLEEVES]
        lines.append(f"| {m} | " + " | ".join(cells) + " |")

    held_on = last_pnl.strftime("%Y-%m-%d") if last_pnl is not None else "无"
    lines += ["", f"最近一个有持仓的收益日（{held_on}），等权方案下的单票上限后仓位：", ""]
    w_ew = latest.get("等权") or {}
    if pi is None:
        lines.append("温度文件缺失，下表用 π=100% 只为把公式写全，不代表当日温度。")
    any_name = False
    for name in SLEEVES:
        members = last_names.get(name) or []
        wk = float(w_ew.get(name, 0.0))
        n_k = len(members)
        if n_k <= 0:
            lines.append(f"- {name}：当日无持仓")
            continue
        joined = "、".join(members)
        if wk <= 0:
            lines.append(f"- {name}（{joined}）：当天在池里，这一方案的袖子权重为 0")
            any_name = True
            continue
        any_name = True
        raw = pi_v * wk / n_k
        capped = min(raw, kelly_cap)
        lines.append(
            f"- {name}（{joined}）：π×w/n = {raw:.1%}，取小后每只 {capped:.1%}"
        )
    if not any_name:
        lines.append("- 最近一日四条袖子都没有可计价的持仓。")

    lines += ["", "## 取数", ""]
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")

    path = os.path.join(OUT_DIR, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    wide.to_csv(os.path.join(OUT_DIR, "sleeve_returns.csv"), encoding="utf-8-sig")
    folds.to_csv(os.path.join(OUT_DIR, "folds.csv"), index=False, encoding="utf-8-sig")
    return path


def main() -> None:
    end = datetime.now().strftime("%Y-%m-%d")
    symbols, universe = resolve_study_symbols()
    print(universe, flush=True)
    if not symbols:
        raise SystemExit("研究宇宙为空")
    panel, notes = build_panel(symbols, end)
    if panel.empty:
        raise SystemExit("没有可用日线")
    panel = attach_q(panel, symbols, end, notes)
    print("  组装袖子日收益 …", flush=True)
    wide, last_names, last_pnl = build_sleeve_returns(panel)
    if wide.empty:
        raise SystemExit("袖子收益为空")
    print(f"  收益日 {len(wide)}，走样本外 …", flush=True)
    folds, wide, stitched, weights_pack = walk_forward(wide)
    path = write_report(
        universe=universe,
        n_symbols=len(symbols),
        notes=notes,
        wide=wide,
        folds=folds,
        stitched=stitched,
        weights_pack=weights_pack,
        last_names=last_names,
        last_pnl=last_pnl,
        end=end,
    )
    print(f"报告 → {path}", flush=True)


if __name__ == "__main__":
    main()
