#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场温度计 V2.3 回测与仓位映射校准

验证「温度分 vs 上证未来 N 日收益」关系，并生成/应用校准后的阶梯仓位映射。

用法（在 ma_strategy_project 目录下）：
    python pybroker_integration/market_temperature_backtest.py --start 20230101
    python pybroker_integration/market_temperature_backtest.py --start 20230101 --forward 5,10,20
    python pybroker_integration/market_temperature_backtest.py --start 20230101 --calibrate --apply
    python pybroker_integration/market_temperature_backtest.py --warm-cache --start 20220101 --fast

说明：未传 --end 时，自动截止到最近有数据的交易日。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Any, Dict, List

import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from market_temperature_model import (  # noqa: E402
    CALIBRATION_JSON_PATH,
    DEFAULT_POSITION_BUCKETS,
    PERCENTILE_WINDOW,
    PRIMARY_INDEX,
    build_forward_returns,
    compute_market_temperature,
    compute_score_at_date,
    ensure_metrics_cache,
    fetch_index_daily_panel,
    fetch_trade_cal_dates,
    load_metrics_cache,
    print_result,
    resolve_trade_date,
    result_to_dict,
    slice_index_dfs_as_of,
    _get_tushare_pro,
    _get_tushare_token,
)

DEFAULT_BACKTEST_CSV = os.path.join(_SCRIPT_DIR, "market_temperature_backtest.csv")
DEFAULT_CALIBRATE_HORIZON = 10
POSITION_PCTS = [0, 20, 40, 70, 100]
POSITION_LABELS = ["空仓", "轻仓 20%", "中仓 40%", "重仓 70%", "满仓 100%"]


def analyze_default_buckets(df: pd.DataFrame, horizons: List[int]) -> pd.DataFrame:
    """当前默认阶梯下各分数段的上证未来收益统计。"""
    edges = [0, 20, 40, 60, 80, 100.001]
    labels = ["0-20", "20-40", "40-60", "60-80", "80-100"]
    work = df.dropna(subset=["total_score"]).copy()
    work["score_bucket"] = pd.cut(
        work["total_score"], bins=edges, labels=labels, right=False, include_lowest=True
    )
    rows: List[Dict[str, Any]] = []
    for lb in labels:
        sub = work[work["score_bucket"] == lb]
        if sub.empty:
            continue
        row: Dict[str, Any] = {
            "score_bucket": lb,
            "count": len(sub),
            "score_mean": round(float(sub["total_score"].mean()), 1),
        }
        for h in horizons:
            col = f"fwd_ret_{h}d"
            if col not in sub.columns:
                continue
            s = pd.to_numeric(sub[col], errors="coerce").dropna()
            row[f"mean_fwd_ret_{h}d"] = round(float(s.mean()), 3) if not s.empty else float("nan")
            row[f"win_fwd_ret_{h}d"] = round(float((s > 0).mean() * 100), 1) if not s.empty else float("nan")
        rows.append(row)
    return pd.DataFrame(rows)


def suggest_calibrated_buckets(
    df: pd.DataFrame,
    forward_col: str,
    n_buckets: int = 5,
) -> tuple[List[Dict[str, Any]], pd.DataFrame]:
    """
    按未来收益从低到高排序分数五分位，映射到 0/20/40/70/100 仓位。
    边界取各五分位的 score 上界。
    """
    work = df.dropna(subset=["total_score", forward_col]).copy()
    if len(work) < n_buckets * 5:
        raise ValueError(f"有效样本过少（{len(work)}），无法校准")

    work["score_quintile"] = pd.qcut(
        work["total_score"], q=n_buckets, labels=False, duplicates="drop"
    )
    stats = (
        work.groupby("score_quintile", as_index=False)
        .agg(
            score_min=("total_score", "min"),
            score_max=("total_score", "max"),
            mean_fwd=(forward_col, "mean"),
            win_rate=(forward_col, lambda x: float((x > 0).mean())),
            count=("total_score", "count"),
        )
    )
    stats["pos_rank"] = stats["mean_fwd"].rank(method="first").astype(int) - 1
    stats = stats.sort_values("score_max").reset_index(drop=True)

    buckets: List[Dict[str, Any]] = []
    prev_max = 0.0
    for _, row in stats.iterrows():
        pos_idx = int(row["pos_rank"])
        pos = POSITION_PCTS[min(pos_idx, len(POSITION_PCTS) - 1)]
        label = POSITION_LABELS[min(pos_idx, len(POSITION_LABELS) - 1)]
        boundary = float(row["score_max"])
        if boundary <= prev_max:
            boundary = prev_max + 0.1
        buckets.append({
            "max_score": round(boundary + 0.01, 2),
            "position_pct": pos,
            "label": label,
            "score_quintile": int(row["score_quintile"]),
            "mean_fwd": round(float(row["mean_fwd"]), 4),
            "win_rate": round(float(row["win_rate"]), 4),
        })
        prev_max = boundary

    buckets.sort(key=lambda x: x["max_score"])
    if buckets:
        buckets[-1]["max_score"] = 101.0
    return buckets, stats.sort_values("mean_fwd").reset_index(drop=True)


def run_backtest(
    pro,
    start_date: str,
    end_date: str,
    horizons: List[int],
    *,
    fast: bool = False,
    warm_cache: bool = False,
    min_breadth_history: int = 60,
    quiet: bool = False,
) -> pd.DataFrame:
    cal_dates = fetch_trade_cal_dates(pro, start_date, end_date)
    if not cal_dates:
        raise RuntimeError("交易日历为空")

    if warm_cache:
        ensure_metrics_cache(pro, end_date, warm=True)

    cache = load_metrics_cache()
    panel = fetch_index_daily_panel(pro, end_date)
    sh_panel = panel.get(PRIMARY_INDEX, pd.DataFrame())
    fwd = build_forward_returns(sh_panel, cal_dates, horizons)

    rows: List[Dict[str, Any]] = []
    total = len(cal_dates)
    for i, td in enumerate(cal_dates):
        if not quiet and (i + 1) % 50 == 0:
            print(f"  回测进度 {i + 1}/{total} ({td})...", file=sys.stderr)

        hist = cache[cache["trade_date"].astype(str) < td]
        if len(hist.dropna(subset=["up_ratio"])) < min_breadth_history:
            continue

        idx_asof = slice_index_dfs_as_of(panel, td)
        cache_asof = cache[cache["trade_date"].astype(str) <= td].copy()
        if cache_asof.empty:
            continue

        sc = compute_score_at_date(
            td,
            cache_asof,
            idx_asof,
            pro=None if fast else pro,
            include_hot=not fast,
        )
        row = dict(sc)
        fwd_hit = fwd[fwd["trade_date"].astype(str) == td]
        if not fwd_hit.empty:
            row.update(fwd_hit.iloc[0].to_dict())
        rows.append(row)

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def print_bucket_report(stats_df: pd.DataFrame, title: str, horizons: List[int]) -> None:
    print(f"\n{title}")
    print("-" * 72)
    if stats_df.empty:
        print("  (无数据)")
        return
    cols = ["score_bucket", "count", "score_mean"]
    for h in horizons:
        cols.extend([f"mean_fwd_ret_{h}d", f"win_fwd_ret_{h}d"])
    show = [c for c in cols if c in stats_df.columns]
    print(stats_df[show].to_string(index=False))


def save_calibration(
    buckets: List[Dict[str, Any]],
    stats_df: pd.DataFrame,
    *,
    start_date: str,
    end_date: str,
    forward_col: str,
    sample_count: int,
) -> None:
    os.makedirs(os.path.dirname(CALIBRATION_JSON_PATH), exist_ok=True)
    payload = {
        "version": "V2.3",
        "calibrated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "backtest_range": [start_date, end_date],
        "forward_days": int(forward_col.replace("fwd_ret_", "").replace("d", "")),
        "sample_count": sample_count,
        "buckets": [
            {k: b[k] for k in ("max_score", "position_pct", "label") if k in b}
            for b in buckets
        ],
        "quintile_stats": stats_df.to_dict(orient="records"),
        "default_buckets": DEFAULT_POSITION_BUCKETS,
    }
    with open(CALIBRATION_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n校准映射已写入: {CALIBRATION_JSON_PATH}")


def _print_daily_position_report() -> None:
    """校准/回测后输出用户真正关心的每日仓位报告。"""
    try:
        result = compute_market_temperature()
        print()
        print_result(result)
        out = os.path.abspath(os.path.join(_SCRIPT_DIR, "market_temperature_latest.csv"))
        pd.DataFrame([result_to_dict(result)]).to_csv(out, index=False, encoding="utf-8-sig")
        print(f"\n报告已保存: {out}")
    except Exception as e:
        print(f"\n每日仓位报告生成失败: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="市场温度计 V2.3 回测与校准")
    parser.add_argument("--start", required=True, help="回测起始 YYYYMMDD")
    parser.add_argument(
        "--end",
        default=None,
        help="回测结束 YYYYMMDD；默认自动取最近有数据的交易日",
    )
    parser.add_argument("--forward", default="5,10,20", help="未来收益 horizon，逗号分隔")
    parser.add_argument("--out-csv", default=DEFAULT_BACKTEST_CSV, help="回测明细 CSV")
    parser.add_argument("--fast", action="store_true", help="跳过热点评分(中性10分)，显著加速")
    parser.add_argument("--warm-cache", action="store_true", help="回测前补齐 metrics 缓存")
    parser.add_argument("--calibrate", action="store_true", help="根据回测生成校准映射")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="与 --calibrate 联用，写入 config/market_temperature_calibration.json",
    )
    parser.add_argument(
        "--calibrate-horizon",
        type=int,
        default=DEFAULT_CALIBRATE_HORIZON,
        help="校准使用的未来收益天数（默认10）",
    )
    parser.add_argument(
        "--brief",
        action="store_true",
        help="精简日志：不打印回测明细表，优先输出每日仓位报告",
    )
    parser.add_argument(
        "--show-report",
        action="store_true",
        help="回测结束后输出每日仓位报告（--brief / --apply 时默认开启）",
    )
    args = parser.parse_args()

    if not _get_tushare_token():
        print("未配置 TuShare token")
        return

    horizons = sorted({int(x.strip()) for x in args.forward.split(",") if x.strip().isdigit()})
    if not horizons:
        horizons = [5, 10, 20]

    pro = _get_tushare_pro()
    if pro is None:
        print("无法初始化 TuShare")
        return

    end_date = (args.end or "").strip() or resolve_trade_date(pro)
    show_report = args.show_report or args.brief or args.apply

    if not args.brief:
        print("=" * 60)
        print("市场温度计 V2.3 回测")
        print("=" * 60)
        print(f"区间: {args.start} ~ {end_date}")
        print(f"未来收益: {horizons} 个交易日")
        print(f"模式: {'快速(热点中性)' if args.fast else '完整(含热点)'}")
        if not args.end:
            print("结束日: 未指定，已自动截至最近交易日")
    else:
        print(f"回测校准进行中… 区间 {args.start} ~ {end_date}（日志精简，完成后输出仓位报告）")

    try:
        df = run_backtest(
            pro,
            args.start,
            end_date,
            horizons,
            fast=args.fast,
            warm_cache=args.warm_cache,
            min_breadth_history=min(60, PERCENTILE_WINDOW // 4),
        )
    except Exception as e:
        err = str(e)
        print(f"回测失败: {e}")
        if "7897" in err or "Proxy" in err or "proxy" in err or "timed out" in err.lower():
            print("提示: 本机代理(如 Clash 127.0.0.1:7897)超时。")
            print("      已尝试绕过系统代理；若仍失败请关闭代理或检查网络后重试。")
        return
    if df.empty:
        cache = load_metrics_cache()
        breadth_n = int(cache["up_ratio"].notna().sum()) if not cache.empty else 0
        print("回测无有效样本（检查缓存或放宽 min_breadth_history）")
        if breadth_n < min(60, PERCENTILE_WINDOW // 4):
            print(f"提示: 缓存中仅有 {breadth_n} 日广度(up_ratio)，请先运行:")
            print("  python pybroker_integration/market_temperature_model.py --warm-cache")
        return

    out = os.path.abspath(args.out_csv)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    if not args.brief:
        print(f"\n回测明细: {out} ({len(df)} 行)")
    else:
        print(f"回测完成: {len(df)} 个交易日样本（明细见「查看 · 回测明细」）")

    if not args.brief:
        default_stats = analyze_default_buckets(df, horizons)
        print_bucket_report(default_stats, "【默认阶梯】分数段 vs 上证未来收益", horizons)

        corr_rows = []
        for h in horizons:
            col = f"fwd_ret_{h}d"
            sub = df[["total_score", col]].dropna()
            if len(sub) < 10:
                continue
            corr = float(sub["total_score"].corr(sub[col]))
            corr_rows.append({"horizon": f"{h}d", "corr_score_fwd": round(corr, 4), "n": len(sub)})
        if corr_rows:
            print("\n【相关性】温度分 vs 未来收益")
            print(pd.DataFrame(corr_rows).to_string(index=False))

    if args.calibrate:
        h = args.calibrate_horizon
        fwd_col = f"fwd_ret_{h}d"
        if fwd_col not in df.columns:
            print(f"缺少列 {fwd_col}，无法校准")
            return
        try:
            buckets, qstats = suggest_calibrated_buckets(df, fwd_col)
        except ValueError as e:
            print(f"校准失败: {e}")
            return

        if not args.brief:
            print(f"\n【建议校准映射】基于 {fwd_col}（按收益排序的五分位）")
            print(f"{'max_score':>10} {'仓位':>8}  标签        mean_fwd   win_rate")
            for b in buckets:
                print(
                    f"{b['max_score']:>10.1f} {b['position_pct']:>7.0f}%  "
                    f"{b['label']:<10}  {b.get('mean_fwd', 0):>8.2f}%  {b.get('win_rate', 0)*100:>6.1f}%"
                )

        if args.apply:
            save_calibration(
                buckets,
                qstats,
                start_date=args.start,
                end_date=end_date,
                forward_col=fwd_col,
                sample_count=len(df),
            )
            if args.brief:
                print(f"校准映射已更新（基于 {fwd_col}，样本 {len(df)}）")
            else:
                print("每日报告将自动加载该校准映射（存在校准文件时显示 V2.3）")
        else:
            print("\n确认后请加 --apply 写入校准文件")

    if show_report:
        _print_daily_position_report()


if __name__ == "__main__":
    main()
