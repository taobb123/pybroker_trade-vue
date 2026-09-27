#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文档第 15 节：把现有回测里的 W4、W6、M+、Q、G 收成日收益，再做样本外比较。

来源是 market_neutral/output/latest/factor_snapshot.csv（2025-06-06～2026-07-31）。
W4 / W6：该调仓日 combo 4 / 6 的等权，持有到下次调仓。
M+ / Q：与市场中性回测相同，因子前 10% 做多。M+ 按周调仓，Q 按月调仓。
G：公告日不晚于调仓日的营收同比、净利润同比，在当日池内取前 13，按月调仓。
四层稳健质量分的现成拉取不带公告日，不能直接套到这段历史上。

比较：等权、按收益排序、收缩后的均值—方差。λ 与收缩强度事先固定。
不修改线上配置。
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

from backtest_sy_002028_threshold import fetch_ohlc_qfq, six_digit_to_ts_code  # noqa: E402
from factor_growthT_indicator import GROWTH_TOP_N_DEFAULT  # noqa: E402
from market_neutral.portfolio.long_short_index import select_long_short  # noqa: E402
from trend_pullback_chips import get_tushare_pro  # noqa: E402

OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "doc15_sleeves")
SNAPSHOT = os.path.join(
    _SCRIPT_DIR, "market_neutral", "output", "latest", "factor_snapshot.csv"
)
SLEEVES = ("W4", "W6", "M+", "Q", "G")
QUANTILE = 0.10
GROWTH_TOP_N = int(GROWTH_TOP_N_DEFAULT)
TRAIN_DAYS = 84
TEST_DAYS = 21
MIN_OBS = 15
HOLDOUT_FRAC = 0.20
LAMBDA = 1.0
SHRINK = 0.5
GRID_STEP = 0.05


def _finite(x: float) -> bool:
    return x == x and x is not None


def load_snapshot() -> pd.DataFrame:
    df = pd.read_csv(SNAPSHOT)
    df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    df["symbol"] = df["symbol"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    df["combo_id"] = pd.to_numeric(df["combo_id"], errors="coerce")
    return df


def load_closes(symbols: Sequence[str], start: str, end: str) -> pd.DataFrame:
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = os.path.join(OUT_DIR, "closes.csv")
    frames: List[pd.DataFrame] = []
    have = set()
    if os.path.isfile(cache):
        old = pd.read_csv(cache)
        old["symbol"] = old["symbol"].astype(str).str.zfill(6)
        old["date"] = pd.to_datetime(old["date"]).dt.normalize()
        frames.append(old)
        have = set(old["symbol"].unique())
    todo = [s for s in symbols if s not in have]
    for i, sym in enumerate(todo):
        try:
            raw = fetch_ohlc_qfq(sym, start, end)
        except Exception as exc:
            print(f"  [px] {sym} 跳过: {exc}", flush=True)
            raw = None
        if raw is not None and not raw.empty:
            d = raw.copy()
            d["date"] = pd.to_datetime(d["date"]).dt.normalize()
            d["close"] = pd.to_numeric(d["close"], errors="coerce")
            d["symbol"] = sym
            frames.append(d[["date", "symbol", "close"]])
        if (i + 1) % 20 == 0 or i + 1 == len(todo):
            print(f"  [px] {i + 1}/{len(todo)}", flush=True)
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "close"])
    out = pd.concat(frames, ignore_index=True)
    out = out.dropna(subset=["close"])
    out = out.drop_duplicates(["date", "symbol"], keep="last")
    out.to_csv(cache, index=False, encoding="utf-8-sig")
    return out


def load_growth(symbols: Sequence[str], end: str) -> pd.DataFrame:
    cache = os.path.join(OUT_DIR, "growth_fina.csv")
    if os.path.isfile(cache):
        g = pd.read_csv(cache)
        g["symbol"] = g["symbol"].astype(str).str.zfill(6)
        g["ann_date"] = pd.to_datetime(g["ann_date"], errors="coerce")
        return g.dropna(subset=["ann_date"])
    pro = get_tushare_pro()
    rows: List[pd.DataFrame] = []
    e = end.replace("-", "")
    for i, sym in enumerate(symbols):
        try:
            df = pro.fina_indicator(
                ts_code=six_digit_to_ts_code(sym),
                start_date="20200101",
                end_date=e,
                fields="ts_code,ann_date,end_date,or_yoy,netprofit_yoy",
            )
        except Exception as exc:
            print(f"  [g] {sym} 跳过: {exc}", flush=True)
            df = None
        if df is not None and not df.empty:
            d = df.copy()
            d["symbol"] = sym
            rows.append(d)
        if (i + 1) % 20 == 0 or i + 1 == len(symbols):
            print(f"  [g] {i + 1}/{len(symbols)}", flush=True)
    if not rows:
        return pd.DataFrame(columns=["symbol", "ann_date", "or_yoy", "netprofit_yoy"])
    out = pd.concat(rows, ignore_index=True)
    out["ann_date"] = pd.to_datetime(out["ann_date"], errors="coerce")
    out["or_yoy"] = pd.to_numeric(out["or_yoy"], errors="coerce")
    out["netprofit_yoy"] = pd.to_numeric(out["netprofit_yoy"], errors="coerce")
    out = out.dropna(subset=["ann_date"])
    out.to_csv(cache, index=False, encoding="utf-8-sig")
    return out


def _members_quantile(day: pd.DataFrame, variant: str) -> List[str]:
    longs, _shorts, _note = select_long_short(day, variant, quantile=QUANTILE)
    if longs is None or longs.empty:
        return []
    return longs["symbol"].astype(str).str.zfill(6).tolist()


def _members_growth(day: pd.DataFrame, fina: pd.DataFrame, asof: pd.Timestamp) -> List[str]:
    if fina is None or fina.empty:
        return []
    syms = day["symbol"].astype(str).str.zfill(6).unique().tolist()
    sub = fina[(fina["symbol"].isin(syms)) & (fina["ann_date"] <= asof)]
    if sub.empty:
        return []
    last = sub.sort_values(["symbol", "ann_date"]).groupby("symbol", as_index=False).tail(1)
    last = last[(last["or_yoy"].notna()) | (last["netprofit_yoy"].notna())].copy()
    if last.empty:
        return []
    last["score"] = (
        0.5 * last["or_yoy"].rank(method="average", pct=True).fillna(0.5)
        + 0.5 * last["netprofit_yoy"].rank(method="average", pct=True).fillna(0.5)
    )
    last = last.sort_values(["score", "symbol"], ascending=[False, True])
    return last["symbol"].head(GROWTH_TOP_N).astype(str).tolist()


def build_books(snap: pd.DataFrame, fina: pd.DataFrame) -> Dict[str, List[Tuple[pd.Timestamp, List[str]]]]:
    books = {k: [] for k in SLEEVES}
    q_month = None
    g_month = None
    for dt, day in snap.groupby("date", sort=True):
        dt = pd.Timestamp(dt)
        c4 = day.loc[day["combo_id"] == 4, "symbol"].astype(str).tolist()
        c6 = day.loc[day["combo_id"] == 6, "symbol"].astype(str).tolist()
        books["W4"].append((dt, list(dict.fromkeys(c4))))
        books["W6"].append((dt, list(dict.fromkeys(c6))))
        books["M+"].append((dt, _members_quantile(day, "M+")))
        month = (dt.year, dt.month)
        if month != q_month:
            books["Q"].append((dt, _members_quantile(day, "Q")))
            q_month = month
        if month != g_month:
            books["G"].append((dt, _members_growth(day, fina, dt)))
            g_month = month
    return books


def _active(schedule: List[Tuple[pd.Timestamp, List[str]]], day: pd.Timestamp) -> List[str]:
    chosen: List[str] = []
    for dt, members in schedule:
        if dt < day:
            chosen = members
        else:
            break
    return chosen


def sleeve_returns(
    books: Dict[str, List[Tuple[pd.Timestamp, List[str]]]],
    closes: pd.DataFrame,
) -> pd.DataFrame:
    px = closes.pivot(index="date", columns="symbol", values="close").sort_index()
    dates = list(px.index)
    rows = []
    for i in range(1, len(dates)):
        today = pd.Timestamp(dates[i])
        prev = pd.Timestamp(dates[i - 1])
        rec = {"date": today}
        for name in SLEEVES:
            members = _active(books[name], today)
            rets = []
            for sym in members:
                if sym not in px.columns:
                    continue
                c0 = px.at[prev, sym]
                c1 = px.at[today, sym]
                try:
                    c0f = float(c0)
                    c1f = float(c1)
                except (TypeError, ValueError):
                    continue
                if _finite(c0f) and _finite(c1f) and c0f > 0 and c1f > 0:
                    rets.append(c1f / c0f - 1.0)
            rec[name] = float(np.mean(rets)) if rets else np.nan
            rec[f"n_{name}"] = len(rets)
        rows.append(rec)
    return pd.DataFrame(rows).set_index("date").sort_index()


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


def _ew(names: Sequence[str]) -> Dict[str, float]:
    if not names:
        return {}
    w = 1.0 / len(names)
    return {n: w for n in names}


def _rank_weights(hist: pd.DataFrame, names: Sequence[str]) -> Dict[str, float]:
    mu = hist[list(names)].mean(skipna=True)
    order = mu.rank(method="average", ascending=True)
    total = float(order.sum())
    if not _finite(total) or total <= 0:
        return _ew(names)
    return {n: float(order[n]) / total for n in names}


def _mv_weights(hist: pd.DataFrame, names: Sequence[str]) -> Dict[str, float]:
    cols = list(names)
    sub = hist[cols]
    mu = sub.mean(skipna=True).fillna(0.0).to_numpy(dtype=float)
    cov = sub.cov(min_periods=MIN_OBS).fillna(0.0).to_numpy(dtype=float)
    diag_mean = float(np.mean(np.diag(cov))) if len(cols) else 0.0
    if not _finite(diag_mean):
        diag_mean = 0.0
    shrunk = (1.0 - SHRINK) * cov + SHRINK * (np.eye(len(cols)) * diag_mean)
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


def _eligible(hist: pd.DataFrame) -> List[str]:
    out = []
    for name in SLEEVES:
        if name in hist.columns and int(hist[name].notna().sum()) >= MIN_OBS:
            out.append(name)
    return out


def _apply(row: pd.Series, weights: Dict[str, float]) -> float:
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
        return {"n": float(len(r)), "total": np.nan, "sharpe": np.nan, "mdd": np.nan}
    total = float((1.0 + r).prod() - 1.0)
    std = float(r.std(ddof=0))
    sharpe = float(r.mean() / std * np.sqrt(252.0)) if std > 1e-12 else np.nan
    eq = (1.0 + r).cumprod()
    mdd = float((eq / eq.cummax() - 1.0).min())
    return {"n": float(len(r)), "total": total, "sharpe": sharpe, "mdd": mdd}


def walk_forward(wide: pd.DataFrame):
    dates = list(wide.index)
    n = len(dates)
    hold_start = int(n * (1.0 - HOLDOUT_FRAC))
    hold_start = min(max(hold_start, TRAIN_DAYS + 5), n)
    methods = ("等权", "按收益排序", "均值方差")

    def pack(train_idx, test_idx):
        hist = wide.loc[train_idx]
        names = _eligible(hist)
        if len(names) < 2:
            names = [c for c in SLEEVES if int(hist[c].notna().sum()) > 0]
            weights = {m: _ew(names) for m in methods}
        else:
            weights = {
                "等权": _ew(names),
                "按收益排序": _rank_weights(hist, names),
                "均值方差": _mv_weights(hist, names),
            }
        test = wide.loc[test_idx]
        series = {
            m: test.apply(lambda row, ww=w: _apply(row, ww), axis=1)
            for m, w in weights.items()
        }
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
                    "test_start": pd.Timestamp(test_idx[0]).strftime("%Y-%m-%d"),
                    "test_end": pd.Timestamp(test_idx[-1]).strftime("%Y-%m-%d"),
                    "n": int(p["n"]),
                    "total": p["total"],
                    "sharpe": p["sharpe"],
                    "mdd": p["mdd"],
                    "weights": "; ".join(f"{k}={v:.2f}" for k, v in weights[m].items()),
                }
            )
        fold_id += 1
        i += TEST_DAYS

    hold_series = {}
    if hold_start >= TRAIN_DAYS and hold_start < n:
        weights, hold_series = pack(dates[hold_start - TRAIN_DAYS : hold_start], dates[hold_start:])
        for m in methods:
            p = _perf(hold_series[m])
            fold_rows.append(
                {
                    "fold": "holdout",
                    "method": m,
                    "test_start": pd.Timestamp(dates[hold_start]).strftime("%Y-%m-%d"),
                    "test_end": pd.Timestamp(dates[-1]).strftime("%Y-%m-%d"),
                    "n": int(p["n"]),
                    "total": p["total"],
                    "sharpe": p["sharpe"],
                    "mdd": p["mdd"],
                    "weights": "; ".join(f"{k}={v:.2f}" for k, v in weights[m].items()),
                }
            )
    stitched_s = {
        m: pd.concat(stitched[m]) if stitched[m] else pd.Series(dtype=float) for m in methods
    }
    return pd.DataFrame(fold_rows), stitched_s, hold_series


def _pct(x: float) -> str:
    if x != x:
        return "—"
    return f"{x * 100:.2f}%"


def _num(x: float) -> str:
    if x != x:
        return "—"
    return f"{x:.2f}"


def _beats(challenger: Dict[str, float], base: Dict[str, float]) -> bool:
    return (
        challenger["total"] == challenger["total"]
        and base["total"] == base["total"]
        and challenger["total"] > base["total"]
        and challenger["total"] > 0
        and challenger["sharpe"] == challenger["sharpe"]
        and base["sharpe"] == base["sharpe"]
        and challenger["sharpe"] > base["sharpe"]
    )


def write_report(wide: pd.DataFrame, folds: pd.DataFrame, stitched, hold_series, notes: List[str]) -> str:
    methods = ("等权", "按收益排序", "均值方差")
    wf = {m: _perf(stitched[m]) for m in methods}
    ho = {m: _perf(hold_series[m]) if m in hold_series else _perf(pd.Series(dtype=float)) for m in methods}
    own = {name: _perf(wide[name]) for name in SLEEVES}

    pick_oos = wf["等权"]["total"] > 0 and ho["等权"]["total"] > 0
    construct = []
    for m in ("按收益排序", "均值方差"):
        if _beats(wf[m], wf["等权"]) and _beats(ho[m], ho["等权"]):
            construct.append(m)

    if pick_oos and construct:
        conclusion = (
            "这段样本外，等权累计收益为正，选股这一层在赚钱。"
            + "、".join(construct)
            + "在滚动测试和最后一段都高于等权且自身累计为正，组合构造也多赚到了钱。"
        )
    elif pick_oos and not construct:
        conclusion = (
            "这段样本外，等权累计收益为正，系统赚到的钱来自袖子本身的选股。"
            "按收益排序和均值—方差没有在两段里同时超过等权并保持正收益，组合构造没有多赚钱。"
        )
    elif (not pick_oos) and construct:
        conclusion = (
            "等权在样本外没有赚到钱，选股这一层没有单独成立。"
            + "、".join(construct)
            + "在两段都高于等权且累计为正，多出来的钱来自组合构造。"
        )
    else:
        conclusion = (
            "等权没有在滚动测试和最后一段同时赚到钱，按收益排序和均值—方差也没有在两段里同时赚到超过等权的正收益。"
            "因此既不能说系统靠选股赚钱，也不能说靠组合构造赚钱。某方案若少亏，只说明少亏。"
        )
    detail = (
        f"分开看：滚动测试里等权累计 {_pct(wf['等权']['total'])}，"
        f"按收益排序 {_pct(wf['按收益排序']['total'])}，均值—方差 {_pct(wf['均值方差']['total'])}。"
        f"最后一段（不参与选权重）等权 {_pct(ho['等权']['total'])}，"
        f"按收益排序 {_pct(ho['按收益排序']['total'])}，均值—方差 {_pct(ho['均值方差']['total'])}。"
    )
    if (
        wf["按收益排序"]["total"] > wf["等权"]["total"]
        and wf["均值方差"]["total"] > wf["等权"]["total"]
        and ho["按收益排序"]["total"] < ho["等权"]["total"]
        and ho["均值方差"]["total"] < ho["等权"]["total"]
    ):
        detail += "滚动段里后两种更高，最后一段里它们更差。权重越集中到训练窗里收益最高的那一条，最后一段亏得越多。"

    corr = wide[list(SLEEVES)].corr()
    lines = [
        "# 文档第 15 节袖子实验",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。",
        "",
        "把现有回测截面收成五条日收益：W4、W6、M+、Q、G。",
        "截面文件：`market_neutral/output/latest/factor_snapshot.csv`。",
        "W4、W6 是该调仓日 combo 4、combo 6 的等权，持有到下次调仓。",
        f"M+、Q 用回测同一条规则：因子前 {QUANTILE:.0%} 做多。M+ 随周调仓，Q 只在月份变化时调仓。",
        f"G 取公告日不晚于调仓日的营收同比与净利润同比，池内前 {GROWTH_TOP_N} 名，按月调仓。",
        "四层稳健质量分的拉取不带公告日，不能直接当成这段历史的 G。",
        "收益是收盘到下一交易日收盘，不含手续费。调仓日当天仍用上一期持仓。",
        f"估计窗 {TRAIN_DAYS} 个交易日，测试窗 {TEST_DAYS} 个交易日，最后约 20% 只评价一次。",
        f"均值—方差 λ={LAMBDA:.0f}，协方差向对角收缩 {SHRINK:.0%}，只做多且权重和为 1。按收益排序把估计窗里的平均日收益从低到高排名，权重大小跟名次成正比。",
        "不写回线上配置。",
        "",
        "## 命题",
        "",
        conclusion,
        "",
        detail,
        "",
        "判定只看样本外。等权代表选股之后不再调袖子权重。组合构造要同时满足：滚动测试和最后一段的累计收益都高于等权，夏普也更高，并且该方案自己的累计收益为正。",
        "",
        "## 样本外",
        "",
        "| 方法 | 滚动测试累计 | 滚动夏普 | 最后一段累计 | 最后一段夏普 | 最后一段最大回撤 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for m in methods:
        a, b = wf[m], ho[m]
        lines.append(
            f"| {m} | {_pct(a['total'])} | {_num(a['sharpe'])} | {_pct(b['total'])} | {_num(b['sharpe'])} | {_pct(b['mdd'])} |"
        )
    lines += [
        "",
        "夏普按日收益均值除以波动。累计收益是复利。",
        "",
        "## 各袖子全样本（只描述，不参与判定）",
        "",
        "| 袖子 | 有收益天数 | 累计 | 夏普 | 最大回撤 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name in SLEEVES:
        p = own[name]
        lines.append(
            f"| {name} | {int(p['n'])} | {_pct(p['total'])} | {_num(p['sharpe'])} | {_pct(p['mdd'])} |"
        )
    lines += ["", "## 各折", ""]
    if folds.empty:
        lines.append("样本长度不够切开。")
    else:
        for _, r in folds.iterrows():
            lines.append(
                f"- {r['fold']} · {r['method']} · {r['test_start']} ～ {r['test_end']} · "
                f"累计 {_pct(float(r['total']))} · 夏普 {_num(float(r['sharpe']))} · {r['weights']}"
            )
    lines += [
        "",
        "## 相关",
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
    if not os.path.isfile(SNAPSHOT):
        raise SystemExit(f"缺少回测截面 {SNAPSHOT}")
    snap = load_snapshot()
    symbols = sorted(snap["symbol"].unique())
    start = (snap["date"].min() - pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    end = snap["date"].max().strftime("%Y-%m-%d")
    notes = [
        f"截面 {snap['date'].min().strftime('%Y-%m-%d')} ～ {end}，{snap['date'].nunique()} 个调仓日，{len(symbols)} 只",
    ]
    print(notes[0], flush=True)
    print("  日线 …", flush=True)
    closes = load_closes(symbols, start, end)
    notes.append(f"日线 {closes['symbol'].nunique()} 只，{closes['date'].nunique()} 个交易日")
    print("  成长财务 …", flush=True)
    fina = load_growth(symbols, end)
    notes.append(f"成长财务行数 {len(fina)}")
    print("  组装五条收益 …", flush=True)
    books = build_books(snap, fina)
    for name in SLEEVES:
        sizes = [len(m) for _dt, m in books[name]]
        notes.append(
            f"{name} 调仓 {len(sizes)} 次，持仓中位 {int(np.median(sizes)) if sizes else 0} 只"
        )
    wide = sleeve_returns(books, closes)
    # 只保留截面覆盖到的区间
    wide = wide.loc[(wide.index > snap["date"].min()) & (wide.index <= snap["date"].max())]
    folds, stitched, hold_series = walk_forward(wide)
    path = write_report(wide, folds, stitched, hold_series, notes)
    print(f"报告 → {path}", flush=True)


if __name__ == "__main__":
    main()
