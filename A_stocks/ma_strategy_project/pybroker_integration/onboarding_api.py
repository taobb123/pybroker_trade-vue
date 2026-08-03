#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Onboarding API（M3）：身份选择 → 推荐基础策略 → 当日 +3 bonus。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth_api import get_current_user, _row_user, _get_membership
from db import get_conn, init_db
from membership_service import add_bonus_runs, get_quota_status

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

PERSONAS = ("investor", "researcher", "explorer")
ONBOARDING_BONUS = 3
RECOMMENDED_STEP_ID = "roc_20"
RECOMMENDED_TITLE = "20日 ROC 排序"


def _meta(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "done": bool(user.get("onboarding_done")),
        "persona": user.get("persona"),
        "bonus_runs": ONBOARDING_BONUS,
        "recommended_step_id": RECOMMENDED_STEP_ID,
        "recommended_title": RECOMMENDED_TITLE,
        "personas": [
            {"id": "investor", "label": "个人投资者", "hint": "想快速筛选与跟踪标的"},
            {"id": "researcher", "label": "研究 / 分析", "hint": "偏因子与回测链路"},
            {"id": "explorer", "label": "先随便看看", "hint": "先熟悉平台再定方向"},
        ],
    }


@router.get("/status")
def onboarding_status(user: dict[str, Any] = Depends(get_current_user)):
    return {"ok": True, **_meta(user)}


class CompleteBody(BaseModel):
    """完成引导。skip_persona=true 时 persona 记为 null。"""

    persona: Literal["investor", "researcher", "explorer"] | None = None
    skip_persona: bool = False


@router.post("/complete")
def onboarding_complete(
    body: CompleteBody,
    user: dict[str, Any] = Depends(get_current_user),
):
    init_db()
    uid = user["id"]
    if user.get("onboarding_done"):
        return {
            "ok": True,
            "already_done": True,
            "user": user,
            "quota": get_quota_status(uid),
            **_meta(user),
        }

    if body.skip_persona:
        persona: str | None = None
    else:
        persona = body.persona
        if persona is not None and persona not in PERSONAS:
            raise HTTPException(status_code=400, detail="无效身份")

    conn = get_conn()
    conn.execute(
        "UPDATE users SET onboarding_done=1, persona=? WHERE id=?",
        (persona, uid),
    )
    conn.commit()

    # 仅首次完成赠送；already_done 分支不会走到这里
    quota = add_bonus_runs(uid, ONBOARDING_BONUS)
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    fresh = _row_user(row, _get_membership(uid))
    return {
        "ok": True,
        "already_done": False,
        "user": fresh,
        "quota": quota,
        **_meta(fresh),
    }
