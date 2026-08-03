#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户注册 / 登录 / 资料（M1）。密码 PBKDF2；令牌 HMAC 签名。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from db import get_conn, init_db
from membership_service import get_effective_plan, ensure_membership_row

router = APIRouter(prefix="/api/auth", tags=["auth"])

# 开发默认密钥；生产请设环境变量 MVP_JWT_SECRET
_SECRET = (os.environ.get("MVP_JWT_SECRET") or "workflow-mvp-dev-secret-change-me").encode("utf-8")
_TOKEN_TTL_SEC = 60 * 60 * 24 * 14  # 14 天
_PBKDF2_ITERS = 120_000


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2_{_PBKDF2_ITERS}${_b64url(salt)}${_b64url(dk)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt_b64, hash_b64 = stored.split("$", 2)
        iters = int(algo.split("_", 1)[1])
        salt = _b64url_decode(salt_b64)
        expect = _b64url_decode(hash_b64)
        got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
        return hmac.compare_digest(got, expect)
    except Exception:
        return False


def issue_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": int(time.time()) + _TOKEN_TTL_SEC,
        "iat": int(time.time()),
    }
    body = _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = _b64url(hmac.new(_SECRET, body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_token(token: str) -> dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
        expect = _b64url(hmac.new(_SECRET, body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expect):
            raise ValueError("bad sig")
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        return payload
    except Exception as e:
        raise HTTPException(status_code=401, detail="无效或过期的登录态") from e


def _avatar(nickname: str, email: str) -> str:
    base = (nickname or email or "?").strip()
    return (base[:1] or "?").upper()


def _row_user(row: Any, membership: Any | None = None) -> dict[str, Any]:
    plan, expire_at = get_effective_plan(row["id"])
    return {
        "id": row["id"],
        "email": row["email"],
        "nickname": row["nickname"],
        "phone": row["phone"] or "",
        "avatar_text": row["avatar_text"],
        "role": row["role"],
        "status": row["status"],
        "onboarding_done": bool(row["onboarding_done"]),
        "persona": row["persona"],
        "invite_code": row["invite_code"] or "",
        "plan": plan,
        "expire_at": expire_at,
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def _get_membership(user_id: str) -> Any | None:
    conn = get_conn()
    return conn.execute("SELECT * FROM memberships WHERE user_id=?", (user_id,)).fetchone()


def get_current_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="请先登录")
    token = authorization.split(" ", 1)[1].strip()
    payload = decode_token(token)
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (payload["sub"],)).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="用户不存在")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="账号已禁用")
    return _row_user(row)


class RegisterBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=6, max_length=128)
    nickname: str | None = None
    phone: str | None = None


class LoginBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ProfileBody(BaseModel):
    nickname: str | None = None
    phone: str | None = None


def seed_demo_user() -> None:
    """确保演示账号存在：demo@workflow.local / demo1234"""
    init_db()
    conn = get_conn()
    email = "demo@workflow.local"
    row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
    if row:
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
            hash_password("demo1234"),
            "演示用户",
            "",
            "演",
            "user",
            "active",
            0,
            None,
            "WF-DEMO",
            now,
            None,
        ),
    )
    conn.commit()
    ensure_membership_row(uid)


@router.on_event("startup")
def _startup() -> None:
    # 若未挂到 app startup，首次请求也会 seed
    seed_demo_user()


def _normalize_email(email: str) -> str:
    e = email.strip().lower()
    if "@" not in e or "." not in e.split("@")[-1]:
        raise HTTPException(status_code=400, detail="邮箱格式无效")
    return e


@router.post("/register")
def register(body: RegisterBody):
    init_db()
    seed_demo_user()
    email = _normalize_email(body.email)
    conn = get_conn()
    if conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
        raise HTTPException(status_code=400, detail="邮箱已注册")
    uid = f"usr_{secrets.token_hex(8)}"
    nickname = (body.nickname or email.split("@")[0] or "用户").strip()[:32]
    phone = (body.phone or "").strip()[:32]
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
            hash_password(body.password),
            nickname,
            phone,
            _avatar(nickname, email),
            "user",
            "active",
            0,
            None,
            f"WF-{secrets.token_hex(3).upper()}",
            now,
            now,
        ),
    )
    conn.commit()
    ensure_membership_row(uid)
    token = issue_token(uid, email)
    user = _row_user(
        conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone(),
        _get_membership(uid),
    )
    return {"ok": True, "token": token, "user": user}


@router.post("/login")
def login(body: LoginBody):
    init_db()
    seed_demo_user()
    email = _normalize_email(body.email)
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(status_code=401, detail="邮箱或密码错误")
    if row["status"] != "active":
        raise HTTPException(status_code=403, detail="账号已禁用")
    now = _utcnow()
    conn.execute("UPDATE users SET last_login_at=? WHERE id=?", (now, row["id"]))
    conn.commit()
    token = issue_token(row["id"], row["email"])
    user = _row_user(row, _get_membership(row["id"]))
    user["last_login_at"] = now
    return {"ok": True, "token": token, "user": user}


@router.get("/me")
def me(user: dict[str, Any] = Depends(get_current_user)):
    return {"ok": True, "user": user}


@router.patch("/me")
def patch_me(body: ProfileBody, user: dict[str, Any] = Depends(get_current_user)):
    conn = get_conn()
    nickname = user["nickname"]
    phone = user["phone"]
    if body.nickname is not None:
        nickname = body.nickname.strip()[:32] or nickname
    if body.phone is not None:
        phone = body.phone.strip()[:32]
    avatar = _avatar(nickname, user["email"])
    conn.execute(
        "UPDATE users SET nickname=?, phone=?, avatar_text=? WHERE id=?",
        (nickname, phone, avatar, user["id"]),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
    return {"ok": True, "user": _row_user(row, _get_membership(user["id"]))}
