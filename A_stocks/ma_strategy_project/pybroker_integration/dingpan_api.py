# -*- coding: utf-8 -*-
"""盯盘 API。不注册进日常工作流步骤，不改观察池。"""
from __future__ import annotations

import csv
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel, Field

from capm.sources import OHLC_CACHE, fetch_act_bars, load_ohlc, parse_symbols, store_ohlc
from dingpan import reports_for_symbols

router = APIRouter(prefix="/api/dingpan", tags=["dingpan"])

_NAME_CACHE: dict[str, str] = {}
_LOCAL_LOADED = False
_CODE_FIELDS = ("symbol", "代码", "股票代码", "ts_code")
_NAME_FIELDS = ("stock_name", "股票名称", "证券简称", "名称")


class DingpanBody(BaseModel):
    symbols: str = Field(default="")
    refresh: bool = Field(default=False)


@router.post("")
def run_dingpan(body: DingpanBody | None = None) -> dict:
    params = body or DingpanBody()
    codes, truncated = parse_symbols(params.symbols, limit=40)
    if not codes:
        return {"items": [], "truncated": False, "note": "观察池里没有股票"}
    if params.refresh:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=420)).strftime("%Y-%m-%d")
        fresh = fetch_act_bars(codes, start, end)
        if fresh is not None and not getattr(fresh, "empty", True):
            store_ohlc(fresh, OHLC_CACHE)
    bars = load_ohlc(set(codes), cache_path=OHLC_CACHE)
    items = reports_for_symbols(codes, bars)
    names = names_for(codes)
    for item in items:
        item["name"] = names.get(item.get("symbol") or "", "")
    return {
        "items": items,
        "truncated": truncated,
        "note": "",
    }


def _remember_name(code: str, name: str) -> None:
    text = str(name or "").strip()
    if not code or code in _NAME_CACHE:
        return
    if not text or text == code or text.lower() in {"nan", "none"}:
        return
    _NAME_CACHE[code] = text


def _code_of(raw: str) -> str:
    head = str(raw or "").split(".", 1)[0]
    digits = "".join(ch for ch in head if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else ""


def _read_csv_text(path: Path) -> str:
    for encoding in ("utf-8-sig", "gbk"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def _ingest_name_csv(path: Path) -> None:
    try:
        if path.stat().st_size > 3_000_000:
            return
    except OSError:
        return
    text = _read_csv_text(path)
    if not text:
        return
    reader = csv.DictReader(StringIO(text))
    fields = {str(name).strip(): name for name in (reader.fieldnames or []) if name}
    code_key = next((fields[key] for key in _CODE_FIELDS if key in fields), None)
    name_key = next((fields[key] for key in _NAME_FIELDS if key in fields), None)
    if not code_key or not name_key:
        return
    for row in reader:
        _remember_name(_code_of(row.get(code_key) or ""), row.get(name_key) or "")


def _load_local_names() -> None:
    global _LOCAL_LOADED
    if _LOCAL_LOADED:
        return
    _LOCAL_LOADED = True
    root = Path(__file__).resolve().parent
    for path in root.glob("*.csv"):
        _ingest_name_csv(path)


def names_for(codes: list[str]) -> dict[str, str]:
    """本地行情表里的简称优先；没有的再向行情接口要一次。"""
    _load_local_names()
    missing = [code for code in codes if code not in _NAME_CACHE]
    if missing:
        try:
            from stock_names import resolve_stock_names

            found = resolve_stock_names(missing)
        except Exception:
            found = {}
        for code in missing:
            _remember_name(code, str(found.get(code) or ""))
    return {code: _NAME_CACHE.get(code, "") for code in codes}
