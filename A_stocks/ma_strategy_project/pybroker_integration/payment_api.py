#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""支付下单 / 查询 / 回调（R5 + M2 入库）。

真微信/支付宝需商户密钥；当前 simulate：
  create → pending → simulate-pay / callback → paid → memberships 更新
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth_api import get_current_user
from db import get_conn, init_db
from membership_service import PLAN_PERIOD_DAYS, apply_membership, get_quota_status

router = APIRouter(prefix="/api/payment", tags=["payment"])

PlanId = Literal["free", "pro", "team"]
ChannelId = Literal["wechat", "alipay", "mock"]

PLAN_AMOUNT_YUAN: dict[str, int] = {
    "free": 0,
    "pro": 99,
    "team": 0,
}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _order_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"PAY-{stamp}-{secrets.token_hex(3).upper()}"


def _row_to_order(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "plan": row["plan"],
        "channel": row["channel"],
        "amount_yuan": row["amount_yuan"],
        "period_days": row["period_days"],
        "status": row["status"],
        "created_at": row["created_at"],
        "paid_at": row["paid_at"],
        "provider_ref": row["provider_ref"],
        "provider": "simulate",
    }


class CreatePaymentBody(BaseModel):
    plan: PlanId = "pro"
    channel: ChannelId = "mock"


class CallbackBody(BaseModel):
    order_id: str
    provider_ref: str | None = None
    success: bool = True


@router.get("/channels")
def list_channels():
    # 邀请内测：不展示伪微信/支付宝；正式收款后再加真渠道
    return {
        "provider": "invite_simulate",
        "channels": [
            {
                "id": "mock",
                "label": "内测开通",
                "mode": "simulate",
                "hint": "邀请内测 · 确认后立即生效 · 付费不退",
            },
        ],
    }


@router.post("/create")
def create_payment(
    body: CreatePaymentBody,
    user: dict[str, Any] = Depends(get_current_user),
):
    init_db()
    if body.plan == "team":
        raise HTTPException(status_code=400, detail="Team 仅支持人工开通")
    if body.plan == "free":
        raise HTTPException(status_code=400, detail="Free 无需支付，请直接切换")

    amount = PLAN_AMOUNT_YUAN.get(body.plan)
    if amount is None:
        raise HTTPException(status_code=400, detail="未知套餐")

    oid = _order_id()
    period = PLAN_PERIOD_DAYS.get(body.plan, 30)
    now = _utcnow()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO payments(
          id, user_id, plan, amount_yuan, channel, status, period_days,
          provider_ref, created_at, paid_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            oid,
            user["id"],
            body.plan,
            amount,
            body.channel,
            "pending",
            period,
            None,
            now,
            None,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM payments WHERE id=?", (oid,)).fetchone()
    order = _row_to_order(row)
    return {
        "ok": True,
        "order": order,
        "pay": {
            "mode": "simulate",
            "message": "请调用 /api/payment/simulate-pay/{order_id} 完成支付确认",
            "simulate_path": f"/api/payment/simulate-pay/{oid}",
        },
    }


@router.get("/order/{order_id}")
def get_order(order_id: str, user: dict[str, Any] = Depends(get_current_user)):
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM payments WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    if row["user_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权查看该订单")
    return {"ok": True, "order": _row_to_order(row)}


@router.get("/orders")
def list_orders(user: dict[str, Any] = Depends(get_current_user)):
    init_db()
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM payments WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
        (user["id"],),
    ).fetchall()
    return {"ok": True, "orders": [_row_to_order(r) for r in rows]}


def _mark_paid(order_id: str, provider_ref: str | None = None) -> dict[str, Any]:
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM payments WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    if row["status"] == "paid":
        return _row_to_order(row)
    if row["status"] == "cancelled":
        raise HTTPException(status_code=400, detail="订单已取消，不可再标记支付")
    # pending / failed 均可纠偏为 paid

    paid_at = _utcnow()
    ref = provider_ref or f"sim-{secrets.token_hex(4)}"
    conn.execute(
        "UPDATE payments SET status=?, paid_at=?, provider_ref=? WHERE id=?",
        ("paid", paid_at, ref, order_id),
    )
    conn.commit()
    apply_membership(row["user_id"], row["plan"], period_days=int(row["period_days"] or 0))
    try:
        from events_service import track_event

        track_event(
            "payment_success",
            user_id=row["user_id"],
            props={
                "order_id": order_id,
                "plan": row["plan"],
                "amount_yuan": row["amount_yuan"],
                "channel": row["channel"],
            },
        )
    except Exception:
        pass
    row = conn.execute("SELECT * FROM payments WHERE id=?", (order_id,)).fetchone()
    order = _row_to_order(row)
    order["membership_quota"] = get_quota_status(row["user_id"])
    return order


@router.post("/simulate-pay/{order_id}")
def simulate_pay(order_id: str, user: dict[str, Any] = Depends(get_current_user)):
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT * FROM payments WHERE id=?", (order_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="订单不存在")
    if row["user_id"] != user["id"] and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="无权支付该订单")
    order = _mark_paid(order_id)
    return {"ok": True, "order": order}


@router.post("/callback/{channel}")
def payment_callback(channel: ChannelId, body: CallbackBody):
    if channel not in ("wechat", "alipay", "mock"):
        raise HTTPException(status_code=400, detail="未知渠道")
    init_db()
    if not body.success:
        # 渠道失败 → failed（与用户主动 cancel 区分）
        conn = get_conn()
        row = conn.execute("SELECT * FROM payments WHERE id=?", (body.order_id,)).fetchone()
        if row and row["status"] == "pending":
            conn.execute(
                "UPDATE payments SET status=? WHERE id=?",
                ("failed", body.order_id),
            )
            conn.commit()
            row = conn.execute("SELECT * FROM payments WHERE id=?", (body.order_id,)).fetchone()
            return {"ok": True, "order": _row_to_order(row)}
        raise HTTPException(status_code=404, detail="订单不存在或不可标记失败")
    order = _mark_paid(body.order_id, body.provider_ref)
    return {"ok": True, "order": order}
