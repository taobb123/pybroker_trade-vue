#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统能力：选股层与组合构造层分开检验。

选股层：组内等权。看 W2∪W3、W4∪W6、M+、Q、G 各自在前段和最后一段是否都赚到钱。
构造层：在这些收益序列已经给定之后，比较
  等权、按收益排序、均值—方差、半凯利缩放、温度 π(S) 缩放。
一个工具要在滚动测试和最后一段都高于等权、夏普也更高，且自身累计为正，才算构造层赚到钱。

不修改线上配置。输入用已经落盘的两条收益，不再改入池规则。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from kelly_position import (  # noqa: E402
    KELLY_CAP,
    estimate_p_b_from_month_rets,
    half_kelly_capped,
)

OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "system_capability")
GROUP_CSV = os.path.join(_SCRIPT_DIR, "output", "h0_w23_w46", "group_returns.csv")
SLEEVE_CSV = os.path.join(_SCRIPT_DIR, "output", "doc15_sleeves", "sleeve_returns.csv")
TEMP_CSV = os.path.join(_SCRIPT_DIR, "market_temperature_backtest.csv")

SELECTION = ("W2+W3", "W4+W6", "M+", "Q", "G")
TRAIN_DAYS = 84
TEST_DAYS = 21
MIN_OBS = 15
HOLDOUT_FRAC = 0.20
LAMBDA = 1.0
SHRINK = 0.5
GRID_STEP = 0.05
METHODS = ("等权", "按收益排序", "均值方差", "半凯利", "温度")


def _finite(x: float) -> bool:
    return x == x and x is not None


def load_panel() -> Tuple[pd.DataFrame, List[str]]:
    notes: List[str] = []
    if not os.path.isfile(GROUP_CSV) or not os.path.isfile(SLEEVE_CSV):
        raise SystemExit("缺少选股层收益。请先运行 h0_w23_vs_w46.py 和 doc15_sleeve_experiment.py")
    g = pd.read_csv(GROUP_CSV, parse_dates=["date"]).set_index("date").sort_index()
    s = pd.read_csv(SLEEVE_CSV, parse_dates=["date"]).set_index("date").sort_index()
    panel = pd.DataFrame(index=g.index.union(s.index).sort_values())
    panel["W2+W3"] = g["W2+W3"]
    panel["W4+W6"] = g["W4+W6"]
    for col in ("M+", "Q", "G"):
        panel[col] = s[col] if col in s.columns else np.nan
    panel = panel.dropna(how="all")
    notes.append(
        f"选股序列 {panel.index.min().strftime('%Y-%m-%d')} ～ {panel.index.max().strftime('%Y-%m-%d')}，{len(panel)} 天"
    )
    return panel[list(SELECTION)], notes


def load_pi() -> pd.Series:
    if not os.path.isfile(TEMP_CSV):
        return pd.Series(dtype=float)
    t = pd.read_csv(TEMP_CSV)
    t["date"] = pd.to_datetime(t["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    t["pi"] = pd.to_numeric(t["position_pct"], errors="coerce") / 100.0
    t = t.dropna(subset=["date", "pi"]).sort_values("date")
    return t.drop_duplicates("date", keep="last").set_index("date")["pi"]


def _perf(rets: pd.Series) -> Dict[str, float]:
    r = pd.to_numeric(rets, errors="coerce").dropna()
    n = int(len(r))
    if n < 5:
        return {"n": float(n), "total": np.nan, "sharpe": np.nan}
    total = float((1.0 + r).prod() - 1.0)
    std = float(r.std(ddof=0))
    sharpe = float(r.mean() / std * np.sqrt(252.0)) if std > 1e-12 else np.nan
    return {"n": float(n), "total": total, "sharpe": sharpe}


def _pct(x: float) -> str:
    if x != x:
        return "—"
    return f"{x * 100:.2f}%"


def _num(x: float) -> str:
    if x != x:
        return "—"
    return f"{x:.2f}"


def _split(idx: pd.Index) -> Tuple[pd.Index, pd.Index]:
    n = len(idx)
    cut = int(n * (1.0 - HOLDOUT_FRAC))
    cut = min(max(cut, TRAIN_DAYS + 5), n - 5) if n > TRAIN_DAYS + 10 else max(n // 2, 1)
    return idx[:cut], idx[cut:]


def _simplex(names: Sequence[str], step: float = GRID_STEP):
    units = int(round(1.0 / step))

    def rec(left: int, k: int):
        if k == 1:
            yield (left,)
            return
        for i in range(left + 1):
            yield from ((i,) + tail for tail in rec(left - i, k - 1))

    n = len(names)
    for comb in rec(units, n):
        yield {names[i]: comb[i] / units for i in range(n)}


def _ew(names: Sequence[str]) -> Dict[str, float]:
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


def _eligible(hist: pd.DataFrame, names: Sequence[str]) -> List[str]:
    out = []
    for name in names:
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


def _month_rets(daily: pd.Series) -> pd.Series:
    r = pd.to_numeric(daily, errors="coerce").dropna()
    if r.empty:
        return r
    return r.groupby(r.index.to_period("M")).apply(lambda x: float((1.0 + x).prod() - 1.0))


def _kelly_scale(daily_before: pd.Series) -> float:
    month = _month_rets(daily_before)
    if len(month) > 1:
        month = month.iloc[:-1]
    p, b, _n, _nw, _nl, note = estimate_p_b_from_month_rets(month)
    if note:
        return float(KELLY_CAP)
    _full, _half, capped = half_kelly_capped(p, b)
    return float(capped)


def _pi_on(pi: pd.Series, day: pd.Timestamp) -> float:
    if pi.empty:
        return 1.0
    prior = pi.loc[: day - pd.Timedelta(days=1)]
    if prior.empty:
        return 1.0
    return float(prior.iloc[-1])


def walk_forward(panel: pd.DataFrame, pi: pd.Series):
    dates = list(panel.dropna(how="all").index)
    front, hold = _split(pd.Index(dates))
    region = list(front)
    stitched = {m: [] for m in METHODS}
    fold_rows = []

    def ew_book(frame: pd.DataFrame) -> pd.Series:
        names = [c for c in SELECTION if c in frame.columns]
        w = _ew(names)
        return frame.apply(lambda row, ww=w: _apply(row, ww), axis=1)

    def one_window(train_idx, test_idx, fold_name):
        hist = panel.loc[train_idx]
        names = _eligible(hist, SELECTION)
        if len(names) < 2:
            names = [c for c in SELECTION if int(hist[c].notna().sum()) > 0]
        weights = {
            "等权": _ew(names),
            "按收益排序": _rank_weights(hist, names),
            "均值方差": _mv_weights(hist, names) if len(names) >= 2 else _ew(names),
        }
        test = panel.loc[test_idx]
        series = {}
        for m in ("等权", "按收益排序", "均值方差"):
            series[m] = test.apply(lambda row, ww=weights[m]: _apply(row, ww), axis=1)
        past = ew_book(panel.loc[: pd.Timestamp(train_idx[-1])])
        scale = _kelly_scale(past)
        series["半凯利"] = series["等权"] * scale
        ew = series["等权"]
        series["温度"] = pd.Series(
            [
                (np.nan if not _finite(float(ew.loc[d])) else _pi_on(pi, pd.Timestamp(d)) * float(ew.loc[d]))
                for d in ew.index
            ],
            index=ew.index,
        )
        for m in METHODS:
            stitched[m].append(series[m])
            p = _perf(series[m])
            fold_rows.append(
                {
                    "fold": fold_name,
                    "method": m,
                    "test_start": pd.Timestamp(test_idx[0]).strftime("%Y-%m-%d"),
                    "test_end": pd.Timestamp(test_idx[-1]).strftime("%Y-%m-%d"),
                    "total": p["total"],
                    "sharpe": p["sharpe"],
                    "note": f"kelly={scale:.2f}" if m == "半凯利" else "",
                }
            )
        return series

    i = TRAIN_DAYS
    fold_id = 1
    while i < len(region):
        train_idx = region[i - TRAIN_DAYS : i]
        test_idx = region[i : min(i + TEST_DAYS, len(region))]
        if len(test_idx) < 5:
            break
        one_window(train_idx, test_idx, fold_id)
        fold_id += 1
        i += TEST_DAYS

    hold_series = {}
    if len(hold) >= 5 and len(front) >= TRAIN_DAYS:
        train_idx = list(front)[-TRAIN_DAYS:]
        hold_series = one_window(train_idx, list(hold), "holdout")

    stitched_s = {
        m: pd.concat(stitched[m]) if stitched[m] else pd.Series(dtype=float) for m in METHODS
    }
    # 滚动测试不含最后一段。holdout 被 one_window 追加进了 stitched，拆回去。
    wf = {}
    ho = {}
    for m in METHODS:
        full = stitched_s[m]
        if hold_series:
            ho[m] = hold_series[m]
            wf[m] = full.iloc[: len(full) - len(hold_series[m])]
        else:
            ho[m] = pd.Series(dtype=float)
            wf[m] = full
    return pd.DataFrame(fold_rows), wf, ho, front, hold


def _passes(challenger: Dict[str, float], base: Dict[str, float]) -> bool:
    return (
        challenger["total"] == challenger["total"]
        and base["total"] == base["total"]
        and challenger["sharpe"] == challenger["sharpe"]
        and base["sharpe"] == base["sharpe"]
        and challenger["total"] > base["total"]
        and challenger["sharpe"] > base["sharpe"]
        and challenger["total"] > 0
    )


def write_report(panel, notes, folds, wf, ho, front, hold) -> str:
    os.makedirs(OUT_DIR, exist_ok=True)
    sel_rows = []
    picked = []
    for name in SELECTION:
        a = _perf(panel.loc[front, name])
        b = _perf(panel.loc[hold, name])
        ok = a["total"] == a["total"] and b["total"] == b["total"] and a["total"] > 0 and b["total"] > 0
        if ok:
            picked.append(name)
        sel_rows.append((name, a, b, ok))

    if picked:
        sel_text = "选股层里，" + "、".join(picked) + " 的等权在前段和最后一段累计都为正。这些组在这段样本上赚到了钱。"
    else:
        sel_text = "选股层里，没有一个信号组的等权在前段和最后一段累计都为正。这段样本不能说系统靠选股赚钱。"

    a23 = _perf(panel.loc[hold, "W2+W3"])
    a46 = _perf(panel.loc[hold, "W4+W6"])
    if a46["total"] == a46["total"] and a23["total"] == a23["total"] and a46["total"] > a23["total"]:
        pair = "最后一段 W4∪W6 的等权累计高于 W2∪W3。"
    else:
        pair = "最后一段 W4∪W6 的等权累计没有高于 W2∪W3。"

    wf_p = {m: _perf(wf[m]) for m in METHODS}
    ho_p = {m: _perf(ho[m]) for m in METHODS}
    passed = []
    for m in METHODS:
        if m == "等权":
            continue
        if _passes(wf_p[m], wf_p["等权"]) and _passes(ho_p[m], ho_p["等权"]):
            passed.append(m)
    if passed:
        con_text = "构造层里，" + "、".join(passed) + " 在滚动测试和最后一段都高于等权，夏普也更高，且自身累计为正。多出来的钱来自组合构造。"
    else:
        con_text = "构造层里，没有工具同时满足：滚动测试和最后一段都高于等权、夏普更高、自身累计为正。这段样本不能说系统靠组合构造赚钱。"

    lines = [
        "# 系统能力：选股与组合构造",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。",
        "",
        "两层分开写。选股层权重固定为等权。构造层只在这些日收益已经给定之后配权或缩放总仓位。",
        "半凯利和温度都作用在等权组合上：半凯利用测试窗之前的月收益估计，温度用收益日之前已经公布的 π(S)。",
        f"估计窗 {TRAIN_DAYS} 个交易日，测试窗 {TEST_DAYS} 个交易日。最后约 20% 只评价一次。",
        "一个构造工具要在两段都高于等权、夏普也更高，并且自身累计为正，才算赚到钱。",
        "不写回线上配置。",
        "",
        "## 选股层",
        "",
        sel_text,
        pair,
        "",
        "| 信号组 | 前段累计 | 前段夏普 | 最后一段累计 | 最后一段夏普 | 两段都为正 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, a, b, ok in sel_rows:
        lines.append(
            f"| {name} | {_pct(a['total'])} | {_num(a['sharpe'])} | {_pct(b['total'])} | {_num(b['sharpe'])} | {'是' if ok else '否'} |"
        )
    lines += [
        "",
        "## 组合构造层",
        "",
        con_text,
        "",
        "| 工具 | 滚动测试累计 | 滚动夏普 | 最后一段累计 | 最后一段夏普 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for m in METHODS:
        a, b = wf_p[m], ho_p[m]
        lines.append(
            f"| {m} | {_pct(a['total'])} | {_num(a['sharpe'])} | {_pct(b['total'])} | {_num(b['sharpe'])} |"
        )
    lines += ["", "## 各折", ""]
    if folds.empty:
        lines.append("样本不够切开。")
    else:
        for _, r in folds.iterrows():
            extra = f" · {r['note']}" if str(r["note"]) else ""
            lines.append(
                f"- {r['fold']} · {r['method']} · {r['test_start']} ～ {r['test_end']} · "
                f"累计 {_pct(float(r['total']))} · 夏普 {_num(float(r['sharpe']))}{extra}"
            )
    lines += ["", "## 取数", ""]
    for note in notes:
        lines.append(f"- {note}")
    lines.append(f"- 前段 {pd.Timestamp(front[0]).strftime('%Y-%m-%d')} ～ {pd.Timestamp(front[-1]).strftime('%Y-%m-%d')}")
    if len(hold):
        lines.append(f"- 最后一段 {pd.Timestamp(hold[0]).strftime('%Y-%m-%d')} ～ {pd.Timestamp(hold[-1]).strftime('%Y-%m-%d')}")
    lines.append("")
    path = os.path.join(OUT_DIR, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    panel.to_csv(os.path.join(OUT_DIR, "selection_returns.csv"), encoding="utf-8-sig")
    folds.to_csv(os.path.join(OUT_DIR, "folds.csv"), index=False, encoding="utf-8-sig")
    return path


def main() -> None:
    panel, notes = load_panel()
    pi = load_pi()
    notes.append(f"温度序列 {len(pi)} 天" if len(pi) else "没有温度回测序列，π 按 100% 计")
    print("走两层检验 …", flush=True)
    folds, wf, ho, front, hold = walk_forward(panel, pi)
    path = write_report(panel, notes, folds, wf, ho, front, hold)
    print(f"报告 → {path}", flush=True)


if __name__ == "__main__":
    main()
