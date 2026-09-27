#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
问题三：检验第 15 节的信号命题，不比较权重方法。

命题：
  H0: Ann(Long(W2 ∪ W3)) ≤ Ann(Long(W4 ∪ W6))

固定等权。同一批股票、同一套初始 θ 的 Phase1 分类。
滚动 6 个交易日、同票只留最新 combo。
落到 2 或 3 的进 W2∪W3，落到 4 或 6 的进 W4∪W6。
D_t = R_t(W4∪W6) − R_t(W2∪W3)。

最后约 20% 交易日只评价一次。最后一段年化仍然是 W4∪W6 更高，才把命题标成这段样本支持。
不修改线上配置，不做均值—方差。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_SCRIPT_DIR)
for p in (_SCRIPT_DIR, _PROJ):
    if p not in sys.path:
        sys.path.insert(0, p)

from backtest_sy_002028_threshold import fetch_ohlc_qfq  # noqa: E402
from fetch_vp_six_combo import _ensure_volume_col  # noqa: E402
from sleeve_mv_experiment import (  # noqa: E402
    BREAK_N,
    MA20_LB,
    RANGE_N,
    VOL_MA,
    WATCH_DAYS,
    combo_id_row,
)

OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "h0_w23_w46")
SNAPSHOT = os.path.join(
    _SCRIPT_DIR, "market_neutral", "output", "latest", "factor_snapshot.csv"
)
FETCH_START = "2024-09-01"
EVAL_START = "2025-06-06"
HOLDOUT_FRAC = 0.20
GROUPS = ("W2+W3", "W4+W6")


def _finite(x: float) -> bool:
    return x == x and x is not None


def load_symbols() -> List[str]:
    df = pd.read_csv(SNAPSHOT, usecols=["symbol"])
    syms = (
        df["symbol"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    )
    return sorted(set(s for s in syms if len(s) == 6))


def load_bars(symbols: Sequence[str], end: str) -> pd.DataFrame:
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = os.path.join(OUT_DIR, "bars.csv")
    frames: List[pd.DataFrame] = []
    have = set()
    if os.path.isfile(cache):
        old = pd.read_csv(cache)
        old["symbol"] = old["symbol"].astype(str).str.zfill(6)
        old["date"] = pd.to_datetime(old["date"])
        frames.append(old)
        have = set(old["symbol"].unique())
    todo = [s for s in symbols if s not in have]
    need_cols = ["date", "symbol", "close", "high", "low", "volume"]
    for i, sym in enumerate(todo):
        try:
            raw = fetch_ohlc_qfq(sym, FETCH_START, end)
        except Exception as exc:
            print(f"  [px] {sym} 跳过: {exc}", flush=True)
            raw = None
        if raw is not None and not raw.empty:
            d = _ensure_volume_col(raw)
            d["date"] = pd.to_datetime(d["date"])
            for c in ("close", "high", "low", "volume"):
                d[c] = pd.to_numeric(d[c], errors="coerce")
            d["symbol"] = sym
            frames.append(d[need_cols])
        if todo and ((i + 1) % 20 == 0 or i + 1 == len(todo)):
            print(f"  [px] {i + 1}/{len(todo)}", flush=True)
    if not frames:
        return pd.DataFrame(columns=need_cols)
    out = pd.concat(frames, ignore_index=True).dropna(subset=["close"])
    out = out.drop_duplicates(["date", "symbol"], keep="last")
    out.to_csv(cache, index=False, encoding="utf-8-sig")
    return out


def classify(bars: pd.DataFrame) -> pd.DataFrame:
    frames: List[pd.DataFrame] = []
    need = max(65, RANGE_N, VOL_MA + 1, BREAK_N + 1)
    for sym, raw in bars.groupby("symbol", sort=False):
        d = raw.sort_values("date").reset_index(drop=True)
        d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
        d["ma60"] = d["close"].rolling(60, min_periods=60).mean()
        d["vol_ma"] = d["volume"].shift(1).rolling(VOL_MA, min_periods=VOL_MA).mean()
        d["range_low"] = d["low"].rolling(RANGE_N, min_periods=RANGE_N).min()
        d["range_high"] = d["high"].rolling(RANGE_N, min_periods=RANGE_N).max()
        d["ma20_prev"] = d["ma20"].shift(MA20_LB)
        d["prior_high"] = d["high"].shift(1).rolling(BREAK_N, min_periods=BREAK_N).max()
        d["prev_close"] = d["close"].shift(1)
        d = d.iloc[need:].copy()
        d = d.dropna(subset=["ma20", "ma60", "vol_ma", "ma20_prev", "prior_high", "prev_close"])
        d = d[(d["vol_ma"] > 0) & (d["prev_close"] > 0) & (d["close"] > 0)]
        if d.empty:
            continue
        span = d["range_high"] - d["range_low"]
        d["range_pct"] = ((d["close"] - d["range_low"]) / span).where(span > 1e-12, 0.5).clip(0.0, 1.0)
        d["vol_ratio"] = d["volume"] / d["vol_ma"]
        d["symbol"] = sym
        d["combo_id"] = d.apply(combo_id_row, axis=1).astype(int)
        frames.append(d[["symbol", "date", "close", "combo_id"]])
    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    return out


def group_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """收益日记在次日。持仓用当日收盘已经知道的滚动观察池。"""
    work = panel.sort_values(["symbol", "date"])
    dates = list(work["date"].drop_duplicates().sort_values())
    by_sym = {
        sym: g.drop_duplicates("date").set_index("date").sort_index()
        for sym, g in work.groupby("symbol", sort=False)
    }
    closes: Dict[Tuple[str, pd.Timestamp], float] = {}
    for sym, g in by_sym.items():
        for dt, c in g["close"].items():
            cf = float(c)
            if _finite(cf) and cf > 0:
                closes[(sym, pd.Timestamp(dt))] = cf

    rows = []
    for i, d in enumerate(dates[:-1]):
        nxt = dates[i + 1]
        start = dates[max(0, i - WATCH_DAYS + 1)]
        g23: List[str] = []
        g46: List[str] = []
        for sym, g in by_sym.items():
            window = g[(g.index >= start) & (g.index <= d)]
            if window.empty:
                continue
            cid = int(window.iloc[-1]["combo_id"])
            if cid in (2, 3):
                g23.append(sym)
            elif cid in (4, 6):
                g46.append(sym)

        def _ret(members: List[str]) -> Tuple[float, int]:
            rets = []
            for sym in members:
                c0 = closes.get((sym, d))
                c1 = closes.get((sym, nxt))
                if c0 and c1 and c0 > 0 and c1 > 0:
                    rets.append(c1 / c0 - 1.0)
            if not rets:
                return float("nan"), 0
            return float(np.mean(rets)), len(rets)

        r23, n23 = _ret(g23)
        r46, n46 = _ret(g46)
        rows.append(
            {
                "date": nxt,
                "W2+W3": r23,
                "W4+W6": r46,
                "n_W2+W3": n23,
                "n_W4+W6": n46,
            }
        )
    out = pd.DataFrame(rows).set_index("date").sort_index()
    return out


def _perf(rets: pd.Series) -> Dict[str, float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    n = int(len(r))
    if n < 5:
        return {"n": float(n), "total": np.nan, "ann": np.nan, "sharpe": np.nan, "mdd": np.nan}
    total = float((1.0 + r).prod() - 1.0)
    ann = float((1.0 + total) ** (252.0 / n) - 1.0)
    std = float(r.std(ddof=0))
    sharpe = float(r.mean() / std * np.sqrt(252.0)) if std > 1e-12 else np.nan
    eq = (1.0 + r).cumprod()
    mdd = float((eq / eq.cummax() - 1.0).min())
    return {"n": float(n), "total": total, "ann": ann, "sharpe": sharpe, "mdd": mdd}


def _diff_stats(d: pd.Series) -> Dict[str, float]:
    x = pd.to_numeric(d, errors="coerce").dropna()
    n = int(len(x))
    if n < 5:
        return {"n": float(n), "mean": np.nan, "t": np.nan, "pos": np.nan}
    std = float(x.std(ddof=1))
    t = float(x.mean() / (std / np.sqrt(n))) if std > 1e-12 else np.nan
    return {
        "n": float(n),
        "mean": float(x.mean()),
        "t": t,
        "pos": float((x > 0).mean()),
    }


def _pct(x: float) -> str:
    if x != x:
        return "—"
    return f"{x * 100:.2f}%"


def _num(x: float) -> str:
    if x != x:
        return "—"
    return f"{x:.2f}"


def write_report(wide: pd.DataFrame, notes: List[str]) -> str:
    both = wide.dropna(subset=["W2+W3", "W4+W6"]).copy()
    both["D"] = both["W4+W6"] - both["W2+W3"]
    n = len(both)
    cut = int(n * (1.0 - HOLDOUT_FRAC))
    cut = min(max(cut, 20), n - 5) if n > 30 else max(n // 2, 1)
    front = both.iloc[:cut]
    hold = both.iloc[cut:]

    segs = {
        "前段": front,
        "最后一段": hold,
        "全样本": both,
    }
    perf = {
        seg: {g: _perf(df[g]) for g in GROUPS}
        for seg, df in segs.items()
    }
    dstat = {seg: _diff_stats(df["D"]) for seg, df in segs.items()}

    front_ok = (
        perf["前段"]["W4+W6"]["ann"] > perf["前段"]["W2+W3"]["ann"]
        and dstat["前段"]["mean"] > 0
    )
    hold_ok = (
        perf["最后一段"]["W4+W6"]["ann"] > perf["最后一段"]["W2+W3"]["ann"]
        and dstat["最后一段"]["mean"] > 0
    )
    if hold_ok and front_ok:
        conclusion = (
            "前段和最后一段都是 W4∪W6 的年化更高，而且日差均值大于 0。"
            "就这段样本、这批股票、等权多头而言，第 15 节命题得到支持。"
            "这不是组合构造的结论，也没有改线上观察池。"
        )
    elif hold_ok and not front_ok:
        conclusion = (
            "最后一段 W4∪W6 的年化更高、日差均值大于 0，但前段不是这样。"
            "最后一段单独成立，还不能把命题标成稳定成立。"
        )
    elif front_ok and not hold_ok:
        conclusion = (
            "前段看起来 W4∪W6 更好，最后一段没有保持。"
            "按问题三的标准，命题仍不能标成成立。"
        )
    else:
        conclusion = (
            "最后一段并不是 W4∪W6 的年化更高且日差均值为正。"
            "这段样本不支持「W4∪W6 的等权多头优于 W2∪W3」。命题不能标成成立。"
        )

    lines = [
        "# 问题三：W2∪W3 对 W4∪W6",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。",
        "",
        "命题：Ann(Long(W2∪W3)) ≤ Ann(Long(W4∪W6))。",
        "权重固定为组内等权。不比较等权、收益排序和均值—方差。",
        "同一批股票用初始 θ 的 Phase1 分类。滚动 6 个交易日，同票只留最新 combo。",
        "combo 2 或 3 进入 W2∪W3，combo 4 或 6 进入 W4∪W6。",
        "D = 当日 W4∪W6 收益 − 当日 W2∪W3 收益。两边都有持仓的交易日才进入比较。",
        "收益是持仓日收盘到下一交易日收盘，不含手续费。",
        "最后约 20% 交易日只评价一次。最后一段仍然成立，才把命题标成这段样本支持。",
        "前段不是滚动选权重，只是留出最后一段之前的样本，用来看结论会不会反转。",
        "不写回线上配置。",
        "",
        "## 命题",
        "",
        conclusion,
        "",
        f"前段 {front.index.min().strftime('%Y-%m-%d')} ～ {front.index.max().strftime('%Y-%m-%d')}，"
        f"最后一段 {hold.index.min().strftime('%Y-%m-%d')} ～ {hold.index.max().strftime('%Y-%m-%d')}。"
        if n else "没有可比较的交易日。",
        "",
        "## 对照",
        "",
        "| 组合 | 前段累计 | 前段年化 | 前段夏普 | 前段最大回撤 | 最后一段累计 | 最后一段年化 | 最后一段夏普 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for g in GROUPS:
        a = perf["前段"][g]
        b = perf["最后一段"][g]
        lines.append(
            f"| {g} | {_pct(a['total'])} | {_pct(a['ann'])} | {_num(a['sharpe'])} | {_pct(a['mdd'])} | "
            f"{_pct(b['total'])} | {_pct(b['ann'])} | {_num(b['sharpe'])} |"
        )
    da, db = perf["前段"], perf["最后一段"]
    lines.append(
        "| 差值（4+6 减 2+3） | "
        f"{_pct(da['W4+W6']['total'] - da['W2+W3']['total'])} | "
        f"{_pct(da['W4+W6']['ann'] - da['W2+W3']['ann'])} | "
        f"{_num(da['W4+W6']['sharpe'] - da['W2+W3']['sharpe'])} | "
        f"{_pct(da['W4+W6']['mdd'] - da['W2+W3']['mdd'])} | "
        f"{_pct(db['W4+W6']['total'] - db['W2+W3']['total'])} | "
        f"{_pct(db['W4+W6']['ann'] - db['W2+W3']['ann'])} | "
        f"{_num(db['W4+W6']['sharpe'] - db['W2+W3']['sharpe'])} |"
    )
    lines += [
        "",
        "## 日差",
        "",
        "日差均值大于 0，表示 W4∪W6 的等权日收益平均更高。t 只描述均值离 0 有多远，不当成多重检验之后的最终判决。",
        "",
        "| 区间 | 天数 | 日差均值 | t | 日差为正的比例 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for seg in ("前段", "最后一段", "全样本"):
        s = dstat[seg]
        lines.append(
            f"| {seg} | {int(s['n'])} | {_pct(s['mean'])} | {_num(s['t'])} | {_pct(s['pos'])} |"
        )
    lines += ["", "## 取数", ""]
    cov23 = float(wide["W2+W3"].notna().mean()) if len(wide) else 0.0
    cov46 = float(wide["W4+W6"].notna().mean()) if len(wide) else 0.0
    notes = list(notes) + [
        f"有收益的交易日占比：W2+W3 {cov23:.0%}，W4+W6 {cov46:.0%}",
        f"两边同时有持仓 {len(both)} 天",
        f"同时有持仓时，W2+W3 持仓中位 {int(both['n_W2+W3'].median()) if len(both) else 0} 只，"
        f"W4+W6 持仓中位 {int(both['n_W4+W6'].median()) if len(both) else 0} 只",
    ]
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")
    path = os.path.join(OUT_DIR, "report.md")
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    wide.to_csv(os.path.join(OUT_DIR, "group_returns.csv"), encoding="utf-8-sig")
    return path


def main() -> None:
    end = "2026-07-31"
    symbols = load_symbols()
    if not symbols:
        raise SystemExit("截面没有股票")
    notes = [
        f"宇宙来自 4+6 回测截面，共 {len(symbols)} 只。2+3 与 4+6 是这批股票在不同日子的分类，不是两套独立名单。",
        f"取数 {FETCH_START} ～ {end}，比较从 {EVAL_START} 开始。",
    ]
    print(notes[0], flush=True)
    bars = load_bars(symbols, end)
    print(f"  分类 {bars['symbol'].nunique()} 只 …", flush=True)
    panel = classify(bars)
    if panel.empty:
        raise SystemExit("没有分类结果")
    wide = group_returns(panel)
    wide = wide.loc[wide.index >= pd.Timestamp(EVAL_START)]
    counts = panel["combo_id"].value_counts().to_dict()
    notes.append("分类行数 " + ", ".join(f"combo {k}={int(v)}" for k, v in sorted(counts.items())))
    path = write_report(wide, notes)
    print(f"报告 → {path}", flush=True)


if __name__ == "__main__":
    main()
