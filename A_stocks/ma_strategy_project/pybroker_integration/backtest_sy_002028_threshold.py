#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
思源电气(002028) 阈值触发回测

规则（按当前脚本口径）：
1) 一手=100股
2) 前复权(qfq)日线：触发使用 Low/High
3) 建仓触发：空仓时若当日 Low <= 208 <= High，则允许建仓；建仓成交价=208下跌3%=201.76
4) 加仓触发：持有1手时若当日 Low <= 201.76，则允许加仓；加仓成交价=201.76
5) 卖出触发：持有>=1手时若当日 High >= 208上涨7%=222.56，则卖出1手；成交价=222.56
6) 同一天只能成交一笔
7) 若同一天同时满足卖出与买入触发条件，优先卖出（先卖后买）
8) 仅计入卖出端印花税：0.05%（买入端不计费、忽略佣金/过户费/其他费用）
9) 收益率口径：期末对未卖出部分按最后一天 close 做市值估值
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import pandas as pd


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data.fetcher import DataFetcher

_SCRIPT_DIR_BT = os.path.dirname(os.path.abspath(__file__))
_BACKTEST_WINDOW_YAML = os.path.join(_SCRIPT_DIR_BT, "config", "backtest_sy_threshold.yaml")


def _load_backtest_window_from_yaml() -> tuple[str, str, float]:
    """从 config/backtest_sy_threshold.yaml 读取 START_DATE / END_DATE / INITIAL_CASH。"""
    default_sd, default_ed, default_cash = "2026-01-10", "2026-04-20", 50000.0
    if not os.path.isfile(_BACKTEST_WINDOW_YAML):
        return default_sd, default_ed, default_cash
    try:
        import yaml

        with open(_BACKTEST_WINDOW_YAML, encoding="utf-8") as f:
            d = yaml.safe_load(f) or {}
        sd = str(d.get("START_DATE", default_sd)).strip()
        ed = str(d.get("END_DATE", default_ed)).strip()
        ic = d.get("INITIAL_CASH", default_cash)
        ic_f = float(ic) if ic is not None else default_cash
        return sd, ed, ic_f
    except Exception:
        return default_sd, default_ed, default_cash


START_DATE, END_DATE, INITIAL_CASH = _load_backtest_window_from_yaml()

SYMBOL = "002222"

LOT_SHARES = 100
MAX_LOTS = 2

# 为了区分“触发阈值”和“成交价”，这里拆开定义：
# - 触发阈值：用于判断是否触及/下破/上穿
# - 成交价：用于成交时的价格（按你最新要求：买入=成本下跌3%，卖出=成本上涨7%）
BASE_COST = 64.1

# 建仓触发：触及 208
BUY1_TRIGGER = BASE_COST
# 建仓成交：成本价下跌3%
BUY1_PRICE = round(BASE_COST * (1 - 0.03), 2)

# 加仓触发：下探到 201.76（即成本价-3%）
BUY2_TRIGGER = BUY1_PRICE
# 加仓成交：仍用成本价下跌3%的价格
BUY2_PRICE = BUY1_PRICE

# 卖出价相对基准价涨幅（与 BUY1 -3% 口径独立）
SELL_RELATIVE_UP = 0.11
# 卖出触发/成交：与 SELL_RELATIVE_UP 一致
SELL_PRICE = round(BASE_COST * (1 + SELL_RELATIVE_UP), 2)

STAMP_DUTY_RATE = 0.0005  # 0.05%


def six_digit_to_ts_code(code: str) -> str:
    """6 位代码 → Tushare ts_code（沪/深/北）。"""
    c = "".join(filter(str.isdigit, str(code))).zfill(6)
    if c.startswith("6"):
        return f"{c}.SH"
    if c.startswith(("8", "4")):
        return f"{c}.BJ"
    return f"{c}.SZ"


def fetch_stock_name(symbol: str) -> str:
    """
    证券简称：优先 Tushare pro stock_basic，失败则 AkShare 东财个股信息。
    无 token 或均失败时返回空字符串。
    """
    sym = "".join(filter(str.isdigit, str(symbol))).zfill(6)
    try:
        from config.settings import DATA_CONFIG

        token = ((DATA_CONFIG or {}).get("tushare_token") or "").strip()
        if token:
            import tushare as ts

            ts.set_token(token)
            pro = ts.pro_api()
            ts_code = six_digit_to_ts_code(sym)
            df = pro.stock_basic(ts_code=ts_code, fields="ts_code,name")
            if df is not None and not df.empty and "name" in df.columns:
                n = str(df.iloc[0]["name"]).strip()
                if n and n.lower() != "nan":
                    return n
    except Exception:
        pass
    try:
        import akshare as ak

        df = ak.stock_individual_info_em(symbol=sym)
        if df is None or df.empty:
            return ""
        m = dict(zip(df["item"], df["value"]))
        n = str(m.get("股票简称", "")).strip()
        if n and n.lower() != "nan":
            return n
    except Exception:
        pass
    return ""


def prices_from_base_cost(base_cost: float) -> Tuple[float, float, float, float]:
    """由基准价生成触发/成交价（与模块级 BUY1_* / SELL_PRICE 计算规则一致）。"""
    bc = float(base_cost)
    buy1_trigger = bc
    buy1_price = round(bc * (1 - 0.03), 2)
    buy2_price = buy1_price
    sell_price = round(bc * (1 + SELL_RELATIVE_UP), 2)
    return buy1_trigger, buy1_price, buy2_price, sell_price


def _to_float(x) -> float:
    try:
        return float(x)
    except Exception:
        return float("nan")


def fetch_ohlc_qfq(symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    用 DataFetcher 的 _fetch_from_tushare 拉取前复权 qfq 日线。
    """
    fetcher = DataFetcher()
    df = fetcher._fetch_from_tushare(symbol, start_date, end_date)
    if df is None or df.empty:
        # 兜底：走通用 fetch_stock_data（可能来自数据库/API/其他源）
        df2 = fetcher.fetch_stock_data(code=symbol, start_date=start_date, end_date=end_date, use_mock_if_fail=False)
        if df2 is None or df2.empty:
            raise RuntimeError(f"无法获取{symbol}的历史数据：{start_date}~{end_date}（qfq兜底也失败）")
        df = df2

    if "date" not in df.columns:
        raise RuntimeError("获取到的数据不包含 date 列")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close"]:
        if col in df.columns:
            df[col] = df[col].apply(_to_float)

    df = df.sort_values("date").reset_index(drop=True)
    # 严格过滤区间，避免数据源返回边界外的行
    mask = (df["date"] >= pd.to_datetime(start_date)) & (df["date"] <= pd.to_datetime(end_date))
    df = df.loc[mask].reset_index(drop=True)
    return df


@dataclass
class TradeRecord:
    date: str
    action: str  # BUY1 / BUY2 / SELL
    exec_price: float
    shares_before: int
    shares_after: int
    cash_before: float
    cash_after: float
    stamp_duty: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "date": self.date,
            "action": self.action,
            "exec_price": self.exec_price,
            "shares_before": self.shares_before,
            "shares_after": self.shares_after,
            "cash_before": self.cash_before,
            "cash_after": self.cash_after,
            "stamp_duty": self.stamp_duty,
        }


def backtest_threshold_strategy(
    symbol: str,
    start_date: str,
    end_date: str,
    initial_cash: float = INITIAL_CASH,
    base_cost: Optional[float] = None,
    df: Optional[pd.DataFrame] = None,
) -> Dict:
    bc = float(BASE_COST if base_cost is None else base_cost)
    buy1_trigger, buy1_price, buy2_price, sell_price = prices_from_base_cost(bc)

    if df is None:
        df = fetch_ohlc_qfq(symbol, start_date, end_date)
    else:
        df = df.copy()
    if df.empty:
        raise RuntimeError("OHLC数据为空，无法回测")

    cash = float(initial_cash)
    shares = 0  # 当前持股股数（0/100/200）
    trades: List[TradeRecord] = []
    stamp_duty_total = 0.0

    # BUY1 逻辑的“挂单/待成交”状态：
    # 先触及 BASE_COST（BUY1_TRIGGER） -> 之后任意一天只要触及 BUY1_PRICE 即成交
    armed_buy1 = False

    def lots_held(s: int) -> int:
        return int(round(s / LOT_SHARES))

    for _, row in df.iterrows():
        date_str = row["date"].strftime("%Y-%m-%d")
        low = _to_float(row["low"])
        high = _to_float(row["high"])

        cash_before = cash
        shares_before = shares
        trade_done = False

        # 先卖出（先卖后买），同一天只成交一笔
        if shares_before > 0 and high >= sell_price and not trade_done:
            sell_shares = LOT_SHARES  # 规则：卖出1手
            # 理论上 shares_before 只能是100或200；这里做保护
            sell_shares = min(sell_shares, shares_before)

            sell_value = sell_shares * sell_price
            stamp_duty = sell_value * STAMP_DUTY_RATE
            stamp_duty_total += stamp_duty

            # 卖出回笼资金：成交额 - 印花税
            cash += sell_value - stamp_duty
            shares -= sell_shares

            # 卖出清仓后，重置 BUY1 挂单状态
            if shares == 0:
                armed_buy1 = False

            trades.append(
                TradeRecord(
                    date=date_str,
                    action="SELL",
                    exec_price=sell_price,
                    shares_before=shares_before,
                    shares_after=shares,
                    cash_before=cash_before,
                    cash_after=cash,
                    stamp_duty=stamp_duty,
                )
            )
            trade_done = True

        # 建仓（空仓时）：
        # - 第一步触及基准：Low <= BUY1_TRIGGER <= High -> armed_buy1=True
        # - armed 后成交条件：Low <= BUY1_PRICE <= High（限价单触及）才成交 BUY1
        if shares_before == 0 and not trade_done:
            if not armed_buy1:
                if low <= buy1_trigger <= high:
                    armed_buy1 = True

                    # 允许同一天如果已同时触及 BUY1_PRICE，则立即成交（仍满足“一天一笔”）
                    if low <= buy1_price <= high:
                        buy_shares = LOT_SHARES
                        cost = buy_shares * buy1_price
                        if cash >= cost:
                            cash -= cost
                            shares += buy_shares
                            armed_buy1 = False
                            trades.append(
                                TradeRecord(
                                    date=date_str,
                                    action="BUY1",
                                    exec_price=buy1_price,
                                    shares_before=shares_before,
                                    shares_after=shares,
                                    cash_before=cash_before,
                                    cash_after=cash,
                                )
                            )
                            trade_done = True
                        else:
                            # 资金不足：取消挂单
                            armed_buy1 = False
                            trade_done = True
            else:
                # armed_buy1 已开启：之后只要当日限价触及即可成交
                if low <= buy1_price <= high:
                    buy_shares = LOT_SHARES
                    cost = buy_shares * buy1_price
                    if cash >= cost:
                        cash -= cost
                        shares += buy_shares
                        armed_buy1 = False
                        trades.append(
                            TradeRecord(
                                date=date_str,
                                action="BUY1",
                                exec_price=buy1_price,
                                shares_before=shares_before,
                                shares_after=shares,
                                cash_before=cash_before,
                                cash_after=cash,
                            )
                        )
                        trade_done = True
                    else:
                        armed_buy1 = False
                        trade_done = True

        # 加仓（已有1手时）：按限价单模拟，只有当日 Low <= BUY2_PRICE <= High 才能成交
        if shares_before == LOT_SHARES and not trade_done:
            if low <= buy2_price <= high:
                buy_shares = LOT_SHARES
                cost = buy_shares * buy2_price
                if cash >= cost and lots_held(shares_before + buy_shares) <= MAX_LOTS:
                    cash -= cost
                    shares += buy_shares
                    trades.append(
                        TradeRecord(
                            date=date_str,
                            action="BUY2",
                            exec_price=buy2_price,
                            shares_before=shares_before,
                            shares_after=shares,
                            cash_before=cash_before,
                            cash_after=cash,
                        )
                    )
                    trade_done = True
                else:
                    trade_done = True

    last_close = float(df.iloc[-1]["close"])
    end_assets = cash + shares * last_close
    ret = (end_assets - float(initial_cash)) / float(initial_cash)

    return {
        "symbol": symbol,
        "start_date": start_date,
        "end_date": end_date,
        "initial_cash": float(initial_cash),
        "base_cost": bc,
        "buy1_trigger": buy1_trigger,
        "buy1_price": buy1_price,
        "buy2_price": buy2_price,
        "sell_price": sell_price,
        "final_cash": float(cash),
        "final_shares": int(shares),
        "last_close": last_close,
        "final_assets": float(end_assets),
        "return_pct": float(ret * 100.0),
        "stamp_duty_total": float(stamp_duty_total),
        "trades": [t.to_dict() for t in trades],
    }


def main() -> None:
    _sn = fetch_stock_name(SYMBOL)
    print(f"回测标的: {SYMBOL}" + (f"  {_sn}" if _sn else ""))
    print(f"区间: {START_DATE} ~ {END_DATE}")
    print(f"初始资金: {INITIAL_CASH:,.2f} 元")
    print(f"每手: {LOT_SHARES} 股；最多 {MAX_LOTS} 手")
    print(f"规则: 触及建仓(成交价{BUY1_PRICE})；-3%下探加仓(成交价{BUY2_PRICE})；{SELL_PRICE}上破卖出(成交价{SELL_PRICE})")
    print(f"费用: 仅卖出印花税 {STAMP_DUTY_RATE*100:.3f}%")

    result = backtest_threshold_strategy(SYMBOL, START_DATE, END_DATE, initial_cash=INITIAL_CASH)

    print("=" * 80)
    print(f"期初资产: {result['initial_cash']:,.2f}")
    print(f"期末现金: {result['final_cash']:,.2f}")
    print(f"期末持股: {result['final_shares']} 股")
    print(f"期末close: {result['last_close']:.4f}")
    print(f"期末资产(现金+市值): {result['final_assets']:,.2f}")
    print(f"收益率: {result['return_pct']:.4f}%")
    print(f"卖出端印花税合计: {result['stamp_duty_total']:,.2f} 元")
    print("=" * 80)

    trades_df = pd.DataFrame(result["trades"])
    if trades_df.empty:
        print("没有触发任何交易。")
    else:
        print("交易明细（按执行顺序）：")
        # 输出裁剪列，避免太宽
        show_cols = ["date", "action", "exec_price", "shares_before", "shares_after", "cash_before", "cash_after", "stamp_duty"]
        trades_df = trades_df[show_cols]
        print(trades_df.to_string(index=False))

    # 保存CSV
    # script_dir = os.path.dirname(os.path.abspath(__file__))
    # out_csv = os.path.join(
    #     script_dir,
    #     f"backtest_result_{SYMBOL}_{START_DATE.replace('-', '')}_{END_DATE.replace('-', '')}.csv",
    # )
    # trades_df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    # print(f"交易明细已保存到: {out_csv}")


if __name__ == "__main__":
    main()

