# -*- coding: utf-8 -*-
"""从市场中性截面读取已有 mud_plus，并用系统日线补 T+3。只读截面，不写日常链文件。"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Mapping

import pandas as pd

from risk_return.contract import HOLD_TRADING_DAYS, SNAPSHOT_RELATIVE
from risk_return.samples import assign_deciles, forward_return_exact

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT_PATH = PROJECT_ROOT / SNAPSHOT_RELATIVE

BarsFetcher = Callable[[list[str], str, str], Mapping[str, pd.DataFrame]]


def load_mplus_panel(path: Path | None = None) -> pd.DataFrame:
    """读取截面里的 date、symbol、mud_plus。没有 mud_plus 的行去掉。"""
    dest = Path(path or DEFAULT_SNAPSHOT_PATH)
    if not dest.is_file():
        raise FileNotFoundError(str(dest))
    frame = pd.read_csv(dest, dtype={"symbol": str}, usecols=["date", "symbol", "mud_plus"])
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["mud_plus"] = pd.to_numeric(frame["mud_plus"], errors="coerce")
    frame["symbol"] = (
        frame["symbol"].astype(str).str.replace(r"\D", "", regex=True).str.zfill(6).str[-6:]
    )
    frame = frame.dropna(subset=["date", "mud_plus"])
    frame = frame[frame["symbol"].str.len() == 6]
    return frame[["date", "symbol", "mud_plus"]].reset_index(drop=True)


def _prepare_bars(bars_by_symbol: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    prepared: dict[str, pd.DataFrame] = {}
    for sym, df in bars_by_symbol.items():
        if df is None or df.empty or "date" not in df.columns or "close" not in df.columns:
            continue
        piece = df.copy()
        piece["date"] = pd.to_datetime(piece["date"], errors="coerce").dt.normalize()
        piece["close"] = pd.to_numeric(piece["close"], errors="coerce")
        piece = piece.dropna(subset=["date", "close"])
        piece = piece[piece["close"] > 0]
        if piece.empty:
            continue
        code = "".join(ch for ch in str(sym) if ch.isdigit()).zfill(6)[-6:]
        prepared[code] = piece.sort_values("date").drop_duplicates("date", keep="last")
    return prepared


def samples_from_mplus_panel(
    panel: pd.DataFrame,
    bars_by_symbol: Mapping[str, pd.DataFrame],
    *,
    hold_days: int = HOLD_TRADING_DAYS,
) -> pd.DataFrame:
    """按截面当日 mud_plus 分十分位，再配上各标的自己的 T+3 收益。"""
    columns = ["date", "symbol", "mud_plus", "decile", "fwd_ret"]
    if panel is None or panel.empty:
        return pd.DataFrame(columns=columns)
    ranked = assign_deciles(panel)
    bars = _prepare_bars(bars_by_symbol)
    fwd: list[float] = []
    for row in ranked.itertuples(index=False):
        fwd.append(forward_return_exact(bars.get(str(row.symbol)), row.date, hold_days))
    ranked = ranked.copy()
    ranked["fwd_ret"] = fwd
    ranked = ranked.dropna(subset=["decile", "fwd_ret"])
    if ranked.empty:
        return pd.DataFrame(columns=columns)
    ranked["decile"] = ranked["decile"].astype(int)
    return ranked[columns].reset_index(drop=True)


def bar_window(panel: pd.DataFrame) -> tuple[str, str, list[str]]:
    start = pd.Timestamp(panel["date"].min()).strftime("%Y-%m-%d")
    end = (pd.Timestamp(panel["date"].max()) + pd.Timedelta(days=20)).strftime("%Y-%m-%d")
    symbols = sorted(set(panel["symbol"].astype(str)))
    return start, end, symbols


def fetch_system_bars(panel: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """走市场中性已经在用的日线读取。"""
    from market_neutral.data.prices import fetch_stock_bars

    start, end, symbols = bar_window(panel)
    return fetch_stock_bars(symbols, start, end)
