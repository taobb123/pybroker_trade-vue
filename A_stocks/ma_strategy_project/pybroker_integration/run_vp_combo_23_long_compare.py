#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
回测对比：六组合「底部放量上涨(2)+上涨缩量整理(3)」vs 原「上涨放量突破(4)+下跌放量(6)」。

形态 A：单步骤
  1) 从当日 vp_six_combo_scan.csv 导出 watch_2 / watch_3（不改原步骤默认 watch 4+6）
  2) 归档当日 2+3 快照
  3) 用同一套市场中性参数跑 combo2+3（输出到独立 latest，不覆盖 4+6）
  4) 读取原 market_neutral/output/latest（4+6）metrics，对比「仅多头 *_L」年化
  5) 固定 M-：combo23 最新 factor_snapshot 按 mud_minus Top2 → 东财自选「23M减」
  6) 半凯利仓位（口径A · 上限20%）写入 CSV/日志（仅「23M减」推送票）

前置：建议先跑「量价六组合分类」生成 scan；对比基线需已有「市场中性」4+6 结果。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJ = os.path.dirname(_SCRIPT_DIR)
for p in (_SCRIPT_DIR, _PROJ):
    if p not in sys.path:
        sys.path.insert(0, p)

from fetch_vp_six_combo import (  # noqa: E402
    COMBO_META,
    DEFAULT_OUT_CSV,
    export_combo_watch_lists,
    pattern_entry_symbols_path,
    watch_csv_path,
)
from market_neutral.data.pool_archive import save_watch_snapshot  # noqa: E402
from market_neutral.run import main as market_neutral_main  # noqa: E402
from mx_self_select import add_symbols_to_group  # noqa: E402
from kelly_position import (  # noqa: E402
    build_kelly_rows_for_symbols,
    write_kelly_position_csv,
)

DEFAULT_SCAN = DEFAULT_OUT_CSV
BASELINE_METRICS = os.path.join(
    _SCRIPT_DIR, "market_neutral", "output", "latest", "metrics.csv"
)
COMBO23_LATEST = os.path.join(
    _SCRIPT_DIR, "market_neutral", "output", "combo23_latest"
)
COMPARE_CSV = os.path.join(_SCRIPT_DIR, "vp_combo_23_vs_46_long_annual.csv")
COMPARE_MD = os.path.join(_SCRIPT_DIR, "vp_combo_23_vs_46_long_annual.md")
MMINUS_TOP_CSV = os.path.join(_SCRIPT_DIR, "vp_combo_23_mminus_top.csv")
KELLY_OUT_CSV = os.path.join(_SCRIPT_DIR, "vp_combo_23_kelly_positions.csv")
MX_MMINUS_GROUP = "23M减"
MX_TOP_N_DEFAULT = 2
NEW_IDS = (2, 3)
BASE_IDS = (4, 6)


def _norm_symbol(x) -> str:
    s = "".join(ch for ch in str(x) if ch.isdigit())
    return s.zfill(6) if s else ""


def _pct(x: float) -> str:
    try:
        return f"{100.0 * float(x):.1f}%"
    except Exception:
        return "n/a"


def _combo_label(ids: Tuple[int, ...]) -> str:
    parts = []
    for i in ids:
        name = COMBO_META.get(int(i), {}).get("combo_name", str(i))
        parts.append(f"{i}:{name}")
    return " + ".join(parts)


def export_watch_23(*, scan_csv: str) -> List[str]:
    notes: List[str] = []
    path = os.path.abspath(scan_csv)
    if not os.path.isfile(path):
        notes.append(f"缺少扫描表 {path}：请先跑「量价六组合分类」")
        return notes
    try:
        out_df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        notes.append(f"读取扫描表失败: {exc}")
        return notes
    if out_df.empty or "combo_id" not in out_df.columns:
        notes.append("扫描表无 combo_id，跳过导出 2+3")
        return notes
    primary_txt = pattern_entry_symbols_path(NEW_IDS[0])
    notes.extend(
        export_combo_watch_lists(
            out_df,
            combo_ids=list(NEW_IDS),
            out_dir=_SCRIPT_DIR,
            pattern_entry_symbols_txt=primary_txt,
            primary_combo_id=int(NEW_IDS[0]),
        )
    )
    # 强制写入当日归档（即使 index 已有其它 combo）
    for cid in NEW_IDS:
        wpath = watch_csv_path(cid, out_dir=_SCRIPT_DIR)
        if not os.path.isfile(wpath):
            notes.append(f"导出后仍无 watch[{cid}]")
            continue
        try:
            wdf = pd.read_csv(wpath, encoding="utf-8-sig")
            ap = save_watch_snapshot(wdf, int(cid))
            notes.append(f"强制归档 watch[{cid}] → {ap}")
        except Exception as exc:
            notes.append(f"归档 watch[{cid}] 失败: {exc}")
    return notes


def _load_long_only_metrics(metrics_csv: str) -> Dict[str, dict]:
    if not os.path.isfile(metrics_csv):
        return {}
    try:
        df = pd.read_csv(metrics_csv, encoding="utf-8-sig")
    except Exception:
        return {}
    if df.empty or "variant" not in df.columns:
        return {}
    out: Dict[str, dict] = {}
    for _, r in df.iterrows():
        v = str(r.get("variant") or "")
        if not v.endswith("_L"):
            continue
        out[v] = {
            "variant": v,
            "annual_return": float(r.get("annual_return") or 0),
            "total_return": float(r.get("total_return") or 0),
            "month_win_rate": float(r.get("month_win_rate") or 0),
            "sharpe": float(r.get("sharpe") or 0),
            "max_drawdown": float(r.get("max_drawdown") or 0),
        }
    return out


def pick_mminus_top_from_snapshot(
    snapshot_csv: str,
    *,
    top_n: int = MX_TOP_N_DEFAULT,
) -> Tuple[pd.DataFrame, List[str]]:
    """
    读 combo23 factor_snapshot：取最新交易日截面，按 mud_minus 降序 TopN。
    返回 (排名表, 说明)。
    """
    notes: List[str] = []
    path = os.path.abspath(snapshot_csv)
    if not os.path.isfile(path):
        notes.append(f"无 factor_snapshot：{path}")
        return pd.DataFrame(), notes
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception as exc:
        notes.append(f"读取 factor_snapshot 失败: {exc}")
        return pd.DataFrame(), notes
    if df.empty or "mud_minus" not in df.columns or "symbol" not in df.columns:
        notes.append("factor_snapshot 缺少 symbol/mud_minus")
        return pd.DataFrame(), notes

    work = df.copy()
    work["symbol"] = work["symbol"].map(_norm_symbol)
    work = work[work["symbol"].str.len() == 6]
    work["mud_minus"] = pd.to_numeric(work["mud_minus"], errors="coerce")
    work = work.dropna(subset=["mud_minus"])
    if work.empty:
        notes.append("最新截面无有效 mud_minus")
        return pd.DataFrame(), notes

    if "date" in work.columns:
        asof = pd.to_datetime(work["date"], errors="coerce").max()
        if pd.notna(asof):
            work = work[
                pd.to_datetime(work["date"], errors="coerce") == asof
            ].copy()
            asof_s = pd.Timestamp(asof).strftime("%Y-%m-%d")
        else:
            asof_s = ""
    else:
        asof_s = ""

    # 同代码保留 mud_minus 最大一行
    work = (
        work.sort_values("mud_minus", ascending=False)
        .drop_duplicates(subset=["symbol"], keep="first")
        .reset_index(drop=True)
    )
    n = max(1, int(top_n))
    top = work.head(n).copy()
    top.insert(0, "rank", range(1, len(top) + 1))
    if asof_s:
        top.insert(1, "asof", asof_s)
    cols = [
        c
        for c in (
            "rank",
            "asof",
            "symbol",
            "stock_name",
            "mud_minus",
            "r20",
            "r60",
            "close",
        )
        if c in top.columns
    ]
    top = top[cols]
    notes.append(
        f"M- 截面 {asof_s or 'n/a'} · 候选 {len(work)} · Top{n} by mud_minus"
    )
    return top, notes


def push_mminus_top_to_mx(
    snapshot_csv: str,
    *,
    top_n: int = MX_TOP_N_DEFAULT,
    group_name: str = MX_MMINUS_GROUP,
    out_rank_csv: str = MMINUS_TOP_CSV,
    skip_push: bool = False,
) -> Tuple[List[str], List[str], pd.DataFrame]:
    notes: List[str] = []
    top, pn = pick_mminus_top_from_snapshot(snapshot_csv, top_n=top_n)
    notes.extend(pn)
    out = os.path.abspath(out_rank_csv)
    ddir = os.path.dirname(out)
    if ddir:
        os.makedirs(ddir, exist_ok=True)
    if top is not None and not top.empty:
        top.to_csv(out, index=False, encoding="utf-8-sig")
    else:
        pd.DataFrame(
            columns=["rank", "asof", "symbol", "stock_name", "mud_minus"]
        ).to_csv(out, index=False, encoding="utf-8-sig")
    notes.append(f"M- Top 表 → {out}")

    syms: List[str] = []
    if top is not None and not top.empty:
        syms = [_norm_symbol(x) for x in top["symbol"].tolist()]
        syms = [s for s in syms if len(s) == 6]

    if skip_push:
        notes.append(f"已跳过推送「{group_name}」")
        return syms, notes, top if top is not None else pd.DataFrame()
    if not syms:
        notes.append(f"无 Top 股票，跳过推送「{group_name}」")
        return syms, notes, top if top is not None else pd.DataFrame()

    brief = []
    for _, r in top.iterrows():
        name = str(r.get("stock_name") or "")
        sc = r.get("mud_minus")
        sc_s = f"{float(sc):.3f}" if sc == sc else "-"
        brief.append(
            f"{r.get('symbol')}{(' ' + name) if name else ''} mud_minus={sc_s}"
        )
    notes.append(
        f"M- Top{len(syms)} →「{group_name}」: "
        + ("；".join(brief) if brief else "（空）")
    )
    _ok, push_notes = add_symbols_to_group(syms, group_name=group_name)
    notes.extend(push_notes)
    return syms, notes, top


def write_compare_report(
    *,
    metrics_23: Dict[str, dict],
    metrics_46: Dict[str, dict],
    cfg_note: str,
    out_csv: str,
    out_md: str,
) -> Tuple[str, str]:
    rows = []
    variants = sorted(set(metrics_23) | set(metrics_46))
    for v in variants:
        a = metrics_23.get(v)
        b = metrics_46.get(v)
        ann23 = float(a["annual_return"]) if a else float("nan")
        ann46 = float(b["annual_return"]) if b else float("nan")
        delta = (
            ann23 - ann46
            if a is not None and b is not None
            else float("nan")
        )
        rows.append(
            {
                "variant": v,
                "pool_23_annual": ann23,
                "pool_46_annual": ann46,
                "delta_23_minus_46": delta,
                "pool_23_month_win": a["month_win_rate"] if a else float("nan"),
                "pool_46_month_win": b["month_win_rate"] if b else float("nan"),
                "pool_23_sharpe": a["sharpe"] if a else float("nan"),
                "pool_46_sharpe": b["sharpe"] if b else float("nan"),
            }
        )
    cdf = pd.DataFrame(rows)
    if not cdf.empty and "pool_23_annual" in cdf.columns:
        cdf = cdf.sort_values("pool_23_annual", ascending=False)
    cdf.to_csv(out_csv, index=False, encoding="utf-8-sig")

    best23 = ""
    best46 = ""
    if metrics_23:
        k, m = max(metrics_23.items(), key=lambda kv: kv[1]["annual_return"])
        best23 = f"{k} = {_pct(m['annual_return'])}"
    if metrics_46:
        k, m = max(metrics_46.items(), key=lambda kv: kv[1]["annual_return"])
        best46 = f"{k} = {_pct(m['annual_return'])}"

    lines = [
        "# 仅多头年化对比 · combo2+3 vs combo4+6",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 新池：{_combo_label(NEW_IDS)}",
        f"- 原池：{_combo_label(BASE_IDS)}",
        f"- 主指标：仅多头 `*_L` 年化",
        f"- 参数：{cfg_note}",
        "",
        "| 组别 | 2+3 年化 | 4+6 年化 | 差值(2+3−4+6) | 2+3 月胜率 | 4+6 月胜率 |",
        "|------|----------|----------|---------------|-----------|-----------|",
    ]
    for _, r in cdf.iterrows():
        lines.append(
            f"| {r['variant']} | {_pct(r['pool_23_annual'])} | {_pct(r['pool_46_annual'])} | "
            f"{_pct(r['delta_23_minus_46'])} | {_pct(r['pool_23_month_win'])} | "
            f"{_pct(r['pool_46_month_win'])} |"
        )
    lines.extend(
        [
            "",
            "## 结论摘录",
            f"- 新池(2+3)仅多头年化最高：{best23 or '无'}",
            f"- 原池(4+6)仅多头年化最高：{best46 or '无'}",
            "",
            "## 说明",
            "- 原步骤「量价六组合」仍只导出/归档 4+6；本步骤单独导出 2+3。",
            "- 2+3 历史归档若偏少，长区间回测会更依赖近期池，解读时注意样本偏差。",
            "- 4+6 基线读取 `market_neutral/output/latest/metrics.csv`（勿被本步骤覆盖）。",
            f"- 固定因子 M-：最新截面 `mud_minus` Top2 推东财自选「{MX_MMINUS_GROUP}」。",
            "",
        ]
    )
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return out_csv, out_md


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="回测对比 combo2+3 vs combo4+6（仅多头年化）"
    )
    p.add_argument("--start", default="2025-06-01")
    p.add_argument("--end", default="")
    p.add_argument("--rebalance", default="weekly", choices=["weekly", "monthly"])
    p.add_argument("--q-rebalance", default="monthly", choices=["monthly", "quarterly"])
    p.add_argument("--quantile", type=float, default=0.10)
    p.add_argument("--variants", default="A,B,Q,M+,M-")
    p.add_argument("--scan-csv", default=DEFAULT_SCAN)
    p.add_argument("--baseline-metrics", default=BASELINE_METRICS)
    p.add_argument("--skip-export", action="store_true", help="不从 scan 导出 2+3")
    p.add_argument("--skip-backtest", action="store_true", help="只出对比表（需已有 combo23 metrics）")
    p.add_argument("--no-rotation", action="store_true")
    p.add_argument("--skip-fina", action="store_true")
    p.add_argument(
        "--skip-mx-push",
        action="store_true",
        help="不推送 M- Top 至东财自选「23M减」",
    )
    p.add_argument(
        "--mx-top-n",
        type=int,
        default=MX_TOP_N_DEFAULT,
        help="推送 / 写出的 M- TopN（默认 2）",
    )
    p.add_argument(
        "--mx-group",
        default=MX_MMINUS_GROUP,
        help="东财自选分组名（默认：23M减）",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    print("=" * 64, flush=True)
    print("回测对比 · combo2+3 vs combo4+6 · 主指标=仅多头年化", flush=True)
    print("=" * 64, flush=True)

    if not args.skip_export:
        for note in export_watch_23(scan_csv=str(args.scan_csv)):
            print(f"[export] {note}", flush=True)
    else:
        print("[export] 已跳过", flush=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(_SCRIPT_DIR, "market_neutral", "output", f"combo23_{run_id}")
    metrics_23_path = os.path.join(COMBO23_LATEST, "metrics.csv")

    if not args.skip_backtest:
        mn_argv = [
            "--start",
            str(args.start),
            "--rebalance",
            str(args.rebalance),
            "--q-rebalance",
            str(args.q_rebalance),
            "--quantile",
            str(args.quantile),
            "--variants",
            str(args.variants),
            "--combo-ids",
            "2,3",
            "--output-dir",
            out_dir,
            "--latest-dir",
            COMBO23_LATEST,
        ]
        if str(args.end or "").strip():
            mn_argv.extend(["--end", str(args.end).strip()])
        if args.no_rotation:
            mn_argv.append("--no-rotation")
        if args.skip_fina:
            mn_argv.append("--skip-fina")
        print(f"[backtest] 启动市场中性 combo2+3 → {out_dir}", flush=True)
        rc = int(market_neutral_main(mn_argv) or 0)
        if rc != 0:
            print(f"[backtest] 失败 exit={rc}", flush=True)
            return rc
        metrics_23_path = os.path.join(out_dir, "metrics.csv")
    else:
        print("[backtest] 已跳过，使用 combo23_latest", flush=True)

    metrics_23 = _load_long_only_metrics(metrics_23_path)
    metrics_46 = _load_long_only_metrics(str(args.baseline_metrics))
    if not metrics_23:
        print(f"无 2+3 仅多头指标：{metrics_23_path}", flush=True)
        return 1
    if not metrics_46:
        print(
            f"警告：无 4+6 基线 {args.baseline_metrics}（请先跑「市场中性」步骤）",
            flush=True,
        )

    cfg_note = (
        f"start={args.start} rebalance={args.rebalance} "
        f"q={args.q_rebalance} quantile={args.quantile} variants={args.variants}"
    )
    csv_path, md_path = write_compare_report(
        metrics_23=metrics_23,
        metrics_46=metrics_46,
        cfg_note=cfg_note,
        out_csv=COMPARE_CSV,
        out_md=COMPARE_MD,
    )

    print("=" * 64, flush=True)
    print("【仅多头年化对比】", flush=True)
    try:
        cdf = pd.read_csv(csv_path, encoding="utf-8-sig")
        for _, r in cdf.iterrows():
            print(
                f"  {r['variant']}: 2+3={_pct(r['pool_23_annual'])}  "
                f"4+6={_pct(r['pool_46_annual'])}  "
                f"Δ={_pct(r['delta_23_minus_46'])}",
                flush=True,
            )
    except Exception as exc:
        print(f"打印对比失败: {exc}", flush=True)
    print(f"对比表 → {csv_path}", flush=True)
    print(f"摘要   → {md_path}", flush=True)

    # 优先用本次 run 目录的 snapshot；否则 combo23_latest
    snap_candidates = [
        os.path.join(out_dir, "factor_snapshot.csv"),
        os.path.join(COMBO23_LATEST, "factor_snapshot.csv"),
    ]
    snap_path = next((p for p in snap_candidates if os.path.isfile(p)), snap_candidates[-1])
    print("【东财自选·23M减】", flush=True)
    push_syms, push_notes, top_df = push_mminus_top_to_mx(
        snap_path,
        top_n=int(args.mx_top_n),
        group_name=str(args.mx_group or MX_MMINUS_GROUP),
        out_rank_csv=MMINUS_TOP_CSV,
        skip_push=bool(args.skip_mx_push),
    )
    for note in push_notes:
        print(f"  {note}", flush=True)

    name_map: dict = {}
    if top_df is not None and not top_df.empty and "symbol" in top_df.columns:
        for _, r in top_df.iterrows():
            s = _norm_symbol(r.get("symbol"))
            if len(s) == 6:
                name_map[s] = str(r.get("stock_name") or "")

    print("【凯利仓位·23M减】", flush=True)
    kelly_rows, _st, kelly_notes = build_kelly_rows_for_symbols(
        str(args.mx_group or MX_MMINUS_GROUP),
        push_syms,
        name_map=name_map,
        source_dir_override=COMBO23_LATEST,
    )
    for note in kelly_notes:
        print(f"  {note}", flush=True)
    kelly_path = write_kelly_position_csv(kelly_rows, KELLY_OUT_CSV)
    print(f"  凯利仓位表 → {kelly_path}", flush=True)

    print("=" * 64, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
