#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MVP SQLite 访问层（M1：users + memberships）。"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / ".pybrokercache" / "mvp.db"

_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        _local.conn = conn
    return conn


def init_db() -> None:
    conn = get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY,
          email TEXT NOT NULL UNIQUE COLLATE NOCASE,
          password_hash TEXT NOT NULL,
          nickname TEXT NOT NULL DEFAULT '',
          phone TEXT NOT NULL DEFAULT '',
          avatar_text TEXT NOT NULL DEFAULT '?',
          role TEXT NOT NULL DEFAULT 'user',
          status TEXT NOT NULL DEFAULT 'active',
          onboarding_done INTEGER NOT NULL DEFAULT 0,
          persona TEXT,
          invite_code TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          last_login_at TEXT
        );

        CREATE TABLE IF NOT EXISTS memberships (
          user_id TEXT PRIMARY KEY,
          plan TEXT NOT NULL DEFAULT 'free',
          start_at TEXT,
          expire_at TEXT,
          updated_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS quota_ledger (
          user_id TEXT NOT NULL,
          day TEXT NOT NULL,
          used_runs INTEGER NOT NULL DEFAULT 0,
          bonus_runs INTEGER NOT NULL DEFAULT 0,
          PRIMARY KEY(user_id, day),
          FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS payments (
          id TEXT PRIMARY KEY,
          user_id TEXT NOT NULL,
          plan TEXT NOT NULL,
          amount_yuan INTEGER NOT NULL DEFAULT 0,
          channel TEXT NOT NULL DEFAULT 'mock',
          status TEXT NOT NULL DEFAULT 'pending',
          period_days INTEGER NOT NULL DEFAULT 0,
          provider_ref TEXT,
          created_at TEXT NOT NULL,
          paid_at TEXT,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS events (
          id TEXT PRIMARY KEY,
          user_id TEXT,
          event_name TEXT NOT NULL,
          props_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          FOREIGN KEY(user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS admin_actions (
          id TEXT PRIMARY KEY,
          admin_id TEXT NOT NULL,
          target_user_id TEXT,
          action TEXT NOT NULL,
          payload TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          FOREIGN KEY(admin_id) REFERENCES users(id),
          FOREIGN KEY(target_user_id) REFERENCES users(id)
        );

        CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
        CREATE INDEX IF NOT EXISTS idx_payments_user ON payments(user_id);
        CREATE INDEX IF NOT EXISTS idx_events_name_created ON events(event_name, created_at);
        CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
        CREATE INDEX IF NOT EXISTS idx_admin_actions_created ON admin_actions(created_at);
        """
    )
    conn.commit()
