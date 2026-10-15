# -*- coding: utf-8 -*-
"""自选暴露清单：按当前名单接上全市场暴露，再标出大于 0 的风险。"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

EXPOSURE_COLUMNS = (
    "波动率",
    "动能",
    "流动性",
    "成长性",
    "价值",
    "盈利波动率",
    "财务杠杆",
)
DEFAULT_PATH = Path(__file__).resolve().parent / "output" / "radar_exposure.csv"
UNIVERSE_PATH = Path(__file__).resolve().parent / "output" / "universe_exposure.csv"
RISK_LABELS = (
    ("波动率", "波动风险"),
    ("流动性", "流动风险"),
    ("价值", "价值风险"),
    ("盈利波动率", "盈利波动风险"),
    ("财务杠杆", "杠杆风险"),
)


def column_max_exposures(frame: pd.DataFrame) -> list[dict]:
    """同一股票出现在多个分组时只保留一行，再按列取最大暴露。"""
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return []
    work = frame.copy()
    work["symbol"] = work["symbol"].astype(str).str[-6:].str.zfill(6)
    work = work.drop_duplicates("symbol", keep="first")
    leaders: list[dict] = []
    for column in EXPOSURE_COLUMNS:
        if column not in work.columns:
            continue
        values = pd.to_numeric(work[column], errors="coerce")
        if not values.notna().any():
            continue
        idx = values.idxmax()
        row = work.loc[idx]
        leaders.append(
            {
                "factor": column,
                "symbol": str(row["symbol"]),
                "name": str(row.get("name") or ""),
                "group": str(row.get("group") or ""),
                "exposure": round(float(values.loc[idx]), 2),
            }
        )
    return leaders


def risk_tags_by_symbol(frame: pd.DataFrame) -> dict[str, list[dict]]:
    """每只股票标出大于 0 的风险。该列最大且大于 0 时，标记 maximum。"""
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return {}
    work = frame.copy()
    work["symbol"] = work["symbol"].astype(str).str[-6:].str.zfill(6)
    work = work.drop_duplicates("symbol", keep="first").set_index("symbol", drop=False)
    maxima: dict[str, str] = {}
    numbers: dict[str, pd.Series] = {}
    for column, _label in RISK_LABELS:
        if column not in work.columns:
            continue
        values = pd.to_numeric(work[column], errors="coerce")
        numbers[column] = values
        if not values.notna().any():
            continue
        top = float(values.max())
        if top > 0:
            maxima[column] = str(values.idxmax())
    tags: dict[str, list[dict]] = {}
    for symbol in work.index:
        row_tags: list[dict] = []
        for column, label in RISK_LABELS:
            values = numbers.get(column)
            if values is None or symbol not in values.index:
                continue
            exposure = values.loc[symbol]
            if pd.isna(exposure) or float(exposure) <= 0:
                continue
            row_tags.append(
                {
                    "label": label,
                    "exposure": round(float(exposure), 2),
                    "maximum": maxima.get(column) == symbol,
                }
            )
        tags[str(symbol)] = row_tags
    return tags


def _read_exposure(path: Path | None = None) -> pd.DataFrame:
    dest = path or DEFAULT_PATH
    if not dest.is_file():
        return pd.DataFrame()
    try:
        return pd.read_csv(dest, dtype={"symbol": str}, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def _symbol6(value: object) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[-6:].zfill(6)


def exposures_for_picks(
    picks: list[dict] | None,
    universe: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """当前自选左连接全市场暴露。名单里没有的股票不进入结果。"""
    rows: list[dict] = []
    for pick in picks or []:
        symbol = _symbol6(pick.get("symbol"))
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "name": str(pick.get("name") or ""),
                "group": str(pick.get("group") or ""),
                "rank": pick.get("rank"),
            }
        )
    columns = ["symbol", "name", "group", "rank", *EXPOSURE_COLUMNS]
    base = pd.DataFrame(rows)
    if base.empty:
        return pd.DataFrame(columns=columns)
    frame = universe if universe is not None else _read_exposure(UNIVERSE_PATH)
    if frame is None or frame.empty or "symbol" not in frame.columns:
        return base
    work = frame.copy()
    work["symbol"] = work["symbol"].map(_symbol6)
    keep = ["symbol", *[name for name in EXPOSURE_COLUMNS if name in work.columns]]
    work = work.loc[work["symbol"] != "", keep].drop_duplicates("symbol", keep="first")
    return base.merge(work, on="symbol", how="left")


def risk_tags_for_picks(
    picks: list[dict] | None,
    universe: pd.DataFrame | None = None,
) -> dict[str, list[dict]]:
    """只给当前自选打风险标签。「最大」在这批股票里比较。"""
    return risk_tags_by_symbol(exposures_for_picks(picks, universe))


def leaders_for_picks(
    picks: list[dict] | None,
    universe: pd.DataFrame | None = None,
) -> list[dict]:
    return column_max_exposures(exposures_for_picks(picks, universe))


def load_radar_risk_leaders(path: Path | None = None) -> list[dict]:
    return column_max_exposures(_read_exposure(path))


def load_risk_tags(path: Path | None = None) -> dict[str, list[dict]]:
    return risk_tags_by_symbol(_read_exposure(path))
