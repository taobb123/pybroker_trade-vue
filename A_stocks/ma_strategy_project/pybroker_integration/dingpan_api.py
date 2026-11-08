# -*- coding: utf-8 -*-
"""盯盘 API。不注册进日常工作流步骤，不改观察池。"""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel, Field

from capm.sources import OHLC_CACHE, fetch_act_bars, load_ohlc, parse_symbols, store_ohlc
from dingpan import reports_for_symbols

router = APIRouter(prefix="/api/dingpan", tags=["dingpan"])


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
    return {
        "items": reports_for_symbols(codes, bars),
        "truncated": truncated,
        "note": "",
    }
