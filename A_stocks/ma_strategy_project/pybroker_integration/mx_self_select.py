#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
东财妙想 Skills 自选股管理（mx_selfselect）。

官方接口：
  GET/查询  POST .../self-select/get
  添加/删除 POST .../self-select/manage   Body: {"query": "自然语言"}

认证：Header apikey = Skills Key（mkt_...），优先环境变量 MX_APIKEY，
其次可选本地文件 config/mx_apikey.txt（勿提交仓库）。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Iterable, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APIKEY_FILE = os.path.join(_SCRIPT_DIR, "config", "mx_apikey.txt")
MANAGE_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/manage"
GET_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/get"

# 单次自然语言里放太多代码易失败，按批切分
DEFAULT_CHUNK_SIZE = 20


def load_mx_apikey(*, apikey_file: str = DEFAULT_APIKEY_FILE) -> str:
    env = str(os.environ.get("MX_APIKEY", "") or "").strip()
    if env:
        return env
    path = os.path.abspath(apikey_file)
    if os.path.isfile(path):
        for enc in ("utf-8-sig", "utf-8", "gbk"):
            try:
                with open(path, encoding=enc) as f:
                    for line in f:
                        s = line.strip()
                        if not s or s.startswith("#"):
                            continue
                        return s
            except UnicodeDecodeError:
                continue
    return ""


def _post_json(url: str, *, apikey: str, body: Optional[dict] = None, timeout: int = 90) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "apikey": apikey,
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(err)
        except Exception:
            return {"status": getattr(e, "code", -1), "message": err[:500], "success": False}


def manage_self_select(query: str, *, apikey: str) -> dict:
    return _post_json(MANAGE_URL, apikey=apikey, body={"query": str(query)})


def get_self_select(*, apikey: str) -> dict:
    return _post_json(GET_URL, apikey=apikey, body=None)


def _chunked(items: Sequence[str], size: int) -> List[List[str]]:
    n = max(1, int(size))
    return [list(items[i : i + n]) for i in range(0, len(items), n)]


def add_symbols_to_group(
    symbols: Iterable[str],
    *,
    group_name: str = "量能",
    apikey: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Tuple[bool, List[str]]:
    """
    将股票代码批量加入指定自选分组（自然语言走 /manage）。
    返回 (全部批次成功?, 日志行)。
    """
    notes: List[str] = []
    key = (apikey or load_mx_apikey()).strip()
    if not key:
        notes.append("跳过推送自选：未配置 MX_APIKEY / config/mx_apikey.txt")
        return False, notes

    syms: List[str] = []
    seen = set()
    for raw in symbols:
        s = "".join(ch for ch in str(raw) if ch.isdigit()).zfill(6)
        if len(s) != 6 or s in seen:
            continue
        seen.add(s)
        syms.append(s)

    if not syms:
        notes.append(f"推送自选「{group_name}」：无代码可添加")
        return True, notes

    g = str(group_name or "量能").strip() or "量能"
    ok_all = True
    for batch in _chunked(syms, chunk_size):
        joined = "、".join(batch)
        query = f"把{joined}添加到名为「{g}」的自选股分组"
        resp = manage_self_select(query, apikey=key)
        status = resp.get("status", resp.get("code", -1))
        msg = resp.get("message") or resp.get("data") or ""
        if isinstance(msg, dict):
            msg = json.dumps(msg, ensure_ascii=False)[:200]
        msg_s = str(msg)[:240]
        if status in (0, "0") or str(resp.get("message", "")).upper() == "OK":
            notes.append(f"已推送 {len(batch)} 只 → 分组「{g}」| {msg_s}")
        else:
            ok_all = False
            notes.append(f"推送失败 status={status} batch={batch[:5]}… | {msg_s}")
    return ok_all, notes
