#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0：选股 Alpha 离线报告。

四张表：
  1. 相对沪深300的超额，以及 R = α + β Rm
  2. W2–W6 状态在信号日后 1/3/5/10/20 个交易日的收益
  3. M+、Q、G 的 IC 及随持有期衰减。G 是营收同比与净利润同比
  4. 温度总分 S 分组下的条件收益

不改线上入池规则，不做均值—方差、半凯利、收益排序和温度仓位。
因子只标注 A/B/C/D，不删除、不改观察池。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from h0_w23_vs_w46 import EVAL_START, classify, load_bars, load_symbols  # noqa: E402

OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "p0_alpha")
SNAPSHOT = os.path.join(
    _SCRIPT_DIR, "market_neutral", "output", "latest", "factor_snapshot.csv"
)
GROWTH_CSV = os.path.join(_SCRIPT_DIR, "output", "doc15_sleeves", "growth_fina.csv")
BENCH_CSV = os.path.join(
    _SCRIPT_DIR, "market_neutral", "output", "latest", "benchmark_nav.csv"
)
TEMP_CSV = os.path.join(_SCRIPT_DIR, "market_temperature_backtest.csv")
GROUP_CSV = os.path.join(_SCRIPT_DIR, "output", "h0_w23_w46", "group_returns.csv")
SLEEVE_CSV = os.path.join(_SCRIPT_DIR, "output", "doc15_sleeves", "sleeve_returns.csv")

HOLDOUT_START = "2026-05-13"
EVAL_END = "2026-07-31"
HORIZONS = (1, 3, 5, 10, 20)
STATES = (2, 3, 4, 5, 6)
GAP = 20
THRESHOLDS = (20, 30, 40, 50, 60, 70)
WEAK_S = 40.0
BOOKS = ("W2+W3", "W4+W6", "M+", "Q", "G")


def _finite(x: float) -> bool:
    return x == x and x is not None


def _pct(x: float) -> str:
    if not _finite(x):
        return "—"
    return f"{x * 100:.2f}%"


def _num(x: float) -> str:
    if not _finite(x):
        return "—"
    return f"{x:.3f}"


def load_classified(symbols: Sequence[str]) -> pd.DataFrame:
    os.makedirs(OUT_DIR, exist_ok=True)
    cache = os.path.join(OUT_DIR, "classified.csv")
    if os.path.isfile(cache):
        df = pd.read_csv(cache)
        df["symbol"] = df["symbol"].astype(str).str.zfill(6)
        df["date"] = pd.to_datetime(df["date"])
        return df
    print("  分类 …", flush=True)
    bars = load_bars(symbols, EVAL_END)
    df = classify(bars)
    df.to_csv(cache, index=False, encoding="utf-8-sig")
    return df


def load_bench() -> pd.Series:
    b = pd.read_csv(BENCH_CSV, parse_dates=["date"])
    b = b.sort_values("date")
    eq = pd.to_numeric(b["equity"], errors="coerce")
    r = eq.pct_change()
    out = pd.Series(r.to_numpy(), index=pd.to_datetime(b["date"])).dropna()
    out.index = out.index.normalize()
    return out


def load_temp() -> pd.DataFrame:
    t = pd.read_csv(TEMP_CSV)
    t["date"] = pd.to_datetime(t["trade_date"].astype(str), format="%Y%m%d", errors="coerce")
    t["S"] = pd.to_numeric(t["total_score"], errors="coerce")
    t = t.dropna(subset=["date", "S"]).sort_values("date")
    t["date"] = t["date"].dt.normalize()
    return t.drop_duplicates("date", keep="last").set_index("date")[["S"]]


def load_books() -> pd.DataFrame:
    g = pd.read_csv(GROUP_CSV, parse_dates=["date"]).set_index("date").sort_index()
    s = pd.read_csv(SLEEVE_CSV, parse_dates=["date"]).set_index("date").sort_index()
    df = pd.DataFrame(index=g.index.union(s.index).sort_values())
    df["W2+W3"] = g["W2+W3"]
    df["W4+W6"] = g["W4+W6"]
    for col in ("M+", "Q", "G"):
        df[col] = s[col] if col in s.columns else np.nan
    df.index = pd.to_datetime(df.index).normalize()
    return df


def _ols(y: np.ndarray, x: np.ndarray) -> Tuple[float, float]:
    if len(y) < 8:
        return float("nan"), float("nan")
    design = np.column_stack([np.ones(len(y)), x])
    coef, _, _, _ = np.linalg.lstsq(design, y, rcond=None)
    return float(coef[0]), float(coef[1])


def alpha_table(books: pd.DataFrame, market: pd.Series) -> pd.DataFrame:
    rows = []
    for name in BOOKS:
        both = pd.DataFrame({"s": books[name], "m": market}).dropna()
        both = both.loc[(both.index >= EVAL_START) & (both.index <= EVAL_END)]
        for seg, part in (
            ("前段", both.loc[both.index < HOLDOUT_START]),
            ("最后一段", both.loc[both.index >= HOLDOUT_START]),
            ("全样本", both),
        ):
            if len(part) < 8:
                rows.append({"book": name, "seg": seg, "n": len(part)})
                continue
            a, beta = _ols(part["s"].to_numpy(), part["m"].to_numpy())
            tot_s = float((1.0 + part["s"]).prod() - 1.0)
            tot_m = float((1.0 + part["m"]).prod() - 1.0)
            rows.append(
                {
                    "book": name,
                    "seg": seg,
                    "n": int(len(part)),
                    "total": tot_s,
                    "mkt": tot_m,
                    "excess": tot_s - tot_m,
                    "alpha_ann": a * 252.0,
                    "beta": beta,
                }
            )
    return pd.DataFrame(rows)


def _by_symbol(panel: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    out = {}
    for sym, g in panel.groupby("symbol", sort=False):
        d = g.drop_duplicates("date").sort_values("date").set_index("date")
        out[str(sym).zfill(6)] = d
    return out


def _fwd(g: pd.DataFrame, loc: int, h: int) -> float:
    if loc + h >= len(g):
        return float("nan")
    c0 = float(g.iloc[loc]["close"])
    c1 = float(g.iloc[loc + h]["close"])
    if not (_finite(c0) and _finite(c1) and c0 > 0 and c1 > 0):
        return float("nan")
    return c1 / c0 - 1.0


def event_table(panel: pd.DataFrame, temp: pd.DataFrame) -> pd.DataFrame:
    """同一股票、同一状态，至少隔 20 个交易日才再计一次。"""
    rows = []
    temp_df = temp.reset_index().sort_values("date")
    for sym, g in _by_symbol(panel).items():
        g = g.loc[(g.index >= EVAL_START) & (g.index <= EVAL_END)]
        if g.empty:
            continue
        s_asof = pd.merge_asof(
            pd.DataFrame({"date": g.index}),
            temp_df,
            on="date",
            direction="backward",
        )
        s_map = dict(zip(s_asof["date"], s_asof["S"]))
        for cid in STATES:
            last_loc = -10**9
            for loc, (dt, row) in enumerate(g.iterrows()):
                if int(row["combo_id"]) != cid:
                    continue
                if loc - last_loc < GAP:
                    continue
                last_loc = loc
                rec = {
                    "symbol": sym,
                    "date": dt,
                    "state": cid,
                    "S": s_map.get(dt, np.nan),
                    "seg": "最后一段" if dt >= pd.Timestamp(HOLDOUT_START) else "前段",
                }
                ok = False
                for h in HORIZONS:
                    rec[f"r{h}"] = _fwd(g, loc, h)
                    if _finite(rec[f"r{h}"]):
                        ok = True
                if ok:
                    rows.append(rec)
    return pd.DataFrame(rows)


def _event_stats(ev: pd.DataFrame, mask: pd.Series) -> Dict[str, float]:
    sub = ev.loc[mask]
    out = {"n": float(len(sub))}
    for h in HORIZONS:
        col = f"r{h}"
        if sub.empty or col not in sub.columns:
            out[f"mu{h}"] = np.nan
            out[f"p{h}"] = np.nan
            out[f"med{h}"] = np.nan
            continue
        x = pd.to_numeric(sub[col], errors="coerce").dropna()
        out[f"mu{h}"] = float(x.mean()) if len(x) else np.nan
        out[f"p{h}"] = float((x > 0).mean()) if len(x) else np.nan
        out[f"med{h}"] = float(x.median()) if len(x) else np.nan
    weak = sub[pd.to_numeric(sub["S"], errors="coerce") <= WEAK_S] if len(sub) else sub
    x20 = pd.to_numeric(weak.get("r20", pd.Series(dtype=float)), errors="coerce").dropna()
    out["weak_n"] = float(len(x20))
    out["weak20"] = float(x20.mean()) if len(x20) else np.nan
    return out


def load_growth() -> pd.DataFrame:
    g = pd.read_csv(GROWTH_CSV)
    g["symbol"] = g["symbol"].astype(str).str.zfill(6)
    g["ann_date"] = pd.to_datetime(g["ann_date"], errors="coerce")
    g["or_yoy"] = pd.to_numeric(g["or_yoy"], errors="coerce")
    g["netprofit_yoy"] = pd.to_numeric(g["netprofit_yoy"], errors="coerce")
    return g.dropna(subset=["ann_date"])


def _score_g(fina: pd.DataFrame, symbols: Sequence[str], asof: pd.Timestamp) -> pd.DataFrame:
    sub = fina[(fina["symbol"].isin(symbols)) & (fina["ann_date"] <= asof)]
    if sub.empty:
        return pd.DataFrame(columns=["symbol", "G"])
    last = sub.sort_values(["symbol", "ann_date"]).groupby("symbol", as_index=False).tail(1)
    last = last[(last["or_yoy"].notna()) | (last["netprofit_yoy"].notna())].copy()
    if last.empty:
        return pd.DataFrame(columns=["symbol", "G"])
    last["G"] = (
        0.5 * last["or_yoy"].rank(method="average", pct=True).fillna(0.5)
        + 0.5 * last["netprofit_yoy"].rank(method="average", pct=True).fillna(0.5)
    )
    return last[["symbol", "G"]]


def ic_frame(bars_panel: pd.DataFrame, fina: pd.DataFrame, temp: pd.DataFrame) -> pd.DataFrame:
    snap = pd.read_csv(SNAPSHOT)
    snap["date"] = pd.to_datetime(snap["date"]).dt.normalize()
    snap["symbol"] = snap["symbol"].astype(str).str.replace(r"\.0$", "", regex=True).str.zfill(6)
    snap["mud_plus"] = pd.to_numeric(snap["mud_plus"], errors="coerce")
    snap["company_q"] = pd.to_numeric(snap["company_q"], errors="coerce")
    by = _by_symbol(bars_panel)
    rows = []
    for dt, day in snap.groupby("date", sort=True):
        dt = pd.Timestamp(dt)
        if dt < pd.Timestamp(EVAL_START) or dt > pd.Timestamp(EVAL_END):
            continue
        syms = day["symbol"].tolist()
        gscore = _score_g(fina, syms, dt)
        day = day.merge(gscore, on="symbol", how="left")
        s_val = np.nan
        if not temp.empty:
            prior = temp.loc[:dt]
            if len(prior):
                s_val = float(prior.iloc[-1]["S"])
        base = {
            "date": dt,
            "seg": "最后一段" if dt >= pd.Timestamp(HOLDOUT_START) else "前段",
            "S": s_val,
        }
        for h in HORIZONS:
            rets = []
            for _, r in day.iterrows():
                g = by.get(str(r["symbol"]))
                if g is None or dt not in g.index:
                    rets.append(np.nan)
                    continue
                loc = g.index.get_loc(dt)
                if isinstance(loc, slice):
                    loc = int(loc.start)
                rets.append(_fwd(g, int(loc), h))
            day[f"r{h}"] = rets
            rec = dict(base)
            rec["h"] = h
            rec["n"] = int(pd.Series(rets).notna().sum())
            for col, key in (("mud_plus", "M+"), ("company_q", "Q"), ("G", "G")):
                pair = day[[col, f"r{h}"]].dropna()
                if len(pair) < 8:
                    rec[key] = np.nan
                    rec[f"{key}_top10"] = np.nan
                    rec[f"{key}_top50"] = np.nan
                    continue
                rec[key] = float(pair[col].corr(pair[f"r{h}"], method="spearman"))
                thr10 = pair[col].quantile(0.90)
                thr50 = pair[col].quantile(0.50)
                rec[f"{key}_top10"] = float(pair.loc[pair[col] >= thr10, f"r{h}"].mean())
                rec[f"{key}_top50"] = float(pair.loc[pair[col] >= thr50, f"r{h}"].mean())
            rows.append(rec)
    return pd.DataFrame(rows)


def _mean(s: pd.Series) -> float:
    x = pd.to_numeric(s, errors="coerce").dropna()
    return float(x.mean()) if len(x) else float("nan")


def label_state(st: Dict[str, float]) -> str:
    r5, r20, weak = st.get("mu5", np.nan), st.get("mu20", np.nan), st.get("weak20", np.nan)
    if _finite(r5) and _finite(r20) and r5 > 0 and r20 < 0:
        return "C"
    if _finite(r20) and r20 > 0 and _finite(weak) and weak < 0:
        return "A"
    if _finite(r5) and _finite(r20) and abs(r5) < 0.005 and abs(r20) < 0.01:
        return "B"
    return "未归入"


def label_factor(ic_means: Dict[int, float], top10_20: float, top50_20: float, weak20: float) -> str:
    r5 = ic_means.get(-5, np.nan)  # placeholder overwritten below
    return ""


def label_factor_row(mu5: float, mu20: float, ics: Dict[int, float], top10: float, top50: float, weak20: float) -> str:
    if _finite(mu5) and _finite(mu20) and mu5 > 0 and mu20 < 0:
        return "C"
    if _finite(top10) and _finite(top50) and top10 > top50 and top10 < 0:
        return "D"
    ic5 = ics.get(5, np.nan)
    if _finite(ic5) and ic5 > 0.02 and _finite(weak20) and weak20 < 0:
        return "A"
    if all(_finite(ics.get(h, np.nan)) and abs(ics[h]) < 0.02 for h in (1, 5, 10, 20)):
        return "B"
    return "未归入"


def temp_table(books: pd.DataFrame, temp: pd.DataFrame) -> pd.DataFrame:
    t = temp.reset_index().sort_values("date")
    left = books.reset_index().rename(columns={"index": "date"})
    if "date" not in left.columns:
        left = books.copy()
        left["date"] = left.index
        left = left.reset_index(drop=True)
    left["date"] = pd.to_datetime(left["date"]).dt.normalize()
    # 收益日 t 使用严格早于 t 的温度
    t = t.rename(columns={"date": "temp_date"})
    left = left.sort_values("date")
    t["temp_date"] = pd.to_datetime(t["temp_date"])
    # merge_asof 需要右表键 <= 左表；把温度日期整体视为信号日，收益用下一日。这里收益索引已是实现日，温度用前一已知日。
    left["asof"] = left["date"] - pd.Timedelta(days=1)
    merged = pd.merge_asof(
        left.sort_values("asof"),
        t.sort_values("temp_date"),
        left_on="asof",
        right_on="temp_date",
        direction="backward",
    )
    rows = []
    for name in BOOKS:
        for s0 in THRESHOLDS:
            sub = merged[(merged["S"] > s0) & merged[name].notna()]
            sub = sub[(sub["date"] >= EVAL_START) & (sub["date"] <= EVAL_END)]
            x = pd.to_numeric(sub[name], errors="coerce").dropna()
            rows.append(
                {
                    "book": name,
                    "rule": f"S>{s0}",
                    "n": int(len(x)),
                    "mean": float(x.mean()) if len(x) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def write_report(
    alpha: pd.DataFrame,
    events: pd.DataFrame,
    ic: pd.DataFrame,
    temps: pd.DataFrame,
    notes: List[str],
) -> str:
    lines = [
        "# P0 选股 Alpha 报告",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。",
        "",
        "本报告不改线上入池规则，也不做仓位优化。",
        "状态 W2–W6 用初始参数的 Phase1。同一股票、同一状态至少隔 20 个交易日再计一次。",
        "G 是公告日不晚于截面日的营收同比与净利润同比，各占一半，不是四层稳健质量分。",
        f"最后一段从 {HOLDOUT_START} 起，到 {EVAL_END}。",
        "标签只作诊断：A 有正向关系但弱市（S≤40）未来收益为负；B 各期限关系都接近 0；C 短正长负；D 前 10% 好于前 50% 但前 10% 仍为负。未归入表示样本里未来收益为负，或 IC 为负。不据此删除因子。",
        "",
        "## 超额与 Alpha",
        "",
        "超额 = 信号组累计收益 − 同期沪深300累计收益。Alpha 是日回归截距乘 252，Beta 是对沪深300 日收益的斜率。最后一段只有约 57 个交易日，Alpha×252 会被短样本放大，这段优先看超额。",
        "",
        "| 信号组 | 区间 | 天数 | 累计 | 沪深300 | 超额 | Alpha×252 | Beta |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for _, r in alpha.iterrows():
        lines.append(
            f"| {r['book']} | {r['seg']} | {int(r['n'])} | {_pct(r.get('total', np.nan))} | "
            f"{_pct(r.get('mkt', np.nan))} | {_pct(r.get('excess', np.nan))} | "
            f"{_pct(r.get('alpha_ann', np.nan))} | {_num(r.get('beta', np.nan))} |"
        )

    lines += [
        "",
        "## 状态的未来收益",
        "",
        "收益是信号日收盘到其后第 h 个交易日收盘。上涨比例是这段收益大于 0 的次数占比。",
        "",
    ]
    state_labels = []
    for seg_name, seg_mask_fn in (
        ("全样本", lambda d: pd.Series(True, index=d.index)),
        ("最后一段", lambda d: d["seg"] == "最后一段"),
    ):
        lines.append(f"### {seg_name}")
        lines.append("")
        lines.append("| 状态 | 次数 | 1日 | 3日 | 5日 | 10日 | 20日 | 20日上涨比例 | 弱市20日 | 标签 |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for cid in STATES:
            if events.empty:
                break
            mask = (events["state"] == cid) & seg_mask_fn(events)
            st = _event_stats(events, mask)
            lab = label_state(st)
            if seg_name == "全样本":
                state_labels.append((f"W{cid}", lab, st))
            lines.append(
                f"| W{cid} | {int(st['n'])} | {_pct(st['mu1'])} | {_pct(st['mu3'])} | {_pct(st['mu5'])} | "
                f"{_pct(st['mu10'])} | {_pct(st['mu20'])} | {_pct(st['p20'])} | {_pct(st['weak20'])} | {lab} |"
            )
        lines.append("")

    lines += [
        "## 因子 IC",
        "",
        "IC 是截面 Spearman 相关，再对调仓日取平均。前 10% / 前 50% 是当日分数达到该分位的股票，其未来收益的截面均值，再对调仓日取平均。",
        "",
        "| 因子 | 区间 | IC 1日 | IC 5日 | IC 10日 | IC 20日 | 前10%的20日 | 前50%的20日 | 标签 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    factor_labels = []
    if not ic.empty:
        for seg in ("全样本", "前段", "最后一段"):
            part = ic if seg == "全样本" else ic[ic["seg"] == ("最后一段" if seg == "最后一段" else "前段")]
            for key in ("M+", "Q", "G"):
                ics = {h: _mean(part.loc[part["h"] == h, key]) for h in HORIZONS}
                top10 = _mean(part.loc[part["h"] == 20, f"{key}_top10"])
                top50 = _mean(part.loc[part["h"] == 20, f"{key}_top50"])
                mu5 = _mean(part.loc[part["h"] == 5, f"{key}_top10"])
                mu20 = top10
                weak_rows = part[(part["h"] == 20) & (pd.to_numeric(part["S"], errors="coerce") <= WEAK_S)]
                weak20 = _mean(weak_rows[f"{key}_top10"]) if len(weak_rows) else np.nan
                lab = label_factor_row(mu5, mu20, ics, top10, top50, weak20)
                if seg == "全样本":
                    factor_labels.append((key, lab, ics, top10, top50, mu5))
                lines.append(
                    f"| {key} | {seg} | {_num(ics[1])} | {_num(ics[5])} | {_num(ics[10])} | {_num(ics[20])} | "
                    f"{_pct(top10)} | {_pct(top50)} | {lab if seg == '全样本' else '—'} |"
                )

    lines += [
        "",
        "## 按温度分组的日收益",
        "",
        "收益日使用严格早于该日的温度总分。表内是日收益均值，不是累计。",
        "",
        "| 信号组 | 条件 | 天数 | 日收益均值 |",
        "| --- | --- | --- | --- |",
    ]
    for _, r in temps.iterrows():
        lines.append(f"| {r['book']} | {r['rule']} | {int(r['n'])} | {_pct(r['mean'])} |")

    lines += ["", "## 标签", ""]
    for name, lab, _st in state_labels:
        lines.append(f"- {name}：{lab}")
    for key, lab, *_rest in factor_labels:
        lines.append(f"- {key}：{lab}")
    lines += ["", "## 取数", ""]
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")
    path = os.path.join(OUT_DIR, "report.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def main() -> None:
    symbols = load_symbols()
    notes = [f"宇宙与 4+6 回测截面相同，{len(symbols)} 只", f"比较区间 {EVAL_START} ～ {EVAL_END}"]
    print(notes[0], flush=True)
    panel = load_classified(symbols)
    notes.append(f"分类行 {len(panel)}")
    bench = load_bench()
    temp = load_temp()
    books = load_books()
    print("  超额 …", flush=True)
    alpha = alpha_table(books, bench)
    print("  状态事件 …", flush=True)
    events = event_table(panel, temp)
    notes.append(f"状态事件 {len(events)}")
    print("  IC …", flush=True)
    fina = load_growth()
    ic = ic_frame(panel, fina, temp)
    notes.append(f"IC 截面日 {ic['date'].nunique() if not ic.empty else 0}")
    print("  温度 …", flush=True)
    temps = temp_table(books, temp)
    path = write_report(alpha, events, ic, temps, notes)
    alpha.to_csv(os.path.join(OUT_DIR, "alpha.csv"), index=False, encoding="utf-8-sig")
    if not events.empty:
        events.to_csv(os.path.join(OUT_DIR, "events.csv"), index=False, encoding="utf-8-sig")
    if not ic.empty:
        ic.to_csv(os.path.join(OUT_DIR, "ic.csv"), index=False, encoding="utf-8-sig")
    temps.to_csv(os.path.join(OUT_DIR, "temperature.csv"), index=False, encoding="utf-8-sig")
    print(f"报告 → {path}", flush=True)


if __name__ == "__main__":
    main()
