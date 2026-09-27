#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回测对比开关与年化冠军追加。

现有四组始终保留：2+3 的 Q、G，4+6 的 M+、G。
只有「打开回测」且仅多头年化报告未超过一个月时，才为每池再追加年化最高、且不在这四组里的因子。
"""

from __future__ import annotations

import calendar
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

_SCRIPT_DIR = Path(__file__).resolve().parent
SWITCH_PATH = _SCRIPT_DIR / "config" / "backtest_compare_switch.json"
COMPARE_CSV = _SCRIPT_DIR / "vp_combo_23_vs_46_long_annual.csv"
COMPARE_MD = _SCRIPT_DIR / "vp_combo_23_vs_46_long_annual.md"

BASE_FACTORS = {
    "23": frozenset({"Q", "G"}),
    "46": frozenset({"M+", "G"}),
}
POOL_ANNUAL_COL = {"23": "pool_23_annual", "46": "pool_46_annual"}
POOL_TAB = {"23": "2+3", "46": "4+6"}

# 已有雷达 Tab 不改名；追加因子用「因子·池」。
_BASE_TAB = {
    ("23", "Q"): "Q",
    ("23", "G"): "G·2+3",
    ("46", "M+"): "M加",
    ("46", "G"): "G·4+6",
}

# 追加因子的现成排名表。A·4+6 从形态建仓扫描按形态分排序，不在此列。
EXTRA_RANK_CSV = {
    ("23", "B"): _SCRIPT_DIR / "vp_combo_23_valuation_rank.csv",
    ("23", "M-"): _SCRIPT_DIR / "vp_combo_23_mminus_top.csv",
    ("46", "B"): _SCRIPT_DIR / "pattern_entry_valuation_rank.csv",
    ("46", "M-"): _SCRIPT_DIR / "pattern_entry_mminus_rank.csv",
    ("46", "Q"): _SCRIPT_DIR / "pattern_entry_q_rank.csv",
}
PATTERN_SCAN_CSV = _SCRIPT_DIR / "pattern_entry_scan.csv"


def canonical_factor(raw: Any) -> str:
    s = str(raw or "").strip().upper().replace("＋", "+").replace("－", "-")
    if s.endswith("_L"):
        s = s[:-2]
    return {
        "MPLUS": "M+",
        "M_PLUS": "M+",
        "MMINUS": "M-",
        "M_MINUS": "M-",
    }.get(s, s)


def tab_name(pool: str, factor: str) -> str:
    return _BASE_TAB.get((pool, factor), f"{factor}·{POOL_TAB[pool]}")


def read_switch(path: Path = SWITCH_PATH) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return bool(data.get("enabled"))


def write_switch(enabled: bool, path: Path = SWITCH_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"enabled": bool(enabled)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def plus_one_month(dt: datetime) -> datetime:
    year, month = dt.year, dt.month + 1
    if month > 12:
        year, month = year + 1, 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def report_is_expired(generated_at: Optional[datetime], now: Optional[datetime] = None) -> bool:
    if generated_at is None:
        return False
    now = now or datetime.now()
    return now > plus_one_month(generated_at)


def parse_generated_at(md_text: str) -> Optional[datetime]:
    for line in md_text.splitlines():
        if "生成时间" not in line:
            continue
        tail = line.split("：", 1)[-1].strip()
        for fmt, width in (("%Y-%m-%d %H:%M:%S", 19), ("%Y-%m-%d", 10)):
            try:
                return datetime.strptime(tail[:width], fmt)
            except ValueError:
                continue
    return None


def load_compare_rows(path: Path = COMPARE_CSV) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    for enc in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            with path.open(encoding=enc, newline="") as fh:
                return list(csv.DictReader(fh))
        except UnicodeDecodeError:
            continue
        except OSError:
            return []
    return []


def champion_factor(rows: list[dict[str, Any]], pool: str) -> Optional[str]:
    col = POOL_ANNUAL_COL[pool]
    best_factor: Optional[str] = None
    best_val: Optional[float] = None
    for row in rows:
        factor = canonical_factor(row.get("variant"))
        if not factor:
            continue
        try:
            val = float(row.get(col) or "")
        except (TypeError, ValueError):
            continue
        if best_val is None or val > best_val:
            best_val = val
            best_factor = factor
    return best_factor


def route_snapshot(
    *,
    now: Optional[datetime] = None,
    switch_on: Optional[bool] = None,
    rows: Optional[list[dict[str, Any]]] = None,
    generated_at: Optional[datetime] = None,
    md_path: Path = COMPARE_MD,
    csv_path: Path = COMPARE_CSV,
) -> dict[str, Any]:
    """决定年化追加是否生效，以及每池要多出来的因子。"""
    now = now or datetime.now()
    if switch_on is None:
        switch_on = read_switch()
    if rows is None:
        rows = load_compare_rows(csv_path)
    if generated_at is None and md_path.is_file():
        try:
            generated_at = parse_generated_at(md_path.read_text(encoding="utf-8"))
        except OSError:
            generated_at = None
    expired = report_is_expired(generated_at, now) if generated_at else False
    append = bool(switch_on) and bool(rows) and not expired
    extras: list[dict[str, str]] = []
    champions: dict[str, Optional[str]] = {}
    if append:
        for pool in ("23", "46"):
            factor = champion_factor(rows, pool)
            champions[pool] = factor
            if factor and factor not in BASE_FACTORS[pool]:
                extras.append(
                    {
                        "pool": pool,
                        "factor": factor,
                        "tab": tab_name(pool, factor),
                    }
                )
    else:
        for pool in ("23", "46"):
            champions[pool] = champion_factor(rows, pool) if rows else None
    return {
        "switch_on": bool(switch_on),
        "generated_at": generated_at.strftime("%Y-%m-%d %H:%M:%S") if generated_at else None,
        "expired": expired,
        "append": append,
        "champions": champions,
        "extras": extras,
        "groups": ["M加", "Q", "G·4+6", "G·2+3"] + [e["tab"] for e in extras],
    }


def expiry_hint(snapshot: dict[str, Any]) -> Optional[str]:
    if not snapshot.get("expired"):
        return None
    when = snapshot.get("generated_at") or "未知"
    return (
        f"回测对比报告已过期（生成于 {when}）。"
        "年化追加已停用，因子自选只保留 M加 / Q / G·4+6 / G·2+3。"
        "请在「回测对比」打开回测并重新运行，生成新表后再恢复追加。"
    )


def extra_rank_path(pool: str, factor: str) -> Optional[Path]:
    if pool == "46" and factor == "A":
        return PATTERN_SCAN_CSV if PATTERN_SCAN_CSV.is_file() else None
    path = EXTRA_RANK_CSV.get((pool, factor))
    if path is not None and path.is_file():
        return path
    return None
