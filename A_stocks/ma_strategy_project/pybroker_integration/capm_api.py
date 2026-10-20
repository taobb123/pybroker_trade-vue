# -*- coding: utf-8 -*-
"""收益归因 API。不注册进日常工作流步骤，不改观察池。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from capm.service import sleeves_payload, stocks_payload
from capm.sources import fetch_act_bars, fetch_benchmark, latest_trading_day

router = APIRouter(prefix="/api/capm", tags=["capm"])


class StockBody(BaseModel):
    universe: str = Field(default="vp6")
    symbols: str = Field(default="")
    refresh: bool = Field(default=False)


@router.get("/sleeves")
def sleeves() -> dict:
    return sleeves_payload()


@router.get("/stocks")
def stocks(
    universe: str = Query(default="vp6"),
    symbols: str = Query(default=""),
) -> dict:
    return stocks_payload(universe=universe, symbols=symbols, refresh=False)


@router.post("/stocks")
def stocks_refresh(body: StockBody | None = None) -> dict:
    params = body or StockBody()
    return stocks_payload(
        universe=params.universe,
        symbols=params.symbols,
        refresh=params.refresh,
        ohlc_fetcher=fetch_act_bars if params.refresh else None,
        session_end=latest_trading_day() if params.refresh else None,
        bench_fetcher=fetch_benchmark if params.refresh else None,
    )
