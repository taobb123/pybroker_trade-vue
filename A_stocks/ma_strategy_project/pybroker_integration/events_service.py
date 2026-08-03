#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""行为事件写入与漏斗聚合（M4）。"""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timezone
from typing import Any

from db import get_conn, init_db

ALLOWED_EVENTS = frozenset(
    {
        "page_view",
        "run_strategy",
        "export_report",
        "click_upgrade",
        "payment_success",
    }
)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def track_event(
    event_name: str,
    user_id: str | None = None,
    props: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_name not in ALLOWED_EVENTS:
        raise ValueError(f"未知事件: {event_name}")
    init_db()
    eid = f"evt_{secrets.token_hex(8)}"
    now = _utcnow()
    payload = json.dumps(props or {}, ensure_ascii=False)
    conn = get_conn()
    conn.execute(
        "INSERT INTO events(id, user_id, event_name, props_json, created_at) VALUES(?,?,?,?,?)",
        (eid, user_id, event_name, payload, now),
    )
    conn.commit()
    return {
        "id": eid,
        "user_id": user_id,
        "event_name": event_name,
        "props": props or {},
        "created_at": now,
    }


def _unique_users(event_name: str) -> int:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT user_id) AS n
        FROM events
        WHERE event_name=? AND user_id IS NOT NULL AND user_id != ''
        """,
        (event_name,),
    ).fetchone()
    return int(row["n"] or 0)


def funnel_stats() -> dict[str, Any]:
    """产品漏斗：关键页 UV → 注册 → 运行 → 点升级 → 支付成功。"""
    init_db()
    conn = get_conn()
    registered = int(
        conn.execute("SELECT COUNT(*) AS n FROM users WHERE status='active'").fetchone()["n"]
        or 0
    )
    steps = [
        {"key": "page_view", "label": "关键页访问用户", "count": _unique_users("page_view")},
        {"key": "registered", "label": "注册用户", "count": registered},
        {"key": "run_strategy", "label": "运行策略用户", "count": _unique_users("run_strategy")},
        {"key": "click_upgrade", "label": "点击升级用户", "count": _unique_users("click_upgrade")},
        {
            "key": "payment_success",
            "label": "支付成功用户",
            "count": _unique_users("payment_success"),
        },
    ]
    return {"ok": True, "steps": steps}
