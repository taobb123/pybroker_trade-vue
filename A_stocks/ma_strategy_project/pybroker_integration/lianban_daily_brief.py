# 数据来源：连板网 lianban.net（MCP https://lianban.net/mcp ，CC BY 4.0）
"""每个交易日 17:30 拉取连板网复盘、龙虎榜、炸板与晋级，以及题材发酵逻辑和新闻，写成 reports/YYYY-MM-DD.md。"""

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
ZB_POOL_URL = "https://push2ex.eastmoney.com/getTopicZBPool"
INDUSTRY_URL = "https://push2.eastmoney.com/api/qt/ulist.np/get"
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
            buckets[label].append(
                {
                    "board": int(board),
                    "stocks": _stocks_in_cell(cells[column]),
                    "rate": _cell_rate(cells[column]),
                }
            )
    return buckets


def _cell_rate(cell: str) -> dict | None:
    head = re.search(r'<div class="hd[^"]*">(.*?)</div>', cell, re.S)
    if not head:
        return None
    plain = re.sub(r"<[^>]+>", " ", head.group(1))
    plain = re.sub(r"\s+", " ", plain)
    count_match = re.search(r"共(\d+)只", plain)
    rate_match = re.search(r"(\d+)进(\d+)\s+([\d.]+)%", plain)
    if not count_match and not rate_match:
        return None
    rate: dict = {"count": int(count_match.group(1)) if count_match else None}
    if rate_match:
        rate["from_board"] = int(rate_match.group(1))
        rate["to_board"] = int(rate_match.group(2))
        rate["pct"] = float(rate_match.group(3))
    return rate


def ladder_from_tianti(html: str, day: str) -> list[dict]:
    return ladders_from_tianti(html).get(day[5:], [])


def boards_from_two(rows: list[dict]) -> list[dict]:
    """2 板及以上，从最高有个股的板位列到最低有个股的板位。

    更高处的空行丢掉（多日表格留下的表头）。两端有个股时，中间缺档保留为空板。
    """
    by_board: dict[int, list] = {}
    for row in rows or []:
        board = row.get("board")
        if not isinstance(board, int) or board < 2:
            continue
        stocks = list(row.get("stocks") or [])
        prev = by_board.get(board)
        if prev is None or (not prev and stocks):
            by_board[board] = stocks
    occupied = [board for board, stocks in by_board.items() if stocks]
    if not occupied:
        return []
    high, low = max(occupied), min(occupied)
    return [{"board": board, "stocks": by_board.get(board, [])} for board in range(high, low - 1, -1)]


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


UP_PHASES = {"修复期", "升温期"}
DOWN_PHASES = {"高潮期", "降温期"}
VOTE_SCORE = {
    "守住": 1,
    "收缩": 1,
    "起板向上": 1,
    "未守住": -1,
    "炸板": -1,
    "走弱": -1,
    "扩张": -1,
    "起板向下": -1,
    "高位向下": -1,
}


def _phase_key(phase: str) -> str:
    text = str(phase or "").strip()
    if text in {"修复", "升温", "高潮", "降温", "退潮", "冰点"}:
        return text + "期"
    return text


def _token_vote(token: str) -> int:
    word = str(token or "").strip().split("（")[0].strip()
    return VOTE_SCORE.get(word, 0)


def _pct_direction(today: float | None, prev: float | None) -> str:
    if today is None or prev is None:
        return "缺失"
    if today > prev:
        return "向上"
    if today < prev:
        return "向下"
    return "持平"


def _stock_key(stock: dict) -> str:
    code = str(stock.get("code") or "").strip()
    if code:
        return code
    return str(stock.get("name") or "").strip()


def promotion_levels(today_rows: list[dict], prev_rows: list[dict]) -> list[dict]:
    """按天梯行头的 N进N+1 口径列出晋级与未晋级。"""
    today_by = {row.get("board"): row for row in today_rows or []}
    prev_by = {row.get("board"): row for row in prev_rows or []}
    levels = []
    for board, row in sorted(today_by.items(), reverse=True):
        if not isinstance(board, int):
            continue
        rate = row.get("rate") or {}
        if "pct" not in rate:
            continue
        src = rate.get("from_board")
        promoted = list(row.get("stocks") or [])
        promoted_keys = {_stock_key(stock) for stock in promoted}
        failed = []
        for stock in (prev_by.get(src) or {}).get("stocks") or []:
            if _stock_key(stock) not in promoted_keys:
                failed.append(stock)
        prev_rate = (prev_by.get(board) or {}).get("rate") or {}
        prev_pct = prev_rate.get("pct") if prev_rate.get("from_board") == src else None
        levels.append(
            {
                "from_board": src,
                "to_board": board,
                "pct": rate.get("pct"),
                "prev_pct": prev_pct,
                "direction": _pct_direction(rate.get("pct"), prev_pct),
                "promoted": promoted,
                "failed": failed,
            }
        )
    levels.sort(key=lambda item: item["from_board"] or 0)
    return levels


def promotion_vote(levels: list[dict]) -> str:
    """起板段看 1进2、2进3，高位段看 3进4 及以上里最高的一档。"""
    if not levels:
        return "缺失"
    low = [item["direction"] for item in levels if item["from_board"] in (1, 2)]
    high = [item for item in levels if isinstance(item["from_board"], int) and item["from_board"] >= 3]
    high_dir = ""
    known_high = [item for item in high if item["direction"] in ("向上", "向下", "持平")]
    if known_high:
        high_dir = max(known_high, key=lambda item: item["from_board"])["direction"]
    low_up = "向上" in low and "向下" not in low
    low_down = "向下" in low
    if high_dir == "向下" and low_up:
        return "分裂"
    if high_dir == "向下":
        return "高位向下"
    if low_up:
        return "起板向上"
    if low_down:
        return "起板向下"
    if high_dir == "向上":
        return "起板向上"
    if any(item["direction"] == "持平" for item in levels):
        return "持平"
    return "缺失"


def review_page_blocked(html: str) -> bool:
    if not html or not html.strip():
        return True
    return "FP_GATE" in html or "正在打开" in html or "浏览器校验" in html


def parse_zhaban(html: str) -> list[dict]:
    """从当日复盘页截取炸板卡片。校验页或没有炸板段时返回空列表。"""
    if review_page_blocked(html) or "炸板" not in html:
        return []
    start = html.find("炸板")
    rest = html[start:]
    end = len(rest)
    for marker in ("龙虎榜", "题材复盘", "热点题材", "连板天梯", "<footer"):
        pos = rest.find(marker, 2)
        if 0 < pos < end:
            end = pos
    section = rest[:end]
    chunks = re.split(r'(?=<a\b[^>]*href="/gu/\d{6}\.html")', section)
    if len(chunks) <= 1:
        chunks = re.split(r'(?=<div\b[^>]*data-c="\d{6}")', section)
    stocks = []
    seen = set()
    for chunk in chunks:
        parsed = _zhaban_chunk(chunk)
        if not parsed:
            continue
        key = parsed.get("code") or parsed["name"]
        if key in seen:
            continue
        seen.add(key)
        stocks.append(parsed)
    if stocks:
        return stocks
    plain = unescape(re.sub(r"<[^>]+>", " ", section))
    plain = re.sub(r"\s+", " ", plain)
    for match in re.finditer(
        r"([\u4e00-\u9fffA-Za-zＡ-Ｚ]{2,8})\s+(\d{2}:\d{2})封\s*·\s*[昨炸](\d+)",
        plain,
    ):
        name = match.group(1)
        if "炸" in name or "板" in name:
            continue
        if name in seen:
            continue
        seen.add(name)
        stocks.append(
            {
                "name": name,
                "code": "",
                "time": match.group(2),
                "prev_board": int(match.group(3)),
                "theme": "",
            }
        )
    return stocks


def _zhaban_chunk(chunk: str) -> dict | None:
    code_match = re.search(r'/gu/(\d{6})\.html|data-c="(\d{6})"', chunk)
    text = unescape(re.sub(r"<[^>]+>", " ", chunk))
    text = re.sub(r"\s+", " ", text).strip()
    time_match = re.search(r"(\d{2}:\d{2})\s*封", text)
    prev_match = re.search(r"[昨炸]\s*(\d+)", text)
    if not time_match and not prev_match:
        return None
    name = ""
    name_attr = re.search(r'data-nm="([^"]+)"', chunk)
    if name_attr:
        name = unescape(name_attr.group(1)).strip()
    if not name:
        name_match = re.search(r"([\u4e00-\u9fffA-Za-zＡ-Ｚ]{2,8})", text)
        name = name_match.group(1) if name_match else ""
    if not name or "炸" in name or name.startswith("昨"):
        return None
    theme_match = re.search(r'class="r"[^>]*>([^<]+)', chunk)
    return {
        "name": name,
        "code": (code_match.group(1) or code_match.group(2)) if code_match else "",
        "time": time_match.group(1) if time_match else "",
        "prev_board": int(prev_match.group(1)) if prev_match else None,
        "theme": unescape(theme_match.group(1)).strip() if theme_match else "",
    }


def theme_hit(theme: str, wanted: str) -> bool:
    theme = str(theme or "").strip()
    wanted = str(wanted or "").strip()
    if len(theme) < 2 or len(wanted) < 2:
        return False
    return theme == wanted or theme in wanted or wanted in theme


def _theme_indexes(rows: list[dict]) -> tuple[dict, dict]:
    by_code: dict[str, str] = {}
    by_name: dict[str, str] = {}
    for row in rows or []:
        for stock in row.get("stocks") or []:
            theme = str(stock.get("theme") or "").strip()
            if not theme:
                continue
            code = str(stock.get("code") or "").strip()
            name = str(stock.get("name") or "").strip()
            if code:
                by_code[code] = theme
            if name:
                by_name[name] = theme
    return by_code, by_name


def _lookup_theme(item: dict, indexes: list[tuple[dict, dict]]) -> str:
    theme = str(item.get("theme") or "").strip()
    if theme:
        return theme
    code = str(item.get("code") or "").strip()
    name = str(item.get("name") or "").strip()
    for by_code, by_name in indexes:
        if code and by_code.get(code):
            return by_code[code]
        if name and by_name.get(name):
            return by_name[name]
    return ""


def follower_themes(leader: dict | None, themes: list[dict]) -> list[str]:
    names = []
    leader_theme = str((leader or {}).get("theme") or "").strip()
    if leader_theme:
        names.append(leader_theme)
    if themes:
        top = str((themes[0] or {}).get("name") or "").strip()
        if top and top not in names:
            names.append(top)
    return names


def filter_follower_zhaban(stocks: list[dict], themes: list[str]) -> list[dict]:
    """天梯题材或东方财富行业与跟风题材同一行业即算跟风。"""
    picked = []
    for item in stocks or []:
        labels = [item.get("theme") or "", item.get("industry") or ""]
        if any(theme_hit(label, theme) for label in labels for theme in themes):
            picked.append(item)
    return picked


def zhaban_vote(today_count: int | None, prev_count: int | None) -> str:
    if today_count is None or prev_count is None:
        return "缺失"
    if today_count < prev_count:
        return "收缩"
    if today_count > prev_count:
        return "扩张"
    return "持平"


def space_leader_fate(leader: dict | None, today_rows: list[dict], zhaban: list[dict]) -> tuple[str, str]:
    """第一票收盘只看昨日空间龙：晋级为守住，在炸板名单里为炸板，否则未守住。"""
    if not leader or not _leader_name(leader):
        return "缺失", "未取到昨日空间龙"
    name = _leader_name(leader)
    code = str(leader.get("code") or "").strip()
    board = leader.get("board")
    for item in zhaban or []:
        same = (code and item.get("code") == code) or item.get("name") == name
        if same:
            return "炸板", f"昨日{board}板，今日炸板"
    for row in today_rows or []:
        height = row.get("board")
        if not isinstance(height, int) or not isinstance(board, int) or height <= board:
            continue
        for stock in row.get("stocks") or []:
            same = (code and stock.get("code") == code) or stock.get("name") == name
            if same:
                return "守住", f"昨日{board}板，今日{height}板"
    board_text = board if isinstance(board, int) else "—"
    return "未守住", f"昨日{board_text}板，今日未晋级"


def seam_conclusion(phase: str, tokens: list[str]) -> str:
    if any(str(token).startswith("分裂") for token in tokens):
        return "信号分裂"
    votes = [_token_vote(token) for token in tokens]
    known = [vote for vote in votes if vote]
    if len(known) < 2:
        return "观察"
    if any(vote > 0 for vote in known) and any(vote < 0 for vote in known):
        return "信号分裂"
    phase_key = _phase_key(phase)
    if known[0] > 0 and phase_key in UP_PHASES:
        return "分歧转一致"
    if known[0] < 0 and phase_key in DOWN_PHASES:
        return "一致转分歧"
    return "观察"


def _fmt_names(stocks: list[dict]) -> str:
    if not stocks:
        return "无"
    return "、".join(stock_label(stock) for stock in stocks)


def _fmt_pct(value) -> str:
    if value is None:
        return "—"
    number = float(value)
    text = f"{number:.0f}%" if number == int(number) else f"{number:.1f}%"
    return text


def render_promotion_section(levels: list[dict]) -> list[str]:
    lines = ["## 晋级名单", ""]
    if not levels:
        lines.extend(["未取到天梯晋级率。", ""])
        return lines
    lines.extend(["晋级率取自连板天梯行头，与当日复盘页同口径。", ""])
    for level in levels:
        src = level["from_board"]
        dst = level["to_board"]
        prev = f"前一交易日 {_fmt_pct(level['prev_pct'])}，" if level["prev_pct"] is not None else ""
        lines.append(f"{src}进{dst} {_fmt_pct(level['pct'])}，{prev}{level['direction']}。")
        lines.append("")
        lines.append(f"### {src}进{dst} 晋级（{len(level['promoted'])}只）")
        lines.append("")
        if level["promoted"]:
            for stock in level["promoted"]:
                lines.append(f"- {stock_label(stock)}")
        else:
            lines.append("- 无")
        lines.append("")
        lines.append(f"### {src}进{dst} 未晋级（{len(level['failed'])}只）")
        lines.append("")
        if level["failed"]:
            for stock in level["failed"]:
                lines.append(f"- {stock_label(stock)}")
        else:
            lines.append("- 无")
        lines.append("")
    return lines


def render_zhaban_section(
    known: bool,
    stocks: list[dict],
    follower: list[dict],
    themes: list[str],
    kpi_count,
    prev_known: bool,
    prev_follower_count: int | None,
    vote: str,
) -> list[str]:
    lines = ["## 炸板名单", ""]
    theme_text = "、".join(themes) if themes else "未取到"
    if not known:
        count = kpi_count if kpi_count is not None else "—"
        lines.append(f"跟风题材：{theme_text}。炸板池没有返回名单，连板网炸板家数为 {count}。")
        lines.append("")
        return lines
    prev_text = str(prev_follower_count) if prev_known and prev_follower_count is not None else "—"
    pool_note = f"全市场 {len(stocks)} 只"
    if kpi_count is not None and int(kpi_count) != len(stocks):
        pool_note += f"，连板网家数 {kpi_count}"
    lines.append(
        f"跟风题材：{theme_text}。{pool_note}，跟风 {len(follower)} 只，前一交易日跟风 {prev_text} 只，{vote}。"
    )
    lines.append("")
    follower_keys = {_stock_key(item) for item in follower}
    others = [item for item in stocks if _stock_key(item) not in follower_keys]
    lines.extend(_zhaban_group("跟风", follower))
    if others:
        lines.extend(_zhaban_group("其余", others))
    return lines


def _zhaban_group(title: str, stocks: list[dict]) -> list[str]:
    lines = [f"### {title}（{len(stocks)}只）", ""]
    if not stocks:
        lines.extend(["- 无", ""])
        return lines
    for item in stocks:
        lines.append(f"- {_format_zhaban(item)}")
    lines.append("")
    return lines


def _format_zhaban(item: dict) -> str:
    name = item.get("name") or "—"
    code = str(item.get("code") or "").strip()
    head = f"{name} {code}".strip() if code else name
    bits = []
    if item.get("time"):
        bits.append(f"{item['time']}封")
    blows = item.get("blows")
    if blows is None:
        blows = item.get("prev_board")
    if blows is not None and blows != "":
        bits.append(f"炸{blows}次")
    label = str(item.get("theme") or item.get("industry") or "").strip()
    body = " · ".join([head, *bits]) if bits else head
    if label:
        return f"{body}（{label}）"
    return body


def render_seam_section(
    leader: dict | None,
    prev_leader: dict | None,
    phase: str,
    themes: list[str],
    fate: str,
    fate_detail: str,
    vote2: str,
    vote3: str,
) -> list[str]:
    phase_text = _phase_key(phase) or "缺失"
    conclusion = seam_conclusion(phase_text, [fate, vote2, vote3])
    leader_text = _format_board_leader(leader)
    board = (leader or {}).get("board")
    if leader_text != "未取到" and isinstance(board, int):
        leader_text = f"{leader_text}，{board}板"
    code = str((prev_leader or {}).get("code") or "").strip()
    inspected = _leader_name(prev_leader) or "未取到"
    if code:
        inspected = f"{inspected}（{code}）"
    theme_text = "、".join(themes) if themes else "未取到"
    return [
        "## 分歧转一致",
        "",
        "空间龙只取最高板第一只。收盘第一票看昨日空间龙是否晋级；次日开盘只按这一只的高开或低开改第一票。",
        "",
        f"- 空间龙：{leader_text}",
        f"- 跟风题材：{theme_text}",
        f"- 阶段：{phase_text}",
        f"- 检验对象：{inspected}",
        f"- 收盘：{fate}（{fate_detail}）",
        f"- 第一票：{fate}",
        f"- 第二票：{vote2}",
        f"- 第三票：{vote3}",
        f"- 结论：{conclusion}",
        "- 次日开盘：待定",
        "",
    ]


def _seam_line(text: str, label: str) -> str:
    match = re.search(rf"^- {label}：(.+)$", text, re.M)
    return match.group(1).strip() if match else ""


def apply_open_revision(text: str, gap: str) -> str:
    """次日开盘只改第一票，并按三票重写结论。平开不改第一票。"""
    if "- 次日开盘：待定" not in text:
        return text
    if gap not in ("高开", "低开", "平开"):
        return text
    if gap == "平开":
        return text.replace("- 次日开盘：待定", "- 次日开盘：平开，第一票不改", 1)
    new_vote = "守住" if gap == "高开" else "走弱"
    old_vote = _seam_line(text, "第一票")
    verb = "维持" if old_vote == new_vote else "改为"
    text = re.sub(r"^- 第一票：.+$", f"- 第一票：{new_vote}", text, count=1, flags=re.M)
    conclusion = seam_conclusion(
        _seam_line(text, "阶段"),
        [new_vote, _seam_line(text, "第二票"), _seam_line(text, "第三票")],
    )
    text = re.sub(r"^- 结论：.+$", f"- 结论：{conclusion}", text, count=1, flags=re.M)
    return text.replace("- 次日开盘：待定", f"- 次日开盘：{gap}，第一票{verb}{new_vote}", 1)


def stock_secid(code: str) -> str:
    text = str(code or "").strip()
    if text.startswith("6"):
        return "1." + text
    if text.startswith("9") and not text.startswith("92"):
        return "1." + text
    return "0." + text


def fetch_open_gap(code: str, day: str) -> str | None:
    """当日开盘相对前收：高开、低开或平开。"""
    end = day.replace("-", "")
    query = urllib.parse.urlencode(
        {
            "secid": stock_secid(code),
            "klt": "101",
            "fqt": "1",
            "end": end,
            "lmt": "5",
            "fields1": "f1",
            "fields2": "f51,f52,f53",
        }
    )
    body, _ctype = _request(
        f"{KLINE_URL}?{query}",
        None,
        {"User-Agent": BROWSER_UA, "Accept": "application/json", "Referer": "https://quote.eastmoney.com/"},
        timeout=20,
    )
    data = json.loads(body)
    bars = []
    for item in ((data.get("data") or {}).get("klines") or []):
        parts = str(item).split(",")
        if len(parts) < 3:
            continue
        bars.append((parts[0], float(parts[1]), float(parts[2])))
    for index, (bar_day, open_price, _close) in enumerate(bars):
        if bar_day != day or index == 0:
            continue
        prev_close = bars[index - 1][2]
        if open_price > prev_close:
            return "高开"
        if open_price < prev_close:
            return "低开"
        return "平开"
    return None


def revise_previous_open(prev_path: Path, open_day: str) -> None:
    if not prev_path.exists():
        return
    text = prev_path.read_text(encoding="utf-8")
    if "- 次日开盘：待定" not in text:
        return
    code_match = re.search(r"^- 检验对象：.+（(\d{6})）\s*$", text, re.M)
    if not code_match:
        log(f"{prev_path.name} 缺少检验对象代码，次日开盘不改第一票")
        return
    gap = fetch_open_gap(code_match.group(1), open_day)
    if gap is None:
        log(f"{prev_path.name} 未取到 {open_day} 开盘，第一票保持待定")
        return
    revised = apply_open_revision(text, gap)
    if revised == text:
        return
    prev_path.write_text(revised, encoding="utf-8", newline="\n")
    log(f"{prev_path.name} 次日开盘{gap}，已改第一票")


def _with_theme(stocks: list[dict], indexes: list[tuple[dict, dict]]) -> list[dict]:
    themed = []
    for item in stocks or []:
        copied = dict(item)
        copied["theme"] = _lookup_theme(copied, indexes)
        themed.append(copied)
    return themed


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
    seam_sections: list[str] | None = None,
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
    if seam_sections:
        lines.extend(seam_sections)
    page = review.get("page") or f"https://lianban.net/days/{day}.html"
    sources = ["连板网 lianban.net"]
    if indices or market.get("turnover") is not None or any((item.get("title") or "") for item in (logics or [])):
        sources.append("指数、成交额、题材新闻与炸板池：东方财富")
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
    prev_tianti: list[dict] = []
    if _rows_have_stocks(today_tianti) and not _leaders_have_codes(rows):
        leader_today = today_tianti
    if prev_day:
        prev_tianti = tianti_map.get(prev_day[5:], [])
        if _rows_have_stocks(prev_tianti) and not _leaders_have_codes(prev_rows):
            leader_prev = prev_tianti
    today_board = today_tianti if _rows_have_stocks(today_tianti) else leader_today
    prev_board = prev_tianti if _rows_have_stocks(prev_tianti) else leader_prev
    seam_sections = _seam_sections(day, review, prev_review, prev_day, today_board, prev_board)
    tiers = boards_from_two(rows)
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
        seam_sections,
    )
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / f"{day}.md"
    path.write_text(text, encoding="utf-8", newline="\n")
    if prev_day:
        try:
            revise_previous_open(REPORTS / f"{prev_day}.md", day)
        except Exception as exc:
            log(f"次日开盘修订失败：{exc}")
    return path


def _fmt_seal_time(value) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    digits = digits.zfill(6)
    return f"{digits[:2]}:{digits[2:4]}"


def zhaban_from_pool(payload: dict) -> tuple[list[dict], int | None]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        data = payload if isinstance(payload, dict) else {}
    pool = data.get("pool") or []
    total = data.get("tc")
    stocks = []
    for item in pool:
        if not isinstance(item, dict):
            continue
        name = str(item.get("n") or "").strip()
        code = str(item.get("c") or "").strip()
        if not name and not code:
            continue
        blows = item.get("zbc")
        stocks.append(
            {
                "name": name,
                "code": code,
                "time": _fmt_seal_time(item.get("fbt")),
                "blows": int(blows) if blows is not None and str(blows) != "" else None,
                "industry": str(item.get("hybk") or "").strip(),
                "theme": "",
            }
        )
    return stocks, int(total) if total is not None else None


def fetch_zhaban_pool(day: str) -> list[dict]:
    """东方财富炸板池。请求失败时抛错，由调用方记为名单缺失。"""
    date = day.replace("-", "")
    stocks: list[dict] = []
    total = None
    for page in range(5):
        query = urllib.parse.urlencode(
            {
                "ut": "7eea3edcaed734bea9cbfc24409ed989",
                "dpt": "wz.ztzt",
                "Pageindex": page,
                "pagesize": 100,
                "sort": "fbt:asc",
                "date": date,
            }
        )
        body, _ctype = _request(
            f"{ZB_POOL_URL}?{query}",
            None,
            {
                "User-Agent": BROWSER_UA,
                "Accept": "application/json",
                "Referer": "https://quote.eastmoney.com/",
            },
            timeout=20,
        )
        page_stocks, page_total = zhaban_from_pool(json.loads(body))
        if total is None:
            total = page_total
        stocks.extend(page_stocks)
        if not page_stocks or (total is not None and len(stocks) >= total):
            break
    return fill_industry_names(stocks)


def apply_industry_names(stocks: list[dict], names: dict[str, str]) -> list[dict]:
    """用行情接口的行业全称替换炸板池里被截断的 hybk。"""
    for item in stocks:
        full = str(names.get(str(item.get("code") or "").strip()) or "").strip()
        if full and full != "-":
            item["industry"] = full
    return stocks


def fetch_industry_names(codes: list[str]) -> dict[str, str]:
    secids = [stock_secid(str(code).strip()) for code in codes if str(code or "").strip()]
    found: dict[str, str] = {}
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json",
        "Referer": "https://quote.eastmoney.com/",
    }
    for start in range(0, len(secids), 50):
        query = urllib.parse.urlencode(
            {
                "fltt": 2,
                "np": 1,
                "fields": "f12,f100",
                "secids": ",".join(secids[start : start + 50]),
            }
        )
        body, _ctype = _request(f"{INDUSTRY_URL}?{query}", None, headers, timeout=20)
        rows = ((json.loads(body).get("data") or {}).get("diff")) or []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = str(row.get("f12") or "").strip()
            name = str(row.get("f100") or "").strip()
            if code and name and name != "-":
                found[code] = name
    return found


def fill_industry_names(stocks: list[dict]) -> list[dict]:
    if not stocks:
        return stocks
    try:
        names = fetch_industry_names([item.get("code") for item in stocks])
    except Exception as exc:
        log(f"行业全称获取失败：{exc}")
        return stocks
    return apply_industry_names(stocks, names)


def _seam_sections(
    day: str,
    review: dict,
    prev_review: dict | None,
    prev_day: str | None,
    today_board: list[dict],
    prev_board: list[dict],
) -> list[str]:
    leader = first_board_leader(today_board)
    prev_leader = first_board_leader(prev_board) if prev_day else None
    themes = follower_themes(leader, top_themes(review, 1))
    levels = promotion_levels(today_board, prev_board if prev_day else [])
    vote3 = promotion_vote(levels)
    try:
        today_zhaban = fetch_zhaban_pool(day)
        today_known = True
    except Exception as exc:
        log(f"炸板池获取失败：{exc}")
        today_zhaban = []
        today_known = False
    if prev_day:
        try:
            prev_zhaban = fetch_zhaban_pool(prev_day)
            prev_known = True
        except Exception as exc:
            log(f"上一交易日炸板池获取失败：{exc}")
            prev_zhaban = []
            prev_known = False
    else:
        prev_zhaban = []
        prev_known = False
    kpi_count = (review.get("kpi") or {}).get("zhaban")
    indexes = [_theme_indexes(prev_board), _theme_indexes(today_board)]
    today_zhaban = _with_theme(today_zhaban, indexes)
    prev_zhaban = _with_theme(prev_zhaban, indexes)
    follower = filter_follower_zhaban(today_zhaban, themes) if today_known else []
    prev_follower = len(filter_follower_zhaban(prev_zhaban, themes)) if prev_known else None
    vote2 = zhaban_vote(len(follower) if today_known else None, prev_follower)
    fate, detail = space_leader_fate(prev_leader, today_board, today_zhaban if today_known else [])
    phase = str((review.get("kpi") or {}).get("emotion_phase") or "")
    sections: list[str] = []
    sections.extend(
        render_zhaban_section(
            today_known,
            today_zhaban,
            follower,
            themes,
            kpi_count,
            prev_known,
            prev_follower,
            vote2,
        )
    )
    sections.extend(render_promotion_section(levels))
    sections.extend(
        render_seam_section(leader, prev_leader, phase, themes, fate, detail, vote2, vote3)
    )
    return sections


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
    tiers = boards_from_two(rows)
    assert [row["board"] for row in tiers] == [4, 3, 2], tiers
    gapped = [
        {"board": 7, "stocks": []},
        {"board": 6, "stocks": [{"name": "甲"}]},
        {"board": 4, "stocks": []},
        {"board": 2, "stocks": [{"name": "乙"}]},
        {"board": 1, "stocks": [{"name": "丙"}]},
    ]
    gapped_tiers = boards_from_two(gapped)
    assert [row["board"] for row in gapped_tiers] == [6, 5, 4, 3, 2], gapped_tiers
    assert gapped_tiers[1]["stocks"] == []
    assert gapped_tiers[0]["stocks"][0]["name"] == "甲"
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
    assert "## 分歧转一致" not in report
    rate_html = """
    <table><thead><tr><th>板位</th><th><b>11-11</b></th><th><b>11-10</b></th></tr></thead>
    <tbody>
      <tr data-h="4"><th>4板</th>
        <td><div class="hd">共1只 <span class="rt">3进4 50%</span></div>
          <div class="tti-s" data-c="603366"><a data-nm="日出东方">日出东方</a><div class="r">光伏</div></div>
        </td>
        <td><div class="hd">共1只 <span class="rt">3进4 100%</span></div>
          <div class="tti-s" data-c="002578"><a data-nm="闽发铝业">闽发铝业</a><div class="r">光伏支架</div></div>
        </td>
      </tr>
      <tr data-h="2"><th>2板</th>
        <td><div class="hd">共1只 <span class="rt">1进2 20%</span></div>
          <div class="tti-s" data-c="600000"><a data-nm="甲">甲</a><div class="r">机器人概念</div></div>
        </td>
        <td><div class="hd">共1只 <span class="rt">1进2 10%</span></div>
          <div class="tti-s" data-c="600001"><a data-nm="乙">乙</a><div class="r">机器人概念</div></div>
        </td>
      </tr>
      <tr data-h="1"><th>1板</th>
        <td><div class="hd">共2只</div></td>
        <td><div class="hd">共2只</div>
          <div class="tti-s" data-c="600000"><a data-nm="甲">甲</a><div class="r">机器人概念</div></div>
          <div class="tti-s" data-c="600002"><a data-nm="丙">丙</a><div class="r">光伏</div></div>
        </td>
      </tr>
    </tbody></table>
    """
    rated = ladders_from_tianti(rate_html)
    levels = promotion_levels(rated["11-11"], rated["11-10"])
    assert [item["from_board"] for item in levels] == [1, 3], levels
    assert levels[0]["direction"] == "向上"
    assert levels[0]["failed"][0]["name"] == "丙"
    assert promotion_vote(levels) == "分裂"
    low_only = [item for item in levels if item["from_board"] < 3]
    for item in low_only:
        item["direction"] = "向下"
    assert promotion_vote(low_only) == "起板向下"
    assert seam_conclusion("升温期", ["守住", "收缩", "起板向上"]) == "分歧转一致"
    assert seam_conclusion("高潮期", ["未守住", "扩张", "起板向下"]) == "一致转分歧"
    assert seam_conclusion("高潮期", ["守住", "收缩", "起板向下"]) == "信号分裂"
    assert seam_conclusion("退潮期", ["未守住", "扩张", "起板向下"]) == "观察"
    zhaban_html = """
    <div>炸板 2只 · 封板后掉队</div>
    <a href="/gu/002442.html" data-nm="保利联合">保利联合</a> 09:25封 · 昨1 <div class="r">光伏</div>
    <a href="/gu/600715.html" data-nm="文投控股">文投控股</a> 09:40封 · 昨2 <div class="r">AI视频</div>
    <a href="/gu/603017.html" data-nm="清源股份">清源股份</a> 09:30封 · 炸3
    龙虎榜
    """
    blown = parse_zhaban(zhaban_html)
    assert [item["name"] for item in blown] == ["保利联合", "文投控股", "清源股份"], blown
    assert blown[0]["prev_board"] == 1 and blown[0]["theme"] == "光伏"
    assert blown[2]["prev_board"] == 3
    follow = filter_follower_zhaban(blown, ["光伏", "机器人概念"])
    assert [item["name"] for item in follow] == ["保利联合"]
    assert parse_zhaban("<script>window.FP_GATE=1</script>正在打开") == []
    pool_rows, pool_total = zhaban_from_pool(
        {
            "data": {
                "tc": 1,
                "pool": [
                    {
                        "c": "603628",
                        "n": "清源股份",
                        "fbt": 93055,
                        "zbc": 3,
                        "hybk": "光伏设备",
                    }
                ],
            }
        }
    )
    assert pool_total == 1
    assert pool_rows[0]["code"] == "603628"
    assert pool_rows[0]["time"] == "09:30"
    assert pool_rows[0]["blows"] == 3
    themed = _with_theme(pool_rows, [({"603628": "光伏"}, {})])
    assert themed[0]["theme"] == "光伏"
    assert [item["name"] for item in filter_follower_zhaban(pool_rows, ["光伏"])] == ["清源股份"]
    assert [item["name"] for item in filter_follower_zhaban(themed, ["光伏"])] == ["清源股份"]
    assert "炸3次" in _format_zhaban(pool_rows[0])
    assert _format_zhaban(pool_rows[0]).endswith("（光伏设备）")
    assert "行业" not in _format_zhaban(pool_rows[0])
    short_industry = [{"code": "603275", "name": "众辰科技", "time": "09:49", "blows": 2, "industry": "自动化设"}]
    apply_industry_names(short_industry, {"603275": "自动化设备"})
    assert short_industry[0]["industry"] == "自动化设备"
    assert _format_zhaban(short_industry[0]).endswith("（自动化设备）")
    assert review_page_blocked("<script>window.FP_GATE=1</script>")
    leader = {"name": "闽发铝业", "code": "002578", "board": 6, "theme": "光伏支架"}
    held, detail = space_leader_fate(leader, rated["11-11"], [])
    assert held == "未守住", detail
    promoted_rows = [
        {"board": 7, "stocks": [{"name": "闽发铝业", "code": "002578", "theme": "光伏支架"}]}
    ]
    assert space_leader_fate(leader, promoted_rows, [])[0] == "守住"
    assert space_leader_fate(leader, promoted_rows, [{"name": "闽发铝业", "code": "002578"}])[0] == "炸板"
    themes = follower_themes(
        {"name": "日出东方", "theme": "光伏", "board": 4},
        [{"name": "机器人概念", "limit_up": 22}, {"name": "光通信", "limit_up": 13}],
    )
    assert themes == ["光伏", "机器人概念"]
    sample = "\n".join(
        [
            "- 阶段：高潮期",
            "- 第一票：未守住",
            "- 第二票：扩张",
            "- 第三票：起板向下",
            "- 结论：一致转分歧",
            "- 次日开盘：待定",
        ]
    )
    revised = apply_open_revision(sample, "高开")
    assert "- 第一票：守住" in revised
    assert "- 结论：信号分裂" in revised
    assert "次日开盘：高开，第一票改为守住" in revised
    kept = apply_open_revision(sample, "低开")
    assert "- 第一票：走弱" in kept
    assert "- 结论：一致转分歧" in kept
    assert "第一票改为走弱" in kept
    assert apply_open_revision(sample, "平开") == sample.replace("待定", "平开，第一票不改")
    assert stock_secid("600000") == "1.600000"
    assert stock_secid("002442") == "0.002442"
    assert stock_secid("920045") == "0.920045"
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
