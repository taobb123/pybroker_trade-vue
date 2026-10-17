# -*- coding: utf-8 -*-
"""收益归因 API。不注册进日常工作流步骤，不改观察池。"""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from capm.service import sleeves_payload, stocks_payload

router = APIRouter(prefix="/api/capm", tags=["capm"])


class StockBody(BaseModel):
    universe: str = Field(default="watch46")
    symbols: str = Field(default="")
    refresh: bool = Field(default=False)


@router.get("/sleeves")
def sleeves() -> dict:
    return sleeves_payload()


@router.get("/stocks")
def stocks(
    universe: str = Query(default="watch46"),
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
    )
