#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""薄 Admin API（M5）。"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth_api import get_current_user, _row_user, _get_membership
from db import get_conn, init_db
from membership_service import (
    add_bonus_runs,
    apply_membership,
    get_quota_status,
)
from payment_api import _mark_paid, _row_to_order

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def require_admin(user: dict[str, Any] = Depends(get_current_user)) -> dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


def log_admin_action(
    admin_id: str,
    action: str,
    target_user_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    init_db()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO admin_actions(id, admin_id, target_user_id, action, payload, created_at)
        VALUES(?,?,?,?,?,?)
        """,
        (
            f"adm_{secrets.token_hex(8)}",
            admin_id,
            target_user_id,
            action,
            json.dumps(payload or {}, ensure_ascii=False),
            _utcnow(),
        ),
    )
    conn.commit()


def seed_admin_user() -> None:
    """admin@workflow.local / admin1234"""
    from auth_api import hash_password
    from membership_service import ensure_membership_row

    init_db()
    conn = get_conn()
    email = "admin@workflow.local"
    row = conn.execute("SELECT id, role FROM users WHERE email=?", (email,)).fetchone()
    if row:
        if row["role"] != "admin":
            conn.execute("UPDATE users SET role='admin' WHERE id=?", (row["id"],))
            conn.commit()
        return
    uid = f"usr_{secrets.token_hex(8)}"
    now = _utcnow()
    conn.execute(
        """
        INSERT INTO users(
          id, email, password_hash, nickname, phone, avatar_text,
          role, status, onboarding_done, persona, invite_code, created_at, last_login_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            uid,
            email,
            hash_password("admin1234"),
            "管理员",
            "",
            "管",
            "admin",
            "active",
            1,
            None,
            "WF-ADMIN",
            now,
            None,
        ),
    )
    conn.commit()
    ensure_membership_row(uid)


@router.get("/users")
def list_users(_admin: dict[str, Any] = Depends(require_admin)):
    init_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM users ORDER BY created_at DESC LIMIT 200"
    ).fetchall()
    out = []
    for row in rows:
        u = _row_user(row, _get_membership(row["id"]))
        q = get_quota_status(row["id"])
        out.append(
            {
                **u,
                "today_used": q["used_runs"],
                "today_bonus": q["bonus_runs"],
                "today_remaining": q["remaining"],
                "daily_limit": q["daily_limit"],
            }
        )
    return {"ok": True, "users": out}


class StatusBody(BaseModel):
    status: Literal["active", "disabled"]


@router.post("/users/{user_id}/status")
def set_user_status(
    user_id: str,
    body: StatusBody,
    admin: dict[str, Any] = Depends(require_admin),
):
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="用户不存在")
    if row["role"] == "admin" and body.status == "disabled":
        raise HTTPException(status_code=400, detail="不能禁用管理员账号")
    conn.execute("UPDATE users SET status=? WHERE id=?", (body.status, user_id))
    conn.commit()
    log_admin_action(admin["id"], "set_status", user_id, {"status": body.status})
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return {"ok": True, "user": _row_user(row)}


class MembershipBody(BaseModel):
    plan: Literal["free", "pro", "team"]
    period_days: int | None = Field(default=None, ge=0, le=3650)


@router.post("/users/{user_id}/membership")
def set_membership(
    user_id: str,
    body: MembershipBody,
    admin: dict[str, Any] = Depends(require_admin),
):
    init_db()
    conn = get_conn()
    if not conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
        raise HTTPException(status_code=404, detail="用户不存在")
    days = body.period_days
    if body.plan == "free":
        days = 0
    elif days is None:
        days = 30 if body.plan == "pro" else 0
    m = apply_membership(user_id, body.plan, period_days=days)
    log_admin_action(
        admin["id"],
        "set_membership",
        user_id,
        {"plan": body.plan, "period_days": days, "expire_at": m.get("expire_at")},
    )
    return {"ok": True, "membership": m, "quota": get_quota_status(user_id)}


class BonusBody(BaseModel):
    n: int = Field(default=3, ge=1, le=100)


@router.post("/users/{user_id}/bonus")
def add_user_bonus(
    user_id: str,
    body: BonusBody,
    admin: dict[str, Any] = Depends(require_admin),
):
    init_db()
    conn = get_conn()
    if not conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
        raise HTTPException(status_code=404, detail="用户不存在")
    q = add_bonus_runs(user_id, body.n)
    log_admin_action(admin["id"], "add_bonus", user_id, {"n": body.n})
    return {"ok": True, "quota": q}


@router.post("/users/{user_id}/reset-onboarding")
def reset_onboarding(user_id: str, admin: dict[str, Any] = Depends(require_admin)):
    init_db()
    conn = get_conn()
    if not conn.execute("SELECT id FROM users WHERE id=?", (user_id,)).fetchone():
        raise HTTPException(status_code=404, detail="用户不存在")
    conn.execute(
        "UPDATE users SET onboarding_done=0, persona=NULL WHERE id=?",
        (user_id,),
    )
    conn.commit()
    log_admin_action(admin["id"], "reset_onboarding", user_id, {})
    row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return {"ok": True, "user": _row_user(row)}


@router.get("/orders")
def list_orders(
    status: str | None = Query(default=None),
    _admin: dict[str, Any] = Depends(require_admin),
):
    init_db()
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM payments WHERE status=? ORDER BY created_at DESC LIMIT 200",
            (status,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM payments ORDER BY created_at DESC LIMIT 200"
        ).fetchall()
    return {"ok": True, "orders": [_row_to_order(r) for r in rows]}


class OrderActionBody(BaseModel):
    action: Literal["mark_paid", "cancel"]


@router.post("/orders/{order_id}/action")
def order_action(
    order_id: str,
    body: OrderActionBody,
    admin: dict[str, Any] = Depends(require_admin),
):
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM payments WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    if body.action == "mark_paid":
        order = _mark_paid(order_id, provider_ref=f"admin-{secrets.token_hex(3)}")
        log_admin_action(
            admin["id"],
            "order_mark_paid",
            row["user_id"],
            {"order_id": order_id},
        )
        return {"ok": True, "order": order}
    if row["status"] == "paid":
        raise HTTPException(status_code=400, detail="已支付订单不可取消")
    conn.execute(
        "UPDATE payments SET status=? WHERE id=?",
        ("cancelled", order_id),
    )
    conn.commit()
    log_admin_action(
        admin["id"],
        "order_cancel",
        row["user_id"],
        {"order_id": order_id},
    )
    row = conn.execute("SELECT * FROM payments WHERE id=?", (order_id,)).fetchone()
    return {"ok": True, "order": _row_to_order(row)}
