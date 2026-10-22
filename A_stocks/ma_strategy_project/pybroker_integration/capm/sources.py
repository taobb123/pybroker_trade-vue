# -*- coding: utf-8 -*-
"""只读沪深300净值、信号组日收益和本地日线。补齐日线只写 capm/cache。"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCH_CSV = PROJECT_ROOT / "market_neutral" / "output" / "latest" / "benchmark_nav.csv"
GROUP_CSV = PROJECT_ROOT / "output" / "h0_w23_w46" / "group_returns.csv"
SLEEVE_CSV = PROJECT_ROOT / "output" / "doc15_sleeves" / "sleeve_returns.csv"
BARS_FALLBACK = PROJECT_ROOT / "output" / "h0_w23_w46" / "bars.csv"
BARS_CACHE = PROJECT_ROOT / "capm" / "cache" / "bars.csv"
OHLC_CACHE = PROJECT_ROOT / "capm" / "cache" / "ohlc.csv"
BENCH_CACHE = PROJECT_ROOT / "capm" / "cache" / "benchmark.csv"
VP6_SCAN = PROJECT_ROOT / "vp_six_combo_scan.csv"
WATCH_FILES = (
    PROJECT_ROOT / "vp_combo_watch_4.csv",
    PROJECT_ROOT / "vp_combo_watch_6.csv",
)
STOCK_WATCH_FILES = (
    PROJECT_ROOT / "vp_combo_watch_4.csv",
    PROJECT_ROOT / "vp_combo_watch_6.csv",
    PROJECT_ROOT / "vp_combo_watch_2.csv",
    PROJECT_ROOT / "vp_combo_watch_3.csv",
)
THEME_RANK_FILES = (
    PROJECT_ROOT / "pattern_entry_mplus_rank.csv",
    PROJECT_ROOT / "pattern_entry_g_rank.csv",
    PROJECT_ROOT / "vp_combo_23_q_rank.csv",
    PROJECT_ROOT / "vp_combo_23_g_rank.csv",
)
PATTERN_SCAN = PROJECT_ROOT / "pattern_entry_scan.csv"
_CODE_COLUMNS = ("symbol", "股票代码", "代码")
_NAME_COLUMNS = ("stock_name", "股票名称", "名称")

SLEEVES = ("W2+W3", "W4+W6", "M+", "Q", "G")
GROUP_COLUMNS = ("W2+W3", "W4+W6")
SLEEVE_COLUMNS = ("M+", "Q", "G")
FETCH_PAD_START = "2025-06-01"


def nav_to_returns(frame: pd.DataFrame) -> pd.Series:
    if "date" not in frame.columns or "equity" not in frame.columns:
        raise ValueError("沪深300净值缺少 date 或 equity")
    work = frame
    if "variant" in work.columns:
        mask = work["variant"].astype(str).str.contains("300", na=False)
        if bool(mask.any()):
            work = work.loc[mask]
    work = work.copy()
    work["date"] = pd.to_datetime(work["date"], errors="coerce").dt.normalize()
    work["equity"] = pd.to_numeric(work["equity"], errors="coerce")
    work = work.dropna(subset=["date", "equity"]).sort_values("date")
    returns = work["equity"].pct_change()
    out = pd.Series(returns.to_numpy(), index=work["date"])
    out = out[~out.index.duplicated(keep="last")]
    return out.replace([float("inf"), float("-inf")], pd.NA).dropna()


def load_market(path: Path | None = None, cache_path: Path | None = None) -> pd.Series:
    file = Path(path or BENCH_CSV)
    if not file.is_file():
        raise FileNotFoundError("缺少沪深300净值 benchmark_nav.csv")
    series = nav_to_returns(pd.read_csv(file))
    cache = Path(cache_path) if cache_path is not None else (None if path is not None else BENCH_CACHE)
    if cache is not None and cache.is_file():
        try:
            extra = nav_to_returns(pd.read_csv(cache))
        except (OSError, ValueError):
            extra = pd.Series(dtype=float)
        if not extra.empty:
            series = pd.concat([series, extra])
            series = series[~series.index.duplicated(keep="last")].sort_index()
    return series


def latest_trading_day(now: datetime | None = None, opens: list | None = None) -> str:
    """最近一个已收盘的交易日。15:05 前不用当天，避免日线还没出来。"""
    moment = now or datetime.now()
    cutoff = moment.replace(hour=15, minute=5, second=0, microsecond=0)
    day = pd.Timestamp(moment).normalize()
    if moment < cutoff:
        day -= pd.Timedelta(days=1)
    sessions = opens if opens is not None else _fetch_open_days(day - pd.Timedelta(days=30), day)
    if sessions:
        eligible = sorted(pd.Timestamp(item).normalize() for item in sessions if pd.Timestamp(item).normalize() <= day)
        if eligible:
            return eligible[-1].date().isoformat()
    while int(day.weekday()) >= 5:
        day -= pd.Timedelta(days=1)
    return day.date().isoformat()


def _fetch_open_days(start: pd.Timestamp, end: pd.Timestamp) -> list:
    try:
        from market_radar import get_tushare_bundle

        _, pro = get_tushare_bundle()
        cal = pro.trade_cal(
            exchange="SSE",
            start_date=pd.Timestamp(start).strftime("%Y%m%d"),
            end_date=pd.Timestamp(end).strftime("%Y%m%d"),
            is_open="1",
        )
    except Exception:
        return []
    if cal is None or getattr(cal, "empty", True) or "cal_date" not in cal.columns:
        return []
    dates = pd.to_datetime(cal["cal_date"].astype(str), format="%Y%m%d", errors="coerce")
    return [item for item in dates.dropna().dt.normalize().tolist()]


def fetch_benchmark(start: str, end: str) -> pd.DataFrame:
    """补沪深300收盘。失败时返回空表，不改市场中性回测产物。"""
    empty = pd.DataFrame(columns=["date", "equity", "variant"])
    try:
        from market_radar import get_tushare_bundle

        _, pro = get_tushare_bundle()
        raw = pro.index_daily(
            ts_code="000300.SH",
            start_date=pd.Timestamp(start).strftime("%Y%m%d"),
            end_date=pd.Timestamp(end).strftime("%Y%m%d"),
        )
    except Exception:
        return empty
    if raw is None or raw.empty or "trade_date" not in raw.columns or "close" not in raw.columns:
        return empty
    frame = pd.DataFrame(
        {
            "date": pd.to_datetime(raw["trade_date"].astype(str), format="%Y%m%d", errors="coerce"),
            "equity": pd.to_numeric(raw["close"], errors="coerce"),
            "variant": "沪深300",
        }
    )
    return frame.dropna(subset=["date", "equity"])


def store_benchmark(rows: pd.DataFrame, cache_path: Path) -> None:
    if rows is None or rows.empty or "date" not in rows.columns:
        return
    fresh = rows.copy()
    if "equity" not in fresh.columns and "close" in fresh.columns:
        fresh["equity"] = fresh["close"]
    if "equity" not in fresh.columns:
        return
    fresh["date"] = pd.to_datetime(fresh["date"], errors="coerce").dt.normalize()
    fresh["equity"] = pd.to_numeric(fresh["equity"], errors="coerce")
    fresh["variant"] = "沪深300"
    fresh = fresh.dropna(subset=["date", "equity"])
    if fresh.empty:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    if cache_path.is_file():
        old = pd.read_csv(cache_path)
        merged = pd.concat([old, fresh[["date", "equity", "variant"]]], ignore_index=True)
    else:
        merged = fresh[["date", "equity", "variant"]]
    merged["date"] = pd.to_datetime(merged["date"], errors="coerce").dt.normalize()
    merged = merged.dropna(subset=["date", "equity"]).drop_duplicates(["date"], keep="last")
    merged.sort_values("date").to_csv(cache_path, index=False, encoding="utf-8-sig")


def load_books(
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
) -> pd.DataFrame:
    group_file = Path(group_path or GROUP_CSV)
    sleeve_file = Path(sleeve_path or SLEEVE_CSV)
    missing = [p.name for p in (group_file, sleeve_file) if not p.is_file()]
    if missing:
        raise FileNotFoundError("缺少信号组日收益: " + "、".join(missing))
    group = pd.read_csv(group_file)
    sleeve = pd.read_csv(sleeve_file)
    for frame, cols, path in (
        (group, GROUP_COLUMNS, group_file),
        (sleeve, SLEEVE_COLUMNS, sleeve_file),
    ):
        absent = [col for col in ("date", *cols) if col not in frame.columns]
        if absent:
            raise ValueError(f"{path.name} 缺少列: {', '.join(absent)}")
    group["date"] = pd.to_datetime(group["date"], errors="coerce").dt.normalize()
    sleeve["date"] = pd.to_datetime(sleeve["date"], errors="coerce").dt.normalize()
    merged = group[["date", *GROUP_COLUMNS]].merge(
        sleeve[["date", *SLEEVE_COLUMNS]],
        on="date",
        how="outer",
    )
    for col in SLEEVES:
        merged[col] = pd.to_numeric(merged[col], errors="coerce")
    return merged.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)


def load_watch(paths: tuple[Path, ...] | None = None) -> list[dict[str, str]]:
    files = paths or WATCH_FILES
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    found = False
    for path in files:
        if not path.is_file():
            continue
        found = True
        frame = pd.read_csv(path, dtype={"symbol": str})
        if "symbol" not in frame.columns:
            continue
        names = frame["stock_name"] if "stock_name" in frame.columns else ""
        for symbol, name in zip(frame["symbol"], names):
            code = _code(symbol)
            if not code or code in seen:
                continue
            seen.add(code)
            rows.append({"symbol": code, "stock_name": "" if pd.isna(name) else str(name)})
    if not found:
        names = "、".join(path.name for path in files)
        raise FileNotFoundError(f"缺少观察表 {names}")
    return rows


def load_theme_universe(
    rank_paths: tuple[Path, ...] | None = None,
    scan_path: Path | None = None,
) -> tuple[list[dict[str, str]], list[str]]:
    """形态建仓与回测对比的题材全表。排名表不截前 N，量能只留确认建仓。"""
    ranks = rank_paths if rank_paths is not None else THEME_RANK_FILES
    scan = Path(scan_path) if scan_path is not None else PATTERN_SCAN
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    missing: list[str] = []
    found = False
    for path in (*ranks, scan):
        frame = _read_symbol_table(path)
        if frame is None:
            if path.is_file():
                found = True
            else:
                missing.append(path.name)
            continue
        found = True
        for item in _symbol_rows(frame, entry_only=path == scan):
            if item["symbol"] in seen:
                continue
            seen.add(item["symbol"])
            rows.append(item)
    if not found:
        raise FileNotFoundError(
            "缺少形态建仓和回测对比的题材全表：" + "、".join(missing or [p.name for p in (*ranks, scan)])
        )
    if not rows:
        raise ValueError("形态建仓和回测对比的题材全表里没有股票")
    return rows, missing


def _read_symbol_table(path: Path) -> pd.DataFrame | None:
    if not path.is_file():
        return None
    try:
        frame = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
    except pd.errors.EmptyDataError:
        return None
    except UnicodeDecodeError:
        frame = pd.read_csv(path, dtype=str, encoding="utf-8")
    if frame is None or frame.empty or len(frame.columns) == 0:
        return None
    return frame


def _named_column(frame: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    lookup = {str(col).strip(): col for col in frame.columns}
    for name in names:
        if name in lookup:
            return str(lookup[name])
    return None


def _symbol_rows(frame: pd.DataFrame, *, entry_only: bool) -> list[dict[str, str]]:
    code_col = _named_column(frame, _CODE_COLUMNS)
    if code_col is None:
        return []
    name_col = _named_column(frame, _NAME_COLUMNS)
    state_code = _named_column(frame, ("state_code",))
    select_tag = _named_column(frame, ("select_tag",))
    state = _named_column(frame, ("state",))
    entry = _named_column(frame, ("entry",))
    rows: list[dict[str, str]] = []
    for _, record in frame.iterrows():
        if entry_only and not _confirmed_entry(record, state_code, select_tag, state, entry):
            continue
        code = _code(record.get(code_col))
        if not code:
            continue
        name = ""
        if name_col is not None:
            raw = record.get(name_col)
            name = "" if pd.isna(raw) else str(raw).strip()
            if name.lower() in {"nan", "none"}:
                name = ""
        rows.append({"symbol": code, "stock_name": name})
    return rows


def _confirmed_entry(
    record: pd.Series,
    state_code: str | None,
    select_tag: str | None,
    state: str | None,
    entry: str | None,
) -> bool:
    if state_code is not None:
        return str(record.get(state_code) or "").strip().lower() == "entry"
    if select_tag is not None:
        return str(record.get(select_tag) or "").strip() == "待选后通过"
    if state is not None:
        return str(record.get(state) or "").strip() == "建仓"
    if entry is not None:
        return str(record.get(entry) or "").strip().lower() in {"1", "true", "yes", "y"}
    return False


def load_vp6(path: Path | None = None) -> list[dict[str, str]]:
    file = Path(path or VP6_SCAN)
    if not file.is_file():
        raise FileNotFoundError("缺少量价六组合分类结果 vp_six_combo_scan.csv")
    frame = pd.read_csv(file, dtype={"symbol": str})
    if "symbol" not in frame.columns:
        raise ValueError("vp_six_combo_scan.csv 缺少 symbol")
    names = frame["stock_name"] if "stock_name" in frame.columns else ""
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for symbol, name in zip(frame["symbol"], names):
        code = _code(symbol)
        if not code or code in seen:
            continue
        seen.add(code)
        rows.append({"symbol": code, "stock_name": "" if pd.isna(name) else str(name)})
    return rows


def load_ohlc(
    symbols: set[str],
    *,
    cache_path: Path | None = None,
) -> pd.DataFrame:
    file = Path(cache_path or OHLC_CACHE)
    columns = ["date", "symbol", "high", "low", "close", "volume"]
    if not file.is_file():
        return pd.DataFrame(columns=columns)
    frame = pd.read_csv(file, dtype={"symbol": str})
    if not set(columns).issubset(frame.columns):
        return pd.DataFrame(columns=columns)
    frame = frame[columns].copy()
    frame["symbol"] = frame["symbol"].map(_code)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    for col in ("high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["symbol", "date", "high", "low", "close", "volume"])
    frame = frame[frame["symbol"].isin(symbols)]
    return frame.drop_duplicates(["symbol", "date"], keep="last").sort_values(["symbol", "date"])


def store_ohlc(new_rows: pd.DataFrame, cache_path: Path) -> None:
    needed = {"date", "symbol", "high", "low", "close", "volume"}
    if new_rows is None or new_rows.empty or not needed.issubset(new_rows.columns):
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fresh = new_rows[list(needed)].copy()
    fresh["symbol"] = fresh["symbol"].map(_code)
    fresh["date"] = pd.to_datetime(fresh["date"], errors="coerce").dt.normalize()
    for col in ("high", "low", "close", "volume"):
        fresh[col] = pd.to_numeric(fresh[col], errors="coerce")
    fresh = fresh.dropna(subset=["symbol", "date", "high", "low", "close", "volume"])
    if fresh.empty:
        return
    if cache_path.is_file():
        old = load_ohlc(set(fresh["symbol"]).union(_cached_symbols(cache_path)), cache_path=cache_path)
        merged = pd.concat([old, fresh], ignore_index=True)
    else:
        merged = fresh
    merged = merged.drop_duplicates(["symbol", "date"], keep="last")
    merged.to_csv(cache_path, index=False, encoding="utf-8-sig")


def fetch_act_bars(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """补齐主力表演所需的高低收和成交量。失败的代码跳过。"""
    from backtest_sy_002028_threshold import fetch_ohlc_qfq

    frames: list[pd.DataFrame] = []
    for index, symbol in enumerate(symbols):
        try:
            raw = fetch_ohlc_qfq(symbol, start, end)
        except Exception:
            raw = None
        if raw is not None and not raw.empty and {"date", "high", "low", "close", "volume"}.issubset(raw.columns):
            frames.append(
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(raw["date"], errors="coerce"),
                        "symbol": symbol,
                        "high": pd.to_numeric(raw["high"], errors="coerce"),
                        "low": pd.to_numeric(raw["low"], errors="coerce"),
                        "close": pd.to_numeric(raw["close"], errors="coerce"),
                        "volume": pd.to_numeric(raw["volume"], errors="coerce"),
                    }
                )
            )
        if index + 1 < len(symbols):
            time.sleep(0.12)
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True).dropna(subset=["date", "close", "high", "low", "volume"])


def _cached_symbols(cache_path: Path) -> set[str]:
    if not cache_path.is_file():
        return set()
    frame = pd.read_csv(cache_path, dtype={"symbol": str}, usecols=["symbol"])
    return {code for code in frame["symbol"].map(_code) if code}


def parse_symbols(text: str, limit: int = 80) -> tuple[list[str], bool]:
    chunks = []
    buf = ""
    for char in text.replace("，", ",").replace("；", ",").replace(";", ","):
        if char.isalnum() or char == ".":
            buf += char
        elif buf:
            chunks.append(buf)
            buf = ""
    if buf:
        chunks.append(buf)
    out: list[str] = []
    seen: set[str] = set()
    for item in chunks:
        digits = "".join(ch for ch in item if ch.isdigit())
        if len(digits) < 6:
            continue
        code = digits[:6]
        if code in seen:
            continue
        seen.add(code)
        out.append(code)
    return out[:limit], len(out) > limit


def load_closes(
    symbols: set[str],
    *,
    cache_path: Path | None = None,
    fallback_path: Path | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in (cache_path or BARS_CACHE, fallback_path or BARS_FALLBACK):
        if path is None or not Path(path).is_file():
            continue
        frame = pd.read_csv(
            Path(path),
            usecols=lambda col: col in {"date", "symbol", "close"},
            dtype={"symbol": str},
        )
        if not {"date", "symbol", "close"}.issubset(frame.columns):
            continue
        frame["symbol"] = frame["symbol"].map(_code)
        frame = frame[frame["symbol"].isin(symbols)]
        if frame.empty:
            continue
        frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frames.append(frame.dropna(subset=["date", "close"]))
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "close"])
    # 缓存在前，同一天以缓存为准。
    merged = pd.concat(frames, ignore_index=True)
    merged = merged.drop_duplicates(["symbol", "date"], keep="first")
    return merged.sort_values(["symbol", "date"]).reset_index(drop=True)


def closes_to_returns(closes: pd.DataFrame) -> dict[str, pd.Series]:
    out: dict[str, pd.Series] = {}
    if closes.empty:
        return out
    for symbol, part in closes.groupby("symbol", sort=False):
        ordered = part.sort_values("date")
        returns = ordered["close"].pct_change()
        series = pd.Series(returns.to_numpy(), index=ordered["date"])
        series = series.replace([float("inf"), float("-inf")], pd.NA).dropna()
        out[str(symbol)] = series
    return out


def store_closes(new_rows: pd.DataFrame, cache_path: Path) -> None:
    if new_rows.empty:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fresh = new_rows[["date", "symbol", "close"]].copy()
    fresh["symbol"] = fresh["symbol"].map(_code)
    fresh["date"] = pd.to_datetime(fresh["date"], errors="coerce").dt.normalize()
    fresh["close"] = pd.to_numeric(fresh["close"], errors="coerce")
    fresh = fresh.dropna(subset=["symbol", "date", "close"])
    if cache_path.is_file():
        old = pd.read_csv(cache_path, dtype={"symbol": str})
        old["symbol"] = old["symbol"].map(_code)
        old["date"] = pd.to_datetime(old["date"], errors="coerce").dt.normalize()
        old["close"] = pd.to_numeric(old["close"], errors="coerce")
        merged = pd.concat([old[["date", "symbol", "close"]], fresh], ignore_index=True)
    else:
        merged = fresh
    merged = merged.drop_duplicates(["symbol", "date"], keep="last")
    merged.to_csv(cache_path, index=False, encoding="utf-8-sig")


def fetch_closes(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    """补齐时才访问行情。失败的代码跳过，不改观察池。"""
    from backtest_sy_002028_threshold import fetch_ohlc_qfq

    frames: list[pd.DataFrame] = []
    for index, symbol in enumerate(symbols):
        try:
            raw = fetch_ohlc_qfq(symbol, start, end)
        except Exception:
            raw = None
        if raw is not None and not raw.empty and "close" in raw.columns and "date" in raw.columns:
            frames.append(
                pd.DataFrame(
                    {
                        "date": pd.to_datetime(raw["date"], errors="coerce"),
                        "symbol": symbol,
                        "close": pd.to_numeric(raw["close"], errors="coerce"),
                    }
                )
            )
        if index + 1 < len(symbols):
            time.sleep(0.12)
    if not frames:
        return pd.DataFrame(columns=["date", "symbol", "close"])
    return pd.concat(frames, ignore_index=True).dropna(subset=["date", "close"])


def _code(value: object) -> str:
    text = str(value).strip()
    if text.lower() in {"", "nan", "none"}:
        return ""
    if text.endswith(".0"):
        text = text[:-2]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits or len(digits) > 6:
        return digits[:6] if len(digits) > 6 else ""
    return digits.zfill(6)
