#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""两套自选池的 T0 建仓 / T+2 持有回测。

分数是成长因子「总分」（雷达组内名次用的就是这列），用当前排名表，回测期内不重算。
量能：收盘满仓买入分数最高的一只；并列时取当日涨幅更低的一只。
其它自选（M加 / Q / G·2+4 / G·1+3+5 各前 3，去掉已在量能里的代码）：收盘满仓买入分数最低的一只；
并列时按因子组顺序，再按组内名次。同一只股票在多组出现时，取它的较低分。
持有到建仓后第 2 个交易日收盘卖出，再按当天规则开新仓。成交用收盘价。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import Any, Optional

import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
for _p in (_SCRIPT_DIR, _PROJECT_ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from backtest_strength_rotation import (  # noqa: E402
    COMMISSION,
    DEFAULT_CASH,
    DEFAULT_START,
    LOT,
    STAMP,
    _finite,
    bar_on,
    commission_fee,
    fetch_index_daily,
    fetch_stock_bars,
    get_pro,
    is_halted,
    is_limit_down,
    is_limit_up,
)
from market_radar import GROWTH_PICK_TABLES, VOLUME_GROWTH_CSV  # noqa: E402

FACTOR_ORDER = ("M加", "Q", "G·2+4", "G·1+3+5")
OUT_DIR = os.path.join(_SCRIPT_DIR, "output", "score_t2_compare")
HOLD_STEP = 2


def _safe_print(msg: str) -> None:
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("gbk", errors="replace").decode("gbk", errors="replace"), flush=True)


def _read_csv(path) -> pd.DataFrame:
    last: Optional[Exception] = None
    for enc in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return pd.read_csv(path, encoding=enc)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"无法读取 {path}: {last}")


def _pct(v: float) -> str:
    return f"{100.0 * float(v):.2f}%"


def load_pools() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """量能全部；其余四组各前 3，并去掉已经出现在量能里的代码。"""
    vol_df = _read_csv(VOLUME_GROWTH_CSV)
    volume: list[dict[str, Any]] = []
    vol_syms: set[str] = set()
    for _, row in vol_df.iterrows():
        sym = str(row["股票代码"]).zfill(6)
        vol_syms.add(sym)
        volume.append(
            {
                "symbol": sym,
                "name": str(row["股票名称"]).strip(),
                "group": "量能",
                "rank": int(row["排名"]),
                "score": float(row["总分"]),
                "factor_ord": 0,
            }
        )
    others: list[dict[str, Any]] = []
    order = {name: i for i, name in enumerate(FACTOR_ORDER)}
    for group, path in GROWTH_PICK_TABLES:
        df = _read_csv(path)
        df = df[pd.to_numeric(df["排名"], errors="coerce") <= 3]
        for _, row in df.iterrows():
            sym = str(row["股票代码"]).zfill(6)
            if sym in vol_syms:
                continue
            others.append(
                {
                    "symbol": sym,
                    "name": str(row["股票名称"]).strip(),
                    "group": group,
                    "rank": int(row["排名"]),
                    "score": float(row["总分"]),
                    "factor_ord": order.get(group, 99),
                }
            )
    return volume, others


def day_pct(bars: dict[str, pd.DataFrame], symbol: str, dt: pd.Timestamp) -> Optional[float]:
    row = bar_on(bars, symbol, dt)
    if row is None:
        return None
    return _finite(row.get("pct"))


def pick_volume(
    pool: list[dict[str, Any]],
    bars: dict[str, pd.DataFrame],
    dt: pd.Timestamp,
) -> Optional[dict[str, Any]]:
    """满仓买入分数最高的一只。并列时取当日涨幅更低的一只。"""

    def tie_pct(item: dict[str, Any]) -> float:
        pct = day_pct(bars, item["symbol"], dt)
        return pct if pct is not None else 1e9

    if not pool:
        return None
    return sorted(pool, key=lambda r: (-r["score"], tie_pct(r), r["symbol"]))[0]


def pick_other(
    pool: list[dict[str, Any]],
    bars: dict[str, pd.DataFrame],
    dt: pd.Timestamp,
) -> Optional[dict[str, Any]]:
    """满仓买入分数最低的一只。并列时按因子组顺序，再按组内名次。同一只股票取它的较低分。"""
    del bars, dt
    best: dict[str, dict[str, Any]] = {}
    for row in pool:
        cur = best.get(row["symbol"])
        key = (row["score"], row["factor_ord"], row["rank"], row["symbol"])
        if cur is None or key < cur["_key"]:
            best[row["symbol"]] = {**row, "_key": key}
    if not best:
        return None
    return sorted(best.values(), key=lambda r: r["_key"])[0]


def close_px(bars: dict[str, pd.DataFrame], symbol: str, dt: pd.Timestamp) -> Optional[float]:
    row = bar_on(bars, symbol, dt)
    if row is None:
        return None
    px = _finite(row.get("close"))
    if px is None or px <= 0:
        return None
    return px


def can_buy(bars, names, symbol, dt) -> bool:
    row = bar_on(bars, symbol, dt)
    if is_halted(row):
        return False
    return not is_limit_up(row, symbol, names.get(symbol, ""))


def can_sell(bars, names, symbol, dt) -> bool:
    row = bar_on(bars, symbol, dt)
    if is_halted(row):
        return False
    return not is_limit_down(row, symbol, names.get(symbol, ""))


def shares_for(budget: float, price: float, *, pay_stamp: bool) -> int:
    if budget <= 0 or price <= 0:
        return 0
    fee_rate = COMMISSION + (STAMP if pay_stamp else 0.0)
    raw = budget / (price * (1.0 + fee_rate))
    n = int(raw // LOT)
    shares = n * LOT
    while shares >= LOT:
        notional = shares * price
        fee = commission_fee(notional) + (notional * STAMP if pay_stamp else 0.0)
        if notional + fee <= budget + 1e-6:
            return shares
        shares -= LOT
    return 0


def sell_fee(notional: float) -> float:
    return commission_fee(notional) + abs(notional) * STAMP


def buy_fee(notional: float) -> float:
    return commission_fee(notional)


def run_book(
    *,
    key: str,
    label: str,
    mode: str,
    calendar: list[pd.Timestamp],
    bars: dict[str, pd.DataFrame],
    names: dict[str, str],
    volume: list[dict[str, Any]],
    others: list[dict[str, Any]],
    initial_cash: float,
) -> dict[str, Any]:
    cash = float(initial_cash)
    long_pos: Optional[dict[str, Any]] = None
    short_pos: Optional[dict[str, Any]] = None
    entry_i: Optional[int] = None
    cycle_mark: Optional[float] = None
    cycle_pnls: list[float] = []
    skipped = 0
    fee_total = 0.0
    equity_rows: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    pick_log: list[dict[str, Any]] = []

    def mark(dt: pd.Timestamp) -> float:
        eq = cash
        if long_pos:
            px = close_px(bars, long_pos["symbol"], dt)
            if px:
                eq += long_pos["shares"] * px
        if short_pos:
            px = close_px(bars, short_pos["symbol"], dt)
            if px:
                eq -= short_pos["shares"] * px
        return eq

    def log_trade(dt, action, side, symbol, price, shares, fee) -> None:
        trades.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "strategy": key,
                "action": action,
                "side": side,
                "symbol": symbol,
                "name": names.get(symbol, ""),
                "price": round(price, 4),
                "shares": int(shares),
                "fee": round(fee, 4),
                "cash_after": round(cash, 2),
            }
        )

    def try_close(dt: pd.Timestamp) -> bool:
        nonlocal cash, long_pos, short_pos, fee_total, skipped
        if long_pos is None and short_pos is None:
            return True
        long_px = None
        short_px = None
        if long_pos is not None:
            if entry_i is not None and calendar[entry_i] >= dt:
                return False
            if not can_sell(bars, names, long_pos["symbol"], dt):
                skipped += 1
                return False
            long_px = close_px(bars, long_pos["symbol"], dt)
            if not long_px:
                skipped += 1
                return False
        if short_pos is not None:
            if not can_buy(bars, names, short_pos["symbol"], dt):
                skipped += 1
                return False
            short_px = close_px(bars, short_pos["symbol"], dt)
            if not short_px:
                skipped += 1
                return False
        long_fee = sell_fee(long_pos["shares"] * long_px) if long_pos is not None and long_px else 0.0
        short_cost = 0.0
        short_fee = 0.0
        if short_pos is not None and short_px:
            short_cost = short_pos["shares"] * short_px
            short_fee = buy_fee(short_cost)
        proceeds = (long_pos["shares"] * long_px - long_fee) if long_pos is not None and long_px else 0.0
        if cash + proceeds + 1e-6 < short_cost + short_fee:
            skipped += 1
            return False
        if long_pos is not None and long_px:
            cash += proceeds
            fee_total += long_fee
            log_trade(dt, "SELL", "long", long_pos["symbol"], long_px, long_pos["shares"], long_fee)
            long_pos = None
        if short_pos is not None and short_px:
            cash -= short_cost + short_fee
            fee_total += short_fee
            log_trade(dt, "COVER", "short", short_pos["symbol"], short_px, short_pos["shares"], short_fee)
            short_pos = None
        return True

    def try_open(dt: pd.Timestamp, eq: float) -> bool:
        nonlocal cash, long_pos, short_pos, fee_total, skipped
        if mode == "volume":
            row = pick_volume(volume, bars, dt)
        else:
            row = pick_other(others, bars, dt)
        plan = [("long", row, 1.0)] if row else []
        if not plan:
            skipped += 1
            return False
        opened = False
        for side, row, weight in plan:
            if row is None:
                continue
            sym = row["symbol"]
            if side == "long" and not can_buy(bars, names, sym, dt):
                skipped += 1
                continue
            if side == "short" and not can_sell(bars, names, sym, dt):
                skipped += 1
                continue
            px = close_px(bars, sym, dt)
            if not px:
                skipped += 1
                continue
            budget = eq * weight
            if side == "long":
                sh = shares_for(min(budget, cash), px, pay_stamp=False)
                if sh < LOT:
                    skipped += 1
                    continue
                notional = sh * px
                fee = buy_fee(notional)
                if notional + fee > cash + 1e-6:
                    skipped += 1
                    continue
                cash -= notional + fee
                fee_total += fee
                long_pos = {"symbol": sym, "shares": sh, "name": row["name"], "score": row["score"]}
                log_trade(dt, "BUY", "long", sym, px, sh, fee)
                opened = True
            else:
                sh = shares_for(budget, px, pay_stamp=True)
                if sh < LOT:
                    skipped += 1
                    continue
                notional = sh * px
                fee = sell_fee(notional)
                cash += notional - fee
                fee_total += fee
                short_pos = {"symbol": sym, "shares": sh, "name": row["name"], "score": row["score"]}
                log_trade(dt, "SHORT", "short", sym, px, sh, fee)
                opened = True
        if opened:
            pick_log.append(
                {
                    "date": dt.strftime("%Y-%m-%d"),
                    "long": "" if not long_pos else f"{long_pos['name']} {long_pos['symbol']}",
                    "short": "" if not short_pos else f"{short_pos['name']} {short_pos['symbol']}",
                }
            )
        return opened

    for i, dt in enumerate(calendar):
        action = "hold"
        if (long_pos or short_pos) and entry_i is not None and i >= entry_i + HOLD_STEP:
            mark_before = mark(dt)
            if try_close(dt):
                if cycle_mark and cycle_mark > 0:
                    cycle_pnls.append(mark(dt) / cycle_mark - 1.0)
                cycle_mark = None
                entry_i = None
                action = "flat"
            else:
                action = "flat_fail"
            del mark_before
        if entry_i is None and long_pos is None and short_pos is None:
            eq = mark(dt)
            if try_open(dt, eq):
                entry_i = i
                cycle_mark = mark(dt)
                action = "open" if action == "hold" else "reopen"
        eq = mark(dt)
        prev = equity_rows[-1]["equity"] if equity_rows else initial_cash
        equity_rows.append(
            {
                "date": dt.strftime("%Y-%m-%d"),
                "strategy": key,
                "label": label,
                "equity": round(eq, 2),
                "day_return": (eq / prev - 1.0) if prev else 0.0,
                "cash": round(cash, 2),
                "long_symbol": "" if not long_pos else long_pos["symbol"],
                "long_name": "" if not long_pos else long_pos["name"],
                "short_symbol": "" if not short_pos else short_pos["symbol"],
                "short_name": "" if not short_pos else short_pos["name"],
                "action": action,
            }
        )

    eq_df = pd.DataFrame(equity_rows)
    rets = pd.to_numeric(eq_df["day_return"], errors="coerce").fillna(0.0) if not eq_df.empty else pd.Series(dtype=float)
    end_eq = float(eq_df["equity"].iloc[-1]) if not eq_df.empty else initial_cash
    total = end_eq / float(initial_cash) - 1.0
    n = max(1, len(eq_df))
    years = n / 252.0
    annual = (1.0 + total) ** (1.0 / years) - 1.0 if years > 0 and (1.0 + total) > 0 else -1.0
    nav = eq_df["equity"] / float(initial_cash) if not eq_df.empty else pd.Series([1.0])
    peak = nav.cummax()
    mdd = float((nav / peak - 1.0).min()) if len(nav) else 0.0
    vol = float(rets.std(ddof=0)) * np.sqrt(252.0) if len(rets) > 1 else 0.0
    sharpe = float(annual / vol) if vol > 1e-12 else 0.0
    win = float(np.mean([p > 0 for p in cycle_pnls])) if cycle_pnls else 0.0
    longs = [p["long"] for p in pick_log if p["long"]]
    shorts = [p["short"] for p in pick_log if p["short"]]
    return {
        "key": key,
        "label": label,
        "total_return": total,
        "annual_return": annual,
        "max_drawdown": mdd,
        "sharpe": sharpe,
        "vol": vol,
        "win_rate": win,
        "n_cycles": len(cycle_pnls),
        "n_open": len(pick_log),
        "skipped": skipped,
        "fee_total": fee_total,
        "fee_pct": fee_total / float(initial_cash),
        "end_equity": end_eq,
        "end_long": "" if eq_df.empty else str(eq_df["long_name"].iloc[-1]),
        "end_long_symbol": "" if eq_df.empty else str(eq_df["long_symbol"].iloc[-1]),
        "end_short": "" if eq_df.empty else str(eq_df["short_name"].iloc[-1]),
        "end_short_symbol": "" if eq_df.empty else str(eq_df["short_symbol"].iloc[-1]),
        "unique_longs": sorted(set(longs)),
        "unique_shorts": sorted(set(shorts)),
        "trade_days": int(n),
        "equity": eq_df,
        "trades": pd.DataFrame(trades),
        "picks": pd.DataFrame(pick_log),
    }


def hs300_nav(pro, start: str, end: str, calendar: list[pd.Timestamp]) -> pd.Series:
    idx = fetch_index_daily(pro, start, end)
    idx = idx.set_index("date")["close"].sort_index()
    aligned = []
    last = None
    for dt in calendar:
        if dt in idx.index and pd.notna(idx.loc[dt]):
            last = float(idx.loc[dt])
        aligned.append(last)
    s = pd.Series(aligned, index=calendar, dtype=float)
    base = s.dropna().iloc[0]
    return s / base


def write_summary(path: str, volume, others, books: list[dict[str, Any]], hs: Optional[float], start: str, end: str, cash: float) -> None:
    vol_lines = "、".join(f"{r['name']}{r['symbol']}（{r['score']:.4f}）" for r in sorted(volume, key=lambda x: -x["score"]))
    best_other: dict[str, dict[str, Any]] = {}
    for row in others:
        cur = best_other.get(row["symbol"])
        key = (row["score"], row["factor_ord"], row["rank"])
        if cur is None or key < cur["_key"]:
            best_other[row["symbol"]] = {**row, "_key": key}
    other_sorted = sorted(best_other.values(), key=lambda r: r["_key"])
    other_lines = "、".join(
        f"{r['name']}{r['symbol']}（{r['group']} {r['score']:.4f}）" for r in other_sorted
    )
    lines = [
        "# 量能买最高分 vs 其它自选买最低分 · 持有 T+2",
        "",
        f"- 区间：{start} ~ {end}",
        f"- 每套初始资金 {cash:,.0f}，各自独立记账，单票满仓",
        "- 分数：成长因子总分（当前排名表，回测期内不重算）",
        "- 量能：买入分数最高的一只；并列取当日涨幅更低的一只",
        "- 其它自选：M加 / Q / G·2+4 / G·1+3+5 各前 3，去掉量能代码；买入分数最低的一只。同一只在多组出现时取较低分，并列按因子组顺序再按组内名次",
        "- 节奏：收盘建仓，持有到之后第 2 个交易日收盘卖出，再按当天规则开新仓。涨停买不进、跌停卖不出、停牌或不足 1 手则跳过",
        "- 费用：佣金万三、最低 5 元；卖出另计印花税 0.05%",
        "- 夏普：年化收益 / 日收益标准差年化，无风险利率为 0",
        "",
        f"- 量能池（分数从高到低）：{vol_lines}",
        f"- 其它自选（分数从低到高）：{other_lines}",
        "",
        "| 策略 | 总收益 | 年化 | 最大回撤 | 夏普 | 波动 | 完整周期 | 周期胜率 | 费用占本金 | 期末权益 | 实际交易过的股票 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for b in books:
        names_traded = "、".join(b["unique_longs"] + [f"空{x}" for x in b["unique_shorts"]]) or "—"
        lines.append(
            f"| {b['label']} | {_pct(b['total_return'])} | {_pct(b['annual_return'])} | {_pct(b['max_drawdown'])} | "
            f"{b['sharpe']:.2f} | {_pct(b['vol'])} | {b['n_cycles']} | {_pct(b['win_rate'])} | {_pct(b['fee_pct'])} | "
            f"{b['end_equity']:,.0f} | {names_traded} |"
        )
    if hs is not None:
        lines.append(f"| 沪深300买入持有 | {_pct(hs)} | — | — | — | — | — | — | — | — | 指数 |")
    lines += [
        "",
        "当前总分没有并列，也没有逐日历史，所以每个 T0 选中的股票相同。T2 仍先卖掉再买回，费用记在收益里。",
        "",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main() -> int:
    start = DEFAULT_START
    end = datetime.now().strftime("%Y-%m-%d")
    cash = DEFAULT_CASH
    os.makedirs(OUT_DIR, exist_ok=True)

    _safe_print("【1/4】读取成长因子总分")
    volume, others = load_pools()
    names = {r["symbol"]: r["name"] for r in volume + others}
    symbols = list(names)
    _safe_print("  量能 " + "、".join(f"{r['name']}{r['score']:.3f}" for r in sorted(volume, key=lambda x: -x["score"])))
    _safe_print(f"  其它自选 {len({r['symbol'] for r in others})} 只")

    _safe_print("【2/4】拉取日线")
    bars = fetch_stock_bars(symbols, start, end)
    missing = [s for s in symbols if s not in bars]
    if missing:
        _safe_print("  无行情: " + ",".join(missing))
    calendar = sorted(
        {
            pd.Timestamp(d).normalize()
            for df in bars.values()
            for d in df["date"]
            if pd.Timestamp(start) <= pd.Timestamp(d).normalize() <= pd.Timestamp(end)
        }
    )
    if len(calendar) < 3:
        raise RuntimeError("交易日不足，无法做 T0/T2")
    _safe_print(f"  {calendar[0].date()} ~ {calendar[-1].date()}  共 {len(calendar)} 个交易日")

    _safe_print("【3/4】回测")
    books = [
        run_book(
            key="volume_high",
            label="量能买最高分",
            mode="volume",
            calendar=calendar,
            bars=bars,
            names=names,
            volume=volume,
            others=others,
            initial_cash=cash,
        ),
        run_book(
            key="other_low",
            label="其它自选买最低分",
            mode="other",
            calendar=calendar,
            bars=bars,
            names=names,
            volume=volume,
            others=others,
            initial_cash=cash,
        ),
    ]
    hs_ret = None
    hs_nav = None
    try:
        pro = get_pro()
        hs_nav = hs300_nav(pro, start, end, calendar)
        if hs_nav.notna().any():
            hs_ret = float(hs_nav.dropna().iloc[-1] - 1.0)
    except Exception as exc:
        _safe_print(f"  沪深300跳过: {exc}")

    eq = pd.concat([b["equity"] for b in books], ignore_index=True)
    tr = pd.concat([b["trades"] for b in books if not b["trades"].empty], ignore_index=True)
    eq.to_csv(os.path.join(OUT_DIR, "equity_curve.csv"), index=False, encoding="utf-8-sig")
    tr.to_csv(os.path.join(OUT_DIR, "trades.csv"), index=False, encoding="utf-8-sig")
    if hs_nav is not None:
        hs_nav.rename("hs300_nav").reset_index().rename(columns={"index": "date"}).to_csv(
            os.path.join(OUT_DIR, "hs300_nav.csv"), index=False, encoding="utf-8-sig"
        )
    metrics = pd.DataFrame(
        [
            {k: v for k, v in b.items() if k not in {"equity", "trades", "picks"}}
            for b in books
        ]
    )
    metrics.to_csv(os.path.join(OUT_DIR, "metrics.csv"), index=False, encoding="utf-8-sig")
    write_summary(
        os.path.join(OUT_DIR, "summary.md"),
        volume,
        others,
        books,
        hs_ret,
        str(calendar[0].date()),
        str(calendar[-1].date()),
        cash,
    )
    _safe_print("【4/4】结果")
    for b in books:
        _safe_print(
            f"  {b['label']}  收益={_pct(b['total_return'])}  年化={_pct(b['annual_return'])}  "
            f"回撤={_pct(b['max_drawdown'])}  夏普={b['sharpe']:.2f}  "
            f"期末={b['end_equity']:.0f}  费用={b['fee_total']:.0f}  "
            f"多={ '/'.join(b['unique_longs']) or '-' }  空={ '/'.join(b['unique_shorts']) or '-' }"
        )
    if hs_ret is not None:
        _safe_print(f"  沪深300  {_pct(hs_ret)}")
    _safe_print(f"  输出 → {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
