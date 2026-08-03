#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最优 BASE_COST 表：按股票代码 upsert，每个代码只保留最新一次搜索结果。
表文件仅由脚本写入/更新；删除行请用户在本机手动编辑 CSV。
"""

from __future__ import annotations

import os
from datetime import datetime
import pandas as pd

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OPTIMAL_BASE_CSV = os.path.join(SCRIPT_DIR, "optimal_base_cost.csv")

COLUMNS = [
    "symbol",
    "stock_name",
    "optimal_base_cost",
    "start_date",
    "end_date",
    "return_pct",
    "updated_at",
]


def _read_optimal_csv(path: str) -> pd.DataFrame:
    """兼容 UTF-8（脚本写入）与 GBK（Excel 另存常见）。"""
    last: UnicodeDecodeError | None = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "cp936"):
        try:
            return pd.read_csv(path, dtype=str, encoding=enc)
        except UnicodeDecodeError as e:
            last = e
            continue
    if last is not None:
        raise last
    raise OSError(f"无法读取 CSV: {path}")


def ensure_table_exists(path: str = DEFAULT_OPTIMAL_BASE_CSV) -> None:
    if not os.path.isfile(path):
        pd.DataFrame(columns=COLUMNS).to_csv(path, index=False, encoding="utf-8-sig")


def upsert_optimal_base(
    symbol: str,
    optimal_base_cost: float,
    start_date: str,
    end_date: str,
    return_pct: float,
    *,
    stock_name: str = "",
    path: str = DEFAULT_OPTIMAL_BASE_CSV,
) -> None:
    """同一 symbol 只保留一行：先删旧行再追加新行。"""
    ensure_table_exists(path)
    sym = "".join(filter(str.isdigit, str(symbol))).zfill(6)
    df = _read_optimal_csv(path)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    df = df[COLUMNS]
    df = df[df["symbol"].astype(str).str.strip().str.zfill(6) != sym]
    name = (stock_name or "").strip()
    new_row = pd.DataFrame(
        [
            {
                "symbol": sym,
                "stock_name": name,
                "optimal_base_cost": f"{float(optimal_base_cost):.2f}",
                "start_date": str(start_date).strip(),
                "end_date": str(end_date).strip(),
                "return_pct": f"{float(return_pct):.6f}",
                "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        ]
    )
    out = pd.concat([df, new_row], ignore_index=True)
    out.to_csv(path, index=False, encoding="utf-8-sig")


def load_optimal_base_table(path: str = DEFAULT_OPTIMAL_BASE_CSV) -> pd.DataFrame:
    if not os.path.isfile(path):
        return pd.DataFrame(columns=COLUMNS)
    df = _read_optimal_csv(path)
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = pd.NA
    return df[COLUMNS]
