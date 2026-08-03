# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from datetime import datetime
from typing import Dict, Optional

import pandas as pd


def _pct(x: float) -> str:
    try:
        return f"{100.0 * float(x):.1f}%"
    except Exception:
        return "n/a"


def _benchmark_nav(
    benchmark_df: Optional[pd.DataFrame],
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> pd.DataFrame:
    """指数收盘价对齐区间后 rebase 到 1。列: date, nav。"""
    if benchmark_df is None or benchmark_df.empty:
        return pd.DataFrame(columns=["date", "nav"])
    b = benchmark_df.copy()
    b["date"] = pd.to_datetime(b["date"]).dt.normalize()
    b = b.sort_values("date")
    if start:
        b = b[b["date"] >= pd.Timestamp(str(start)[:10])]
    if end:
        b = b[b["date"] <= pd.Timestamp(str(end)[:10])]
    if b.empty or "close" not in b.columns:
        return pd.DataFrame(columns=["date", "nav"])
    close = pd.to_numeric(b["close"], errors="coerce")
    c0 = float(close.iloc[0]) if len(close) else float("nan")
    if not (c0 == c0 and c0 > 0):
        return pd.DataFrame(columns=["date", "nav"])
    out = pd.DataFrame({"date": b["date"].values, "nav": (close / c0).values})
    return out


def _attach_excess_vs_benchmark(
    metrics_df: pd.DataFrame,
    benchmark_nav: pd.DataFrame,
) -> pd.DataFrame:
    """相对基准：总收益差 / 年化差（同期 buy&hold）。"""
    if metrics_df is None or metrics_df.empty or benchmark_nav is None or benchmark_nav.empty:
        return metrics_df
    nav = pd.to_numeric(benchmark_nav["nav"], errors="coerce").dropna()
    if len(nav) < 2:
        return metrics_df
    b_total = float(nav.iloc[-1] / nav.iloc[0] - 1.0)
    n = len(nav)
    years = max(n / 252.0, 1e-9)
    b_ann = (1.0 + b_total) ** (1.0 / years) - 1.0
    df = metrics_df.copy()
    df["bench_total_return"] = b_total
    df["bench_annual_return"] = b_ann
    df["excess_total"] = pd.to_numeric(df.get("total_return"), errors="coerce") - b_total
    df["excess_annual"] = pd.to_numeric(df.get("annual_return"), errors="coerce") - b_ann
    return df


def write_report(
    results: dict,
    *,
    out_dir: str,
    cfg_info: dict,
    benchmark_df: Optional[pd.DataFrame] = None,
) -> str:
    """写出 summary.md / metrics.csv / equity_curve.png / holdings / rebalance / factor。"""
    os.makedirs(out_dir, exist_ok=True)

    metrics_rows = []
    equity_frames = []
    rebal_frames = []
    factor_df: Optional[pd.DataFrame] = None
    holdings_latest = pd.DataFrame()

    for v, pack in results.items():
        met = dict(pack.get("metrics") or {})
        met["variant"] = v
        metrics_rows.append(met)
        eq = pack.get("equity")
        if eq is not None and not eq.empty:
            equity_frames.append(eq)
        reb = pack.get("rebalance")
        if reb is not None and not reb.empty:
            rebal_frames.append(reb)
        if factor_df is None and pack.get("factor") is not None:
            factor_df = pack["factor"]
        h = pack.get("holdings")
        if h is not None and not h.empty:
            if (
                holdings_latest.empty
                or v == "ROT"
                or (v == "Q" and "ROT" not in results)
                or (v == "B" and "Q" not in results and "ROT" not in results)
            ):
                holdings_latest = h.copy()
                holdings_latest["variant"] = v

    start = str(cfg_info.get("start_date") or "")
    end = str(cfg_info.get("end_date") or "")
    bench_nav = _benchmark_nav(benchmark_df, start=start or None, end=end or None)
    metrics_df = _attach_excess_vs_benchmark(pd.DataFrame(metrics_rows), bench_nav)
    metrics_path = os.path.join(out_dir, "metrics.csv")
    metrics_df.to_csv(metrics_path, index=False, encoding="utf-8-sig")

    if equity_frames:
        eq_all = pd.concat(equity_frames, ignore_index=True)
        eq_all.to_csv(os.path.join(out_dir, "equity_curve.csv"), index=False, encoding="utf-8-sig")
        bench_name = str(cfg_info.get("benchmark_name") or "沪深300")
        # 图例用英文，避免默认 matplotlib 中文字体缺失
        plot_label = str(cfg_info.get("benchmark_plot_label") or "CSI 300")
        # 主图：排除纯腿辅助序列（若有）；保留 *_L 仅多头
        main_eq = eq_all[~eq_all["variant"].astype(str).str.endswith(("_long", "_short"))].copy()
        _plot_equity(
            main_eq,
            os.path.join(out_dir, "equity_curve.png"),
            benchmark_nav=bench_nav,
            benchmark_label=plot_label,
        )
        _plot_leg_decompose(
            eq_all,
            os.path.join(out_dir, "equity_legs.png"),
        )
        if not bench_nav.empty:
            bn = bench_nav.copy()
            bn["variant"] = bench_name
            bn["equity"] = bn["nav"]  # rebase 后相对净值
            bn[["date", "variant", "equity"]].to_csv(
                os.path.join(out_dir, "benchmark_nav.csv"),
                index=False,
                encoding="utf-8-sig",
            )

    if rebal_frames:
        reb_all = pd.concat(rebal_frames, ignore_index=True)
        reb_all.to_csv(os.path.join(out_dir, "rebalance_log.csv"), index=False, encoding="utf-8-sig")

    if holdings_latest is not None and not holdings_latest.empty:
        holdings_latest.to_csv(
            os.path.join(out_dir, "holdings_latest.csv"),
            index=False,
            encoding="utf-8-sig",
        )

    if factor_df is not None and not factor_df.empty:
        factor_df.to_csv(
            os.path.join(out_dir, "factor_snapshot.csv"),
            index=False,
            encoding="utf-8-sig",
        )

    summary_path = os.path.join(out_dir, "summary.md")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write(_render_summary_md(metrics_df, cfg_info, holdings_latest))
    return summary_path


def _plot_equity(
    eq_all: pd.DataFrame,
    path: str,
    *,
    benchmark_nav: Optional[pd.DataFrame] = None,
    benchmark_label: str = "CSI 300",
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(10, 5))
        for v, g in eq_all.groupby("variant"):
            g = g.sort_values("date")
            x = pd.to_datetime(g["date"])
            y = pd.to_numeric(g["equity"], errors="coerce")
            y0 = float(y.iloc[0]) if len(y) else 1.0
            nav = y / y0 if y0 else y
            vs = str(v)
            lw = 1.2 if vs.endswith("_L") else 1.6
            ls = ":" if vs.endswith("_L") else "-"
            ax.plot(x, nav, label=vs, linewidth=lw, linestyle=ls)
        if benchmark_nav is not None and not benchmark_nav.empty:
            b = benchmark_nav.sort_values("date")
            ax.plot(
                pd.to_datetime(b["date"]),
                pd.to_numeric(b["nav"], errors="coerce"),
                label=benchmark_label,
                color="#333333",
                linewidth=2.0,
                linestyle="--",
                alpha=0.85,
                zorder=5,
            )
        ax.set_title("Market Neutral — Stock L/S vs CSI 300 (_L = long-only)")
        ax.set_xlabel("Date")
        ax.set_ylabel("NAV (rebased)")
        ax.legend(fontsize=8, ncol=2)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        fig.savefig(path, dpi=120)
        plt.close(fig)
        print(f"  [report] 净值图 → {path}", flush=True)
    except Exception as exc:
        print(f"  [report] 跳过绘图: {exc}", flush=True)


def _plot_leg_decompose(eq_all: pd.DataFrame, path: str) -> None:
    """按因子画：合成 / 多头腿净值 / 空头腿净值（rebase）。

    视觉风格对齐 equity_curve.png：适中画布 + 清晰字号/坐标轴/线宽，
    避免超大 figsize 导致缩略时字体发虚。
    """
    if eq_all is None or eq_all.empty:
        return
    if "long_ret" not in eq_all.columns or "short_ret" not in eq_all.columns:
        return
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        base = eq_all[~eq_all["variant"].astype(str).str.endswith("_L")].copy()
        # 排除 EQ/ROT 等无腿的合成
        variants = [
            v
            for v in base["variant"].astype(str).unique()
            if v not in ("EQ", "ROT") and "long_ret" in base.columns
        ]
        if not variants:
            return
        n = len(variants)
        cols = 2
        rows = (n + cols - 1) // cols
        # 与净值总图 (10×5@120) 同量级清晰度；略放大便于多子图阅读
        fig, axes = plt.subplots(rows, cols, figsize=(14, 4.2 * rows), squeeze=False)
        for i, v in enumerate(sorted(variants)):
            ax = axes[i // cols][i % cols]
            g = base[base["variant"].astype(str) == v].sort_values("date")
            if g.empty:
                continue
            x = pd.to_datetime(g["date"])
            for col, lab, style, lw in (
                ("equity", "L/S", "-", 1.8),
                ("equity_long", "Long", "--", 1.5),
                ("equity_short", "Short", ":", 1.5),
            ):
                if col not in g.columns:
                    continue
                y = pd.to_numeric(g[col], errors="coerce")
                y0 = float(y.iloc[0]) if len(y) else 1.0
                if not (y0 == y0 and y0 > 0):
                    continue
                ax.plot(x, y / y0, label=lab, linewidth=lw, linestyle=style)
            ax.set_title(str(v), fontsize=12, fontweight="bold")
            ax.set_xlabel("Date", fontsize=10)
            ax.set_ylabel("NAV (rebased)", fontsize=10)
            ax.tick_params(axis="both", which="major", labelsize=9, width=1.1, length=5)
            for spine in ax.spines.values():
                spine.set_linewidth(1.2)
            ax.legend(fontsize=9, frameon=True, fancybox=False, edgecolor="#333333")
            ax.grid(True, alpha=0.3, linewidth=0.8)
        for j in range(n, rows * cols):
            axes[j // cols][j % cols].axis("off")
        fig.suptitle(
            "Long vs Short leg NAV (rebased)",
            fontsize=13,
            fontweight="bold",
            y=1.01,
        )
        fig.tight_layout()
        fig.savefig(path, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  [report] 多空腿图 → {path}", flush=True)
    except Exception as exc:
        print(f"  [report] 跳过多空腿图: {exc}", flush=True)


def _render_summary_md(
    metrics_df: pd.DataFrame,
    cfg_info: dict,
    holdings: pd.DataFrame,
) -> str:
    pool = cfg_info.get("pool", "combo4+6")
    hedge = cfg_info.get("hedge", "个股多空")
    rebal = cfg_info.get("rebalance", "weekly")
    q_rebal = cfg_info.get("q_rebalance", "monthly")
    start = cfg_info.get("start_date", "")
    end = cfg_info.get("end_date", "")
    q = cfg_info.get("quantile", 0.10)
    q_pct = int(round(float(q) * 100))
    bn = str(cfg_info.get("benchmark_name") or "沪深300")
    bench_line = ""
    if metrics_df is not None and not metrics_df.empty and "bench_total_return" in metrics_df.columns:
        bt = float(metrics_df["bench_total_return"].iloc[0] or 0)
        ba = float(metrics_df["bench_annual_return"].iloc[0] or 0)
        bench_line = f"- {bn} 同期 buy&hold：总收益 {_pct(bt)}，年化 {_pct(ba)}"
    lines = [
        "# 市场中性 MVP 报告（个股多空 + Rank IC）",
        "",
        f"- 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 池={pool}  对冲={hedge}  默认调仓={rebal}  Q调仓={q_rebal}  区间={start}~{end}",
        f"- 规则：因子横截面 **前{q_pct}% 做多 / 后{q_pct}% 做空**（等权，资金中性）",
        f"- Rank IC：因子与未来收益 Spearman；默认前瞻5日，Q前瞻20日",
        f"- 净值图基准：{bn}（虚线）；超额年化=策略年化−{bn}年化",
        f"- 多空拆分：各组记录多头/空头腿收益；`*_L`=仅做多前{q_pct}%（服务无法做空的买入决策）；见 equity_legs.png",
    ]
    if cfg_info.get("rotation"):
        lines.append(
            "- 轮动：EQ=五因子等权；ROT=滚动ICIR×温度分档软权重 + 温度阶梯仓位缩放（主KPI月胜率）"
        )
    if bench_line:
        lines.append(bench_line)
    lines.extend(
        [
            "",
            "| 组别 | 调仓 | 年化 | 最大回撤 | 夏普 | 总收益 | 超额年化 | 月胜率 | Rank IC | ICIR | IC样本 |",
            "|------|------|------|----------|------|--------|----------|--------|---------|------|--------|",
        ]
    )
    label = {
        "A": "A 形态",
        "B": "B 相对PE",
        "C": "C 形态+PE合成",
        "Q": "Q 公司估值(轻量)",
        "M+": "M+ 动量MUD",
        "M-": "M- 反转MUD",
        "EQ": "EQ 五因子等权",
        "ROT": "ROT 轮动+温度",
        "A_L": "A_L 仅多头",
        "B_L": "B_L 仅多头",
        "C_L": "C_L 仅多头",
        "Q_L": "Q_L 仅多头",
        "M+_L": "M+_L 仅多头",
        "M-_L": "M-_L 仅多头",
    }
    by_v: Dict[str, dict] = {}
    for _, r in metrics_df.iterrows():
        v = str(r.get("variant", ""))
        by_v[v] = r.to_dict()
        freq = str(r.get("rebalance_freq") or rebal)
        ric = r.get("rank_ic")
        ric_s = f"{float(ric):.3f}" if ric is not None and pd.notna(ric) else "-"
        icir = r.get("icir")
        icir_s = f"{float(icir):.2f}" if icir is not None and pd.notna(icir) else "-"
        lines.append(
            f"| {label.get(v, v)} | {freq} | {_pct(r.get('annual_return', 0))} | "
            f"{_pct(r.get('max_drawdown', 0))} | {float(r.get('sharpe', 0) or 0):.2f} | "
            f"{_pct(r.get('total_return', 0))} | {_pct(r.get('excess_annual', 0))} | "
            f"{_pct(r.get('month_win_rate', 0))} | "
            f"{ric_s} | {icir_s} | "
            f"{int(r.get('ic_count', 0) or 0)} |"
        )

    # 多空腿贡献表（不含 *_L / EQ / ROT）
    leg_rows = []
    for v, r in by_v.items():
        if v.endswith("_L") or v in ("EQ", "ROT"):
            continue
        if "long_total_return" not in r and "short_total_return" not in r:
            continue
        leg_rows.append((v, r))
    if leg_rows:
        lines.append("")
        lines.append("## 多空腿贡献（买入决策参考）")
        lines.append("")
        lines.append(
            "| 组别 | 多头累计 | 空头累计 | 多头月胜率 | 空头月胜率 | 多头份额 | 主导 |"
        )
        lines.append(
            "|------|----------|----------|------------|------------|----------|------|"
        )
        for v, r in leg_rows:
            lt = float(r.get("long_total_return", 0) or 0)
            st = float(r.get("short_total_return", 0) or 0)
            share = float(r.get("long_contrib_share", 0) or 0)
            if lt >= 0 and st >= 0:
                dom = "双侧赚" if abs(lt) + abs(st) > 0 else "-"
            elif lt > st:
                dom = "多头主导" if lt > 0 else "空头拖累更轻"
            else:
                dom = "空头主导" if st > 0 else "多头拖累更轻"
            if st > 0 and lt <= 0:
                dom = "主要靠空头"
            if lt > 0 and st <= 0:
                dom = "主要靠多头"
            lines.append(
                f"| {label.get(v, v)} | {_pct(lt)} | {_pct(st)} | "
                f"{_pct(r.get('long_month_win_rate', 0))} | {_pct(r.get('short_month_win_rate', 0))} | "
                f"{share:.2f} | {dom} |"
            )
        lines.append("")
        lines.append(
            "_说明：空头累计>0 表示做空腿赚钱；若「主要靠空头」，仅做多时不宜直接照搬该因子。_"
        )
        # 仅多头 *_L 对照
        long_only = [(v, r) for v, r in by_v.items() if v.endswith("_L")]
        if long_only:
            lines.append("")
            lines.append("### 仅多头对照 `*_L`")
            lines.append("")
            lines.append("| 组别 | 年化 | 总收益 | 月胜率 | 夏普 |")
            lines.append("|------|------|--------|--------|------|")
            for v, r in sorted(long_only, key=lambda kv: float(kv[1].get("annual_return", 0) or 0), reverse=True):
                lines.append(
                    f"| {label.get(v, v)} | {_pct(r.get('annual_return', 0))} | "
                    f"{_pct(r.get('total_return', 0))} | {_pct(r.get('month_win_rate', 0))} | "
                    f"{float(r.get('sharpe', 0) or 0):.2f} |"
                )

    lines.append("")
    lines.append("## 结论摘要")
    if "EQ" in by_v and "ROT" in by_v:
        lines.append(
            f"- EQ vs ROT 月胜率：{_pct(by_v['EQ'].get('month_win_rate', 0))} vs "
            f"{_pct(by_v['ROT'].get('month_win_rate', 0))}；"
            f"年化 {_pct(by_v['EQ'].get('annual_return', 0))} vs {_pct(by_v['ROT'].get('annual_return', 0))}"
        )
    # 推荐：仅多头年化最高的 *_L
    long_only_all = [(v, r) for v, r in by_v.items() if str(v).endswith("_L")]
    if long_only_all:
        best_l, best_lm = max(
            long_only_all,
            key=lambda kv: float(kv[1].get("annual_return", 0) or 0),
        )
        lines.append(
            f"- 仅多头年化最高：{label.get(best_l, best_l)} = {_pct(best_lm.get('annual_return', 0))} "
            f"（月胜率 {_pct(best_lm.get('month_win_rate', 0))}）"
        )
    if "B" in by_v and "Q" in by_v:
        lines.append(
            f"- Q vs B RankIC：{float(by_v['Q'].get('rank_ic',0) or 0):.3f} vs "
            f"{float(by_v['B'].get('rank_ic',0) or 0):.3f}"
        )
    if "M+" in by_v and "M-" in by_v:
        lines.append(
            f"- M+ vs M- RankIC：{float(by_v['M+'].get('rank_ic',0) or 0):.3f} vs "
            f"{float(by_v['M-'].get('rank_ic',0) or 0):.3f}"
        )
    if by_v:
        ranked = sorted(
            (
                (k, m)
                for k, m in by_v.items()
                if not str(k).endswith("_L") and k not in ("EQ", "ROT")
            ),
            key=lambda kv: float(kv[1].get("rank_ic", 0) or 0)
            if kv[1].get("rank_ic") == kv[1].get("rank_ic")
            else float("-inf"),
            reverse=True,
        )
        if ranked:
            best_v, best_m = ranked[0]
            lines.append(
                f"- Rank IC 最高：{label.get(best_v, best_v)} = {float(best_m.get('rank_ic',0) or 0):.3f}"
            )

    prefer = (
        "ROT"
        if "ROT" in by_v
        else ("Q" if "Q" in by_v else ("B" if "B" in by_v else next(iter(by_v), "A")))
    )
    lines.append("")
    lines.append(f"## 最近持仓 / 权重（优先 {prefer}）")
    # 轮动权重表
    if holdings is not None and not holdings.empty and any(
        str(c).startswith("w_") for c in holdings.columns
    ):
        show = holdings.tail(1)
        lines.append("")
        lines.append("| date | temp | scale | " + " | ".join(["A", "B", "Q", "M+", "M-"]) + " |")
        lines.append("|------|------|-------|-----|-----|-----|------|------|")
        for _, r in show.iterrows():
            cells = [
                str(r.get("date", "")),
                str(r.get("temp_bucket", "")),
                f"{float(r.get('position_scale', 1) or 1):.0%}",
            ]
            for f in ("A", "B", "Q", "M+", "M-"):
                cells.append(f"{float(r.get(f'w_{f}', 0) or 0):.0%}")
            lines.append("| " + " | ".join(cells) + " |")
    elif holdings is not None and not holdings.empty:
        show = holdings.head(30)
        lines.append("")
        lines.append("| symbol | name | side | weight | factor | upside |")
        lines.append("|--------|------|------|--------|--------|--------|")
        for _, r in show.iterrows():
            up = r.get("upside")
            up_s = f"{100*float(up):.1f}%" if up is not None and pd.notna(up) else "-"
            fac = r.get("factor")
            fac_s = f"{float(fac):.3f}" if fac is not None and pd.notna(fac) else "-"
            lines.append(
                f"| {r.get('symbol','')} | {r.get('name','')} | {r.get('side','')} | "
                f"{float(r.get('weight', 0) or 0):.1%} | {fac_s} | {up_s} |"
            )
    else:
        lines.append("")
        lines.append("_无持仓（候选为空）_")

    lines.append("")
    lines.append("## 因子说明")
    lines.append("- **B**：相对行业/池内 PE 的 upside（现有）")
    lines.append("- **Q**：0.4×ROE分位 + 0.3×OCF/营收分位 + 0.3×upside分位（公告日点-in-time）")
    lines.append("- **M+**：波动调整60日动量 + 量比（动量MUD）")
    lines.append("- **M-**：−R20 分位（反转MUD，跌越多分越高）")
    lines.append("- 已取消空指数；对冲腿为同池因子后分位个股")
    lines.append("")
    return "\n".join(lines)
