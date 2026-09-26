#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第一期 · 块 A 参数搜索。

只搜索会改变观察池（combo 4 / 6）成员的 Phase1 常数：
放量阈值、底部位置、高位位置。
样本外得分 = 入池日收盘到其后第 10 个交易日收盘的收益。
同一只股票 10 个交易日内只计一次，避免连续入池把同一段行情算很多遍。

不修改 VP_SIX_CONFIG、PATTERN_ENTRY_CONFIG、workflow_runner.yaml。
缩量阈值与形态回踩常数在这份得分下不改变观察池成员，锁定在
docs/系统参数初始状态.md。

输出：output/param_block_a/report.md 与 trials.csv、folds.csv。
"""

from __future__ import annotations

import itertools
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_SCRIPT_DIR)
for p in (_SCRIPT_DIR, _PROJ):
    if p not in sys.path:
        sys.path.insert(0, p)

from backtest_sy_002028_threshold import fetch_ohlc_qfq  # noqa: E402
from fetch_vp_six_combo import (  # noqa: E402
    DEFAULT_STOCKS_POOL_TXT,
    DEFAULT_SYMBOLS_POOL_TXT,
    VP_SIX_CONFIG,
    _assign_combo_phase1,
    _classify_position,
    _ensure_volume_col,
    load_symbols_pool_txt,
)

OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "param_block_a")
FORWARD_DAYS = 10
MIN_EVENTS = 8
FETCH_START = "2023-01-01"

# 初始状态（与 docs/系统参数初始状态.md 一致）
BASE_AMP = float(VP_SIX_CONFIG["vol_amplify_ratio"])
BASE_SHR = float(VP_SIX_CONFIG["vol_shrink_ratio"])
BASE_BOT = float(VP_SIX_CONFIG["bottom_range_pct"])
BASE_HIGH = float(VP_SIX_CONFIG["high_range_pct"])
STAGNANT_ABS = float(VP_SIX_CONFIG["stagnant_abs_pct"])
VOL_MA = int(VP_SIX_CONFIG["vol_ma_bars"])
RANGE_N = int(VP_SIX_CONFIG["range_lookback_bars"])
BREAK_N = int(VP_SIX_CONFIG["breakout_lookback_bars"])
MA20_LB = int(VP_SIX_CONFIG["downtrend_ma20_lookback"])

AMP_GRID = (1.2, 1.5, 1.8, 2.2)
BOT_GRID = (0.20, 0.30, 0.40)
HIGH_GRID = (0.70, 0.80, 0.90)


@dataclass(frozen=True)
class Theta:
    amp: float
    bot: float
    high: float

    def key(self) -> str:
        return f"amp={self.amp:.2f}|bot={self.bot:.2f}|high={self.high:.2f}"


def _finite(x: float) -> bool:
    return x == x and x is not None


def resolve_study_symbols() -> Tuple[List[str], str]:
    """与线上六组合相同：自定义列表非空则用它，否则股票池。"""
    custom = load_symbols_pool_txt(DEFAULT_SYMBOLS_POOL_TXT)
    if custom:
        return custom, f"自定义列表 {DEFAULT_SYMBOLS_POOL_TXT}（{len(custom)} 只）"
    pool = load_symbols_pool_txt(DEFAULT_STOCKS_POOL_TXT)
    return pool, f"股票池 {DEFAULT_STOCKS_POOL_TXT}（{len(pool)} 只）"


def build_panel(symbols: Sequence[str], end: str) -> Tuple[pd.DataFrame, List[str]]:
    notes: List[str] = []
    frames: List[pd.DataFrame] = []
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
        d = d.sort_values("date").reset_index(drop=True)
        d["ma20"] = d["close"].rolling(20, min_periods=20).mean()
        d["ma60"] = d["close"].rolling(60, min_periods=60).mean()
        d["vol_ma"] = d["volume"].shift(1).rolling(VOL_MA, min_periods=VOL_MA).mean()
        d["range_low"] = d["low"].rolling(RANGE_N, min_periods=RANGE_N).min()
        d["range_high"] = d["high"].rolling(RANGE_N, min_periods=RANGE_N).max()
        d["ma20_prev"] = d["ma20"].shift(MA20_LB)
        d["prior_high"] = d["high"].shift(1).rolling(BREAK_N, min_periods=BREAK_N).max()
        d["prev_close"] = d["close"].shift(1)
        d["fwd_close"] = d["close"].shift(-FORWARD_DAYS)
        d["symbol"] = sym
        need = max(65, RANGE_N, VOL_MA + 1, BREAK_N + 1)
        d = d.iloc[need:].copy()
        d = d.dropna(subset=["ma20", "ma60", "vol_ma", "ma20_prev", "prior_high", "prev_close", "fwd_close"])
        d = d[d["vol_ma"] > 0]
        d = d[d["prev_close"] > 0]
        d = d[d["fwd_close"] > 0]
        if d.empty:
            notes.append(f"{sym} 有效样本为空")
            continue
        span = d["range_high"] - d["range_low"]
        d["range_pct"] = ((d["close"] - d["range_low"]) / span).where(span > 1e-12, 0.5)
        d["range_pct"] = d["range_pct"].clip(0.0, 1.0)
        d["vol_ratio"] = d["volume"] / d["vol_ma"]
        d["fwd_ret"] = d["fwd_close"] / d["close"] - 1.0
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
                    "fwd_ret",
                ]
            ]
        )
        notes.append(f"{sym} 有效日 {len(d)}")
    if not frames:
        return pd.DataFrame(), notes
    panel = pd.concat(frames, ignore_index=True)
    panel["date"] = pd.to_datetime(panel["date"])
    return panel, notes


def combo_id_row(row: pd.Series, theta: Theta) -> int:
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
        bottom_range_pct=theta.bot,
        high_range_pct=theta.high,
    )
    cid, _exact = _assign_combo_phase1(
        position_stage=pos,
        vol_amplify=vol_ratio >= theta.amp,
        vol_shrink=vol_ratio <= BASE_SHR,
        price_up=c1 > c0,
        price_down=c1 < c0,
        is_breakout=c1 >= float(row["prior_high"]) * 0.998,
        is_stagnant=abs(pct) <= STAGNANT_ABS,
    )
    return int(cid)


def watch_events(panel: pd.DataFrame, theta: Theta) -> pd.DataFrame:
    if panel.empty:
        return panel
    cids = [combo_id_row(row, theta) for _, row in panel.iterrows()]
    ev = panel.copy()
    ev["combo_id"] = cids
    ev = ev[ev["combo_id"].isin((4, 6))].copy()
    if ev.empty:
        return ev
    ev = ev.sort_values(["symbol", "date"])
    # 10 个交易日去重：用全市场交易日序号
    order = {d: i for i, d in enumerate(sorted(panel["date"].unique()))}
    ev["ord"] = ev["date"].map(order)
    keep_idx: List[int] = []
    last: Dict[str, int] = {}
    for i, row in ev.iterrows():
        sym = str(row["symbol"])
        od = int(row["ord"])
        prev = last.get(sym)
        if prev is not None and od < prev + FORWARD_DAYS:
            continue
        last[sym] = od
        keep_idx.append(i)
    return ev.loc[keep_idx]


def summarize(ev: pd.DataFrame) -> Dict[str, float]:
    if ev is None or ev.empty:
        return {"n": 0, "n4": 0, "n6": 0, "mean": float("nan"), "hit": float("nan")}
    r = ev["fwd_ret"]
    return {
        "n": int(len(ev)),
        "n4": int((ev["combo_id"] == 4).sum()),
        "n6": int((ev["combo_id"] == 6).sum()),
        "mean": float(r.mean()),
        "hit": float((r > 0).mean()),
    }


def grid() -> List[Theta]:
    return [Theta(a, b, h) for a, b, h in itertools.product(AMP_GRID, BOT_GRID, HIGH_GRID)]


def split_dates(dates: Sequence[pd.Timestamp]) -> Tuple[List[Tuple[str, pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]], Tuple[pd.Timestamp, pd.Timestamp]]:
    ds = list(sorted(pd.to_datetime(list(dates))))
    n = len(ds)
    hold_n = max(20, n // 5)
    hold = ds[-hold_n:]
    pre = ds[:-hold_n]
    if len(pre) < 40:
        cut = max(1, int(len(pre) * 0.7))
        folds = [("fold1", pre[0], pre[cut - 1], pre[cut], pre[-1])]
    else:
        c1 = len(pre) // 3
        c2 = 2 * len(pre) // 3
        folds = [
            ("fold1", pre[0], pre[c1 - 1], pre[c1], pre[c2 - 1]),
            ("fold2", pre[0], pre[c2 - 1], pre[c2], pre[-1]),
        ]
    return folds, (hold[0], hold[-1])


def in_range(ev: pd.DataFrame, start, end) -> pd.DataFrame:
    if ev.empty:
        return ev
    m = (ev["date"] >= pd.Timestamp(start)) & (ev["date"] <= pd.Timestamp(end))
    return ev.loc[m]


def top_quartile(rows: List[dict]) -> List[dict]:
    eligible = [r for r in rows if r["n"] >= MIN_EVENTS and _finite(r["mean"])]
    if not eligible:
        return []
    eligible.sort(key=lambda r: r["mean"], reverse=True)
    k = max(1, len(eligible) // 4)
    return eligible[:k]


def median_theta(rows: List[dict]) -> Optional[Theta]:
    if not rows:
        return None
    def med(vals: List[float], grid_vals: Sequence[float]) -> float:
        s = sorted(vals)
        if len(s) % 2:
            m = s[len(s) // 2]
        else:
            m = 0.5 * (s[len(s) // 2 - 1] + s[len(s) // 2])
        return min(grid_vals, key=lambda g: abs(g - m))

    return Theta(
        med([r["amp"] for r in rows], AMP_GRID),
        med([r["bot"] for r in rows], BOT_GRID),
        med([r["high"] for r in rows], HIGH_GRID),
    )


def shrink_does_not_change_combo(panel: pd.DataFrame) -> bool:
    """缩量只改 match_exact，不改 combo_id。抽一天核对。"""
    if panel.empty:
        return True
    row = panel.iloc[len(panel) // 2]
    theta = Theta(BASE_AMP, BASE_BOT, BASE_HIGH)
    # combo_id_row 内部缩量固定为 BASE_SHR；这里直接调用两次相位函数
    c1 = float(row["close"])
    c0 = float(row["prev_close"])
    pos = _classify_position(
        close=c1,
        ma20=float(row["ma20"]),
        ma60=float(row["ma60"]),
        ma20_prev_n=float(row["ma20_prev"]),
        range_pct=float(row["range_pct"]),
        bottom_range_pct=BASE_BOT,
        high_range_pct=BASE_HIGH,
    )
    common = dict(
        position_stage=pos,
        vol_amplify=float(row["vol_ratio"]) >= BASE_AMP,
        price_up=c1 > c0,
        price_down=c1 < c0,
        is_breakout=c1 >= float(row["prior_high"]) * 0.998,
        is_stagnant=abs((c1 / c0 - 1.0) * 100.0) <= STAGNANT_ABS,
    )
    a, _ = _assign_combo_phase1(vol_shrink=True, **common)
    b, _ = _assign_combo_phase1(vol_shrink=False, **common)
    return int(a) == int(b)


def pct(x: float) -> str:
    if not _finite(x):
        return "—"
    return f"{x * 100:.2f}%"


def main() -> None:
    end = datetime.now().strftime("%Y-%m-%d")
    symbols, uni_note = resolve_study_symbols()
    os.makedirs(OUT_DIR, exist_ok=True)
    panel, fetch_notes = build_panel(symbols, end)
    thetas = grid()
    base = Theta(BASE_AMP, BASE_BOT, BASE_HIGH)

    lines: List[str] = []
    lines.append("# 块 A 第一期参数搜索报告")
    lines.append("")
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。")
    lines.append("")
    lines.append("本报告不写回 `VP_SIX_CONFIG` 与 `config/workflow_runner.yaml`。要回退参数，仍以 `docs/系统参数初始状态.md` 为准。")
    lines.append("")
    lines.append(f"宇宙：{uni_note}。")
    lines.append(f"取数区间：{FETCH_START} ～ {end}。入池后收益窗口：{FORWARD_DAYS} 个交易日。")
    lines.append("计分：combo 4 或 6 的入池日；同一代码 " + str(FORWARD_DAYS) + " 个交易日内只保留第一次。")
    lines.append(f"训练折上至少 {MIN_EVENTS} 次入池才参与选参。")
    lines.append("")
    lines.append("锁定、不参与搜索：")
    lines.append("")
    lines.append(f"- 缩量阈值保持 {BASE_SHR}。Phase1 里它只改 `match_exact`，不改 combo 编号，因此不改变观察池。")
    lines.append("- 形态回踩天数、再突破放量倍数、等待天数保持初始值。它们决定 `entry`，不决定谁进入观察池。这份得分看不到它们。")
    lines.append("- 共振分 60 与 `match_exact` 继续只做标签。")
    lines.append("")
    if fetch_notes:
        lines.append("取数：")
        lines.append("")
        for n in fetch_notes:
            lines.append(f"- {n}")
        lines.append("")

    if panel.empty:
        lines.append("没有可用日线，搜索未执行。")
        _write(lines, pd.DataFrame(), pd.DataFrame())
        return

    shrink_ok = shrink_does_not_change_combo(panel)
    lines.append(
        "缩量开关核对："
        + ("抽查一行，改缩量标记不改变 combo 编号。" if shrink_ok else "抽查发现缩量改变了 combo 编号，需要复查相位函数。")
    )
    lines.append("")

    cache: Dict[str, pd.DataFrame] = {}
    for th in thetas:
        cache[th.key()] = watch_events(panel, th)

    dates = sorted(panel["date"].unique())
    folds, (h0, h1) = split_dates(dates)
    lines.append(f"信号日 {pd.Timestamp(dates[0]).date()} ～ {pd.Timestamp(dates[-1]).date()}，共 {len(dates)} 个交易日。")
    lines.append(f"最终测试段（只看一次，不参与选参）：{pd.Timestamp(h0).date()} ～ {pd.Timestamp(h1).date()}。")
    lines.append("")

    trial_rows: List[dict] = []
    fold_rows: List[dict] = []
    fold_picks: List[Theta] = []

    lines.append("## 各折")
    lines.append("")
    for name, tr0, tr1, te0, te1 in folds:
        scored: List[dict] = []
        for th in thetas:
            ev = in_range(cache[th.key()], tr0, tr1)
            s = summarize(ev)
            row = {"fold": name, "part": "train", "amp": th.amp, "bot": th.bot, "high": th.high, **s}
            scored.append(row)
            trial_rows.append(row)
        chosen_pool = top_quartile(scored)
        pick = median_theta(chosen_pool)
        if pick is None:
            lines.append(f"### {name}")
            lines.append("")
            lines.append(f"训练 {pd.Timestamp(tr0).date()} ～ {pd.Timestamp(tr1).date()} 没有足够入池样本，本折不选参。")
            lines.append("")
            continue
        fold_picks.append(pick)
        te = summarize(in_range(cache[pick.key()], te0, te1))
        base_te = summarize(in_range(cache[base.key()], te0, te1))
        fold_rows.append(
            {
                "fold": name,
                "train_start": str(pd.Timestamp(tr0).date()),
                "train_end": str(pd.Timestamp(tr1).date()),
                "test_start": str(pd.Timestamp(te0).date()),
                "test_end": str(pd.Timestamp(te1).date()),
                "pick_amp": pick.amp,
                "pick_bot": pick.bot,
                "pick_high": pick.high,
                "test_n": te["n"],
                "test_mean": te["mean"],
                "base_test_n": base_te["n"],
                "base_test_mean": base_te["mean"],
            }
        )
        lines.append(f"### {name}")
        lines.append("")
        lines.append(f"训练 {pd.Timestamp(tr0).date()} ～ {pd.Timestamp(tr1).date()}；测试 {pd.Timestamp(te0).date()} ～ {pd.Timestamp(te1).date()}。")
        lines.append(f"训练前四分位的中位参数：放量 {pick.amp:.2f}，底部 {pick.bot:.2f}，高位 {pick.high:.2f}。")
        lines.append(f"该参数在测试段：n={te['n']}，10 日均收益 {pct(te['mean'])}，上涨占比 {pct(te['hit'])}。")
        lines.append(f"初始参数在同一测试段：n={base_te['n']}，10 日均收益 {pct(base_te['mean'])}，上涨占比 {pct(base_te['hit'])}。")
        lines.append("")

    proposed = (
        median_theta([{"amp": t.amp, "bot": t.bot, "high": t.high} for t in fold_picks])
        if fold_picks
        else None
    )

    lines.append("## 最终测试段")
    lines.append("")
    if proposed is None:
        lines.append("各折都没有选出参数。维持初始状态：放量 1.50，底部 0.30，高位 0.80。")
    else:
        ev_p = in_range(cache[proposed.key()], h0, h1)
        ev_b = in_range(cache[base.key()], h0, h1)
        sp = summarize(ev_p)
        sb = summarize(ev_b)
        sym_p4 = set(ev_p.loc[ev_p["combo_id"] == 4, "symbol"].astype(str)) if not ev_p.empty else set()
        sym_b4 = set(ev_b.loc[ev_b["combo_id"] == 4, "symbol"].astype(str)) if not ev_b.empty else set()
        sym_p6 = set(ev_p.loc[ev_p["combo_id"] == 6, "symbol"].astype(str)) if not ev_p.empty else set()
        sym_b6 = set(ev_b.loc[ev_b["combo_id"] == 6, "symbol"].astype(str)) if not ev_b.empty else set()
        lines.append(f"两折中位后再取中位：放量 {proposed.amp:.2f}，底部 {proposed.bot:.2f}，高位 {proposed.high:.2f}。")
        lines.append(f"最终测试段该参数：n={sp['n']}（combo4 {sp['n4']} / combo6 {sp['n6']}），10 日均收益 {pct(sp['mean'])}，上涨占比 {pct(sp['hit'])}。")
        lines.append(f"最终测试段初始参数：n={sb['n']}（combo4 {sb['n4']} / combo6 {sb['n6']}），10 日均收益 {pct(sb['mean'])}，上涨占比 {pct(sb['hit'])}。")
        lines.append("")
        lines.append("成员差（最终测试段里出现过的代码）：")
        lines.append("")
        lines.append(f"- combo4 只在建议参数中：{', '.join(sorted(sym_p4 - sym_b4)) or '无'}")
        lines.append(f"- combo4 只在初始参数中：{', '.join(sorted(sym_b4 - sym_p4)) or '无'}")
        lines.append(f"- combo6 只在建议参数中：{', '.join(sorted(sym_p6 - sym_b6)) or '无'}")
        lines.append(f"- combo6 只在初始参数中：{', '.join(sorted(sym_b6 - sym_p6)) or '无'}")
        lines.append("")
        higher = (
            sp["n"] >= MIN_EVENTS
            and sb["n"] >= MIN_EVENTS
            and _finite(sp["mean"])
            and _finite(sb["mean"])
            and sp["mean"] > sb["mean"]
        )
        thin = len(symbols) < 8 or sp["n6"] >= sp["n4"]
        if higher and sp["mean"] > 0 and not thin:
            lines.append("最终测试段里，建议参数的 10 日均收益高于初始参数，且均值为正。这只是一份报告，线上常数仍是初始状态。若要换参，需另做确认。")
        elif higher:
            lines.append(
                "建议参数的 10 日均收益数值上高于初始参数，但样本只有 "
                f"{len(symbols)} 只，且均值仍为负或入池大多是 combo 6（该组合不随这三项阈值变化）。"
                "这不足以替换初始参数。维持 `docs/系统参数初始状态.md`。"
            )
        else:
            lines.append("最终测试段没有给出足以替换初始参数的证据（样本不足，或建议参数的 10 日均收益没有高于初始参数）。维持 `docs/系统参数初始状态.md`。")
    lines.append("")
    lines.append("Phase1 里，下跌位置只要收盘低于 MA20 且 MA20 下行，就标 combo 6，与放量、底部、高位阈值无关。因此 combo 6 的成员差通常为空；搜索主要移动 combo 4。")
    lines.append("")

    trials = pd.DataFrame(trial_rows)
    folds_df = pd.DataFrame(fold_rows)
    _write(lines, trials, folds_df)
    print(f"报告 → {os.path.join(OUT_DIR, 'report.md')}")


def _write(lines: List[str], trials: pd.DataFrame, folds_df: pd.DataFrame) -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    if not trials.empty:
        trials.to_csv(os.path.join(OUT_DIR, "trials.csv"), index=False, encoding="utf-8-sig")
    if not folds_df.empty:
        folds_df.to_csv(os.path.join(OUT_DIR, "folds.csv"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
