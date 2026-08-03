# -*- coding: utf-8 -*-
"""
从 Tushare 新闻接口拉取资讯，筛选含关键词（默认：异常波动）的新闻并提取 A 股简称。
固定使用新浪新闻源（`src=sina`）。

用法:
  python extract_stocks_by_keyword.py
  python extract_stocks_by_keyword.py --trade-date 2026-04-21
  python extract_stocks_by_keyword.py --start-date 2026-04-21 --end-date 2026-04-21 --keyword 异常
  python extract_stocks_by_keyword.py --output abnormal_names.txt
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# 常见非股票短语（简称误匹配时可继续扩充）
_DEFAULT_STOP = frozenset(
    {
        "概念",
        "板块",
        "成分股",
        "异动",
        "拉升",
        "走强",
        "活跃",
        "盘中",
        "早盘",
        "此前",
        "消息面上",
        "截至发稿",
        "逆市",
        "逆势",
        "短线",
        "大面积",
        "延续",
        "强势",
        "震荡",
        "下挫",
        "走低",
        "内参",
        "价格发布",
        "数据显示",
    }
)

# 条目起始：HH:MM（与 Tushare 资讯粘贴格式一致）
_TIME_HEAD = re.compile(r"(?<!\d)(\d{2}:\d{2})")

# 顿号分隔的列表里，取每段开头的简称
_LEADING_NAME = re.compile(r"^([\u4e00-\u9fff]{2,8}(?:[ABH])?)")


def _get_tushare_pro():
    token = (os.getenv("TUSHARE_TOKEN") or "").strip()
    if not token:
        try:
            from config.settings import DATA_CONFIG

            token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
        except Exception:
            token = ""
    if not token:
        raise RuntimeError(
            "未找到 Tushare Token，请设置环境变量 TUSHARE_TOKEN 或配置 config.settings.DATA_CONFIG['tushare_token']"
        )
    import tushare as ts

    ts.set_token(token)
    return ts.pro_api()


def _normalize_trade_date(s: str) -> str:
    s = str(s).strip().replace("-", "")
    if len(s) != 8 or not s.isdigit():
        raise ValueError("日期格式应为 YYYYMMDD 或 YYYY-MM-DD")
    return s


def _date_to_dash(d: str) -> str:
    return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"


def _build_time_window(args: argparse.Namespace) -> tuple[str, str]:
    if args.trade_date:
        d = _normalize_trade_date(args.trade_date)
        day = _date_to_dash(d)
        return f"{day} {args.start_time}", f"{day} {args.end_time}"

    if args.start_date and args.end_date:
        s = _date_to_dash(_normalize_trade_date(args.start_date))
        e = _date_to_dash(_normalize_trade_date(args.end_date))
        return f"{s} {args.start_time}", f"{e} {args.end_time}"

    today = datetime.now().strftime("%Y-%m-%d")
    return f"{today} {args.start_time}", f"{today} {args.end_time}"


def _fetch_news(pro, src: str, start_dt: str, end_dt: str):
    try:
        return pro.news(src=src, start_date=start_dt, end_date=end_dt)
    except Exception as exc:
        msg = str(exc)
        if "频率超限" in msg or "超限" in msg:
            raise RuntimeError(
                "Tushare news 接口当前频率超限（news 默认 2 次/小时）。请稍后重试，或扩大单次查询时间窗口减少调用次数。"
            ) from exc
        raise RuntimeError(f"调用 Tushare news 接口失败: {msg}") from exc


def _normalize_keyword(keyword: str) -> str:
    return unicodedata.normalize("NFKC", keyword).strip().strip("\"'“”‘’")


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    # 浏览器拷贝文本里常见零宽字符会导致关键字匹配失败
    return re.sub(r"[\u200b\u200c\u200d\ufeff]", "", text)


def _name_before_keyword_pattern(keyword: str) -> re.Pattern[str]:
    """简称紧挨「关键词」常见写法（关键词可自定义，默认涨停）。"""
    kw = _normalize_keyword(keyword)
    if kw == "涨停":
        return re.compile(
            r"([\u4e00-\u9fff]{2,8}(?:[ABH])?)"
            r"(?:(?:直线拉升|直线|触及|T字|一字|逼近))*涨停"
        )
    if kw == "跌停":
        return re.compile(
            r"([\u4e00-\u9fff]{2,8}(?:[ABH])?)(?:(?:直线|一字|触及))*跌停"
        )
    return re.compile(
        rf"([\u4e00-\u9fff]{{2,8}}(?:[ABH])?)"
        rf"(?:[^\n，,。.;；、：:！？!?【】\[\]]{{0,12}}?)"
        rf"{re.escape(kw)}"
    )


def _strip_parentheses(s: str) -> str:
    s = re.sub(r"\([^)]*\)", "", s)
    return re.sub(r"（[^）]*）", "", s)


def _split_entries(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    spans: list[tuple[int, int]] = []
    for m in _TIME_HEAD.finditer(text):
        spans.append((m.start(), m.end()))
    if not spans:
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        return parts if parts else [text]
    entries: list[str] = []
    for i, (start, _) in enumerate(spans):
        end = spans[i + 1][0] if i + 1 < len(spans) else len(text)
        chunk = text[start:end].strip()
        if chunk:
            entries.append(chunk)
    return entries


def _clean_dun_piece(piece: str) -> str:
    piece = piece.strip().rstrip("。；;")
    piece = re.sub(r"等[^、，。]*$", "", piece)
    piece = re.sub(r"^(?:此前|盘中|早盘|消息面上|截至发稿)", "", piece)
    piece = re.sub(r"(冲高|跟涨|走弱|跟跌)$", "", piece)
    return piece.strip().rstrip("。；;")


_NAME_VERB_TAIL = re.compile(
    r"(?:直线拉升|直线|拉升|触及|T字|一字|逼近|冲高|跟涨|走弱|跟跌|发生|出现|发布异动|发布公告|发布|公告称|公告)+$"
)
_BAD_NAME_RE = re.compile(
    r"^(?:公司|股票|交易|截至|属于)"
    r"|(?:公司|股票|交易|公告|风险|波动|提示|截至|属于)$"
)
_ABNORMAL_BODY_NAME = re.compile(
    r"(?:^|[，,。；;\s])([\u4e00-\u9fff]{2,8}(?:[ABH])?)"
    r"(?=(?:发布(?:异动)?公告|公告称|公告))"
)


def _trim_name_verb_tail(name: str) -> str:
    n = name.strip()
    while True:
        n2 = _NAME_VERB_TAIL.sub("", n)
        if n2 == n:
            return n2
        n = n2


def _normalize_list_commas(seg: str) -> str:
    """将「涨停/冲高/跟涨，下一只」类顿号链前的逗号换成 、，便于按顿号拆名单。"""
    seg = re.sub(r"涨停，(?!此前)", "涨停、", seg)
    seg = re.sub(r"冲高，", "冲高、", seg)
    seg = re.sub(r"跟涨，", "跟涨、", seg)
    seg = re.sub(r"跌停，(?!此前)", "跌停、", seg)
    return seg


def extract_names_in_segment(
    segment: str, stopwords: frozenset[str], keyword: str
) -> list[str]:
    kw = _normalize_keyword(keyword)
    seg = _normalize_text(segment)
    seg = _strip_parentheses(seg)
    seg = _normalize_list_commas(seg)
    seen: set[str] = set()
    out: list[str] = []
    limit_pat = _name_before_keyword_pattern(kw)
    is_abnormal_kw = "异常" in kw

    def add(name: str) -> None:
        name = _trim_name_verb_tail(name.strip())
        name = re.sub(
            r"^(?:此前|盘中|早盘|消息面上|截至发稿)",
            "",
            name,
        ).strip()
        if _BAD_NAME_RE.search(name):
            return
        if len(name) < 2 or name in stopwords or name in seen:
            return
        seen.add(name)
        out.append(name)

    # 1) 标题式写法：`【剑桥科技：...异常...】`
    title_pat = re.compile(
        rf"[\[【]\s*([\u4e00-\u9fff]{{2,8}}(?:[ABH])?)\s*[：:][^\]】\n]*?{re.escape(kw)}[^\]】\n]*[\]】]"
    )
    for m in title_pat.finditer(seg):
        add(m.group(1))

    if is_abnormal_kw:
        # “异常”类快讯正文噪声较多，优先使用标题命中；未命中时仅用公告句式兜底。
        if out:
            return out
        for m in _ABNORMAL_BODY_NAME.finditer(seg):
            add(m.group(1))
        return out

    # 2) 「简称 + … + 关键词」（如 粤电力A直线涨停、顺灏股份T字涨停）
    for m in limit_pat.finditer(seg):
        add(m.group(1))

    # 2) 顿号链：乐山电力、宝新能源…（同一条快讯内的跟涨/冲高名单）
    for part in seg.split("、"):
        part = _clean_dun_piece(part)
        if not part or part.startswith("【") or part.startswith("]"):
            continue
        mm = _LEADING_NAME.match(part)
        if not mm:
            continue
        name = mm.group(1)
        if name in stopwords:
            continue
        add(name)

    return out


def extract_names_from_news_rows(news_df, keyword: str, sep: str) -> tuple[list[str], list[str]]:
    kw = _normalize_keyword(keyword)
    all_names: list[str] = []
    details: list[str] = []
    seen_global: set[str] = set()
    if news_df is None or getattr(news_df, "empty", True):
        return all_names, details

    for _, row in news_df.iterrows():
        title = _normalize_text(str(row.get("title", "") or ""))
        content = _normalize_text(str(row.get("content", "") or ""))
        dt = str(row.get("datetime", "") or "").strip()
        segment = f"{title}\n{content}".strip()
        if not segment or kw not in segment:
            continue
        names = extract_names_in_segment(segment, _DEFAULT_STOP, kw)
        if not names:
            continue
        details.append(f"{dt}\t{sep.join(names)}\t{title}")
        for name in names:
            if name in seen_global:
                continue
            seen_global.add(name)
            all_names.append(name)
    return all_names, details


def main() -> int:
    ap = argparse.ArgumentParser(description="从 Tushare 新闻中按关键词提取股票简称")
    ap.add_argument("--trade-date", default="", help="交易日 YYYYMMDD 或 YYYY-MM-DD（与 start/end 二选一）")
    ap.add_argument("--start-date", default="", help="开始日期 YYYYMMDD 或 YYYY-MM-DD")
    ap.add_argument("--end-date", default="", help="结束日期 YYYYMMDD 或 YYYY-MM-DD")
    ap.add_argument("--start-time", default="00:00:00", help="开始时间，默认 00:00:00")
    ap.add_argument("--end-time", default="23:59:59", help="结束时间，默认 23:59:59")
    ap.add_argument("--keyword", "-k", default="异常波动", help="过滤条目关键字（默认：异常波动）")
    ap.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="股票简称输出路径（默认打印到 stdout）",
    )
    ap.add_argument(
        "--detail-output",
        type=Path,
        default=None,
        help="明细输出路径（格式: datetime<TAB>names<TAB>title）",
    )
    ap.add_argument(
        "--sep",
        default="、",
        help="同一条内多个简称的分隔符（默认：、）",
    )
    args = ap.parse_args()
    kw = _normalize_keyword(args.keyword)
    if not kw:
        raise SystemExit("keyword 不能为空")
    if args.trade_date and (args.start_date or args.end_date):
        raise SystemExit("--trade-date 与 --start-date/--end-date 不能同时使用")
    if (args.start_date and not args.end_date) or (args.end_date and not args.start_date):
        raise SystemExit("--start-date 与 --end-date 必须同时提供")

    start_dt, end_dt = _build_time_window(args)
    pro = _get_tushare_pro()
    news_df = _fetch_news(pro, src="sina", start_dt=start_dt, end_dt=end_dt)
    names, details = extract_names_from_news_rows(news_df, keyword=kw, sep=args.sep)

    payload = "\n".join(names)
    if args.output is not None:
        args.output.write_text(payload + ("\n" if payload else ""), encoding="utf-8")
    else:
        sys.stdout.write(payload + ("\n" if payload else ""))
    if args.detail_output is not None:
        args.detail_output.write_text(
            "\n".join(details) + ("\n" if details else ""),
            encoding="utf-8",
        )
    sys.stderr.write(
        f"window={start_dt}~{end_dt}, src=sina, keyword={kw}, news_hits={len(details)}, unique_names={len(names)}\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
