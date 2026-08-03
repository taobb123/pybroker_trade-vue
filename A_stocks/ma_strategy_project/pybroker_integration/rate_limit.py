#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run 发起速率限制（M6）。默认每用户每 60 秒 ≤ 10 次。"""

from __future__ import annotations

import os
import time
from collections import defaultdict, deque

# 与 businessRules.ts RUN_RATE_LIMIT_PER_MINUTE 对齐；可用环境变量覆盖
RUN_RATE_LIMIT = int(os.environ.get("MVP_RUN_RATE_LIMIT", "10"))
RUN_RATE_WINDOW_SEC = int(os.environ.get("MVP_RUN_RATE_WINDOW_SEC", "60"))

_windows: dict[str, deque[float]] = defaultdict(deque)


def check_and_record_run(user_id: str) -> dict:
    """通过则记一次时间戳；超限不记、不扣配额。"""
    now = time.time()
    q = _windows[user_id]
    while q and now - q[0] > RUN_RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= RUN_RATE_LIMIT:
        return {
            "ok": False,
            "code": "rate_limit",
            "reason": (
                f"运行过于频繁：每 {RUN_RATE_WINDOW_SEC} 秒最多 {RUN_RATE_LIMIT} 次，请稍后再试"
            ),
            "limit": RUN_RATE_LIMIT,
            "window_sec": RUN_RATE_WINDOW_SEC,
            "used_in_window": len(q),
        }
    q.append(now)
    return {
        "ok": True,
        "limit": RUN_RATE_LIMIT,
        "window_sec": RUN_RATE_WINDOW_SEC,
        "used_in_window": len(q),
    }
