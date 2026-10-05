# -*- coding: utf-8 -*-
"""行业因子暴露与 M+ 动量观察的数值测试。不访问网络。"""
from __future__ import annotations

import unittest

import pandas as pd

from industry_factor.build import assign_unique_industry, industry_cap_weights, mplus_industry_behavior
from market_radar import industry_exposure_fields, l1_industry_exposure


class IndustryExposureTest(unittest.TestCase):
    def test_each_stock_has_one_industry(self) -> None:
        members = pd.DataFrame(
            {
                "symbol": ["000001", "000002", "000001"],
                "industry_code": ["801780.SI", "801780.SI", "801780.SI"],
                "industry_name": ["银行", "银行", "银行"],
                "in_date": ["20200101", "20200101", "20200101"],
            }
        )
        assigned, conflicts = assign_unique_industry(members)
        self.assertTrue(conflicts.empty)
        self.assertEqual(len(assigned), 2)
        self.assertTrue((assigned["exposure"] == 1).all())
        self.assertEqual(assigned.groupby("symbol")["exposure"].sum().max(), 1)

    def test_overlap_keeps_latest_industry(self) -> None:
        members = pd.DataFrame(
            {
                "symbol": ["000001", "000001"],
                "industry_code": ["801780.SI", "801790.SI"],
                "industry_name": ["银行", "非银金融"],
                "in_date": ["20180101", "20240101"],
            }
        )
        assigned, conflicts = assign_unique_industry(members)
        self.assertEqual(conflicts["symbol"].nunique(), 1)
        row = assigned.set_index("symbol").loc["000001"]
        self.assertEqual(row["industry_code"], "801790.SI")
        self.assertEqual(int(row["exposure"]), 1)

    def test_cap_weights_sum_to_one(self) -> None:
        assigned = pd.DataFrame(
            {
                "symbol": ["000001", "000002", "000003"],
                "industry_code": ["801780.SI", "801780.SI", "801150.SI"],
                "industry_name": ["银行", "银行", "医药生物"],
                "in_date": ["20200101", "20200101", "20200101"],
                "exposure": [1, 1, 1],
            }
        )
        market_value = pd.DataFrame(
            {"symbol": ["000001", "000002", "000003", "000009"], "total_mv": [70.0, 5.0, 25.0, 100.0]}
        )
        coverage, info = industry_cap_weights(assigned, market_value)
        self.assertAlmostEqual(info["cap_weight_sum"], 1.0)
        weights = coverage.set_index("industry_code")["cap_weight"]
        self.assertAlmostEqual(float(weights["801780.SI"]), 0.75)
        self.assertAlmostEqual(float(weights["801150.SI"]), 0.25)
        self.assertEqual(int(coverage.set_index("industry_code").loc["801780.SI", "n_companies"]), 2)

    def test_mplus_keeps_pool_and_groups_mud(self) -> None:
        pool = pd.DataFrame(
            {
                "rank": [1, 2, 3],
                "asof": ["2026-09-28"] * 3,
                "symbol": ["000001", "000002", "000003"],
                "stock_name": ["甲", "乙", "丙"],
                "mud_plus": [0.9, 0.3, 0.6],
            }
        )
        assigned = pd.DataFrame(
            {
                "symbol": ["000001", "000002"],
                "industry_code": ["801780.SI", "801150.SI"],
                "industry_name": ["银行", "医药生物"],
            }
        )
        stocks, grouped, info = mplus_industry_behavior(pool, assigned)
        self.assertEqual(list(stocks["symbol"]), ["000001", "000002", "000003"])
        self.assertEqual(int(stocks.set_index("symbol").loc["000003", "exposure"]), 0)
        self.assertEqual(info["n_pool"], 3)
        self.assertEqual(info["n_mapped"], 2)
        self.assertEqual(info["n_unmapped"], 1)
        means = grouped.set_index("industry_name")["mud_plus_mean"]
        self.assertAlmostEqual(float(means["银行"]), 0.9)
        self.assertAlmostEqual(float(means["医药生物"]), 0.3)
        self.assertAlmostEqual(info["industry_mean_range"], 0.6)
        self.assertEqual(info["n_singleton_industries"], 2)
        self.assertIsNone(info["eta_squared_n_ge_2"])


class RadarIndustryExposureTest(unittest.TestCase):
    def test_l1_exposure_is_one_and_keeps_l2_separate(self) -> None:
        code, name, exposure = l1_industry_exposure(
            {
                "l1_code": "801980.SI",
                "l1_name": "美容护理",
                "l2_code": "801981.SI",
                "l2_name": "个护用品",
            }
        )
        self.assertEqual((code, name, exposure), ("801980.SI", "美容护理", 1))

    def test_missing_l1_uses_saved_exposure(self) -> None:
        fields = industry_exposure_fields(
            "003006",
            {"l2_name": "个护用品"},
            {"003006": ("801980.SI", "美容护理")},
        )
        self.assertEqual(fields["industry_factor_name"], "美容护理")
        self.assertEqual(fields["industry_exposure"], 1)

    def test_unknown_stock_exposure_is_zero(self) -> None:
        fields = industry_exposure_fields("999999", None, {})
        self.assertIsNone(fields["industry_factor_name"])
        self.assertEqual(fields["industry_exposure"], 0)


if __name__ == "__main__":
    unittest.main()
