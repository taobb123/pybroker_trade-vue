#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会员 / 配额 API（M2）。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_api import get_current_user
from membership_service import (
    add_bonus_runs,
    apply_membership,
    consume_run,
    get_quota_status,
)

router = APIRouter(tags=["membership"])


@router.get("/api/membership/me")
def membership_me(user: dict[str, Any] = Depends(get_current_user)):
    q = get_quota_status(user["id"])
    return {
        "ok": True,
        "plan": q["plan"],
        "expire_at": q["expire_at"],
        "quota": q,
    }


@router.get("/api/quota/today")
def quota_today(user: dict[str, Any] = Depends(get_current_user)):
    return {"ok": True, "quota": get_quota_status(user["id"])}


@router.post("/api/quota/consume")
def quota_consume(user: dict[str, Any] = Depends(get_current_user)):
    result = consume_run(user["id"])
    if not result["ok"]:
        code = 429 if result.get("code") == "rate_limit" else 402
        raise HTTPException(status_code=code, detail=result["reason"])
    return result


class SetFreeBody(BaseModel):
    confirm: bool = True


@router.post("/api/membership/set-free")
def set_free(body: SetFreeBody, user: dict[str, Any] = Depends(get_current_user)):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="需要 confirm=true")
    m = apply_membership(user["id"], "free", period_days=0)
    return {"ok": True, "membership": m, "quota": get_quota_status(user["id"])}


class BonusBody(BaseModel):
    n: int = Field(default=3, ge=1, le=100)


@router.post("/api/quota/bonus")
def quota_bonus(body: BonusBody, user: dict[str, Any] = Depends(get_current_user)):
    """仅 Admin 手工加额度（M5）；用户体验次数走 /api/onboarding/complete。"""
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=403,
            detail="体验次数请通过首次引导获取；手工加额度仅管理员可用",
        )
    q = add_bonus_runs(user["id"], body.n)
    return {"ok": True, "quota": q}
