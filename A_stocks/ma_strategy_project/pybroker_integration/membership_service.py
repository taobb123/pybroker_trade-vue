#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""会员 / 配额服务（M2）。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from db import get_conn, init_db

# 与 businessRules.ts 对齐
PLAN_DAILY_QUOTA: dict[str, int] = {
    "free": 10,
    "pro": 100,
    "team": -1,
}
PLAN_PERIOD_DAYS: dict[str, int] = {
    "free": 0,
    "pro": 30,
    "team": 0,
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _isoformat(dt: datetime) -> str:
    return dt.isoformat()


def today_key(local: bool = True) -> str:
    """自然日：用本地日期（与前端一致）。"""
    if local:
        return datetime.now().strftime("%Y-%m-%d")
    return _utcnow().strftime("%Y-%m-%d")


def ensure_membership_row(user_id: str) -> None:
    init_db()
    conn = get_conn()
    row = conn.execute("SELECT user_id FROM memberships WHERE user_id=?", (user_id,)).fetchone()
    if row:
        return
    now = _isoformat(_utcnow())
    conn.execute(
        "INSERT INTO memberships(user_id, plan, start_at, expire_at, updated_at) VALUES(?,?,?,?,?)",
        (user_id, "free", now, None, now),
    )
    conn.commit()


def get_effective_plan(user_id: str) -> tuple[str, str | None]:
    """返回 (plan, expire_at)；过期则回落 free 并写库。"""
    ensure_membership_row(user_id)
    conn = get_conn()
    row = conn.execute("SELECT * FROM memberships WHERE user_id=?", (user_id,)).fetchone()
    plan = (row["plan"] if row else "free") or "free"
    expire_at = row["expire_at"] if row else None
    if plan != "free" and expire_at:
        try:
            exp = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
            if exp.timestamp() < _utcnow().timestamp():
                apply_membership(user_id, "free", period_days=0)
                return "free", None
        except Exception:
            pass
    return plan, expire_at


def apply_membership(user_id: str, plan: str, period_days: int | None = None) -> dict[str, Any]:
    ensure_membership_row(user_id)
    now = _utcnow()
    days = PLAN_PERIOD_DAYS.get(plan, 0) if period_days is None else period_days
    expire_at = None
    if plan != "free" and days and days > 0:
        expire_at = _isoformat(now + timedelta(days=days))
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO memberships(user_id, plan, start_at, expire_at, updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET
          plan=excluded.plan,
          start_at=excluded.start_at,
          expire_at=excluded.expire_at,
          updated_at=excluded.updated_at
        """,
        (user_id, plan, _isoformat(now), expire_at, _isoformat(now)),
    )
    conn.commit()
    return {"user_id": user_id, "plan": plan, "expire_at": expire_at}


def _quota_row(user_id: str, day: str) -> Any:
    conn = get_conn()
    return conn.execute(
        "SELECT * FROM quota_ledger WHERE user_id=? AND day=?",
        (user_id, day),
    ).fetchone()


def ensure_quota_row(user_id: str, day: str | None = None) -> Any:
    init_db()
    day = day or today_key()
    conn = get_conn()
    row = _quota_row(user_id, day)
    if row:
        return row
    conn.execute(
        "INSERT INTO quota_ledger(user_id, day, used_runs, bonus_runs) VALUES(?,?,0,0)",
        (user_id, day),
    )
    conn.commit()
    return _quota_row(user_id, day)


def get_quota_status(user_id: str) -> dict[str, Any]:
    plan, expire_at = get_effective_plan(user_id)
    day = today_key()
    row = ensure_quota_row(user_id, day)
    used = int(row["used_runs"] or 0)
    bonus = int(row["bonus_runs"] or 0)
    limit = PLAN_DAILY_QUOTA.get(plan, 10)
    if limit < 0:
        remaining = None  # unlimited
        available = True
    else:
        remaining = max(0, limit + bonus - used)
        available = remaining > 0
    return {
        "user_id": user_id,
        "day": day,
        "plan": plan,
        "expire_at": expire_at,
        "used_runs": used,
        "bonus_runs": bonus,
        "daily_limit": limit,
        "remaining": remaining,
        "unlimited": limit < 0,
        "available": available,
    }


def consume_run(user_id: str) -> dict[str, Any]:
    """发起 run 前调用：配额 → 限流 → +1 used。限流不扣日配额。"""
    from rate_limit import check_and_record_run

    status = get_quota_status(user_id)
    if not status["available"]:
        return {
            "ok": False,
            "code": "quota_exhausted",
            "reason": f"今日运行次数已用尽（限额 {status['daily_limit']}，档位 {status['plan']}）",
            "quota": status,
        }

    rate = check_and_record_run(user_id)
    if not rate["ok"]:
        return {
            "ok": False,
            "code": "rate_limit",
            "reason": rate["reason"],
            "quota": status,
        }

    day = status["day"]
    conn = get_conn()
    conn.execute(
        "UPDATE quota_ledger SET used_runs = used_runs + 1 WHERE user_id=? AND day=?",
        (user_id, day),
    )
    conn.commit()
    try:
        from events_service import track_event

        track_event(
            "run_strategy",
            user_id=user_id,
            props={"plan": status["plan"], "day": day},
        )
    except Exception:
        pass
    return {"ok": True, "quota": get_quota_status(user_id)}


def add_bonus_runs(user_id: str, n: int) -> dict[str, Any]:
    day = today_key()
    ensure_quota_row(user_id, day)
    conn = get_conn()
    conn.execute(
        "UPDATE quota_ledger SET bonus_runs = bonus_runs + ? WHERE user_id=? AND day=?",
        (n, user_id, day),
    )
    conn.commit()
    return get_quota_status(user_id)
