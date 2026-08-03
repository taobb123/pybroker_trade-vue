# -*- coding: utf-8 -*-
"""
市场中性 MVP 入口。

用法:
  python -m market_neutral.run --variants A,B,Q,M+,M- --q-rebalance monthly
  python run_market_neutral.py --start 2025-06-01 --rebalance weekly --quantile 0.10
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timedelta

_PKG = os.path.dirname(os.path.abspath(__file__))
_INTEG = os.path.dirname(_PKG)
_PROJ = os.path.dirname(_INTEG)
for p in (_INTEG, _PROJ):
    if p not in sys.path:
        sys.path.insert(0, p)

from market_neutral.backtest.engine import (  # noqa: E402
    build_aligned_factor_panel,
    run_all_variants,
)
from market_neutral.config import (  # noqa: E402
    BENCHMARK_INDEX,
    BENCHMARK_INDEX_NAME,
    MNConfig,
    ensure_sys_path,
)
from market_neutral.data import load_observation_pool, unique_symbols  # noqa: E402
from market_neutral.data.pool_archive import (  # noqa: E402
    collect_archived_symbols,
    seed_from_current_watch,
)
from market_neutral.data.prices import (  # noqa: E402
    fetch_daily_basic_panel,
    fetch_index_bars,
    fetch_industry_map,
    fetch_stock_bars,
    rebalance_dates,
    trading_calendar_from_index,
)
from market_neutral.factors import evaluate_pattern_panel, overlay_latest_scan  # noqa: E402
from market_neutral.factors.company_value import (  # noqa: E402
    build_company_q_panel,
    fetch_fina_lite,
)
from market_neutral.factors.mud import compute_mud_panel  # noqa: E402
from market_neutral.factors.value import build_valuation_panel  # noqa: E402
from market_neutral.report.performance import write_report  # noqa: E402


def _norm_variant(x: str) -> str:
    v = str(x).strip().upper().replace("＋", "+").replace("－", "-")
    if v in ("MPLUS", "M_PLUS", "MUD+", "MUD_PLUS"):
        return "M+"
    if v in ("MMINUS", "M_MINUS", "MUD-", "MUD_MINUS"):
        return "M-"
    return v


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="市场中性：形态/PE/公司估值Q/MUD 个股多空 + Rank IC"
    )
    p.add_argument("--start", default="2025-01-01", help="回测起始日 YYYY-MM-DD")
    p.add_argument("--end", default="", help="回测结束日，默认今天")
    p.add_argument(
        "--rebalance",
        default="weekly",
        choices=["weekly", "monthly"],
        help="默认调仓频率（A/B/M+/M-/C）",
    )
    p.add_argument(
        "--q-rebalance",
        default="monthly",
        choices=["monthly", "quarterly"],
        help="公司估值 Q 单独调仓频率",
    )
    p.add_argument("--quantile", type=float, default=0.10, help="多空分位")
    p.add_argument("--top-n", type=int, default=0, help="兼容旧参数")
    p.add_argument("--upside-min", type=float, default=0.0, help="兼容旧参数")
    p.add_argument(
        "--variants",
        default="A,B,Q,M+,M-",
        help="组别：A形态 B相对PE Q公司估值 M+动量MUD M-反转MUD C合成",
    )
    p.add_argument("--skip-pattern-history", action="store_true")
    p.add_argument("--no-archive", action="store_true")
    p.add_argument("--skip-fina", action="store_true", help="跳过财务拉取（Q 仅用 upside）")
    p.add_argument(
        "--no-rotation",
        action="store_true",
        help="关闭因子轮动合成 EQ/ROT（默认开启）",
    )
    p.add_argument(
        "--skip-gbm",
        action="store_true",
        help="轮动仅用 ICIR×温度规则，不用轻量 GBM",
    )
    p.add_argument("--output-dir", default="")
    return p.parse_args(argv)


def _sync_latest(out_dir: str, latest_dir: str) -> None:
    os.makedirs(latest_dir, exist_ok=True)
    for name in (
        "summary.md",
        "metrics.csv",
        "equity_curve.csv",
        "equity_curve.png",
        "holdings_latest.csv",
        "rebalance_log.csv",
        "factor_snapshot.csv",
        "benchmark_nav.csv",
        "rotation_weights.csv",
        "rotation_features.csv",
        "equity_legs.png",
    ):
        src = os.path.join(out_dir, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(latest_dir, name))


def pd_ts(s: str):
    import pandas as pd

    return pd.Timestamp(str(s)[:10]).normalize()


def pd_timestamp_minus_days(s: str, days: int) -> str:
    d = datetime.strptime(str(s)[:10], "%Y-%m-%d") - timedelta(days=int(days))
    return d.strftime("%Y-%m-%d")


def main(argv=None) -> int:
    import pandas as pd

    args = parse_args(argv)
    ensure_sys_path()

    end = (args.end or "").strip() or datetime.now().strftime("%Y-%m-%d")
    variants = tuple(
        _norm_variant(x) for x in str(args.variants).split(",") if x.strip()
    )
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir.strip() or os.path.join(_PKG, "output", run_id)
    warm_start = pd_timestamp_minus_days(args.start, 280)

    cfg = MNConfig(
        start_date=str(args.start)[:10],
        end_date=end[:10],
        rebalance=args.rebalance,
        q_rebalance=args.q_rebalance,
        quantile=float(args.quantile),
        upside_min=float(args.upside_min),
        variants=variants,
        output_dir=out_dir,
        use_watch_archive=not bool(args.no_archive),
    )

    q_pct = int(round(cfg.quantile * 100))
    print("=" * 60, flush=True)
    print(
        f"市场中性 | 个股多空 前{q_pct}%/后{q_pct}% | "
        f"默认调仓={cfg.rebalance} | Q调仓={cfg.q_rebalance}",
        flush=True,
    )
    print(
        f"区间 {cfg.start_date}~{cfg.end_date}  variants={variants}",
        flush=True,
    )
    print("=" * 60, flush=True)

    for note in seed_from_current_watch(
        integration_root=cfg.integration_root,
        combo_ids=cfg.combo_ids,
        root=cfg.watch_archive_dir,
    ):
        print(f"[archive] {note}", flush=True)

    members, _watch = load_observation_pool(cfg)
    symbols = unique_symbols(members)
    for s in collect_archived_symbols(
        cfg.combo_ids, root=cfg.watch_archive_dir, end=cfg.end_date
    ):
        if s not in symbols:
            symbols.append(s)
    print(f"[pool] 成员 {len(members)}，拉行情 {len(symbols)}", flush=True)
    if not symbols:
        print("观察池为空", flush=True)
        return 1

    name_map = {m.symbol: m.stock_name for m in members if m.stock_name}

    print("[data] 指数日历 …", flush=True)
    index_df = fetch_index_bars(warm_start, cfg.end_date)
    print(f"[data] 基准 {BENCHMARK_INDEX_NAME} ({BENCHMARK_INDEX}) …", flush=True)
    bench_df = fetch_index_bars(cfg.start_date, cfg.end_date, ts_code=BENCHMARK_INDEX)
    print(f"[data] 基准行数 {len(bench_df)}", flush=True)
    cal_all = trading_calendar_from_index(index_df)
    rebal_default = rebalance_dates(
        cal_all, cfg.start_date, cfg.end_date, cfg.rebalance
    )
    rebal_q = rebalance_dates(
        cal_all, cfg.start_date, cfg.end_date, cfg.q_rebalance
    )
    cal = [d for d in cal_all if pd_ts(cfg.start_date) <= d <= pd_ts(cfg.end_date)]
    all_rebal = sorted(set(rebal_default) | set(rebal_q))
    print(
        f"[data] 交易日 {len(cal)}，默认调仓 {len(rebal_default)}，Q调仓 {len(rebal_q)}",
        flush=True,
    )
    if not all_rebal:
        print("无调仓日", flush=True)
        return 1

    rebal_by_variant = {}
    for v in variants:
        rebal_by_variant[v] = rebal_q if v == "Q" else rebal_default

    print("[data] 个股行情 …", flush=True)
    bars = fetch_stock_bars(symbols, warm_start, cfg.end_date)

    print("[data] daily_basic 估值 …", flush=True)
    basic = fetch_daily_basic_panel(symbols, cfg.start_date, cfg.end_date)
    industry = fetch_industry_map(symbols)
    valuation = build_valuation_panel(
        basic,
        industry,
        winsor_q_low=cfg.upside_winsor_q_low,
        winsor_q_high=cfg.upside_winsor_q_high,
        clip_low=cfg.upside_clip_low,
        clip_high=cfg.upside_clip_high,
    )
    print(f"[factor] upside 行数 {len(valuation)}", flush=True)

    # 形态：在全部调仓日上评估，保证 Q 日也有截面
    if args.skip_pattern_history:
        print("[factor] 跳过历史形态 …", flush=True)
        from market_neutral.factors import load_latest_pattern_scan

        scan = load_latest_pattern_scan(cfg.pattern_scan_csv)
        rows = []
        if not scan.empty:
            for dt in all_rebal:
                for _, r in scan.iterrows():
                    sc = str(r.get("state_code") or "")
                    rows.append(
                        {
                            "date": pd.Timestamp(dt).normalize(),
                            "symbol": str(r.get("symbol")).zfill(6),
                            "combo_id": int(r.get("combo_id") or 4),
                            "state_code": sc,
                            "state": str(r.get("state") or ""),
                            "score": float(r.get("score") or 0),
                            "entry": bool(r.get("entry", False)),
                            "close": float(r.get("close") or float("nan")),
                            "stock_name": str(r.get("stock_name") or ""),
                            "pattern_ok": sc in ("entry", "confirming", "trial"),
                        }
                    )
        pattern = pd.DataFrame(rows)
    else:
        print("[factor] 形态评估 …", flush=True)
        pattern = evaluate_pattern_panel(members, bars, all_rebal, cfg)
        pattern = overlay_latest_scan(pattern, cfg.pattern_scan_csv)
    print(f"[factor] 形态行数 {len(pattern)}", flush=True)

    need_mud = any(v in ("M+", "M-") for v in variants)
    mud = pd.DataFrame()
    if need_mud:
        print("[factor] MUD M+/M- …", flush=True)
        mud = compute_mud_panel(bars, all_rebal, name_map=name_map)
        print(f"[factor] MUD 行数 {len(mud)}", flush=True)

    need_q = "Q" in variants
    q_panel = pd.DataFrame()
    if need_q:
        print("[factor] 公司估值 Q …", flush=True)
        if args.skip_fina:
            fina = pd.DataFrame()
            print("  [fina] 已跳过", flush=True)
        else:
            fina = fetch_fina_lite(symbols, cfg.start_date, cfg.end_date)
            print(f"  [fina] 行数 {len(fina)}", flush=True)
        q_panel = build_company_q_panel(
            fina, valuation, rebal_q, name_map=name_map
        )
        print(f"[factor] Q 行数 {len(q_panel)}", flush=True)

    print("[factor] 对齐截面 …", flush=True)
    factor = build_aligned_factor_panel(
        pattern, valuation, mud, q_panel, all_rebal
    )
    print(f"[factor] 对齐后 {len(factor)} 行", flush=True)

    print("[backtest] 多空 + Rank IC …", flush=True)
    results = run_all_variants(
        factor_panel=factor,
        bars_by_symbol=bars,
        index_df=index_df,
        calendar=cal,
        rebal_by_variant=rebal_by_variant,
        cfg=cfg,
    )

    enable_rot = not bool(args.no_rotation)
    if enable_rot and len([v for v in variants if v in results]) >= 2:
        print("[rotation] 等权 EQ + 轮动 ROT …", flush=True)
        from market_neutral.rotation import RotationSpec, run_rotation_overlay

        rspec = RotationSpec(use_gbm=not bool(args.skip_gbm))
        extra, weight_sched, feat_panel = run_rotation_overlay(
            results,
            calendar=cal,
            rebal_dates=rebal_default,
            cfg=cfg,
            spec=rspec,
        )
        results.update(extra)
        os.makedirs(out_dir, exist_ok=True)
        if weight_sched is not None and not weight_sched.empty:
            weight_sched.to_csv(
                os.path.join(out_dir, "rotation_weights.csv"),
                index=False,
                encoding="utf-8-sig",
            )
        if feat_panel is not None and not feat_panel.empty:
            feat_panel.to_csv(
                os.path.join(out_dir, "rotation_features.csv"),
                index=False,
                encoding="utf-8-sig",
            )

    cfg_info = {
        "pool": "combo4+6(+archive)" if cfg.use_watch_archive else "combo4+6",
        "hedge": f"个股多空 前{q_pct}%/后{q_pct}%",
        "rebalance": cfg.rebalance,
        "q_rebalance": cfg.q_rebalance,
        "start_date": cfg.start_date,
        "end_date": cfg.end_date,
        "quantile": cfg.quantile,
        "benchmark_name": BENCHMARK_INDEX_NAME,
        "benchmark_code": BENCHMARK_INDEX,
        "rotation": enable_rot,
    }
    summary = write_report(
        results, out_dir=out_dir, cfg_info=cfg_info, benchmark_df=bench_df
    )
    _sync_latest(out_dir, cfg.latest_output_dir)
    print("=" * 60, flush=True)
    print(f"完成 → {out_dir}", flush=True)
    print(f"摘要 → {summary}", flush=True)
    # 从写出的 metrics 读超额，便于控制台对照基准
    try:
        met_all = pd.read_csv(os.path.join(out_dir, "metrics.csv"))
        met_by = {str(r["variant"]): r for _, r in met_all.iterrows()}
    except Exception:
        met_by = {}
    for v, pack in results.items():
        m = pack["metrics"]
        mx = met_by.get(v, {})
        ex = mx.get("excess_annual", None)
        ex_s = f"  超额年化={100*float(ex):.1f}%" if ex is not None and pd.notna(ex) else ""
        ric = m.get("rank_ic", float("nan"))
        icir = m.get("icir", float("nan"))
        try:
            ric_s = f"{float(ric):.3f}" if ric == ric else "n/a"
        except Exception:
            ric_s = "n/a"
        try:
            icir_s = f"{float(icir):.2f}" if icir == icir else "n/a"
        except Exception:
            icir_s = "n/a"
        print(
            f"  [{v}] 年化={100*m.get('annual_return',0):.1f}%  "
            f"回撤={100*m.get('max_drawdown',0):.1f}%  "
            f"夏普={m.get('sharpe',0):.2f}  "
            f"月胜率={100*m.get('month_win_rate',0):.0f}%  "
            f"RankIC={ric_s}  "
            f"ICIR={icir_s}  "
            f"调仓={m.get('rebalance_freq','')}{ex_s}",
            flush=True,
        )
    print("=" * 60, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
