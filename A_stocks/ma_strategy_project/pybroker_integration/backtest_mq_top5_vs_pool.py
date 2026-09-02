#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
M加 / Q：前五 vs 全池，雷达强度第 1 名日频轮动对比。

口径（已确认）：
- 最强 = 雷达强度 50 + 10×相对沪深300 + 8×相对申万板块
- 前五 = factor_growth_ranking.csv 该组前 5（不足则全列）
- 全池 = config/mx_groups/{组}.txt，回测期内冻结
- 只跑第 1 名；ST 保留
- 当日收盘买最强，T+1 收盘切到当日最强
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest_strength_rotation import (  # noqa: E402
    DEFAULT_CASH,
    DEFAULT_START,
    _pct,
    build_daily_ranks,
    fetch_index_daily,
    fetch_stock_bars,
    fetch_sw_daily,
    get_pro,
    plot_equity,
    run_track,
)
from market_radar import (  # noqa: E402
    GROWTH_RANKING_CSV,
    _sector_display,
    resolve_sw_map,
    six_digit,
    to_ts_code,
)
from mx_self_select import group_txt_path, load_group_symbols_txt  # noqa: E402
from stock_names import resolve_stock_names  # noqa: E402

TOP_N = 5
GROUPS = ("M加", "Q")
OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "strength_rotation_mq_top5_pool")

EXPERIMENTS: list[dict[str, str]] = [
    {"id": "mplus_top5", "label": "M加前五", "group": "M加", "mode": "top5"},
    {"id": "mplus_full", "label": "M加全池", "group": "M加", "mode": "full"},
    {"id": "q_top5", "label": "Q前五", "group": "Q", "mode": "top5"},
    {"id": "q_full", "label": "Q全池", "group": "Q", "mode": "full"},
]

COMPARE_PAIRS = (
    ("mplus_top5", "mplus_full", "M加：前五 vs 全池"),
    ("q_top5", "q_full", "Q：前五 vs 全池"),
    ("mplus_top5", "q_top5", "总对比：M加前五 vs Q前五"),
)
PLOT_LABELS = {
    "mplus_top5": "M+ top5",
    "mplus_full": "M+ full",
    "q_top5": "Q top5",
    "q_full": "Q full",
}


def _read_ranking_csv() -> pd.DataFrame:
    path = str(GROWTH_RANKING_CSV)
    if not os.path.isfile(path):
        raise RuntimeError("未找到 factor_growth_ranking.csv，请先运行「按成长因子排序」。")
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        df = pd.read_csv(path, encoding="gbk")
    if df is None or df.empty:
        raise RuntimeError("成长因子排序表为空。")
    cols = {str(c).strip(): c for c in df.columns}
    group_col = cols.get("分组")
    rank_col = cols.get("排名")
    code_col = cols.get("股票代码") or cols.get("代码")
    name_col = cols.get("股票名称") or cols.get("名称")
    if group_col is None or code_col is None:
        raise RuntimeError("成长因子排序表缺少「分组」或「股票代码」列。")
    out = pd.DataFrame(
        {
            "group": df[group_col].astype(str).str.strip(),
            "symbol": df[code_col].map(six_digit),
            "name": df[name_col].astype(str).str.strip() if name_col else "",
            "rank": pd.to_numeric(df[rank_col], errors="coerce") if rank_col else np.nan,
        }
    )
    out = out[out["symbol"].astype(str).str.len() == 6].copy()
    return out.reset_index(drop=True)


def _load_full_pool(group: str) -> list[str]:
    path = group_txt_path(group)
    codes, notes = load_group_symbols_txt(path)
    for line in notes:
        print(f"  {line}", flush=True)
    if not codes:
        raise RuntimeError(f"分组 txt 无代码：{path}")
    return [six_digit(c) for c in codes if six_digit(c)]


def _top_n_from_ranking(ranking: pd.DataFrame, group: str, n: int = TOP_N) -> list[str]:
    sub = ranking[ranking["group"] == group].copy()
    if sub.empty:
        raise RuntimeError(f"排序表没有「{group}」分组。")
    sub["_rk"] = pd.to_numeric(sub["rank"], errors="coerce")
    sub = sub.sort_values(["_rk", "symbol"], ascending=[True, True], na_position="last")
    seen: set[str] = set()
    out: list[str] = []
    for row in sub.itertuples(index=False):
        sym = str(row.symbol)
        if not sym or sym in seen:
            continue
        seen.add(sym)
        out.append(sym)
        if len(out) >= n:
            break
    if not out:
        raise RuntimeError(f"「{group}」前{n}为空。")
    return out


def _universe_frame(
    symbols: list[str],
    *,
    group: str,
    mode: str,
    ranking: pd.DataFrame,
    names: dict[str, str],
) -> pd.DataFrame:
    rank_map: dict[str, Any] = {}
    name_map: dict[str, str] = {}
    sub = ranking[ranking["group"] == group]
    for row in sub.itertuples(index=False):
        rank_map[str(row.symbol)] = row.rank
        if str(row.name or "").strip():
            name_map[str(row.symbol)] = str(row.name).strip()
    rows = []
    for sym in symbols:
        rows.append(
            {
                "symbol": sym,
                "name": names.get(sym) or name_map.get(sym) or sym,
                "group": group,
                "pool": mode,
                "group_rank": rank_map.get(sym) if pd.notna(rank_map.get(sym, np.nan)) else None,
            }
        )
    return pd.DataFrame(rows)


def rerank_in_pool(all_ranks: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    allow = {str(s) for s in symbols}
    sub = all_ranks[all_ranks["symbol"].astype(str).isin(allow)].copy()
    if sub.empty:
        return sub
    parts: list[pd.DataFrame] = []
    for _, g in sub.groupby("date", sort=True):
        g = g.sort_values(["strength", "symbol"], ascending=[False, True]).copy()
        g["rank"] = np.arange(1, len(g) + 1)
        parts.append(g)
    return pd.concat(parts, ignore_index=True)


def _bench_metrics(hs300: pd.DataFrame, start: str, end: str) -> dict[str, float]:
    b = hs300.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.normalize()
    lo, hi = pd.Timestamp(start), pd.Timestamp(end)
    b = b[(b["date"] >= lo) & (b["date"] <= hi)].sort_values("date")
    if b.empty or float(b["close"].iloc[0]) <= 0:
        return {"total_return": 0.0, "max_drawdown": 0.0}
    nav = b["close"].astype(float) / float(b["close"].iloc[0])
    peak = nav.cummax()
    mdd = float((nav / peak - 1.0).min()) if len(nav) else 0.0
    return {"total_return": float(nav.iloc[-1] - 1.0), "max_drawdown": mdd}


def plot_compare(
    equity_map: dict[str, pd.DataFrame],
    labels: dict[str, str],
    bench: pd.DataFrame,
    initial_cash: float,
    path: str,
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as exc:
        print(f"  [report] 跳过对比图: {exc}", flush=True)
        return
    fig, ax = plt.subplots(figsize=(10.5, 5.6))
    for eid, eq in equity_map.items():
        g = eq.sort_values("date")
        if g.empty or initial_cash <= 0:
            continue
        ax.plot(
            pd.to_datetime(g["date"]),
            pd.to_numeric(g["equity"], errors="coerce") / float(initial_cash),
            label=labels.get(eid, eid),
            linewidth=1.7,
        )
    if bench is not None and not bench.empty:
        b = bench.copy()
        b["date"] = pd.to_datetime(b["date"])
        dates = pd.concat([pd.to_datetime(eq["date"]) for eq in equity_map.values() if not eq.empty])
        if not dates.empty:
            b = b[(b["date"] >= dates.min()) & (b["date"] <= dates.max())]
        if not b.empty and float(b["close"].iloc[0]) > 0:
            ax.plot(
                b["date"],
                b["close"] / float(b["close"].iloc[0]),
                label="CSI 300",
                linewidth=1.2,
                linestyle="--",
                color="#888888",
            )
    ax.set_title("M+ / Q  strength #1  (top5 vs full pool)")
    ax.set_xlabel("Date")
    ax.set_ylabel("NAV")
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=120)
    plt.close(fig)
    print(f"  [report] 对比净值图 → {path}", flush=True)


def write_run_summary(
    *,
    path: str,
    label: str,
    universe: pd.DataFrame,
    metrics: dict[str, Any],
    cfg: dict[str, Any],
) -> None:
    mode = "成长排序前 5（不足则全列）" if cfg["mode"] == "top5" else "分组 txt 全池"
    lines = [
        f"# {label} · 雷达强度第 1 名日频轮动",
        "",
        "## 口径",
        "",
        f"- 股票池：{cfg['group']} {mode}，回测期内**冻结名单**",
        "- 最强：雷达强度 `50 + 10×(个股涨跌−沪深300) + 8×(个股涨跌−申万板块)`",
        "- 只持有当日强度第 1 名；满仓一只",
        "- 换仓：目标变了才换；**换仓日收盘卖旧、收盘买新**",
        "- T+1：买入当日不可卖；ST 保留",
        "- 涨停/跌停/停牌或不足 1 手：换仓失败，继续持有",
        f"- 区间：{cfg['start']} ~ {cfg['end']}　初始资金 {cfg['cash']:,.0f}　佣金万三（最低 5 元）+ 印花税 0.05%",
        "",
        f"冻结名单 {len(universe)} 只：",
        "",
        "| 代码 | 名称 | 组成长排名 |",
        "| --- | --- | ---: |",
    ]
    for r in universe.itertuples(index=False):
        rk = r.group_rank
        rk_s = "" if rk is None or (isinstance(rk, float) and rk != rk) else str(int(rk) if float(rk) == int(float(rk)) else rk)
        lines.append(f"| {r.symbol} | {r.name} | {rk_s} |")
    m = metrics
    hold = f"{m.get('end_holding_name', '')} {m.get('end_holding', '')}".strip()
    lines += [
        "",
        "## 绩效",
        "",
        "| 总收益 | 年化 | 最大回撤 | 夏普 | 买入次数 | 完整轮次 | 胜率 | 平均持有(自然日) | 期末持仓 |",
        "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        f"| {_pct(m['total_return'])} | {_pct(m['annual_return'])} | {_pct(m['max_drawdown'])} | "
        f"{float(m['sharpe']):.2f} | {int(m['n_buy'])} | {int(m['n_roundtrips'])} | "
        f"{_pct(m['win_rate'])} | {float(m['avg_hold_calendar_days']):.1f} | {hold or '—'} |",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def _metric_row(metrics: dict[str, Any]) -> str:
    return (
        f"{_pct(metrics['total_return'])} | {_pct(metrics['annual_return'])} | "
        f"{_pct(metrics['max_drawdown'])} | {float(metrics['sharpe']):.2f} | "
        f"{int(metrics['n_buy'])} | {_pct(metrics['win_rate'])} | "
        f"{float(metrics['avg_hold_calendar_days']):.1f}"
    )


def write_compare(
    path: str,
    *,
    results: dict[str, dict[str, Any]],
    universes: dict[str, pd.DataFrame],
    bench: dict[str, float],
    cfg: dict[str, Any],
    ranking: pd.DataFrame,
    full_pools: dict[str, list[str]],
) -> None:
    lines = [
        "# M加 / Q · 前五 vs 全池（强度第 1 名）",
        "",
        "## 口径",
        "",
        f"- 区间：{cfg['start']} ~ {cfg['end']}　初始资金 {cfg['cash']:,.0f}",
        "- 最强 = 雷达强度；只跑第 1 名；日频收盘换仓；T+1；ST 保留；名单冻结",
        "- 前五 = `factor_growth_ranking.csv` 该组前 5；全池 = `config/mx_groups` 分组 txt",
        f"- 沪深300：收益 {_pct(bench['total_return'])}，最大回撤 {_pct(bench['max_drawdown'])}",
        "",
        "## 冻结名单",
        "",
    ]
    for exp in EXPERIMENTS:
        uni = universes[exp["id"]]
        names = "、".join(f"{r.name}{r.symbol}" for r in uni.itertuples(index=False))
        lines.append(f"- **{exp['label']}**（{len(uni)} 只）：{names}")
    lines += ["", "### 前五相对全池", ""]
    for group in GROUPS:
        ranked = ranking[ranking["group"] == group]
        ranked_set = [str(s) for s in ranked["symbol"].tolist() if s]
        full = full_pools[group]
        top = [r.symbol for r in universes["mplus_top5" if group == "M加" else "q_top5"].itertuples(index=False)]
        extra_rank = [s for s in ranked_set if s not in set(full)]
        extra_txt = [s for s in full if s not in set(ranked_set)]
        lines.append(
            f"- **{group}**：排序表 {ranked['symbol'].nunique()} 只，txt {len(full)} 只；"
            f"前五 {', '.join(top)}"
        )
        if extra_rank:
            lines.append(f"  - 在排序表、不在 txt：{', '.join(extra_rank)}")
        if extra_txt:
            lines.append(f"  - 在 txt、不在排序表：{', '.join(extra_txt)}")
    lines += [
        "",
        "## 四套绩效",
        "",
        "| 实验 | 总收益 | 年化 | 最大回撤 | 夏普 | 买入次数 | 胜率 | 平均持有(自然日) |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for exp in EXPERIMENTS:
        m = results[exp["id"]]["metrics"]
        lines.append(f"| {exp['label']} | {_metric_row(m)} |")
    lines.append(f"| 沪深300 | {_pct(bench['total_return'])} | — | {_pct(bench['max_drawdown'])} | — | — | — | — |")

    lines += ["", "## 三组对比", ""]
    for left_id, right_id, title in COMPARE_PAIRS:
        left = results[left_id]
        right = results[right_id]
        lm, rm = left["metrics"], right["metrics"]
        ll = left["label"]
        rl = right["label"]
        winner = ll if lm["total_return"] >= rm["total_return"] else rl
        dd_better = ll if lm["max_drawdown"] >= rm["max_drawdown"] else rl
        lines += [
            f"### {title}",
            "",
            f"- 收益更高： **{winner}**（{ll} {_pct(lm['total_return'])} vs {rl} {_pct(rm['total_return'])}）",
            f"- 回撤更小： **{dd_better}**（{ll} {_pct(lm['max_drawdown'])} vs {rl} {_pct(rm['max_drawdown'])}）",
            f"- 换手：{ll} 买入 {int(lm['n_buy'])} 次，{rl} 买入 {int(rm['n_buy'])} 次",
            "",
        ]
    lines += [f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M加/Q 前五 vs 全池 · 强度第1名日频回测")
    p.add_argument("--start", default=DEFAULT_START, help="起始日 YYYY-MM-DD")
    p.add_argument("--end", default="", help="结束日，默认最近交易日")
    p.add_argument("--cash", type=float, default=DEFAULT_CASH, help="每套实验初始资金")
    p.add_argument("--out", default="", help="输出目录")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    end = str(args.end).strip() or datetime.now().strftime("%Y-%m-%d")
    start = str(args.start).strip()
    cash = float(args.cash)
    out_root = os.path.abspath(str(args.out).strip() or OUT_DIR)
    os.makedirs(out_root, exist_ok=True)

    print("【1/5】读取冻结名单", flush=True)
    ranking = _read_ranking_csv()
    full_pools = {g: _load_full_pool(g) for g in GROUPS}
    top_pools = {g: _top_n_from_ranking(ranking, g, TOP_N) for g in GROUPS}

    pool_by_exp: dict[str, list[str]] = {}
    for exp in EXPERIMENTS:
        g = exp["group"]
        pool_by_exp[exp["id"]] = list(top_pools[g] if exp["mode"] == "top5" else full_pools[g])

    all_symbols: list[str] = []
    seen: set[str] = set()
    for exp in EXPERIMENTS:
        for s in pool_by_exp[exp["id"]]:
            if s not in seen:
                seen.add(s)
                all_symbols.append(s)

    print("  解析名称", flush=True)
    names = resolve_stock_names(all_symbols)
    for row in ranking.itertuples(index=False):
        if str(row.name or "").strip() and not names.get(str(row.symbol)):
            names[str(row.symbol)] = str(row.name).strip()

    universes: dict[str, pd.DataFrame] = {}
    for exp in EXPERIMENTS:
        universes[exp["id"]] = _universe_frame(
            pool_by_exp[exp["id"]],
            group=exp["group"],
            mode=exp["mode"],
            ranking=ranking,
            names=names,
        )
        print(
            f"  {exp['label']} {len(universes[exp['id']])} 只: "
            + "、".join(f"{r.name}{r.symbol}" for r in universes[exp["id"]].itertuples(index=False)),
            flush=True,
        )

    uni_all = pd.concat(
        [universes[e["id"]].assign(experiment=e["id"], label=e["label"]) for e in EXPERIMENTS],
        ignore_index=True,
    )
    uni_all.to_csv(os.path.join(out_root, "universe.csv"), index=False, encoding="utf-8-sig")

    union_rows = []
    seen_u: set[str] = set()
    for exp in EXPERIMENTS:
        for r in universes[exp["id"]].itertuples(index=False):
            if r.symbol in seen_u:
                continue
            seen_u.add(r.symbol)
            union_rows.append({"symbol": r.symbol, "name": r.name, "group": r.group, "group_rank": r.group_rank})
    union_df = pd.DataFrame(union_rows)

    print("【2/5】拉取日线 / 沪深300 / 申万板块", flush=True)
    pro = get_pro()
    bars = fetch_stock_bars(all_symbols, start, end)
    missing = [s for s in all_symbols if s not in bars]
    if missing:
        print(f"  无行情: {', '.join(missing)}", flush=True)
    hs300 = fetch_index_daily(pro, start, end)
    hs300.to_csv(os.path.join(out_root, "hs300.csv"), index=False, encoding="utf-8-sig")
    ts_codes = [to_ts_code(s) for s in bars]
    sw_map = resolve_sw_map(pro, ts_codes)
    sector_of: dict[str, tuple[str, str]] = {}
    sector_codes: list[str] = []
    for sym in bars:
        sw = sw_map.get(to_ts_code(sym)) or {}
        sc, sn, _lv = _sector_display(sw)
        sector_of[sym] = (sc, sn)
        if sc and sc not in sector_codes:
            sector_codes.append(sc)
    sector_pct: dict[str, pd.DataFrame] = {}
    for i, sc in enumerate(sector_codes):
        sector_pct[sc] = fetch_sw_daily(pro, sc, start, end)
        if (i + 1) % 5 == 0 or i + 1 == len(sector_codes):
            print(f"  [sw] {i + 1}/{len(sector_codes)}", flush=True)

    print("【3/5】全样本按日计算强度", flush=True)
    all_ranks = build_daily_ranks(union_df, bars, hs300, sector_of, sector_pct, start, end)
    if all_ranks.empty:
        raise RuntimeError("没有可用的日度强度，请检查行情区间。")
    all_ranks.to_csv(os.path.join(out_root, "daily_strength.csv"), index=False, encoding="utf-8-sig")
    print(f"  {all_ranks['date'].nunique()} 个交易日 × {all_ranks['symbol'].nunique()} 只", flush=True)

    print("【4/5】四套独立回测（仅第 1 名）", flush=True)
    results: dict[str, dict[str, Any]] = {}
    equity_map: dict[str, pd.DataFrame] = {}
    cfg_common = {"start": start, "end": end, "cash": cash}

    for exp in EXPERIMENTS:
        eid = exp["id"]
        dest = os.path.join(out_root, eid)
        os.makedirs(dest, exist_ok=True)
        uni = universes[eid]
        ranks = rerank_in_pool(all_ranks, uni["symbol"].tolist())
        if ranks.empty:
            raise RuntimeError(f"{exp['label']} 无日度排名。")
        ranks.to_csv(os.path.join(dest, "daily_rank.csv"), index=False, encoding="utf-8-sig")
        run_names = {r.symbol: r.name for r in uni.itertuples(index=False)}
        eq, tr, met = run_track(1, ranks, bars, run_names, cash)
        met["experiment"] = eid
        met["label"] = exp["label"]
        eq.to_csv(os.path.join(dest, "equity_curve.csv"), index=False, encoding="utf-8-sig")
        tr.to_csv(os.path.join(dest, "trades.csv"), index=False, encoding="utf-8-sig")
        pd.DataFrame([met]).to_csv(os.path.join(dest, "metrics.csv"), index=False, encoding="utf-8-sig")
        plot_equity(
            eq,
            hs300,
            os.path.join(dest, "equity_curve.png"),
            title=f"{PLOT_LABELS[eid]} strength #1",
        )
        write_run_summary(
            path=os.path.join(dest, "summary.md"),
            label=exp["label"],
            universe=uni,
            metrics=met,
            cfg={**cfg_common, "group": exp["group"], "mode": exp["mode"]},
        )
        results[eid] = {"label": exp["label"], "metrics": met}
        equity_map[eid] = eq
        print(
            f"  {exp['label']}  收益={100 * met['total_return']:.1f}%  "
            f"回撤={100 * met['max_drawdown']:.1f}%  买入 {met['n_buy']} 次",
            flush=True,
        )

    print("【5/5】写对比", flush=True)
    plot_compare(
        equity_map,
        PLOT_LABELS,
        hs300,
        cash,
        os.path.join(out_root, "compare_equity.png"),
    )
    bench = _bench_metrics(hs300, start, end)
    cmp_path = os.path.join(out_root, "compare.md")
    write_compare(
        cmp_path,
        results=results,
        universes=universes,
        bench=bench,
        cfg=cfg_common,
        ranking=ranking,
        full_pools=full_pools,
    )
    metrics_all = pd.DataFrame(
        [{**results[e["id"]]["metrics"], "label": e["label"]} for e in EXPERIMENTS]
    )
    metrics_all.to_csv(os.path.join(out_root, "metrics.csv"), index=False, encoding="utf-8-sig")
    print(f"  对比报告 → {cmp_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
