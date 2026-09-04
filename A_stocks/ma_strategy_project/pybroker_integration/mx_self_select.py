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
import re
import urllib.error
import urllib.request
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_APIKEY_FILE = os.path.join(_SCRIPT_DIR, "config", "mx_apikey.txt")
DEFAULT_MX_GROUPS_DIR = os.path.join(_SCRIPT_DIR, "config", "mx_groups")
MANAGE_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/manage"
GET_URL = "https://mkapi2.dfcfs.com/finskillshub/api/claw/self-select/get"

# 单次自然语言里放太多代码易失败，按批切分
DEFAULT_CHUNK_SIZE = 20
_CODE_RE = re.compile(r"(?<!\d)(\d{6})(?!\d)")
_GROUP_NAME_KEYS = (
    "groupName",
    "group_name",
    "group",
    "name",
    "title",
    "分组",
    "分组名",
    "groupTitle",
)
_STOCK_LIST_KEYS = (
    "stocks",
    "stockList",
    "stock_list",
    "list",
    "items",
    "codes",
    "symbols",
    "members",
    "children",
    "data",
)


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


def _norm_symbol(raw: Any) -> str:
    s = "".join(ch for ch in str(raw or "") if ch.isdigit())
    return s.zfill(6) if s else ""


def _norm_group_name(raw: Any) -> str:
    return str(raw or "").strip()


def _uniq_codes(codes: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in codes:
        s = _norm_symbol(raw)
        if len(s) != 6 or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _add_code(groups: Dict[str, List[str]], group: str, code: Any) -> None:
    g = _norm_group_name(group)
    s = _norm_symbol(code)
    if not g or len(s) != 6:
        return
    bucket = groups.setdefault(g, [])
    if s not in bucket:
        bucket.append(s)


def _extract_codes_from_text(text: str) -> List[str]:
    return _uniq_codes(_CODE_RE.findall(str(text or "")))


def load_group_symbols_txt(path: str) -> Tuple[List[str], List[str]]:
    """
    读取分组 txt（东财导出或一行一码）。返回 (代码列表, 说明)。
    不写回该文件。
    """
    notes: List[str] = []
    p = os.path.abspath(path)
    if not os.path.isfile(p):
        notes.append(f"分组文件不存在: {p}")
        return [], notes
    raw = None
    used = None
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            with open(p, encoding=enc) as f:
                raw = f.read()
            used = enc
            break
        except UnicodeDecodeError:
            continue
    if raw is None:
        notes.append(f"分组文件无法解码: {p}")
        return [], notes
    codes: List[str] = []
    seen = set()
    for line in raw.splitlines():
        s = str(line or "").strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("初始") or s.startswith("代码"):
            continue
        picked = ""
        parts = s.split()
        if len(parts) >= 2 and parts[0].isdigit() and len(parts[0]) <= 4:
            cand = "".join(ch for ch in parts[1] if ch.isdigit())
            if len(cand) == 6:
                picked = cand
        if not picked:
            found = _CODE_RE.findall(s)
            picked = found[0] if found else ""
        if picked and picked not in seen:
            seen.add(picked)
            codes.append(picked)
    notes.append(f"读取 {os.path.basename(p)} ({used}) {len(codes)} 只")
    return codes, notes


def group_txt_path(group_name: str, groups_dir: str = "") -> str:
    d = os.path.abspath(groups_dir or DEFAULT_MX_GROUPS_DIR)
    return os.path.join(d, f"{str(group_name).strip()}.txt")


def write_group_symbols_txt(
    group_name: str,
    symbols: Sequence[str],
    *,
    groups_dir: str = "",
    source_note: str = "",
) -> Tuple[str, List[str]]:
    """
    把代码写入 config/mx_groups/{名}.txt，供「按成长因子排序」与本步推送共用同一名单。
    不回写桌面。返回 (路径, 日志)。
    """
    notes: List[str] = []
    g = str(group_name or "").strip()
    codes: List[str] = []
    seen = set()
    for raw in symbols:
        s = "".join(ch for ch in str(raw) if ch.isdigit()).zfill(6)
        if len(s) != 6 or s in seen:
            continue
        seen.add(s)
        codes.append(s)
    path = group_txt_path(g, groups_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    note = str(source_note or "").strip() or "工作流本轮待成长排序名单"
    lines = [
        f"# 自选分组 {g} · {note}",
        f"# count={len(codes)}",
        *codes,
        "",
    ]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    notes.append(f"已写入「{g}」名单 {len(codes)} 只 → {path}")
    return path, notes


def _group_name_from_mapping(obj: dict) -> str:
    for k in _GROUP_NAME_KEYS:
        if k in obj and isinstance(obj[k], str) and obj[k].strip():
            val = obj[k].strip()
            if k == "group" and val.isdigit():
                continue
            return val
    return ""


def parse_self_select_groups(payload: Any) -> Dict[str, List[str]]:
    """从 get/manage 返回里尽量解析 {分组名: [6位代码, ...]}。"""
    groups: Dict[str, List[str]] = {}

    def walk(obj: Any, current: Optional[str] = None) -> None:
        if obj is None:
            return
        if isinstance(obj, dict):
            name = _group_name_from_mapping(obj) or current
            code_val = obj.get("code") or obj.get("symbol") or obj.get("ts_code") or obj.get("secuCode")
            if name and code_val:
                _add_code(groups, name, code_val)
            for key in _STOCK_LIST_KEYS:
                if key in obj:
                    walk(obj[key], name)
            for k, v in obj.items():
                if k in _STOCK_LIST_KEYS or k in _GROUP_NAME_KEYS:
                    continue
                if k in ("code", "symbol", "ts_code", "secuCode", "status", "message", "success"):
                    continue
                if isinstance(v, (dict, list)):
                    walk(v, name)
            return
        if isinstance(obj, list):
            for item in obj:
                walk(item, current)
            return
        if isinstance(obj, str):
            if current:
                for code in _extract_codes_from_text(obj):
                    _add_code(groups, current, code)
            else:
                _parse_groups_from_text(obj, groups)
            return

    walk(payload)
    if not groups:
        try:
            _parse_groups_from_text(json.dumps(payload, ensure_ascii=False), groups)
        except Exception:
            pass
    return groups


def _parse_groups_from_text(text: str, groups: Dict[str, List[str]]) -> None:
    raw = str(text or "").strip()
    if not raw:
        return
    headers = list(re.finditer(r"[「【\[]([^」】\]]{1,20})[」】\]]", raw))
    if not headers:
        named = list(re.finditer(r"([\w\u4e00-\u9fff]{1,12})(?:分组|自选)", raw))
        if not named:
            return
        for i, m in enumerate(named):
            end = named[i + 1].start() if i + 1 < len(named) else len(raw)
            for code in _extract_codes_from_text(raw[m.end() : end]):
                _add_code(groups, m.group(1), code)
        return
    for i, m in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(raw)
        name = m.group(1).strip()
        for code in _extract_codes_from_text(raw[m.end() : end]):
            _add_code(groups, name, code)


def _manage_ok(resp: dict) -> bool:
    status = resp.get("status", resp.get("code", -1))
    if status in (0, "0"):
        return True
    if str(resp.get("message", "")).upper() == "OK":
        return True
    if resp.get("success") in (True, "true", "True"):
        return True
    return False


def _brief_msg(resp: dict) -> str:
    msg = resp.get("message") or resp.get("data") or ""
    if isinstance(msg, dict):
        msg = json.dumps(msg, ensure_ascii=False)[:200]
    return str(msg)[:240]


def fetch_self_select_groups(
    *,
    apikey: str = "",
    wanted: Optional[Sequence[str]] = None,
) -> Tuple[Dict[str, List[str]], List[str]]:
    """拉取全部自选分组；wanted 非空时对缺的组再用自然语言查询补一次。"""
    notes: List[str] = []
    key = (apikey or load_mx_apikey()).strip()
    if not key:
        notes.append("未配置 MX_APIKEY / config/mx_apikey.txt，无法拉取自选")
        return {}, notes
    resp = get_self_select(apikey=key)
    groups = parse_self_select_groups(resp)
    if not groups:
        notes.append(f"自选 get 未解析到分组 status={resp.get('status', resp.get('code', ''))} {_brief_msg(resp)}")
    else:
        notes.append(
            "已拉取自选分组: "
            + "；".join(f"「{g}」{len(v)}只" for g, v in groups.items())
        )
    for name in wanted or ():
        g = _norm_group_name(name)
        if not g or groups.get(g):
            continue
        q = f"查询名为「{g}」的自选股分组中的股票"
        extra = manage_self_select(q, apikey=key)
        parsed = parse_self_select_groups(extra)
        hit = parsed.get(g) or []
        if not hit:
            for k, v in parsed.items():
                if k == g or g in k or k in g:
                    hit = v
                    break
        if hit:
            groups[g] = hit
            notes.append(f"「{g}」已用查询补全 {len(hit)} 只")
        else:
            notes.append(f"「{g}」查询无代码 {_brief_msg(extra)}")
    return groups, notes


def list_group_symbols(
    group_name: str,
    *,
    groups: Optional[Dict[str, List[str]]] = None,
    apikey: str = "",
) -> List[str]:
    g = _norm_group_name(group_name)
    if groups is None:
        groups, _ = fetch_self_select_groups(apikey=apikey, wanted=[g])
    if g in groups:
        return list(groups[g])
    for k, v in (groups or {}).items():
        if k == g or g in k or k in g:
            return list(v)
    return []


def remove_symbols_from_group(
    symbols: Iterable[str],
    *,
    group_name: str,
    apikey: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Tuple[bool, List[str]]:
    """从指定自选分组删除代码。"""
    notes: List[str] = []
    key = (apikey or load_mx_apikey()).strip()
    if not key:
        notes.append("跳过删除自选：未配置 MX_APIKEY / config/mx_apikey.txt")
        return False, notes
    syms = _uniq_codes(symbols)
    if not syms:
        notes.append(f"删除自选「{group_name}」：无代码")
        return True, notes
    g = _norm_group_name(group_name) or "量能"
    ok_all = True
    for batch in _chunked(syms, chunk_size):
        joined = "、".join(batch)
        query = f"从名为「{g}」的自选股分组中删除{joined}"
        resp = manage_self_select(query, apikey=key)
        if _manage_ok(resp):
            notes.append(f"已从「{g}」删除 {len(batch)} 只 | {_brief_msg(resp)}")
        else:
            ok_all = False
            notes.append(f"删除失败 status={resp.get('status', resp.get('code'))} | {_brief_msg(resp)}")
    return ok_all, notes


def resolve_current_group_symbols(
    group_name: str,
    *,
    apikey: str = "",
    include_local_txt: bool = True,
) -> Tuple[List[str], List[str]]:
    """
    东财该组现有代码，可选再并上本地 config/mx_groups/{名}.txt。
    用于「先清空再写入」时确定要删哪些票。
    """
    notes: List[str] = []
    g = _norm_group_name(group_name)
    if not g:
        notes.append("分组名为空，无法读取现有自选")
        return [], notes
    live = list_group_symbols(g, apikey=apikey)
    if live:
        notes.append(f"东财「{g}」现有 {len(live)} 只")
    else:
        notes.append(f"东财「{g}」拉取为空，清空将依赖本地分组文件")
    extra: List[str] = []
    if include_local_txt:
        path = group_txt_path(g)
        if os.path.isfile(path):
            extra, _ln = load_group_symbols_txt(path)
    combined = _uniq_codes(list(live) + list(extra))
    if extra and len(combined) > len(live):
        notes.append(
            f"合并本地分组文件后待清空 {len(combined)} 只（东财 {len(live)} + 本地多出 {len(combined) - len(live)}）"
        )
    return combined, notes


def replace_live_group_symbols(
    symbols: Iterable[str],
    *,
    group_name: str,
    apikey: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Tuple[bool, List[str]]:
    """拉取该组现有成员 → 清空 → 按新名单写入。只动这一组。"""
    current, notes = resolve_current_group_symbols(group_name, apikey=apikey)
    if not current:
        notes.append(f"未拉到「{_norm_group_name(group_name)}」现有成员，清空可能不完整")
    ok, rn = replace_group_symbols(
        symbols,
        group_name=group_name,
        current_symbols=current,
        apikey=apikey,
        chunk_size=chunk_size,
    )
    notes.extend(rn)
    return ok, notes


def replace_group_symbols(
    symbols: Iterable[str],
    *,
    group_name: str,
    current_symbols: Optional[Sequence[str]] = None,
    apikey: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Tuple[bool, List[str]]:
    """
    按新顺序写回分组：先删现有成员，再按 ranked 顺序加入。
    加入失败时尝试把 current_symbols 加回去，避免把手改名单清空。
    """
    notes: List[str] = []
    ranked = _uniq_codes(symbols)
    current = _uniq_codes(current_symbols or [])
    g = _norm_group_name(group_name)
    if not g:
        notes.append("写回自选失败：分组名为空")
        return False, notes
    if not ranked:
        notes.append(f"「{g}」重排名单为空，不改自选")
        return True, notes
    to_delete = current or ranked
    ok_del, del_notes = remove_symbols_from_group(
        to_delete, group_name=g, apikey=apikey, chunk_size=chunk_size
    )
    notes.extend(del_notes)
    ok_add, add_notes = add_symbols_to_group(
        ranked, group_name=g, apikey=apikey, chunk_size=chunk_size
    )
    notes.extend(add_notes)
    if ok_add:
        return True, notes
    if current:
        notes.append(f"「{g}」按新顺序写入失败，尝试恢复原名单")
        _ok_r, restore_notes = add_symbols_to_group(
            current, group_name=g, apikey=apikey, chunk_size=chunk_size
        )
        notes.extend(restore_notes)
    return False, notes


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
