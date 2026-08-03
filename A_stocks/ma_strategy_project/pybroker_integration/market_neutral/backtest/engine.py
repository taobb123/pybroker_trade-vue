# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np
import pandas as pd

from market_neutral.config import MNConfig
from market_neutral.portfolio.long_short_index import (
    build_target_weights,
    select_long_short,
)


def _close_on(
    bars: Dict[str, pd.DataFrame],
    symbol: str,
    dt: pd.Timestamp,
) -> float:
    df = bars.get(symbol)
    if df is None or df.empty:
        return float("nan")
    sub = df[df["date"] <= pd.Timestamp(dt)]
    if sub.empty:
        return float("nan")
    return float(sub.iloc[-1]["close"])


def _leg_return(
    weights: Dict[str, float],
    prev_px: Dict[str, float],
    bars: Dict[str, pd.DataFrame],
    dt: pd.Timestamp,
) -> Tuple[float, Dict[str, float]]:
    """按权重汇总收益；更新 prev_px。权重可正可负。"""
    ret = 0.0
    w_abs = 0.0
    new_px = dict(prev_px)
    for s, w in weights.items():
        px0 = prev_px.get(s, float("nan"))
        px1 = _close_on(bars, s, dt)
        if px0 == px0 and px0 > 0 and px1 == px1 and px1 > 0:
            ret += float(w) * (px1 / px0 - 1.0)
            w_abs += abs(float(w))
            new_px[s] = px1
    return ret, new_px


def run_variant_backtest(
    *,
    variant: str,
    factor_panel: pd.DataFrame,
    bars_by_symbol: Dict[str, pd.DataFrame],
    index_df: pd.DataFrame,
    calendar: Sequence[pd.Timestamp],
    rebal_dates: Sequence[pd.Timestamp],
    cfg: MNConfig,
    long_only: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    """
    个股多空：因子前 quantile 做多、后 quantile 做空（多头名义=+1，空头=-1）。
    日收益 = 多头组合收益 + 空头组合收益（资金中性、毛敞口约 2x）。
    long_only=True：只持有前分位多头，不做空。
    始终记录 long_ret / short_ret，便于拆分贡献。
    """
    v = str(variant).upper()
    cal = [pd.Timestamp(d).normalize() for d in calendar]
    rebal_set = {pd.Timestamp(d).normalize() for d in rebal_dates}
    if not cal:
        empty = pd.DataFrame()
        return empty, empty, empty, {}

    factor_dates = set()
    if factor_panel is not None and not factor_panel.empty:
        factor_dates = set(pd.to_datetime(factor_panel["date"]).dt.normalize())

    equity = float(cfg.initial_cash)
    equity_long_book = float(cfg.initial_cash)
    equity_short_book = float(cfg.initial_cash)
    long_w: Dict[str, float] = {}
    short_w: Dict[str, float] = {}
    equity_rows: List[dict] = []
    rebal_rows: List[dict] = []
    holdings_latest = pd.DataFrame()
    prev_px: Dict[str, float] = {}

    panel = factor_panel.copy() if factor_panel is not None else pd.DataFrame()
    if not panel.empty:
        panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()

    q = float(getattr(cfg, "quantile", 0.10) or 0.10)

    for i, dt in enumerate(cal):
        if dt in rebal_set and (not factor_dates or dt in factor_dates):
            snap = panel[panel["date"] == dt] if not panel.empty else pd.DataFrame()
            longs, shorts, _note = select_long_short(snap, v, quantile=q)
            targets = build_target_weights(longs, shorts)
            long_w = {
                t["symbol"]: float(t["weight"])
                for t in targets
                if t.get("side") == "long"
            }
            short_w = {
                t["symbol"]: float(t["weight"])
                for t in targets
                if t.get("side") == "short"
            }
            if long_only:
                short_w = {}
            for t in targets:
                if long_only and t.get("side") != "long":
                    continue
                rebal_rows.append(
                    {
                        "date": dt.strftime("%Y-%m-%d"),
                        "variant": v + ("_L" if long_only else ""),
                        "symbol": t["symbol"],
                        "name": t.get("name") or "",
                        "weight": t["weight"],
                        "state": t.get("state") or "",
                        "state_code": t.get("state_code") or "",
                        "upside": t.get("upside"),
                        "fair_price": t.get("fair_price"),
                        "close": t.get("close"),
                        "factor": t.get("factor"),
                        "side": t.get("side"),
                    }
                )
            holdings_latest = pd.DataFrame(
                [
                    r
                    for r in rebal_rows
                    if r["date"] == dt.strftime("%Y-%m-%d")
                ]
            )
            # 调仓成本：多空约 4 次，仅多头约 2 次
            if long_w or short_w:
                mult = 2.0 if long_only else 4.0
                equity *= 1.0 - mult * float(cfg.commission_rate)
                equity_long_book *= 1.0 - 2.0 * float(cfg.commission_rate)
                if not long_only:
                    equity_short_book *= 1.0 - 2.0 * float(cfg.commission_rate)
            prev_px = {}
            for s in set(long_w) | set(short_w):
                prev_px[s] = _close_on(bars_by_symbol, s, dt)

        long_ret = 0.0
        short_ret = 0.0
        if i > 0 and (long_w or short_w):
            long_ret, prev_px = _leg_return(long_w, prev_px, bars_by_symbol, dt)
            if short_w:
                short_ret, prev_px = _leg_return(short_w, prev_px, bars_by_symbol, dt)
        day_ret = long_ret + short_ret

        equity *= 1.0 + day_ret
        equity_long_book *= 1.0 + long_ret
        equity_short_book *= 1.0 + short_ret
        out_v = (v + "_L") if long_only else v
        equity_rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "variant": out_v,
                "equity": equity,
                "day_return": day_ret,
                "long_ret": long_ret,
                "short_ret": short_ret,
                "equity_long": equity_long_book,
                "equity_short": equity_short_book,
                "n_long": len(long_w),
                "n_short": len(short_w),
            }
        )

    equity_df = pd.DataFrame(equity_rows)
    rebal_df = pd.DataFrame(rebal_rows)
    metrics = compute_metrics(equity_df, cfg.initial_cash)
    metrics["variant"] = (v + "_L") if long_only else v
    metrics["long_only"] = bool(long_only)
    return equity_df, rebal_df, holdings_latest, metrics


def compute_metrics(equity_df: pd.DataFrame, initial_cash: float) -> dict:
    if equity_df is None or equity_df.empty:
        return {
            "annual_return": 0.0,
            "max_drawdown": 0.0,
            "sharpe": 0.0,
            "total_return": 0.0,
            "month_win_rate": 0.0,
            "avg_day_return": 0.0,
            "long_total_return": 0.0,
            "short_total_return": 0.0,
            "long_month_win_rate": 0.0,
            "short_month_win_rate": 0.0,
            "long_contrib_share": 0.0,
        }
    eq = equity_df.copy()
    eq["date"] = pd.to_datetime(eq["date"])
    eq = eq.sort_values("date")
    rets = pd.to_numeric(eq["day_return"], errors="coerce").fillna(0.0)
    total_ret = float(eq["equity"].iloc[-1] / float(initial_cash) - 1.0)
    n = max(1, len(eq))
    years = n / 252.0
    annual = (1.0 + total_ret) ** (1.0 / years) - 1.0 if years > 0 else 0.0
    cum = (1.0 + rets).cumprod()
    peak = cum.cummax()
    dd = cum / peak - 1.0
    mdd = float(dd.min()) if len(dd) else 0.0
    vol = float(rets.std(ddof=0)) * np.sqrt(252) if len(rets) > 1 else 0.0
    sharpe = float(annual / vol) if vol > 1e-12 else 0.0
    eq["ym"] = eq["date"].dt.to_period("M")
    month_ret = eq.groupby("ym")["day_return"].apply(lambda x: float((1 + x).prod() - 1))
    win = float((month_ret > 0).mean()) if len(month_ret) else 0.0

    long_total = 0.0
    short_total = 0.0
    long_mwin = 0.0
    short_mwin = 0.0
    contrib_share = 0.0
    if "long_ret" in eq.columns:
        lr = pd.to_numeric(eq["long_ret"], errors="coerce").fillna(0.0)
        long_total = float((1.0 + lr).prod() - 1.0)
        eq["_lr"] = lr
        lm = eq.groupby("ym")["_lr"].apply(lambda x: float((1 + x).prod() - 1))
        long_mwin = float((lm > 0).mean()) if len(lm) else 0.0
    if "short_ret" in eq.columns:
        sr = pd.to_numeric(eq["short_ret"], errors="coerce").fillna(0.0)
        short_total = float((1.0 + sr).prod() - 1.0)
        eq["_sr"] = sr
        sm = eq.groupby("ym")["_sr"].apply(lambda x: float((1 + x).prod() - 1))
        short_mwin = float((sm > 0).mean()) if len(sm) else 0.0
    # 贡献份额：多头累计收益 / (|多|+|空|)，正=多头主导赚钱侧
    abs_sum = abs(long_total) + abs(short_total)
    if abs_sum > 1e-12:
        contrib_share = float(long_total / abs_sum)

    return {
        "annual_return": annual,
        "max_drawdown": mdd,
        "sharpe": sharpe,
        "total_return": total_ret,
        "month_win_rate": win,
        "avg_day_return": float(rets.mean()) if len(rets) else 0.0,
        "trade_days": int(n),
        "long_total_return": long_total,
        "short_total_return": short_total,
        "long_month_win_rate": long_mwin,
        "short_month_win_rate": short_mwin,
        "long_contrib_share": contrib_share,
    }


def run_all_variants(
    *,
    factor_panel: pd.DataFrame,
    bars_by_symbol: Dict[str, pd.DataFrame],
    index_df: pd.DataFrame,
    calendar: Sequence[pd.Timestamp],
    rebal_by_variant: Dict[str, Sequence[pd.Timestamp]],
    cfg: MNConfig,
) -> dict:
    """
    factor_panel: 已对齐的多因子截面（含 pattern/upside/company_q/mud_*）。
    rebal_by_variant: 各组自己的调仓日（Q 可为月/季）。
    """
    from market_neutral.factors.rank_ic import compute_rank_ic

    FACTOR_COL = {
        "A": "pattern_factor",
        "B": "upside",
        "C": "composite_ac",
        "Q": "company_q",
        "M+": "mud_plus",
        "M-": "mud_minus",
    }
    results = {}
    panel = factor_panel.copy() if factor_panel is not None else pd.DataFrame()
    if not panel.empty:
        panel["date"] = pd.to_datetime(panel["date"]).dt.normalize()
        if "pattern_factor" not in panel.columns:
            from market_neutral.portfolio.long_short_index import pattern_factor_score

            panel["pattern_factor"] = pattern_factor_score(panel)
        if "composite_ac" not in panel.columns and "upside" in panel.columns:
            p_pct = panel["pattern_factor"].rank(method="average", pct=True)
            v_pct = pd.to_numeric(panel["upside"], errors="coerce").rank(
                method="average", pct=True
            )
            panel["composite_ac"] = np.where(
                pd.to_numeric(panel["upside"], errors="coerce").notna(),
                0.5 * p_pct + 0.5 * v_pct,
                p_pct,
            )

    for v in cfg.variants:
        key = str(v).upper().replace("＋", "+").replace("－", "-")
        if key in ("MPLUS", "M_PLUS"):
            key = "M+"
        if key in ("MMINUS", "M_MINUS"):
            key = "M-"
        rebal = list(rebal_by_variant.get(key) or rebal_by_variant.get(v) or [])
        eq, reb, hold, met = run_variant_backtest(
            variant=key,
            factor_panel=panel,
            bars_by_symbol=bars_by_symbol,
            index_df=index_df,
            calendar=calendar,
            rebal_dates=rebal,
            cfg=cfg,
            long_only=False,
        )
        fcol = FACTOR_COL.get(key, "upside")
        fwd = (
            int(cfg.ic_forward_days_q)
            if key == "Q"
            else int(cfg.ic_forward_days)
        )
        ic_info = compute_rank_ic(
            panel,
            bars_by_symbol,
            factor_col=fcol if fcol in panel.columns else "upside",
            rebal_dates=rebal,
            forward_days=fwd,
        )
        met = dict(met)
        met.update(ic_info)
        met["rebalance_freq"] = cfg.q_rebalance if key == "Q" else cfg.rebalance
        results[key] = {
            "equity": eq,
            "rebalance": reb,
            "holdings": hold,
            "metrics": met,
            "factor": panel,
        }

        # 仅多头对照：服务无法做空的买入决策
        eq_l, reb_l, hold_l, met_l = run_variant_backtest(
            variant=key,
            factor_panel=panel,
            bars_by_symbol=bars_by_symbol,
            index_df=index_df,
            calendar=calendar,
            rebal_dates=rebal,
            cfg=cfg,
            long_only=True,
        )
        met_l = dict(met_l)
        met_l["rank_ic"] = met.get("rank_ic")
        met_l["icir"] = met.get("icir")
        met_l["ic_count"] = met.get("ic_count", 0)
        met_l["forward_days"] = met.get("forward_days")
        met_l["factor_col"] = met.get("factor_col")
        met_l["rebalance_freq"] = met["rebalance_freq"]
        results[f"{key}_L"] = {
            "equity": eq_l,
            "rebalance": reb_l,
            "holdings": hold_l,
            "metrics": met_l,
            "factor": panel,
        }
    return results


def build_aligned_factor_panel(
    pattern_panel: pd.DataFrame,
    valuation_panel: pd.DataFrame,
    mud_panel: pd.DataFrame,
    q_panel: pd.DataFrame,
    all_rebal_dates: Sequence[pd.Timestamp],
) -> pd.DataFrame:
    """合并形态/PE/MUD/Q 到统一调仓日截面。"""
    base = _align_valuation_to_rebalance(pattern_panel, valuation_panel, all_rebal_dates)
    if base is None or base.empty:
        # 尝试用 mud 做底
        if mud_panel is not None and not mud_panel.empty:
            base = mud_panel.copy()
            base["date"] = pd.to_datetime(base["date"]).dt.normalize()
        else:
            return pd.DataFrame()
    base["date"] = pd.to_datetime(base["date"]).dt.normalize()
    base["symbol"] = base["symbol"].astype(str).str.zfill(6)

    if mud_panel is not None and not mud_panel.empty:
        m = mud_panel.copy()
        m["date"] = pd.to_datetime(m["date"]).dt.normalize()
        m["symbol"] = m["symbol"].astype(str).str.zfill(6)
        cols = [c for c in ("mud_plus", "mud_minus", "r60", "r20", "vol_ratio") if c in m.columns]
        base = base.merge(m[["date", "symbol"] + cols], on=["date", "symbol"], how="outer")

    if q_panel is not None and not q_panel.empty:
        q = q_panel.copy()
        q["date"] = pd.to_datetime(q["date"]).dt.normalize()
        q["symbol"] = q["symbol"].astype(str).str.zfill(6)
        cols = [c for c in ("company_q", "roe", "ocf_to_or") if c in q.columns]
        # Q 调仓日可能是月/季；asof 到 base 的每个 date
        q_rows = []
        for dt, g in base.groupby("date"):
            dt = pd.Timestamp(dt).normalize()
            sub = q[q["date"] <= dt]
            if sub.empty:
                gg = g.copy()
                for c in cols:
                    gg[c] = np.nan
                q_rows.append(gg)
                continue
            last = sub["date"].max()
            day_q = sub[sub["date"] == last][["symbol"] + cols]
            q_rows.append(g.merge(day_q, on="symbol", how="left"))
        base = pd.concat(q_rows, ignore_index=True) if q_rows else base

    if "stock_name" in base.columns:
        base["stock_name"] = base["stock_name"].fillna("")
    return base


# 保留旧签名兼容
def run_all_variants_legacy(
    *,
    pattern_panel: pd.DataFrame,
    valuation_panel: pd.DataFrame,
    bars_by_symbol: Dict[str, pd.DataFrame],
    index_df: pd.DataFrame,
    calendar: Sequence[pd.Timestamp],
    rebal_dates: Sequence[pd.Timestamp],
    cfg: MNConfig,
) -> dict:
    factor = _align_valuation_to_rebalance(pattern_panel, valuation_panel, rebal_dates)
    return run_all_variants(
        factor_panel=factor,
        bars_by_symbol=bars_by_symbol,
        index_df=index_df,
        calendar=calendar,
        rebal_by_variant={str(v): rebal_dates for v in cfg.variants},
        cfg=cfg,
    )


def _align_valuation_to_rebalance(
    pattern: pd.DataFrame,
    valuation: pd.DataFrame,
    rebal_dates: Sequence[pd.Timestamp],
) -> pd.DataFrame:
    """每个调仓日：形态截面 left join 当日或之前最近估值。"""
    if pattern is None or pattern.empty:
        v = valuation.copy() if valuation is not None else pd.DataFrame()
        if v.empty:
            return pd.DataFrame()
        v["date"] = pd.to_datetime(v["date"]).dt.normalize()
        rows = []
        for dt in rebal_dates:
            dt = pd.Timestamp(dt).normalize()
            sub = v[v["date"] <= dt]
            if sub.empty:
                continue
            last = sub["date"].max()
            day = sub[sub["date"] == last].copy()
            day["date"] = dt
            day["pattern_ok"] = False
            day["state_code"] = ""
            day["state"] = ""
            day["score"] = 0.0
            day["entry"] = False
            day["stock_name"] = day.get("stock_name", "")
            rows.append(day)
        return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()

    p = pattern.copy()
    p["date"] = pd.to_datetime(p["date"]).dt.normalize()
    p["symbol"] = p["symbol"].astype(str).str.zfill(6)
    if valuation is None or valuation.empty:
        return p
    v = valuation.copy()
    v["date"] = pd.to_datetime(v["date"]).dt.normalize()
    v["symbol"] = v["symbol"].astype(str).str.zfill(6)
    v_cols = [
        c
        for c in (
            "pe_ttm",
            "pb",
            "fair_price",
            "upside",
            "upside_raw",
            "undervalued",
            "pe_ref",
            "industry",
            "close",
        )
        if c in v.columns
    ]

    out_rows = []
    for dt, g in p.groupby("date"):
        dt = pd.Timestamp(dt).normalize()
        sub_v = v[v["date"] <= dt]
        if sub_v.empty:
            gg = g.copy()
            for c in v_cols:
                gg[c] = np.nan if c != "undervalued" else False
            out_rows.append(gg)
            continue
        last = sub_v["date"].max()
        day_v = sub_v[sub_v["date"] == last][["symbol"] + v_cols].copy()
        if "close" in day_v.columns and "close" in g.columns:
            day_v = day_v.rename(columns={"close": "close_basic"})
            use_cols = [c for c in day_v.columns if c != "symbol"]
        else:
            use_cols = v_cols
        merged = g.merge(day_v[["symbol"] + use_cols], on="symbol", how="left")
        if "close_basic" in merged.columns and "close" not in merged.columns:
            merged["close"] = merged["close_basic"]
        if "undervalued" in merged.columns:
            u = merged["undervalued"]
            merged["undervalued"] = u.where(u.notna(), False).map(bool)
        if "pattern_ok" in merged.columns:
            pk = merged["pattern_ok"]
            merged["pattern_ok"] = pk.where(pk.notna(), False).map(bool)
        out_rows.append(merged)
    return pd.concat(out_rows, ignore_index=True) if out_rows else p
