# -*- coding: utf-8 -*-
"""M+ / T+3 风险收益研究 API。不注册进日常四步工作流。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from risk_return.contract import DEFAULT_N_PATHS, DEFAULT_N_TRADES, DEFAULT_SEED
from risk_return.service import (
    budget_payload,
    correlation_payload,
    copula_payload,
    walkforward_payload,
    latest_payload,
    regime_payload,
    run_payload,
)

router = APIRouter(prefix="/api/risk-return", tags=["risk-return"])


class RunBody(BaseModel):
    n_paths: int = Field(default=DEFAULT_N_PATHS, ge=100, le=20_000)
    n_trades: int = Field(default=DEFAULT_N_TRADES, ge=10, le=500)
    seed: int = Field(default=DEFAULT_SEED)


@router.get("/latest")
def latest() -> dict:
    return latest_payload()


@router.get("/correlation")
def correlation() -> dict:
    return correlation_payload()


@router.get("/regime")
def regime() -> dict:
    return regime_payload()


@router.get("/budget")
def budget() -> dict:
    return budget_payload()


@router.get("/walkforward")
def walkforward() -> dict:
    return walkforward_payload()


@router.get("/copula")
def copula() -> dict:
    return copula_payload()


@router.post("/run")
def run(body: RunBody | None = None) -> dict:
    params = body or RunBody()
    return run_payload(
        n_paths=params.n_paths,
        n_trades=params.n_trades,
        seed=params.seed,
    )
