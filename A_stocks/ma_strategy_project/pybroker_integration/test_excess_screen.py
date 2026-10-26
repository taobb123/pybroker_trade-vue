# -*- coding: utf-8 -*-
"""筛选门闩、交易成本和持有期对照。不读观察池，不改入池规则。"""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd

from excess_screen import (
    MARGIN,
    ROUND_TRIP,
    _pair_return,
    group_flags,
    judge,
    run_from_returns,
    select_excess_pair,
    snapshot,
    trade_cost,
)


def _row(**kwargs: float) -> dict:
    base = {
        "beta_250": 0.3,
        "alpha_250": 0.12,
        "alpha_120": 0.08,
        "excess_120": 0.05,
        "t_alpha_250": 2.0,
        "ir_250": 0.8,
        "stability": 0.75,
        "r2_250": 0.4,
    }
    base.update(kwargs)
    return base


class FlagTests(unittest.TestCase):
    def test_user_band_keeps_mid_alpha_and_drops_the_cap(self) -> None:
        self.assertTrue(group_flags(_row())["U"])
        self.assertTrue(group_flags(_row(alpha_250=0.39))["U"])
        self.assertFalse(group_flags(_row(alpha_250=0.40))["U"])
        self.assertFalse(group_flags(_row(alpha_250=0.45))["U"])
        self.assertTrue(group_flags(_row(alpha_250=-0.05))["U"])
        self.assertFalse(group_flags(_row(alpha_250=-0.10))["U"])
        self.assertFalse(group_flags(_row(alpha_250=-0.11))["U"])

    def test_negative_annual_alpha_stays_in_user_rule_and_out_of_d(self) -> None:
        flags = group_flags(_row(alpha_250=-0.05))
        self.assertTrue(flags["B"])
        self.assertTrue(flags["U"])
        self.assertFalse(flags["C"])
        self.assertFalse(flags["D"])
        self.assertFalse(flags["E"])

    def test_high_alpha_stays_in_d_when_recent_alpha_is_positive(self) -> None:
        flags = group_flags(_row(alpha_250=0.50))
        self.assertTrue(flags["D"])
        self.assertTrue(flags["R"])
        self.assertFalse(flags["U"])

    def test_gross_excess_is_not_enough_for_the_net_rule(self) -> None:
        tiny = group_flags(_row(excess_120=ROUND_TRIP * 0.5))
        self.assertTrue(tiny["U"])
        self.assertTrue(tiny["D"])
        self.assertFalse(tiny["R"])
        covered = group_flags(_row(excess_120=ROUND_TRIP + 0.01))
        self.assertTrue(covered["R"])

    def test_beta_bounds_are_closed_at_zero_and_one_half(self) -> None:
        self.assertTrue(group_flags(_row(beta_250=0.0))["B"])
        self.assertTrue(group_flags(_row(beta_250=0.5))["B"])
        self.assertFalse(group_flags(_row(beta_250=-0.01))["B"])
        self.assertFalse(group_flags(_row(beta_250=0.51))["U"])

    def test_quality_gate_needs_d_plus_all_three_checks(self) -> None:
        self.assertTrue(group_flags(_row())["E"])
        self.assertFalse(group_flags(_row(t_alpha_250=0.99))["E"])
        self.assertFalse(group_flags(_row(ir_250=0.0))["E"])
        self.assertFalse(group_flags(_row(stability=0.49))["E"])
        self.assertTrue(group_flags(_row(stability=0.5))["E"])
        self.assertFalse(group_flags(_row(alpha_120=-0.01))["E"])

    def test_zero_recent_alpha_fails_user_and_d(self) -> None:
        flags = group_flags(_row(alpha_120=0.0))
        self.assertFalse(flags["U"])
        self.assertFalse(flags["D"])
        self.assertTrue(flags["C"])


class CostTests(unittest.TestCase):
    def test_equal_weight_turnover(self) -> None:
        self.assertAlmostEqual(trade_cost(set(), {"a", "b"}), 0.0003, places=8)
        self.assertAlmostEqual(trade_cost({"a", "b"}, set()), 0.0008, places=8)
        self.assertEqual(trade_cost({"a", "b"}, {"a", "b"}), 0.0)
        self.assertAlmostEqual(trade_cost({"a"}, {"a", "b"}), 0.00055, places=8)


class JudgeTests(unittest.TestCase):
    def _groups(self, excess: dict[str, float], holdout_e: float = 0.02, holdout_u: float = 0.01) -> dict:
        groups = {}
        for name, value in excess.items():
            groups[name] = {"excess_net": value, "holdout_excess_net": 0.0}
        groups["E"]["holdout_excess_net"] = holdout_e
        groups["U"]["holdout_excess_net"] = holdout_u
        return groups

    def test_confirmation_needs_lead_holdout_and_sample_size(self) -> None:
        excess = {"A": 0.01, "B": 0.02, "C": 0.03, "D": 0.03 + MARGIN + 0.01, "E": 0.05, "U": 0.04}
        early = judge(self._groups(excess), n_periods=4)
        self.assertTrue(early["d_beats_prior"])
        self.assertTrue(early["e_holdout_positive"])
        self.assertFalse(early["sample_enough"])
        self.assertFalse(early["confirmed"])
        ready = judge(self._groups(excess), n_periods=10)
        self.assertTrue(ready["confirmed"])
        self.assertGreaterEqual(ready["n_holdout"], 2)

    def test_user_rule_is_scored_separately_from_confirmation(self) -> None:
        excess = {"A": 0.05, "B": 0.05, "C": 0.05, "D": 0.04, "E": 0.01, "U": 0.01}
        verdict = judge(self._groups(excess, holdout_e=-0.01), n_periods=10)
        self.assertFalse(verdict["confirmed"])
        self.assertTrue(verdict["u_beats_market"])
        self.assertFalse(verdict["u_beats_pool"])


class PathTests(unittest.TestCase):
    def _frame(self) -> tuple[pd.DataFrame, pd.Series]:
        n = 280
        dates = pd.bdate_range("2024-01-02", periods=n)
        market = pd.Series(np.resize([0.001, -0.001], n), index=dates, dtype=float)
        low = 0.0005 + 0.25 * market
        rich = 0.003 + 0.25 * market
        high = 1.4 * market
        frame = pd.DataFrame({"low": low, "rich": rich, "high": high}, index=dates)
        return frame, market

    def test_snapshot_ignores_future_and_recovers_beta(self) -> None:
        frame, market = self._frame()
        end = 249
        before = snapshot(frame["low"].to_numpy(), market.to_numpy(), end)
        self.assertIsNotNone(before)
        assert before is not None
        self.assertAlmostEqual(before["beta_250"], 0.25, places=6)
        self.assertAlmostEqual(before["alpha_250"], 0.0005 * 252, places=6)
        blown = frame["low"].to_numpy(dtype=float).copy()
        blown[end + 1 :] = 0.2
        after = snapshot(blown, market.to_numpy(), end)
        self.assertEqual(before["beta_250"], after["beta_250"])
        self.assertEqual(before["alpha_120"], after["alpha_120"])

    def test_baskets_follow_the_predeclared_rules(self) -> None:
        frame, market = self._frame()
        result = run_from_returns(frame, market, hold=20)
        self.assertEqual(result["n_periods"], 1)
        members = {name: set(result["groups"][name]["periods"][0]["members"]) for name in ("A", "B", "D", "E", "U", "R")}
        self.assertEqual(members["A"], {"low", "rich", "high"})
        self.assertEqual(members["B"], {"low", "rich"})
        self.assertEqual(members["D"], {"low", "rich"})
        self.assertEqual(members["E"], {"low", "rich"})
        self.assertEqual(members["U"], {"low"})
        self.assertEqual(members["R"], {"low", "rich"})
        self.assertFalse(result["verdict"]["confirmed"])
        self.assertLess(result["groups"]["U"]["total_net"], result["groups"]["U"]["total_gross"])

    def test_gap_does_not_change_beta_when_overlap_is_complete(self) -> None:
        frame, market = self._frame()
        gapped = frame["low"].to_numpy(dtype=float).copy()
        gapped[10:15] = np.nan
        # 决策日仍用满 250 个重叠日：把窗口末端放在序列后部，前面的空洞被丢掉。
        end = 270
        fitted = snapshot(gapped, market.to_numpy(dtype=float), end)
        self.assertIsNotNone(fitted)
        assert fitted is not None
        self.assertAlmostEqual(fitted["beta_250"], 0.25, places=6)


class PairTests(unittest.TestCase):
    def test_short_the_highest_excess_and_long_the_lowest(self) -> None:
        chosen = select_excess_pair(
            [
                {"symbol": "000002", "excess_120": 0.20, "col": 1, "beta_250": 0.2},
                {"symbol": "000001", "excess_120": -0.05, "col": 0, "beta_250": 0.1},
                {"symbol": "000003", "excess_120": 0.01, "col": 2, "beta_250": 0.4},
            ]
        )
        self.assertIsNotNone(chosen)
        assert chosen is not None
        self.assertEqual(chosen["short"], "000002")
        self.assertEqual(chosen["long"], "000001")

    def test_flat_excess_or_single_name_stays_in_cash(self) -> None:
        self.assertIsNone(
            select_excess_pair(
                [
                    {"symbol": "000001", "excess_120": 0.1, "col": 0},
                    {"symbol": "000002", "excess_120": 0.1, "col": 1},
                ]
            )
        )
        self.assertIsNone(select_excess_pair([{"symbol": "000001", "excess_120": 0.2, "col": 0}]))

    def test_pair_return_is_long_minus_short_before_cost(self) -> None:
        self.assertAlmostEqual(_pair_return(0.02, 0.05, (), ()), -0.03, places=8)
        costly = _pair_return(0.02, -0.01, (0.0003,), (0.0008,))
        self.assertLess(costly, _pair_return(0.02, -0.01, (), ()))

    def test_low_beta_path_shorts_the_richer_name(self) -> None:
        frame, market = PathTests()._frame()
        result = run_from_returns(frame, market, hold=20)
        period = result["pair"]["periods"][0]
        self.assertEqual(period["short"], "rich")
        self.assertEqual(period["long"], "low")
        self.assertNotIn("high", (period["short"], period["long"]))
        self.assertGreater(period["short_excess"], period["long_excess"])
        self.assertLess(result["pair"]["total_net"], result["pair"]["total_gross"])


if __name__ == "__main__":
    unittest.main()
