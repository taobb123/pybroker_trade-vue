#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""事件埋点 API（M4）。"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from auth_api import decode_token, get_current_user, _row_user
from db import get_conn, init_db
from events_service import ALLOWED_EVENTS, funnel_stats, track_event

router = APIRouter(prefix="/api/events", tags=["events"])

EventName = Literal[
    "page_view",
    "run_strategy",
    "export_report",
    "click_upgrade",
    "payment_success",
]


def get_optional_user(authorization: str | None = Header(default=None)) -> dict[str, Any] | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        token = authorization.split(" ", 1)[1].strip()
        payload = decode_token(token)
        init_db()
        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE id=?", (payload["sub"],)).fetchone()
        if not row or row["status"] != "active":
            return None
        return _row_user(row)
    except Exception:
        return None


class TrackBody(BaseModel):
    event_name: EventName
    props: dict[str, Any] = Field(default_factory=dict)


@router.post("/track")
def events_track(
    body: TrackBody,
    user: dict[str, Any] | None = Depends(get_optional_user),
):
    if body.event_name not in ALLOWED_EVENTS:
        raise HTTPException(status_code=400, detail="不支持的事件名")
    uid = user["id"] if user else None
    # 付费与运行类事件要求登录，避免匿名刷漏斗
    if body.event_name in ("run_strategy", "export_report", "click_upgrade", "payment_success"):
        if not uid:
            raise HTTPException(status_code=401, detail="请先登录")
    try:
        evt = track_event(body.event_name, user_id=uid, props=body.props)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "event": evt}


@router.get("/funnel")
def events_funnel(_user: dict[str, Any] = Depends(get_current_user)):
    """登录可读漏斗（MVP；M5 可收紧为 admin）。"""
    return funnel_stats()
