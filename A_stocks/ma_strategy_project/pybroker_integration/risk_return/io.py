# -*- coding: utf-8 -*-
"""研究模块自己的读写。路径必须落在 risk_return 内，且不能占用日常链文件名。"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from risk_return.contract import PROTECTED_OUTPUT_NAMES

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_BARS_PATH = PACKAGE_ROOT / "input" / "bars.csv"
DEFAULT_OUTPUT_PATH = PACKAGE_ROOT / "output" / "latest.json"


def assert_research_path(path: Path) -> Path:
    dest = Path(path).resolve()
    if dest.name in PROTECTED_OUTPUT_NAMES:
        raise RuntimeError(f"拒绝写入日常链产物: {dest.name}")
    if "risk_return" not in dest.parts:
        raise RuntimeError("研究文件只能放在 risk_return 目录内")
    return dest


def write_json(report: dict, dest: Path) -> Path:
    path = assert_research_path(dest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def read_json(path: Path) -> dict | None:
    dest = assert_research_path(path)
    if not dest.is_file():
        return None
    return json.loads(dest.read_text(encoding="utf-8"))


def read_bars_csv(path: Path) -> dict[str, pd.DataFrame]:
    dest = assert_research_path(path)
    if dest.name != "bars.csv" or dest.parent.name != "input":
        raise RuntimeError("只读取 risk_return/input/bars.csv")
    if not dest.is_file():
        raise FileNotFoundError(str(dest))
    frame = pd.read_csv(dest)
    required = {"symbol", "date", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"bars.csv 缺少列: {', '.join(sorted(missing))}")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"])
    frame = frame[frame["close"] > 0]
    out: dict[str, pd.DataFrame] = {}
    for raw, grp in frame.groupby(frame["symbol"].astype(str)):
        digits = "".join(ch for ch in str(raw) if ch.isdigit())
        if not digits:
            continue
        code = digits.zfill(6)[-6:]
        piece = grp.sort_values("date").drop_duplicates("date", keep="last")
        out[code] = piece[["date", "close", "volume"]].reset_index(drop=True)
    if not out:
        raise ValueError("bars.csv 没有可用行情")
    return out
