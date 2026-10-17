# -*- coding: utf-8 -*-
"""只读沪深300净值、信号组日收益和本地日线。补齐日线只写 capm/cache。"""
from __future__ import annotations

import time
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BENCH_CSV = PROJECT_ROOT / "market_neutral" / "output" / "latest" / "benchmark_nav.csv"
GROUP_CSV = PROJECT_ROOT / "output" / "h0_w23_w46" / "group_returns.csv"
SLEEVE_CSV = PROJECT_ROOT / "output" / "doc15_sleeves" / "sleeve_returns.csv"
BARS_FALLBACK = PROJECT_ROOT / "output" / "h0_w23_w46" / "bars.csv"
BARS_CACHE = PROJECT_ROOT / "capm" / "cache" / "bars.csv"
WATCH_FILES = (
    PROJECT_ROOT / "vp_combo_watch_4.csv",
    PROJECT_ROOT / "vp_combo_watch_6.csv",
)

SLEEVES = ("W2+W3", "W4+W6", "M+", "Q", "G")
GROUP_COLUMNS = ("W2+W3", "W4+W6")
SLEEVE_COLUMNS = ("M+", "Q", "G")
FETCH_PAD_START = "2025-06-01"


def load_market(path: Path | None = None) -> pd.Series:
    file = Path(path or BENCH_CSV)
    if not file.is_file():
        raise FileNotFoundError("缺少沪深300净值 benchmark_nav.csv")
    frame = pd.read_csv(file)
    if "date" not in frame.columns or "equity" not in frame.columns:
        raise ValueError("沪深300净值缺少 date 或 equity")
    if "variant" in frame.columns:
        mask = frame["variant"].astype(str).str.contains("300", na=False)
        if bool(mask.any()):
            frame = frame.loc[mask]
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.normalize()
    frame["equity"] = pd.to_numeric(frame["equity"], errors="coerce")
    frame = frame.dropna(subset=["date", "equity"]).sort_values("date")
    returns = frame["equity"].pct_change()
    out = pd.Series(returns.to_numpy(), index=frame["date"])
    out = out[~out.index.duplicated(keep="last")]
    return out.replace([float("inf"), float("-inf")], pd.NA).dropna()


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
        raise FileNotFoundError("缺少观察池 vp_combo_watch_4.csv / vp_combo_watch_6.csv")
    return rows


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
