# 数据来源：连板网 lianban.net（MCP https://lianban.net/mcp ，CC BY 4.0）
"""每个交易日 17:30 拉取连板网复盘、龙虎榜，以及题材发酵逻辑和新闻，写成 reports/YYYY-MM-DD.md。"""

from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from html import unescape
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / "reports"
LOG_PATH = REPORTS / "lianban_brief.log"
MCP_URL = "https://lianban.net/mcp"
TIANTI_URL = "https://lianban.net/tianti.html"
KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
NEWS_URL = "https://search-api-web.eastmoney.com/search/jsonp"
INDEXES = (
    ("上证", "1.000001"),
    ("深证", "0.399001"),
    ("创业板", "0.399006"),
    ("科创50", "1.000688"),
    ("上证50", "1.000016"),
    ("北证50", "0.899050"),
)
NEWS_NOISE = ("龙虎榜", "提示风险", "回购", "美股", "盘前", "晨会", "快报", "速览", "期货")
MCP_CONFIG = Path.home() / ".cursor" / "mcp.json"
TZ = ZoneInfo("Asia/Shanghai")
CHANGE_ALERT = 0.30

STOCK_RE = re.compile(
    r"([\u4e00-\u9fff]{2,8}[A-Za-zＡ-Ｚ]?)"
    r"(?:\s*·\s*(\d+天\d+板))?"
    r"(?:\s*(\d+(?:\.\d+)?万))?"
    r"\s*·\s*"
    r"(\d{2}:\d{2})"
    r"\s*·\s*开板(\d+)"
)
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)


def log(message: str) -> None:
    REPORTS.mkdir(parents=True, exist_ok=True)
    line = f"{datetime.now(TZ):%Y-%m-%d %H:%M:%S} {message}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def load_token() -> str:
    env = os.environ.get("LIANBAN_MCP_TOKEN", "").strip()
    if env:
        return env
    if not MCP_CONFIG.is_file():
        return ""
    try:
        data = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    server = (data.get("mcpServers") or {}).get("lianban") or {}
    headers = server.get("headers") or {}
    return str(headers.get("Authorization") or "").strip()


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0)
    try:
        ctx.set_alpn_protocols(["http/1.1"])
    except (NotImplementedError, ssl.SSLError):
        pass
    return ctx


def _request_urllib(url: str, payload: dict | None, headers: dict, timeout: int) -> tuple[str, str]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
        body = resp.read().decode("utf-8", "replace")
        return body, resp.headers.get("Content-Type", "")


def _request_curl(url: str, payload: dict | None, headers: dict, timeout: int) -> tuple[str, str]:
    lines = [
        "silent",
        "show-error",
        "http1.1",
        "ipv4",
        f"max-time = {int(timeout)}",
        f"url = {json.dumps(url)}",
    ]
    for key, value in headers.items():
        lines.append("header = " + json.dumps(f"{key}: {value}"))
    body_path = None
    if payload is not None:
        handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False)
        body_path = Path(handle.name)
        json.dump(payload, handle, ensure_ascii=False)
        handle.close()
        lines.append('request = "POST"')
        lines.append("data = @" + body_path.as_posix())
    try:
        completed = subprocess.run(
            ["curl.exe", "--config", "-"],
            input="\n".join(lines),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout + 5,
            check=False,
        )
    finally:
        if body_path is not None:
            body_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise OSError(detail or f"curl exit {completed.returncode}")
    return completed.stdout, "application/json"


def _request(url: str, payload: dict | None, headers: dict, timeout: int = 30) -> tuple[str, str]:
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            return _request_urllib(url, payload, headers, timeout)
        except (urllib.error.URLError, TimeoutError, OSError, ssl.SSLError) as exc:
            last_error = exc
            try:
                return _request_curl(url, payload, headers, timeout)
            except (OSError, subprocess.TimeoutExpired) as curl_exc:
                last_error = curl_exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"请求失败 {url}: {last_error}")


def _parse_mcp_body(body: str, content_type: str) -> dict:
    text = body.strip()
    if "text/event-stream" in content_type or text.startswith("event:") or text.startswith("data:"):
        chunks = []
        for line in text.splitlines():
            if line.startswith("data:"):
                chunks.append(line[5:].strip())
        text = "\n".join(chunk for chunk in chunks if chunk and chunk != "[DONE]")
    data = json.loads(text)
    if "error" in data:
        raise RuntimeError(data["error"])
    result = data.get("result") or {}
    if result.get("isError"):
        raise RuntimeError(result)
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("text"):
            parts.append(item["text"])
    if not parts:
        return result if isinstance(result, dict) else {}
    merged = parts[0] if len(parts) == 1 else "\n".join(parts)
    try:
        return json.loads(merged)
    except json.JSONDecodeError:
        return {"text": merged}


def mcp_call(tool: str, token: str, **arguments) -> dict:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "User-Agent": "lianban-daily-brief",
    }
    if token:
        headers["Authorization"] = token if token.lower().startswith("bearer ") else f"Bearer {token}"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }
    body, ctype = _request(MCP_URL, payload, headers)
    return _parse_mcp_body(body, ctype)


def fetch_html(url: str) -> str:
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
    body, _ctype = _request(url, None, headers, timeout=40)
    return body


def board_num(label: str) -> int | None:
    match = re.search(r"(\d+)", label or "")
    if match:
        return int(match.group(1))
    cn = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    for char, num in cn.items():
        if char in (label or "") and "板" in label:
            return num
    return None


def parse_stock_blob(text: str) -> list[dict]:
    cleaned = re.sub(r"\s+", " ", text or "").strip()
    found = list(STOCK_RE.finditer(cleaned))
    stocks = []
    for index, match in enumerate(found):
        end = found[index + 1].start() if index + 1 < len(found) else len(cleaned)
        theme = cleaned[match.end() : end].strip(" ·|")
        theme = re.sub(r"^(同屏|⧉)+\s*", "", theme).strip()
        stocks.append(
            {
                "name": match.group(1),
                "rhythm": match.group(2) or "",
                "theme": theme,
            }
        )
    return stocks


def _coerce_stocks(value) -> list[dict]:
    if isinstance(value, dict):
        value = value.get("stocks") or value.get("names") or value.get("list") or value.get("items") or []
    if isinstance(value, str):
        return parse_stock_blob(value)
    stocks = []
    if not isinstance(value, list):
        return stocks
    for item in value:
        if isinstance(item, str):
            stocks.append({"name": item, "rhythm": "", "theme": ""})
        elif isinstance(item, dict):
            name = item.get("name") or item.get("n") or item.get("stock") or ""
            if not name:
                continue
            stocks.append(
                {
                    "name": str(name),
                    "code": str(item.get("code") or item.get("symbol") or item.get("c") or "").strip(),
                    "rhythm": str(item.get("rhythm") or item.get("days") or ""),
                    "theme": str(item.get("theme") or item.get("reason") or item.get("r") or ""),
                }
            )
    return stocks


def _coerce_ladder(obj) -> list[dict]:
    rows: list[dict] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            num = board_num(str(key))
            if num is None:
                continue
            rows.append({"board": num, "stocks": _coerce_stocks(value)})
        return rows
    if isinstance(obj, list):
        for item in obj:
            if not isinstance(item, dict):
                continue
            num = None
            for key in ("board", "height", "level", "b", "n"):
                if key in item:
                    num = board_num(str(item[key]))
                    break
            if num is None:
                continue
            payload = item.get("stocks") or item.get("names") or item.get("list") or item.get("items") or []
            rows.append({"board": num, "stocks": _coerce_stocks(payload)})
    return rows


def ladder_from_review(review: dict) -> list[dict]:
    for key in ("ladder", "tianti", "boards", "board_ladder", "streak_ladder"):
        if key in review:
            rows = _coerce_ladder(review[key])
            if rows:
                return rows
    for value in review.values():
        if isinstance(value, (dict, list)):
            rows = _coerce_ladder(value)
            if rows and any(row["stocks"] for row in rows):
                return rows
    return []


def _stocks_in_cell(cell: str) -> list[dict]:
    stocks = []
    for part in cell.split('<div class="tti-s"')[1:]:
        name_match = re.search(r'data-nm="([^"]*)"', part)
        if not name_match:
            continue
        theme_match = re.search(r'<div class="r">([^<]*)</div>', part)
        meta_match = re.search(r'<div class="m[^"]*">([^<]*)</div>', part)
        rhythm_match = re.search(r"(\d+天\d+板)", meta_match.group(1)) if meta_match else None
        code_match = re.search(r'data-c="([^"]*)"', part)
        stocks.append(
            {
                "name": unescape(name_match.group(1)).strip(),
                "code": unescape(code_match.group(1)).strip() if code_match else "",
                "rhythm": rhythm_match.group(1) if rhythm_match else "",
                "theme": unescape(theme_match.group(1)).strip() if theme_match else "",
            }
        )
    return stocks


def ladders_from_tianti(html: str) -> dict[str, list[dict]]:
    """连板天梯页按列表头日期（MM-DD）分列。"""
    thead_match = re.search(r"<thead>(.*?)</thead>", html, re.S)
    if not thead_match:
        return {}
    headers = re.findall(r"<th\b[^>]*>(.*?)</th>", thead_match.group(1), re.S)
    columns: list[tuple[int, str]] = []
    for index, header in enumerate(headers):
        plain = re.sub(r"<[^>]+>", "", header)
        found = re.search(r"(\d{2}-\d{2})", plain)
        if not found:
            continue
        columns.append((index - 1, found.group(1)))
    if not columns:
        return {}
    buckets: dict[str, list[dict]] = {label: [] for _, label in columns}
    for board, row_html in re.findall(r'<tr data-h="(\d+)"[^>]*>(.*?)</tr>', html, re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.S)
        for column, label in columns:
            if column < 0 or column >= len(cells):
                continue
            buckets[label].append({"board": int(board), "stocks": _stocks_in_cell(cells[column])})
    return buckets


def ladder_from_tianti(html: str, day: str) -> list[dict]:
    return ladders_from_tianti(html).get(day[5:], [])


def top_tiers(rows: list[dict], limit: int = 3) -> list[dict]:
    ranked = [row for row in rows if isinstance(row.get("board"), int)]
    ranked.sort(key=lambda row: row["board"], reverse=True)
    return ranked[:limit]


def top_themes(review: dict, limit: int = 3) -> list[dict]:
    themes = [item for item in (review.get("themes") or []) if isinstance(item, dict)]
    themes.sort(key=lambda item: item.get("limit_up") or 0, reverse=True)
    return themes[:limit]


def youzi_names(seats: list | None) -> list[str]:
    names = []
    for seat in seats or []:
        if not isinstance(seat, dict) or not seat.get("yz"):
            continue
        label = (seat.get("g") or seat.get("n") or "").strip()
        if label and label not in names:
            names.append(label)
    return names


def top_lhb(lhb: dict, limit: int = 5) -> list[dict]:
    stocks = [item for item in (lhb.get("stocks") or []) if isinstance(item, dict)]
    daily = [item for item in stocks if item.get("span", 1) == 1]
    pool = daily or stocks
    best: dict[str, dict] = {}
    for item in pool:
        code = str(item.get("code") or item.get("name") or "")
        prev = best.get(code)
        if prev is None or (item.get("net") or 0) > (prev.get("net") or 0):
            best[code] = item
    ranked = sorted(best.values(), key=lambda item: item.get("net") or 0, reverse=True)
    return ranked[:limit]


def fmt_yuan(value) -> str:
    if value is None:
        return "—"
    number = float(value)
    sign = "-" if number < 0 else ""
    amount = abs(number)
    if amount >= 1e8:
        return f"{sign}{amount / 1e8:.2f}亿"
    if amount >= 1e4:
        return f"{sign}{amount / 1e4:.0f}万"
    return f"{sign}{amount:.0f}元"


def fmt_pct_point(value) -> str:
    if value is None:
        return "—"
    number = float(value)
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.2f}%"


def stock_label(stock: dict) -> str:
    parts = [stock.get("name") or ""]
    if stock.get("rhythm"):
        parts.append(stock["rhythm"])
    text = " · ".join(part for part in parts if part)
    if stock.get("theme"):
        text += f"（{stock['theme']}）"
    return text


def fmt_turnover_market(value) -> str:
    if value is None:
        return "—"
    number = float(value)
    if number >= 1e12:
        return f"{number / 1e12:.2f}万亿"
    if number >= 1e8:
        return f"{number / 1e8:.2f}亿"
    return fmt_yuan(number)


def index_line(indices: list[dict]) -> str:
    parts = []
    for item in indices:
        name = str(item.get("name") or "").strip()
        if not name or item.get("pct") is None:
            continue
        parts.append(f"{name} {fmt_pct_point(item.get('pct'))}")
    return "、".join(parts)


def _theme_keywords(name: str) -> list[str]:
    text = (name or "").strip()
    keys = [text] if text else []
    if text.endswith("概念") and len(text) > 2:
        keys.append(text[:-2])
    return keys


_QUESTION_RE = re.compile(r"[?？]|有哪些|为什么|为何|是什么|如何")
_LOGIC_WORDS = ("景气", "拐点", "扩产", "订单", "涨价", "政策", "需求", "逻辑", "催化", "产能", "回暖", "商业化")
_DRIVER_WORDS = _LOGIC_WORDS + ("签约", "大单")
_REACTION_RE = re.compile(r"涨幅|涨超|大涨|爆火|反弹|走高|走强|ETF|港股|领涨")
_TEASER_RE = re.compile(r"曝光|有哪些|发生了什么|一文看懂|揭秘|一图速览|背后催化因素")


def _is_question(text: str) -> bool:
    return bool(_QUESTION_RE.search(text or ""))


def _is_teaser(text: str) -> bool:
    return bool(_TEASER_RE.search(text or ""))


def logic_score(title: str, keywords: list[str]) -> int:
    score = 0
    if any(key and key in title for key in keywords):
        score += 2
    if any(word in title for word in _LOGIC_WORDS):
        score += 4
    if any(word in title for word in NEWS_NOISE):
        score -= 3
    if _is_question(title):
        score -= 5
    if _is_teaser(title):
        score -= 8
    if len(title) <= 22:
        score += 1
    return score


def _logic_clauses(text: str) -> list[str]:
    raw = re.sub(r"\s+", "", text or "")
    raw = re.sub(r"【[^】]*】", "", raw)
    found = []
    for part in re.split(r"[。！!？?；;]", raw):
        part = part.strip("，,、：:")
        if len(part) < 6 or _is_question(part):
            continue
        found.append(part)
    return found


def _driver_bit(clause: str) -> str:
    bits = [bit.strip() for bit in re.split(r"[，,]", clause) if bit.strip()]
    drivers = []
    for bit in bits:
        if _is_question(bit):
            continue
        has_driver = any(word in bit for word in _DRIVER_WORDS)
        reaction = bool(_REACTION_RE.search(bit))
        if reaction and not has_driver:
            continue
        if _is_teaser(bit):
            continue
        drivers.append(bit)
    hinted = [bit for bit in drivers if any(word in bit for word in _DRIVER_WORDS)]
    chosen = hinted[0] if hinted else (drivers[0] if drivers else "")
    quoted = re.search(r"[“\"]([^”\"]{4,24})[”\"]", chosen)
    if quoted and any(word in quoted.group(1) for word in _DRIVER_WORDS):
        return quoted.group(1)
    if "：" in chosen:
        tail = chosen.split("：")[-1].strip()
        if any(word in tail for word in _DRIVER_WORDS) and 4 <= len(tail) <= 22:
            return tail
    if len(chosen) > 22:
        short = [bit for bit in hinted if len(bit) <= 22]
        return short[0] if short else ""
    return chosen


def summarize_logic(title: str, content: str, theme: str = "") -> str:
    best = ""
    best_score = -10**9
    for clause in _logic_clauses(title) + _logic_clauses(content):
        bit = _driver_bit(clause)
        if not bit or _is_question(bit):
            continue
        score = 1
        if any(word in bit for word in _DRIVER_WORDS):
            score += 4
        if theme and any(key and key in bit for key in _theme_keywords(theme)):
            score += 1
        if score > best_score:
            best_score = score
            best = bit
    return best


def _news_title(row: dict) -> str:
    text = re.sub(r"\s+", " ", str(row.get("title") or "")).strip()
    return text.replace("｜", " ").replace("[", " ").replace("]", " ")


def pick_theme_story(rows: list[dict], name: str, day: str) -> dict:
    keywords = _theme_keywords(name)
    best: dict | None = None
    best_score = -10**9
    for row in rows:
        if not str(row.get("date") or "").startswith(day):
            continue
        title = _news_title(row)
        if not title:
            continue
        has_keyword = any(key in title for key in keywords)
        noisy = any(word in title for word in NEWS_NOISE)
        score = logic_score(title, keywords)
        if not has_keyword and score < 2:
            continue
        if noisy and not has_keyword:
            continue
        if score > best_score:
            best_score = score
            best = row
    if not best:
        return {"logic": "", "news": "", "url": ""}
    title = _news_title(best)
    logic = summarize_logic(title, str(best.get("content") or ""), name)
    url = str(best.get("url") or "").strip()
    if url and not url.startswith("http"):
        url = ""
    return {"logic": logic, "news": title, "url": url}


def pick_theme_logic(rows: list[dict], name: str, day: str) -> str:
    return pick_theme_story(rows, name, day)["logic"]


def _collect_news(keyword: str, day: str, page_limit: int = 12) -> list[dict]:
    rows: list[dict] = []
    for _page in range(1, page_limit + 1):
        batch = _news_page(keyword, _page)
        if not batch:
            break
        rows.extend(batch)
        newest = str(batch[0].get("date") or "")
        oldest = str(batch[-1].get("date") or "")
        if newest and newest < day:
            break
        if oldest and oldest < day:
            break
    return rows


def _kline_bar(secid: str, day: str) -> dict | None:
    end = day.replace("-", "")
    query = urllib.parse.urlencode(
        {
            "secid": secid,
            "klt": "101",
            "fqt": "1",
            "end": end,
            "lmt": "5",
            "fields1": "f1",
            "fields2": "f51,f57,f59",
        }
    )
    body, _ctype = _request(
        f"{KLINE_URL}?{query}",
        None,
        {"User-Agent": BROWSER_UA, "Accept": "application/json", "Referer": "https://quote.eastmoney.com/"},
        timeout=20,
    )
    data = json.loads(body)
    for item in ((data.get("data") or {}).get("klines") or []):
        parts = str(item).split(",")
        if len(parts) < 3 or parts[0] != day:
            continue
        return {"amount": float(parts[1]), "pct": float(parts[2])}
    return None


def fetch_market(day: str) -> dict:
    indices = []
    amounts: dict[str, float] = {}
    for name, secid in INDEXES:
        bar = _kline_bar(secid, day)
        if bar is None:
            continue
        indices.append({"name": name, "pct": bar["pct"]})
        amounts[name] = bar["amount"]
    turnover = None
    if "上证" in amounts and "深证" in amounts:
        turnover = amounts["上证"] + amounts["深证"]
    return {"indices": indices, "turnover": turnover}


def _news_page(keyword: str, page: int) -> list[dict]:
    param = {
        "uid": "",
        "keyword": keyword,
        "type": ["cmsArticleWebOld"],
        "client": "web",
        "clientType": "web",
        "clientVersion": "curr",
        "param": {
            "cmsArticleWebOld": {
                "searchScope": "default",
                "sort": "time",
                "pageIndex": page,
                "pageSize": 20,
                "preTag": "",
                "postTag": "",
            }
        },
    }
    query = urllib.parse.urlencode({"cb": "cb", "param": json.dumps(param, ensure_ascii=False)})
    body, _ctype = _request(
        f"{NEWS_URL}?{query}",
        None,
        {"User-Agent": BROWSER_UA, "Accept": "*/*", "Referer": "https://so.eastmoney.com/"},
        timeout=20,
    )
    text = body.strip()
    start = text.find("(")
    end = text.rfind(")")
    if start >= 0 and end > start:
        text = text[start + 1 : end]
    data = json.loads(text)
    rows = (data.get("result") or {}).get("cmsArticleWebOld") or []
    return rows if isinstance(rows, list) else []


def fetch_theme_logics(themes: list[dict], day: str) -> list[dict]:
    logics = []
    for theme in themes:
        name = str(theme.get("name") or "").strip()
        if not name:
            continue
        keyword = _theme_keywords(name)[-1]
        rows = _collect_news(keyword, day)
        story = pick_theme_story(rows, name, day)
        logics.append(
            {
                "name": name,
                "title": story["logic"],
                "news": story["news"],
                "url": story["url"],
            }
        )
    return logics


def first_board_leader(rows: list[dict] | None) -> dict | None:
    """龙头 = 最高板名单里的第一只。"""
    leaders = highest_leaders(rows or [])
    return leaders[0] if leaders else None


def highest_leaders(rows: list[dict]) -> list[dict]:
    """最高板且有个股的那一档，顺序与天梯页一致。"""
    ranked: list[tuple[int, list]] = []
    for row in rows or []:
        board = row.get("board")
        stocks = row.get("stocks") or []
        if not isinstance(board, int) or not stocks:
            continue
        ranked.append((board, stocks))
    if not ranked:
        return []
    top = max(board for board, _stocks in ranked)
    leaders = []
    for board, stocks in ranked:
        if board != top:
            continue
        for stock in stocks:
            item = dict(stock)
            item["board"] = board
            leaders.append(item)
    return leaders


def _rows_have_stocks(rows: list[dict] | None) -> bool:
    return any(row.get("stocks") for row in (rows or []))


def _leaders_have_codes(rows: list[dict] | None) -> bool:
    leaders = highest_leaders(rows or [])
    return bool(leaders) and all(str(stock.get("code") or "").strip() for stock in leaders)


def _leader_name(stock: dict | None) -> str:
    return str((stock or {}).get("name") or "").strip()


def _format_board_leader(stock: dict | None) -> str:
    name = _leader_name(stock)
    if not name:
        return "未取到"
    theme = str((stock or {}).get("theme") or "").strip()
    if theme:
        return f"{name}（{theme}）"
    return name


def leader_section(
    today_rows: list[dict],
    prev_rows: list[dict] | None,
    prev_day: str | None,
) -> list[str]:
    today = first_board_leader(today_rows)
    prev = first_board_leader(prev_rows) if prev_day else None
    lines = ["## 每日龙头切换", "", "最高板的第一只。", ""]
    lines.append(f"- 今日：{_format_board_leader(today)}")
    if prev_day:
        lines.append(f"- 昨日（{prev_day}）：{_format_board_leader(prev)}")
    else:
        lines.append("- 昨日：未取到上一交易日")
    today_name = _leader_name(today)
    prev_name = _leader_name(prev)
    if not prev_day or not prev_name:
        lines.append("- 切换：无法对照上一交易日")
    elif today_name and today_name == prev_name:
        lines.append(f"- 切换：{today_name} 未切换")
    else:
        lines.append(f"- 切换：{prev_name} → {today_name or '—'}")
    lines.append("")
    return lines


def change_alert(today_up, prev_up, prev_day: str) -> str | None:
    if today_up is None or prev_up is None:
        return None
    today_up = float(today_up)
    prev_up = float(prev_up)
    if prev_up == 0:
        if today_up == 0:
            return None
        return (
            f"> **⚠ 涨停家数显著变化：** 今日 {today_up:.0f} 家，"
            f"上一交易日（{prev_day}）为 0，变化超过 30%。"
        )
    ratio = (today_up - prev_up) / prev_up
    if abs(ratio) <= CHANGE_ALERT:
        return None
    return (
        f"> **⚠ 涨停家数显著变化：** 今日 {today_up:.0f} 家，"
        f"上一交易日（{prev_day}）{prev_up:.0f} 家，"
        f"变化 {ratio:+.1%}，超过 30%。"
    )


def render_report(
    day: str,
    review: dict,
    prev_review: dict | None,
    prev_day: str | None,
    lhb: dict,
    tiers: list[dict],
    ladder_note: str,
    market: dict | None = None,
    logics: list[dict] | None = None,
    today_ladder: list[dict] | None = None,
    prev_ladder: list[dict] | None = None,
) -> str:
    kpi = review.get("kpi") or {}
    prev_kpi = (prev_review or {}).get("kpi") or {}
    lines: list[str] = []
    alert = change_alert(kpi.get("limit_up"), prev_kpi.get("limit_up"), prev_day or "")
    if alert:
        lines.extend([alert, ""])
    lines.append(f"# {day} A股复盘简报")
    lines.append("")
    status = review.get("status_label") or review.get("status") or ""
    phase = kpi.get("emotion_phase") or ""
    if status or phase:
        bits = [bit for bit in (status, phase) if bit]
        lines.append(" / ".join(bits))
        lines.append("")
    market = market or {}
    lines.extend(["## 行情 KPI", ""])
    indices = index_line(market.get("indices") or [])
    if indices:
        lines.extend([indices, ""])
    lines.extend(
        [
            "| 指标 | 数值 |",
            "| --- | --- |",
            f"| 涨停 | {kpi.get('limit_up', '—')} |",
            f"| 连板 | {kpi.get('lianban', '—')} |",
            f"| 最高板 | {kpi.get('max_board', '—')}板 |",
            f"| 封板率 | {kpi.get('seal_rate_pct', '—')}% |",
            f"| 炸板 | {kpi.get('zhaban', '—')} |",
            f"| 两市成交额 | {fmt_turnover_market(market.get('turnover'))} |",
            "",
        ]
    )
    for index, item in enumerate(logics or [], 1):
        title = item.get("title") or "—"
        line = f"{index}. {item.get('name', '—')} — {title}"
        news = str(item.get("news") or "").strip()
        url = str(item.get("url") or "").strip()
        if news and news != title:
            if url:
                line += f"｜[{news}]({url})"
            else:
                line += f"｜{news}"
        lines.append(line)
    if logics:
        lines.append("")
    lines.extend(
        leader_section(
            today_ladder if today_ladder is not None else tiers,
            prev_ladder,
            prev_day,
        )
    )
    lines.extend(["## 连板天梯前三档", ""])
    if ladder_note:
        lines.extend([ladder_note, ""])
    if not tiers:
        lines.append("本次未取到分档个股名单。")
        lines.append("")
    for tier in tiers:
        stocks = tier.get("stocks") or []
        lines.append(f"### {tier['board']}板（{len(stocks)}只）")
        lines.append("")
        if not stocks:
            lines.append("- 无")
        else:
            for stock in stocks:
                lines.append(f"- {stock_label(stock)}")
        lines.append("")
    lines.extend(["## 涨停家数最多的三个题材", ""])
    themes = top_themes(review, 3)
    if not themes:
        lines.append("无题材数据。")
        lines.append("")
    for index, theme in enumerate(themes, 1):
        lines.append(f"{index}. {theme.get('name', '—')} — {theme.get('limit_up', '—')}家")
    lines.extend(["", "## 龙虎榜净买额前五", ""])
    leaders = top_lhb(lhb, 5)
    if not leaders:
        lines.append("无龙虎榜数据。")
        lines.append("")
    else:
        lines.extend(
            [
                "| 名次 | 代码 | 名称 | 净买额 | 涨幅 | 游资席位 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for index, item in enumerate(leaders, 1):
            seats = item.get("seats") or {}
            buy = youzi_names(seats.get("buy"))
            sell = youzi_names(seats.get("sell"))
            marks = []
            if buy:
                marks.append("买入：" + "、".join(buy))
            if sell:
                marks.append("卖出：" + "、".join(sell))
            seat_text = "；".join(marks) if marks else "—"
            lines.append(
                "| {rank} | {code} | {name} | {net} | {chg} | {seats} |".format(
                    rank=index,
                    code=item.get("code") or "—",
                    name=item.get("name") or "—",
                    net=fmt_yuan(item.get("net")),
                    chg=fmt_pct_point(item.get("chg")),
                    seats=seat_text,
                )
            )
        lines.append("")
    page = review.get("page") or f"https://lianban.net/days/{day}.html"
    sources = ["连板网 lianban.net"]
    if indices or market.get("turnover") is not None or any((item.get("title") or "") for item in (logics or [])):
        sources.append("指数、成交额与题材新闻：东方财富")
    lines.extend(
        [
            f"原文：{page}",
            "",
            "数据来源：" + "；".join(sources),
            "",
        ]
    )
    return "\n".join(lines)


def resolve_day(token: str, explicit: str | None) -> tuple[str, list[str]] | None:
    calendar = mcp_call("list_trade_dates", token, limit=10)
    dates = [str(item) for item in (calendar.get("dates") or [])]
    if explicit:
        if explicit not in dates:
            log(f"{explicit} 不在连板网可查交易日中，跳过")
            return None
        return explicit, dates
    today = datetime.now(TZ).strftime("%Y-%m-%d")
    if today in dates:
        return today, dates
    latest = mcp_call("get_daily_review", token)
    latest_day = str((latest.get("kpi") or {}).get("date") or "")
    if latest_day == today:
        return today, dates
    log(f"{today} 不是可查交易日（最近交易日 {dates[0] if dates else latest_day or '未知'}），跳过")
    return None


def build(day: str, dates: list[str], token: str) -> Path:
    review = mcp_call("get_daily_review", token, date=day)
    actual = str((review.get("kpi") or {}).get("date") or day)
    if actual != day:
        raise RuntimeError(f"复盘日期 {actual} 与目标 {day} 不一致")
    lhb = mcp_call("get_lhb", token, date=day, top=40)
    prev_review = None
    prev_day = None
    if day in dates:
        pos = dates.index(day)
        if pos + 1 < len(dates):
            prev_day = dates[pos + 1]
            prev_review = mcp_call("get_daily_review", token, date=prev_day)
    ladder_note = ""
    rows = ladder_from_review(review)
    prev_rows = ladder_from_review(prev_review) if prev_review else []
    tianti_map: dict[str, list[dict]] = {}
    need_tianti = not _rows_have_stocks(rows) or (bool(prev_day) and not _rows_have_stocks(prev_rows))
    if need_tianti or not _leaders_have_codes(rows) or (prev_day and not _leaders_have_codes(prev_rows)):
        try:
            tianti_map = ladders_from_tianti(fetch_html(TIANTI_URL))
        except Exception as exc:
            log(f"天梯页获取失败：{exc}")
            tianti_map = {}
    if not _rows_have_stocks(rows):
        rows = tianti_map.get(day[5:], [])
        if rows:
            ladder_note = "个股名单取自连板天梯页（当日复盘接口未附逐只名单）。"
    if prev_day and not _rows_have_stocks(prev_rows):
        prev_rows = tianti_map.get(prev_day[5:], [])
    leader_today = rows
    leader_prev = prev_rows
    today_tianti = tianti_map.get(day[5:], [])
    if _rows_have_stocks(today_tianti) and not _leaders_have_codes(rows):
        leader_today = today_tianti
    if prev_day:
        prev_tianti = tianti_map.get(prev_day[5:], [])
        if _rows_have_stocks(prev_tianti) and not _leaders_have_codes(prev_rows):
            leader_prev = prev_tianti
    tiers = top_tiers(rows, 3)
    market = {"indices": [], "turnover": None}
    logics: list[dict] = []
    try:
        market = fetch_market(day)
    except Exception as exc:
        log(f"指数与成交额获取失败：{exc}")
    try:
        # 每日简报固定带上涨停家数前三题材的发酵逻辑和新闻。
        logics = fetch_theme_logics(top_themes(review, 3), day)
    except Exception as exc:
        log(f"题材新闻获取失败：{exc}")
        logics = [{"name": item.get("name") or "—", "title": ""} for item in top_themes(review, 3)]
    text = render_report(
        day,
        review,
        prev_review,
        prev_day,
        lhb,
        tiers,
        ladder_note,
        market,
        logics,
        leader_today,
        leader_prev,
    )
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{day}.md"
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def self_test() -> None:
    html = """
    <table><thead><tr><th>板位</th><th><b>11-05</b></th><th><b>11-04</b></th></tr></thead>
    <tbody>
      <tr data-h="4"><th>4板</th><td>
        <div class="tti-s" data-c="002578"><a data-nm="闽发铝业">闽发铝业</a><div class="r">光伏支架</div></div>
        <div class="tti-s" data-c="601599"><a data-nm="浙文影业">浙文影业</a><div class="r">AI视频</div></div>
      </td><td>
        <div class="tti-s" data-c="600000"><a data-nm="昨日龙头">昨日龙头</a><div class="r">机器人</div></div>
      </td></tr>
      <tr data-h="3"><th>3板</th><td>
        <div class="tti-s"><a data-nm="鲁阳节能">鲁阳节能</a><div class="m">5天4板104万</div><div class="r">锂电池</div></div>
      </td><td></td></tr>
      <tr data-h="2"><th>2板</th><td>
        <div class="tti-s"><a data-nm="深中华A">深中华A</a><div class="r">黄金</div></div>
      </td><td></td></tr>
      <tr data-h="1"><th>1板</th><td>
        <div class="tti-s"><a data-nm="赛伍技术">赛伍技术</a><div class="r">光伏</div></div>
      </td><td></td></tr>
    </tbody></table>
    """
    columns = ladders_from_tianti(html)
    rows = columns["11-05"]
    tiers = top_tiers(rows, 3)
    assert [row["board"] for row in tiers] == [4, 3, 2], tiers
    assert [stock["name"] for stock in tiers[0]["stocks"]] == ["闽发铝业", "浙文影业"]
    assert tiers[0]["stocks"][0]["code"] == "002578"
    assert tiers[0]["stocks"][0]["theme"] == "光伏支架"
    prev_rows = columns["11-04"]
    assert highest_leaders(prev_rows)[0]["code"] == "600000"
    assert first_board_leader(rows)["name"] == "闽发铝业"
    assert first_board_leader(prev_rows)["name"] == "昨日龙头"
    switched = "\n".join(leader_section(rows, prev_rows, "2026-11-04"))
    assert "今日：闽发铝业（光伏支架）" in switched
    assert "切换：昨日龙头 → 闽发铝业" in switched
    assert "002578" not in switched
    assert "浙文影业" not in switched
    same = "\n".join(leader_section(rows, rows, "2026-11-04"))
    assert "切换：闽发铝业 未切换" in same
    missing = "\n".join(leader_section(rows, [], None))
    assert "无法对照上一交易日" in missing
    assert tiers[1]["stocks"][0]["rhythm"] == "5天4板"
    assert tiers[2]["stocks"][0]["name"] == "深中华A"
    alert = change_alert(84, 118, "2026-11-04")
    assert alert is None
    assert change_alert(150, 100, "2026-11-04")
    assert change_alert(70, 118, "2026-11-04")
    assert fmt_turnover_market(2.12e12) == "2.12万亿"
    assert index_line([{"name": "上证", "pct": 0.1}, {"name": "深证", "pct": -1.21}]) == "上证 +0.10%、深证 -1.21%"
    news_rows = [
        {"date": "2026-11-06 08:00:00", "title": "次日晨会看光伏"},
        {"date": "2026-11-05 21:13:17", "title": "深股通现身16只个股龙虎榜"},
        {"date": "2026-11-05 21:00:00", "title": "金刚光伏子公司签不超15.36亿元算力大单"},
        {"date": "2026-11-05 18:00:00", "title": "光储产业链景气度边际回暖"},
    ]
    assert pick_theme_logic(news_rows, "光伏", "2026-11-05") == "光储产业链景气度边际回暖"
    teaser_rows = [
        {
            "date": "2026-11-05 16:23:50",
            "title": "光伏设备板块两日累计涨幅超11%，背后催化因素曝光",
            "content": "",
        },
        {
            "date": "2026-11-05 20:26:04",
            "title": "董事长透露“明年储能订单翻倍”后，阳光电源股价躁动",
            "content": "",
            "url": "https://finance.eastmoney.com/a/example.html",
        },
    ]
    story = pick_theme_story(teaser_rows, "光伏", "2026-11-05")
    assert story["logic"] == "明年储能订单翻倍"
    assert "阳光电源" in story["news"]
    assert story["url"].startswith("https://")
    question = "两日累计涨幅超11%！光伏设备板块爆火，背后催化因素有哪些？"
    assert summarize_logic(question, "光伏主链订单回暖。", "光伏") == "光伏主链订单回暖"
    assert "？" not in summarize_logic(question, "光伏主链订单回暖。", "光伏")
    assert summarize_logic("国产大模型商业化加速，催化AI应用行情，传媒ETF鹏涨超4%", "", "AI应用") == "国产大模型商业化加速"
    assert summarize_logic("智能驾驶与机器人催化升温，港股汽车板块迎来反弹", "", "机器人概念") == "智能驾驶与机器人催化升温"
    assert summarize_logic("董事长透露“明年储能订单翻倍”后，阳光电源股价躁动", "", "光伏") == "明年储能订单翻倍"
    review = {
        "status_label": "收盘复盘",
        "kpi": {
            "limit_up": 84,
            "lianban": 21,
            "max_board": 4,
            "seal_rate_pct": 63.6,
            "zhaban": 48,
            "emotion_phase": "升温期",
        },
        "themes": [{"name": "光伏", "limit_up": 18}],
    }
    report = render_report(
        "2026-11-05",
        review,
        {"themes": [{"name": "机器人", "limit_up": 9}]},
        "2026-11-04",
        {},
        [],
        "",
        {"indices": [{"name": "上证", "pct": 0.1}], "turnover": 2.12e12},
        [
            {
                "name": "光伏",
                "title": "光储产业链景气度边际回暖",
                "news": "董事长透露明年储能订单翻倍",
                "url": "https://finance.eastmoney.com/a/1.html",
            },
            {
                "name": "AI应用",
                "title": "AI应用商业化",
                "news": "国产大模型商业化加速",
                "url": "https://finance.eastmoney.com/a/2.html",
            },
        ],
        rows,
        prev_rows,
    )
    assert "| 炸板 | 48 |" in report
    assert "## 每日龙头切换" in report
    assert "今日：闽发铝业（光伏支架）" in report
    assert "切换：昨日龙头 → 闽发铝业" in report
    assert "002578" not in report
    assert "| 两市成交额 | 2.12万亿 |" in report
    assert "上证 +0.10%" in report
    assert "1. 光伏 — 光储产业链景气度边际回暖｜[董事长透露明年储能订单翻倍](https://finance.eastmoney.com/a/1.html)" in report
    assert "2. AI应用 — AI应用商业化｜[国产大模型商业化加速](https://finance.eastmoney.com/a/2.html)" in report
    assert "东方财富" in report
    print("self-test ok")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成连板网每日复盘简报")
    parser.add_argument("--date", help="指定交易日 YYYY-MM-DD，默认今天")
    parser.add_argument("--self-test", action="store_true", help="只跑本地解析自测")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    token = load_token()
    try:
        resolved = resolve_day(token, args.date)
        if resolved is None:
            return 0
        day, dates = resolved
        path = build(day, dates, token)
    except Exception as exc:
        log(f"生成失败：{exc}")
        return 1
    log(f"已写入 {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
