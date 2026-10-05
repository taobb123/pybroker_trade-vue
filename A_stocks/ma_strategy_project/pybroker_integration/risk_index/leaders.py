# -*- coding: utf-8 -*-
"""自选暴露清单：每一列取暴露度最大的一只股票。"""
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


def load_radar_risk_leaders(path: Path | None = None) -> list[dict]:
    return column_max_exposures(_read_exposure(path))


def load_risk_tags(path: Path | None = None) -> dict[str, list[dict]]:
    return risk_tags_by_symbol(_read_exposure(path))
