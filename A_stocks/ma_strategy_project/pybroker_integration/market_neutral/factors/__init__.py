# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import pandas as pd

from market_neutral.config import PATTERN_LONG_STATES, MNConfig, ensure_sys_path
from market_neutral.data import PoolMember

__all__ = [
    "load_latest_pattern_scan",
    "evaluate_pattern_panel",
    "overlay_latest_scan",
]


def load_latest_pattern_scan(path: str) -> pd.DataFrame:
    if not path or not __import__("os").path.isfile(path):
        return pd.DataFrame()
    df = pd.read_csv(path, encoding="utf-8-sig")
    if df.empty:
        return df
    df = df.copy()
    df["symbol"] = (
        df["symbol"]
        .astype(str)
        .map(lambda x: "".join(c for c in x if c.isdigit()).zfill(6))
    )
    return df


def evaluate_pattern_panel(
    members: Sequence[PoolMember],
    bars_by_symbol: Dict[str, pd.DataFrame],
    rebalance_dates: Sequence[pd.Timestamp],
    cfg: MNConfig,
) -> pd.DataFrame:
    """
    在每个调仓日对观察池成员复用 fetch_pattern_entry 形态评估。
    若 cfg.use_watch_archive：按日取 ≤该日 归档池；否则用传入 members。
    """
    ensure_sys_path()
    from fetch_pattern_entry import (
        PATTERN_ENTRY_CONFIG,
        _infer_anchor_from_ohlc,
        get_pattern_for_combo,
        state_label_zh,
    )
    from market_neutral.data.pool_archive import members_asof

    pcfg = dict(PATTERN_ENTRY_CONFIG)
    fallback = list(members)
    rows: List[dict] = []
    n_dates = len(rebalance_dates)
    for di, dt in enumerate(rebalance_dates):
        end_s = pd.Timestamp(dt).strftime("%Y-%m-%d")
        if cfg.use_watch_archive:
            day_members, _w, note = members_asof(
                end_s,
                cfg.combo_ids,
                root=cfg.watch_archive_dir,
                fallback_members=fallback,
            )
        else:
            day_members, note = fallback, "当前池"
        if (di + 1) % 5 == 0 or di == 0 or di + 1 == n_dates:
            print(
                f"  [pattern] 调仓日 {di + 1}/{n_dates} {end_s} "
                f"池={len(day_members)} ({note})",
                flush=True,
            )
        for m in day_members:
            ohlc_full = bars_by_symbol.get(m.symbol)
            if ohlc_full is None or ohlc_full.empty:
                continue
            ohlc = ohlc_full[ohlc_full["date"] <= pd.Timestamp(dt)].copy()
            if len(ohlc) < int(pcfg.get("min_bars", 40)):
                continue
            try:
                anchor = _infer_anchor_from_ohlc(
                    ohlc,
                    symbol=m.symbol,
                    stock_name=m.stock_name or "",
                    combo_id=int(m.combo_id),
                )
                if anchor is None:
                    continue
                pattern = get_pattern_for_combo(int(m.combo_id))
                res = pattern.evaluate(ohlc, anchor, end_date=end_s, cfg=pcfg)
            except Exception:
                continue
            rows.append(
                {
                    "date": pd.Timestamp(dt).normalize(),
                    "symbol": m.symbol,
                    "combo_id": int(m.combo_id),
                    "state_code": res.state,
                    "state": state_label_zh(res.state),
                    "score": float(res.score),
                    "entry": bool(res.entry),
                    "close": float(res.close) if res.close == res.close else float("nan"),
                    "stock_name": res.stock_name or m.stock_name or "",
                    "pattern_ok": res.state in PATTERN_LONG_STATES,
                }
            )
    if not rows:
        return pd.DataFrame(
            columns=[
                "date",
                "symbol",
                "combo_id",
                "state_code",
                "state",
                "score",
                "entry",
                "close",
                "stock_name",
                "pattern_ok",
            ]
        )
    df = pd.DataFrame(rows)
    df = df.sort_values(
        ["date", "symbol", "pattern_ok", "score"], ascending=[True, True, False, False]
    )
    df = df.drop_duplicates(subset=["date", "symbol"], keep="first")
    return df.reset_index(drop=True)


def overlay_latest_scan(
    panel: pd.DataFrame,
    scan_csv: str,
    asof: Optional[pd.Timestamp] = None,
) -> pd.DataFrame:
    """若存在最新 pattern_entry_scan.csv，用其状态覆盖最接近的调仓日截面。"""
    scan = load_latest_pattern_scan(scan_csv)
    if scan.empty or panel.empty or "state_code" not in scan.columns:
        return panel
    if asof is None:
        asof = pd.Timestamp(panel["date"].max())
    asof = pd.Timestamp(asof).normalize()
    # 找 panel 中 <= asof 的最近日期
    dates = sorted(pd.to_datetime(panel["date"]).dt.normalize().unique())
    cand = [d for d in dates if d <= asof]
    if not cand:
        return panel
    target = cand[-1]
    out = panel.copy()
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()
    mask = out["date"] == target
    scan_map = {
        str(r.symbol).zfill(6): r
        for r in scan.itertuples(index=False)
    }
    for idx in out.loc[mask].index:
        sym = str(out.at[idx, "symbol"]).zfill(6)
        if sym not in scan_map:
            continue
        r = scan_map[sym]
        sc = str(getattr(r, "state_code", "") or "")
        out.at[idx, "state_code"] = sc
        out.at[idx, "state"] = str(getattr(r, "state", "") or "")
        out.at[idx, "score"] = float(getattr(r, "score", 0) or 0)
        out.at[idx, "entry"] = bool(getattr(r, "entry", False))
        out.at[idx, "pattern_ok"] = sc in PATTERN_LONG_STATES
        name = str(getattr(r, "stock_name", "") or "")
        if name:
            out.at[idx, "stock_name"] = name
    return out
