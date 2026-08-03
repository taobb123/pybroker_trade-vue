#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本机工作流控制台：读取 YAML 配置，按步执行项目根目录下的脚本；执行中可 POST /api/run/stop 终止当前子进程。
用法（在 pybroker_integration 目录）:
  python -m uvicorn workflow_server:app --host 127.0.0.1 --port 8765 --reload
浏览器打开: http://127.0.0.1:8765/
"""

from __future__ import annotations

import asyncio
import csv
import io
import os
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote

# 剥离 tqdm / Rich 等写入 stderr 的 ANSI 序列，避免在网页里显示为一串控制符
_ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[-/]*[@-~])")
_TABULAR_SUFFIX = frozenset({".csv", ".tsv"})
_IMAGE_SUFFIX = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"})
_IMAGE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}
_TABLE_PREVIEW_MAX = 500

_active_proc_lock = threading.Lock()
_active_proc: subprocess.Popen[bytes] | None = None

import yaml
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from payment_api import router as payment_router
from auth_api import router as auth_router, seed_demo_user
from membership_api import router as membership_router
from onboarding_api import router as onboarding_router
from events_api import router as events_router
from admin_api import router as admin_router, seed_admin_user
from db import init_db

PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = PROJECT_ROOT / "config" / "workflow_runner.yaml"


def _default_config() -> dict[str, Any]:
    return {
        "python_executable": "python",
        "project_root": "",
        "data_sources": {"extra_env": {}},
        "runner": {"merged_log_stderr": "on_error"},
        "steps": [],
    }


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.is_file():
        return _default_config()
    with CONFIG_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    base = _default_config()
    base.update(data)
    if "data_sources" not in data:
        base["data_sources"] = {"extra_env": {}}
    elif isinstance(data.get("data_sources"), dict):
        base["data_sources"] = {"extra_env": dict(data["data_sources"].get("extra_env") or {})}
    dr = _default_config()["runner"]
    if not isinstance(base.get("runner"), dict):
        base["runner"] = dict(dr)
    else:
        for k, v in dr.items():
            base["runner"].setdefault(k, v)
    return base


def save_config(cfg: dict[str, Any]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)


def resolve_project_root(cfg: dict[str, Any]) -> Path:
    raw = (cfg.get("project_root") or "").strip()
    if not raw:
        return PROJECT_ROOT
    return Path(raw).expanduser().resolve()


def _normalize_workspace_rel(rel: str) -> str:
    rel = unquote(rel or "").strip().replace("\\", "/")
    if not rel or rel.startswith("/"):
        raise HTTPException(status_code=400, detail="路径无效")
    parts = [p for p in rel.split("/") if p and p != "."]
    if any(p == ".." for p in parts):
        raise HTTPException(status_code=400, detail="禁止路径中出现 ..")
    return "/".join(parts)


def _is_under(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_workspace_path(cfg: dict[str, Any], rel: str) -> Path:
    raw = unquote((rel or "").strip())
    if not raw:
        raise HTTPException(status_code=400, detail="路径无效")
    # 绝对路径（本机自用）：直接使用，不要求落在 project_root 下
    trial = Path(raw)
    trial = trial.expanduser()
    if trial.is_absolute():
        return trial.resolve()
    rel_n = _normalize_workspace_rel(raw)
    root = resolve_project_root(cfg)
    p = (root / rel_n).resolve()
    root_r = root.resolve()
    if not _is_under(root_r, p):
        raise HTTPException(status_code=400, detail="路径必须在 project_root 内")
    return p


def _read_text_file(path: Path) -> str:
    data = path.read_bytes()
    return _decode_pipe_output(data)


def _parse_tabular(path: Path, max_rows: int) -> tuple[list[str], list[list[str]], bool]:
    text = _read_text_file(path)
    dialect = "excel-tab" if path.suffix.lower() == ".tsv" else "excel"
    reader = csv.reader(io.StringIO(text), dialect=dialect)
    rows_all = list(reader)
    if not rows_all:
        return [], [], False
    headers = [str(c) for c in rows_all[0]]
    body = rows_all[1:]
    truncated = len(body) > max_rows
    body = body[:max_rows]
    return headers, body, truncated


def _validate_glob_pattern(pattern: str) -> str:
    pattern = (pattern or "").strip().replace("\\", "/")
    if not pattern or ".." in pattern or "/" in pattern:
        raise HTTPException(status_code=400, detail="glob 须为项目根下的文件名模式，且不得含 / 或 ..")
    return pattern


def _rel_path_from_root(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _latest_glob_file(root: Path, pattern: str) -> Path | None:
    candidates = [p for p in root.glob(pattern) if p.is_file()]
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def _normalize_header_name(h: str) -> str:
    return re.sub(r"\s+", "", str(h or "").strip()).lower()


def _find_column_index(headers: list[str], column: str) -> int:
    want = _normalize_header_name(column)
    norm = [_normalize_header_name(h) for h in headers]
    if want in norm:
        return norm.index(want)
    for i, h in enumerate(norm):
        if want and want in h:
            return i
    return -1


def _extract_column_text(
    path: Path,
    column: str,
    *,
    skip_empty: bool,
    dedupe: bool,
) -> tuple[str, int]:
    headers, rows, _ = _parse_tabular(path, max_rows=1_000_000)
    if not headers:
        return "", 0
    col_idx = _find_column_index(headers, column)
    if col_idx < 0:
        raise HTTPException(status_code=400, detail=f"未找到列: {column}")
    seen: set[str] = set()
    lines: list[str] = []
    for row in rows:
        if col_idx >= len(row):
            continue
        val = str(row[col_idx] if row[col_idx] is not None else "").strip()
        if skip_empty and not val:
            continue
        if dedupe:
            if val in seen:
                continue
            seen.add(val)
        lines.append(val)
    return "\n".join(lines), len(lines)


def build_env(cfg: dict[str, Any]) -> dict[str, str]:
    env = dict(os.environ)
    # 子进程 Python 尽量用 UTF-8 写 stdout/stderr，便于与网页 UTF-8 一致（可在 YAML extra_env 覆盖）
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8:replace")
    # 默认绕过本机 Clash/系统代理，避免 TuShare 经 127.0.0.1:7897 读超时
    # （可在 YAML data_sources.extra_env 显式设置 HTTP_PROXY 覆盖）
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        env.pop(k, None)
    env.setdefault("NO_PROXY", "*")
    env.setdefault("no_proxy", "*")
    extra = (cfg.get("data_sources") or {}).get("extra_env") or {}
    for k, v in extra.items():
        if v is None or str(v).strip() == "":
            continue
        env[str(k)] = str(v)
    return env


def _decode_pipe_output(raw: bytes | None) -> str:
    """Windows 上子进程常为 GBK/GB18030，统一尝试多种解码减少网页乱码。"""
    if not raw:
        return ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode(sys.getfilesystemencoding() or "utf-8", errors="replace")


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE.sub("", text)


def _compact_subprocess_log(text: str) -> str:
    """去掉常见拉数 INFO / FutureWarning 行，减轻 workflow 输出区刷屏。"""
    if not text:
        return ""
    drop_markers = (
        " - INFO - ",
        "FutureWarning:",
        "Series.fillna with 'method' is deprecated",
        "WARNING: 无法导入父级db_config",
    )
    kept: list[str] = []
    for line in text.splitlines():
        if any(m in line for m in drop_markers):
            continue
        kept.append(line)
    return "\n".join(kept).strip("\n")


def _merged_log_stderr_mode(cfg: dict[str, Any]) -> str:
    r = cfg.get("runner") or {}
    m = str(r.get("merged_log_stderr", "on_error")).lower().strip()
    if m in ("always", "never", "on_error"):
        return m
    return "on_error"


def _attach_stderr_to_merged(cfg: dict[str, Any], err: str, exit_code: int) -> bool:
    if not (err or "").strip():
        return False
    mode = _merged_log_stderr_mode(cfg)
    if mode == "always":
        return True
    if mode == "never":
        return False
    return exit_code != 0


def _step_banner(step_id: str, title: str) -> str:
    return f"\n{'=' * 60}\n# [{step_id}] {title}\n{'=' * 60}\n"


def _resolve_run_mode(
    step: dict[str, Any],
    run_mode_id: str | None,
) -> tuple[str, list[str]]:
    """按 run_modes 解析实际 script / args；未指定模式时用步骤默认配置。"""
    script = str(step.get("script") or "")
    raw_args = step.get("args") or []
    args = list(raw_args) if isinstance(raw_args, list) else []
    if not run_mode_id:
        return script, args
    modes = step.get("run_modes") or []
    if not isinstance(modes, list):
        return script, args
    mode = next((m for m in modes if str(m.get("id")) == run_mode_id), None)
    if not mode:
        raise HTTPException(status_code=400, detail=f"未知运行模式: {run_mode_id}")
    if mode.get("script"):
        script = str(mode["script"])
    if "args" in mode and mode["args"] is not None:
        mode_args = mode["args"]
        if not isinstance(mode_args, list):
            raise HTTPException(status_code=400, detail=f"运行模式 {run_mode_id}: args 须为列表。")
        args = list(mode_args)
    return script, args


def run_one_step(
    cfg: dict[str, Any],
    step: dict[str, Any],
    extra_args: list[str] | None = None,
    run_mode: str | None = None,
) -> dict[str, Any]:
    global _active_proc
    step_id = str(step.get("id", ""))
    title = str(step.get("title", step_id))
    stype = str(step.get("type", "script")).lower()

    if stype in ("manual", "frontend_tool"):
        hint = "手动步骤，未执行命令。" if stype == "manual" else "前端工具，请在页面内操作。"
        log = _step_banner(step_id, title) + f"({hint})\n"
        return {
            "step_id": step_id,
            "exit_code": 0,
            "stdout": "",
            "stderr": "",
            "merged_log": log,
            "skipped": True,
        }

    script = step.get("script")
    script_name, args = _resolve_run_mode(step, run_mode)
    if not script_name or Path(script_name).name != str(script_name):
        raise HTTPException(
            status_code=400,
            detail=f"步骤 {step_id}: script 必须为项目根下的文件名（禁止子路径）。",
        )
    if extra_args:
        if not isinstance(extra_args, list):
            raise HTTPException(status_code=400, detail="extra_args 须为列表。")
        args = args + [str(a) for a in extra_args]

    root = resolve_project_root(cfg)
    script_path = root / script_name
    if not script_path.is_file():
        raise HTTPException(status_code=400, detail=f"脚本不存在: {script_path}")

    py = str(cfg.get("python_executable") or "python")
    cmd = [py, str(script_path)] + [str(a) for a in args]
    env = build_env(cfg)

    proc: subprocess.Popen[bytes] | None = None
    try:
        with _active_proc_lock:
            if _active_proc is not None and _active_proc.poll() is None:
                raise HTTPException(status_code=409, detail="已有步骤正在执行，请先停止后再运行。")
            try:
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(root),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            except OSError as e:
                raise HTTPException(status_code=500, detail=f"无法启动子进程: {e}") from e
            _active_proc = proc
        assert proc.stdout is not None and proc.stderr is not None
        out_b, err_b = proc.communicate()
    finally:
        if proc is not None:
            with _active_proc_lock:
                if _active_proc is proc:
                    _active_proc = None

    rc = int(proc.returncode if proc.returncode is not None else -1)
    out = _compact_subprocess_log(_strip_ansi(_decode_pipe_output(out_b)))
    err = _compact_subprocess_log(_strip_ansi(_decode_pipe_output(err_b)))
    banner = _step_banner(step_id, title)
    merged = banner + f"$ {' '.join(cmd)}\n\n" + out
    if _attach_stderr_to_merged(cfg, err, rc):
        merged += "\n" + err.strip() + "\n"
    merged += f"\n[exit_code={rc}]\n"

    return {
        "step_id": step_id,
        "exit_code": rc,
        "stdout": out,
        "stderr": err,
        "merged_log": merged,
        "skipped": False,
    }


app = FastAPI(title="Stock pool workflow", version="1.0")
app.include_router(payment_router)
app.include_router(auth_router)
app.include_router(membership_router)
app.include_router(onboarding_router)
app.include_router(events_router)
app.include_router(admin_router)


@app.on_event("startup")
def _mvp_startup() -> None:
    init_db()
    seed_demo_user()
    seed_admin_user()


# 可选：同目录下其它静态资源
static_dir = PROJECT_ROOT / "docs"
if static_dir.is_dir():
    app.mount("/docs-assets", StaticFiles(directory=str(static_dir)), name="docs_assets")


@app.get("/")
def index():
    html = PROJECT_ROOT / "docs" / "stock_pool_workflow.html"
    if not html.is_file():
        raise HTTPException(status_code=404, detail="docs/stock_pool_workflow.html 缺失")
    return FileResponse(
        html,
        media_type="text/html; charset=utf-8",
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/api/config")
def api_get_config():
    cfg = load_config()
    return cfg


class ConfigYamlBody(BaseModel):
    yaml_text: str


@app.put("/api/config")
def api_put_config(body: ConfigYamlBody):
    try:
        parsed = yaml.safe_load(body.yaml_text) or {}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"YAML 解析失败: {e}") from e
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=400, detail="根节点须为映射（字典）")
    merged = _default_config()
    merged.update(parsed)
    save_config(merged)
    return {"ok": True}


@app.get("/api/config/raw")
def api_get_config_raw():
    if not CONFIG_PATH.is_file():
        return Response(content="# 尚无配置文件，将使用内置默认\n", media_type="text/yaml; charset=utf-8")
    return Response(content=CONFIG_PATH.read_text(encoding="utf-8"), media_type="text/yaml; charset=utf-8")


class WorkspaceFilePut(BaseModel):
    path: str
    content: str


@app.get("/api/workspace/file")
def api_workspace_file(path: str):
    cfg = load_config()
    try:
        p = resolve_workspace_path(cfg, path)
    except HTTPException:
        raise
    if not p.is_file():
        return {"exists": False, "content": ""}
    try:
        return {"exists": True, "content": _read_text_file(p)}
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.put("/api/workspace/file")
def api_workspace_file_put(body: WorkspaceFilePut):
    cfg = load_config()
    p = resolve_workspace_path(cfg, body.path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body.content, encoding="utf-8")
    except OSError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"ok": True}


@app.get("/api/workspace/table")
def api_workspace_table(path: str, max_rows: int = _TABLE_PREVIEW_MAX):
    cfg = load_config()
    if max_rows < 1:
        max_rows = _TABLE_PREVIEW_MAX
    max_rows = min(max_rows, 2000)
    try:
        p = resolve_workspace_path(cfg, path)
    except HTTPException:
        raise
    path_key = str(p)
    suf = p.suffix.lower()
    if suf in (".xlsx", ".xls"):
        if not p.is_file():
            return {
                "exists": False,
                "path": path_key,
                "headers": [],
                "rows": [],
                "truncated": False,
                "preview_unsupported": True,
                "preview_note": "Excel 文件请在本地打开；网页内仅预览 .csv / .tsv。",
            }
        return {
            "exists": True,
            "path": path_key,
            "headers": [],
            "rows": [],
            "truncated": False,
            "preview_unsupported": True,
            "preview_note": "Excel 文件请在本地用 WPS/Excel 打开；网页内仅预览 .csv / .tsv。",
        }
    if suf in _IMAGE_SUFFIX or suf in (".md", ".markdown", ".txt"):
        # 兼容旧前端误调 table：返回可识别字段，避免裸 HTTP 400
        if suf in (".md", ".markdown"):
            kind = "markdown"
            note = "Markdown 文档请用文档预览打开。"
        elif suf == ".txt":
            kind = "text"
            note = "文本文件请用文本预览打开。"
        else:
            kind = "image"
            note = "图片请用图形预览打开。"
        return {
            "exists": p.is_file(),
            "path": path_key,
            "headers": [],
            "rows": [],
            "truncated": False,
            "preview_unsupported": True,
            "preview_kind": kind,
            "preview_note": note,
        }
    if suf not in _TABULAR_SUFFIX:
        raise HTTPException(
            status_code=400,
            detail="仅支持 .csv / .tsv 表格预览；另支持图片、.md 文档与 .txt 文本预览",
        )
    if not p.is_file():
        return {
            "exists": False,
            "path": path_key,
            "headers": [],
            "rows": [],
            "truncated": False,
        }
    try:
        headers, rows, truncated = _parse_tabular(p, max_rows)
        return {
            "exists": True,
            "path": path_key,
            "headers": headers,
            "rows": rows,
            "truncated": truncated,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法解析表格: {e}") from e


@app.get("/api/workspace/media")
def api_workspace_media(path: str):
    """工作区内图片预览（png/jpg/gif/webp/svg）。"""
    cfg = load_config()
    try:
        p = resolve_workspace_path(cfg, path)
    except HTTPException:
        raise
    suf = p.suffix.lower()
    if suf not in _IMAGE_SUFFIX:
        raise HTTPException(
            status_code=400,
            detail="仅支持图片预览：.png / .jpg / .jpeg / .gif / .webp / .svg",
        )
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在: {path}")
    media_type = _IMAGE_MEDIA_TYPES.get(suf, "application/octet-stream")
    return FileResponse(
        p,
        media_type=media_type,
        filename=p.name,
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/api/workspace/latest")
def api_workspace_latest(glob: str):
    """按修改时间返回 project_root 下匹配 glob 的最新文件（相对路径）。"""
    cfg = load_config()
    pattern = _validate_glob_pattern(glob)
    root = resolve_project_root(cfg)
    latest = _latest_glob_file(root, pattern)
    if latest is None:
        return {"exists": False, "glob": pattern, "rel_path": "", "name": ""}
    rel = _rel_path_from_root(root, latest)
    return {
        "exists": True,
        "glob": pattern,
        "rel_path": rel,
        "name": latest.name,
        "mtime": latest.stat().st_mtime,
    }


@app.get("/api/workspace/column-text")
def api_workspace_column_text(
    path: str,
    column: str,
    dedupe: bool = True,
    skip_empty: bool = True,
):
    """读取表格指定列，可选去重、跳过空值，以换行拼接为纯文本。"""
    cfg = load_config()
    if not (column or "").strip():
        raise HTTPException(status_code=400, detail="须指定 column")
    try:
        p = resolve_workspace_path(cfg, path)
    except HTTPException:
        raise
    if not p.is_file():
        return {"exists": False, "path": path, "column": column, "count": 0, "text": ""}
    if p.suffix.lower() not in _TABULAR_SUFFIX:
        raise HTTPException(status_code=400, detail="仅支持 .csv / .tsv")
    try:
        text, count = _extract_column_text(
            p,
            column.strip(),
            skip_empty=skip_empty,
            dedupe=dedupe,
        )
        return {
            "exists": True,
            "path": _rel_path_from_root(resolve_project_root(cfg), p),
            "column": column.strip(),
            "count": count,
            "text": text,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法读取列: {e}") from e


class RunStepBody(BaseModel):
    extra_args: list[str] = []
    run_mode: str | None = None


@app.post("/api/run/step/{step_id}")
async def api_run_step(step_id: str, body: RunStepBody | None = None):
    cfg = load_config()
    steps = cfg.get("steps") or []
    step = next((s for s in steps if str(s.get("id")) == step_id), None)
    if not step:
        raise HTTPException(status_code=404, detail=f"未知步骤: {step_id}")
    extra: list[str] | None = None
    run_mode: str | None = None
    if body is not None:
        if body.extra_args:
            extra = [str(a) for a in body.extra_args]
        if body.run_mode:
            run_mode = str(body.run_mode)
    try:
        return await asyncio.to_thread(run_one_step, cfg, step, extra, run_mode)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.post("/api/run/stop")
def api_run_stop():
    """终止当前由本服务启动的工作流子进程（对应「运行本步」）。"""
    with _active_proc_lock:
        p = _active_proc
    if p is not None and p.poll() is None:
        try:
            p.terminate()
        except OSError:
            pass
    return {"ok": True}
