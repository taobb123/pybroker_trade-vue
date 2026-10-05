# -*- coding: utf-8 -*-
"""风险指数标准化与价格描述变量。不访问网络。"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from risk_index.fundamental import fundamental_raw
from risk_index.leaders import column_max_exposures, risk_tags_by_symbol
from risk_index.price_descriptors import price_raw_frame
from risk_index.spec import DESCRIPTORS
from risk_index.standardize import compose_indices, zscore


class StandardizeTest(unittest.TestCase):
    def test_zscore_is_zero_mean_unit_std(self) -> None:
        raw = pd.Series(np.linspace(-3, 8, 80))
        score = zscore(raw)
        finite = score[np.isfinite(score)]
        self.assertAlmostEqual(float(finite.mean()), 0.0, places=6)
        self.assertAlmostEqual(float(finite.std(ddof=0)), 1.0, places=6)

    def test_high_multiple_raises_value(self) -> None:
        raw = pd.DataFrame({"PE_TTM": np.linspace(5, 80, 60), "PB": np.linspace(0.5, 8, 60)})
        indices, _ = compose_indices(raw)
        value = indices["价值"]
        self.assertGreater(float(value.iloc[-1]), float(value.iloc[0]))
        finite = value[np.isfinite(value)]
        self.assertAlmostEqual(float(finite.mean()), 0.0, places=6)
        self.assertAlmostEqual(float(finite.std(ddof=0)), 1.0, places=6)

    def test_high_earnings_yield_lowers_value(self) -> None:
        raw = pd.DataFrame({"E/P": np.linspace(0.02, 0.12, 60), "股息率": np.linspace(0.5, 6, 60)})
        indices, _ = compose_indices(raw)
        value = indices["价值"]
        self.assertLess(float(value.iloc[-1]), float(value.iloc[0]))

    def test_turnover_direction_is_unset(self) -> None:
        item = next(d for d in DESCRIPTORS if d.name == "20日平均换手率")
        self.assertIsNone(item.sign)


class ColumnMaxTest(unittest.TestCase):
    def test_each_column_picks_the_max_stock(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["000001", "000002", "000001"],
                "name": ["甲", "乙", "甲"],
                "group": ["M加", "Q", "量能"],
                "波动率": [0.2, 1.1, 0.2],
                "动能": [3.8, 0.4, 3.8],
                "流动性": [-0.2, 0.5, -0.2],
                "成长性": [0.1, 1.4, 0.1],
                "价值": [0.9, -0.3, 0.9],
                "盈利波动率": [0.2, 1.25, 0.2],
                "财务杠杆": [-1.0, 1.03, -1.0],
            }
        )
        leaders = column_max_exposures(frame)
        by_factor = {row["factor"]: row for row in leaders}
        self.assertEqual(by_factor["波动率"]["symbol"], "000002")
        self.assertEqual(by_factor["动能"]["name"], "甲")
        self.assertEqual(by_factor["价值"]["exposure"], 0.9)
        self.assertEqual(len(leaders), 7)

    def test_positive_risks_and_column_maximum(self) -> None:
        frame = pd.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "波动率": [-0.2, 1.1],
                "流动性": [0.4, 0.1],
                "价值": [-0.5, 0.2],
                "盈利波动率": [0.3, -0.1],
                "财务杠杆": [-1.0, -0.2],
            }
        )
        tags = risk_tags_by_symbol(frame)
        first = {item["label"]: item["maximum"] for item in tags["000001"]}
        second = {item["label"]: item["maximum"] for item in tags["000002"]}
        self.assertEqual(list(first), ["流动风险", "盈利波动风险"])
        self.assertTrue(first["流动风险"])
        self.assertTrue(first["盈利波动风险"])
        self.assertEqual(list(second), ["波动风险", "流动风险", "价值风险"])
        self.assertTrue(second["波动风险"])
        self.assertFalse(second["流动风险"])
        self.assertTrue(second["价值风险"])
        by_label = {item["label"]: item for item in tags["000002"]}
        self.assertEqual(by_label["波动风险"]["exposure"], 1.1)


class PriceDescriptorTest(unittest.TestCase):
    def test_high_volatility_stock_has_larger_std(self) -> None:
        calm = _panel("000001", scale=0.002)
        wild = _panel("000002", scale=0.03)
        raw = price_raw_frame(pd.concat([calm, wild], ignore_index=True), hs300_ret60=0.0)
        self.assertGreater(raw.loc["000002", "60日收益率标准差"], raw.loc["000001", "60日收益率标准差"])
        self.assertGreater(raw.loc["000002", "VaR"], raw.loc["000001", "VaR"])
        self.assertGreater(raw.loc["000002", "最大回撤"], 0)

    def test_amount_to_float_uses_circ_mv(self) -> None:
        panel = _panel("000001", scale=0.01)
        raw = price_raw_frame(panel, circ_mv=pd.Series({"000001": 100000.0}))
        self.assertTrue(np.isfinite(raw.loc["000001", "成交额比流通市值"]))


class FundamentalTest(unittest.TestCase):
    def test_cagr_and_leverage_sign_inputs(self) -> None:
        annual = pd.DataFrame(
            {
                "symbol": ["000001"] * 4,
                "year": [2021, 2022, 2023, 2024],
                "revenue": [100, 110, 121, 133.1],
                "net_profit": [10, 12, 9, 15],
                "eps": [1, 1.1, 0.9, 1.3],
                "roe": [8, 9, 7, 10],
                "cfo": [9, 8, 11, 10],
            }
        )
        latest = pd.DataFrame({"interest_cover": [12.0]}, index=["000001"])
        raw = fundamental_raw(latest, annual)
        self.assertAlmostEqual(float(raw.loc["000001", "营业收入3年CAGR"]), 0.1, places=6)
        self.assertTrue(np.isfinite(raw.loc["000001", "3年净利润标准差"]))


def _panel(symbol: str, scale: float) -> pd.DataFrame:
    rng = np.random.default_rng(7 if scale < 0.01 else 11)
    ret = rng.normal(0.0005, scale, 260)
    close = 10 * np.cumprod(1 + ret)
    return pd.DataFrame(
        {
            "symbol": symbol,
            "date": pd.bdate_range("2025-01-01", periods=260),
            "close": close,
            "ret": ret,
            "vol": np.full(260, 1000.0),
            "amount": np.full(260, 5000.0),
        }
    )


if __name__ == "__main__":
    unittest.main()
