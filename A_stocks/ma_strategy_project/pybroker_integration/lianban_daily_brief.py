# 数据来源：连板网 lianban.net（MCP https://lianban.net/mcp ，CC BY 4.0）
"""每个交易日 17:30 拉取连板网复盘与龙虎榜，写成 reports/YYYY-MM-DD.md。"""

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
        stocks.append(
            {
                "name": unescape(name_match.group(1)).strip(),
                "rhythm": rhythm_match.group(1) if rhythm_match else "",
                "theme": unescape(theme_match.group(1)).strip() if theme_match else "",
            }
        )
    return stocks


def ladder_from_tianti(html: str, day: str) -> list[dict]:
    month_day = day[5:]
    thead_match = re.search(r"<thead>(.*?)</thead>", html, re.S)
    if not thead_match:
        return []
    headers = re.findall(r"<th\b[^>]*>(.*?)</th>", thead_match.group(1), re.S)
    column = None
    for index, header in enumerate(headers):
        plain = re.sub(r"<[^>]+>", "", header)
        if month_day in plain:
            column = index - 1
            break
    if column is None or column < 0:
        return []
    rows = []
    for board, row_html in re.findall(r'<tr data-h="(\d+)"[^>]*>(.*?)</tr>', html, re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.S)
        if column >= len(cells):
            continue
        rows.append({"board": int(board), "stocks": _stocks_in_cell(cells[column])})
    return rows


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
    lines.extend(
        [
            "## 行情 KPI",
            "",
            "| 指标 | 数值 |",
            "| --- | --- |",
            f"| 涨停 | {kpi.get('limit_up', '—')} |",
            f"| 连板 | {kpi.get('lianban', '—')} |",
            f"| 最高板 | {kpi.get('max_board', '—')}板 |",
            f"| 封板率 | {kpi.get('seal_rate_pct', '—')}% |",
            "",
            "## 连板天梯前三档",
            "",
        ]
    )
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
    lines.extend(
        [
            f"原文：{page}",
            "",
            "数据来源：连板网 lianban.net",
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
    if rows and any(row["stocks"] for row in rows):
        ladder_note = ""
    else:
        try:
            html = fetch_html(TIANTI_URL)
            rows = ladder_from_tianti(html, day)
            if rows:
                ladder_note = "个股名单取自连板天梯页（当日复盘接口未附逐只名单）。"
        except Exception as exc:
            log(f"天梯页获取失败：{exc}")
            rows = rows or []
    tiers = top_tiers(rows, 3)
    text = render_report(day, review, prev_review, prev_day, lhb, tiers, ladder_note)
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
      </td><td></td></tr>
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
    rows = ladder_from_tianti(html, "2026-11-05")
    tiers = top_tiers(rows, 3)
    assert [row["board"] for row in tiers] == [4, 3, 2], tiers
    assert [stock["name"] for stock in tiers[0]["stocks"]] == ["闽发铝业", "浙文影业"]
    assert tiers[0]["stocks"][0]["theme"] == "光伏支架"
    assert tiers[1]["stocks"][0]["rhythm"] == "5天4板"
    assert tiers[2]["stocks"][0]["name"] == "深中华A"
    alert = change_alert(84, 118, "2026-11-04")
    assert alert is None
    assert change_alert(150, 100, "2026-11-04")
    assert change_alert(70, 118, "2026-11-04")
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
