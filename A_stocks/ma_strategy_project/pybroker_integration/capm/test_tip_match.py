# -*- coding: utf-8 -*-
"""启动前山尖。不改观察池。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from capm.tip_match import _row_key, score_tip, tip_payload


def _frame(symbol: str, closes, volumes, start="2026-01-05") -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": volumes,
        }
    )


def _long_base() -> pd.DataFrame:
    """大约两个月缓缓走低，末端贴出圆弧，山尖只有一根。"""
    closes = [10.0] * 40
    closes.extend([10.4, 10.8, 11.2])
    closes.append(11.6)
    closes.extend(list(np.linspace(11.3, 9.5, 22)))
    closes.extend(list(np.linspace(9.42, 9.20, 16)))
    closes.extend([9.12, 9.08, 9.06, 9.05, 9.07, 9.09, 9.08, 9.10])
    volumes = [100.0] * len(closes)
    volumes[-4] = 230.0
    return _frame("000010", closes, volumes)


def _rounding(tip_at: int = -4, tip_volume: float = 230.0) -> pd.DataFrame:
    """更早有一只更高的翅膀；靠近今天先急跌，再在低点贴着走出圆弧，山尖在这一带。"""
    closes = [12.0] * 55
    closes.append(14.0)
    closes.extend(list(np.linspace(13.0, 10.6, 6)))
    closes.extend(list(np.linspace(10.8, 11.5, 4)))
    closes.append(11.8)
    closes.extend([11.2, 10.6, 10.0, 9.5, 9.15, 8.95, 8.82, 8.74])
    closes.extend([8.70, 8.68, 8.66, 8.65, 8.67, 8.69, 8.68, 8.70])
    volumes = [100.0] * len(closes)
    volumes[tip_at] = tip_volume
    return _frame("000001", closes, volumes)


class TipScoreTest(unittest.TestCase):
    def test_rounding_bottom_with_nearby_tip_matches(self):
        scored = score_tip(_rounding())
        self.assertTrue(scored["matched"])
        self.assertGreater(scored["similarity"], 0)
        self.assertGreaterEqual(scored["tip"], 2.0)
        self.assertIn("整理", scored["reason"])
        self.assertIn("贴着走", scored["reason"])
        self.assertLess(scored["base_n"], 40)
        self.assertIn("1 根", scored["reason"])
        self.assertIn("前 20 日均量", scored["reason"])
        self.assertNotIn("14.00", scored["reason"])

    def test_fewer_tip_bars_rank_higher(self):
        narrow = score_tip(_rounding())
        wide = _rounding()
        wide.loc[wide.index[-6] :, "volume"] = 400.0
        piled = score_tip(wide)
        self.assertTrue(piled["matched"])
        self.assertGreater(piled["tip_n"], narrow["tip_n"])
        self.assertGreater(narrow["similarity"], piled["similarity"])

    def test_two_month_base_ranks_ahead_of_a_short_drop(self):
        long = _long_base()
        long.loc[long.index[-6] :, "volume"] = 400.0
        wide = score_tip(long)
        short = score_tip(_rounding())
        self.assertTrue(wide["matched"])
        self.assertGreaterEqual(wide["base_n"], 40)
        self.assertGreater(wide["tip_n"], short["tip_n"])
        wide["symbol"] = "000010"
        short["symbol"] = "000001"
        self.assertLess(_row_key(wide), _row_key(short))

    def test_volume_below_two_times_is_not_a_tip(self):
        scored = score_tip(_rounding(tip_volume=150.0))
        self.assertFalse(scored["matched"])

    def test_needle_low_is_not_a_bowl(self):
        closes = [11.0] * 50
        closes.append(11.8)
        closes.extend([11.2, 10.5, 9.8, 9.3])
        closes.append(8.5)
        closes.extend([8.95, 9.0, 8.98, 9.02, 9.0, 8.97, 9.01, 8.99, 9.0, 8.98, 9.02, 9.0])
        volumes = [100.0] * len(closes)
        volumes[-3] = 260.0
        scored = score_tip(_frame("000007", closes, volumes))
        self.assertFalse(scored["matched"])

    def test_older_wing_is_not_used(self):
        closes = [14.0]
        closes.extend(list(np.linspace(13.6, 9.2, 50)))
        closes.extend([9.15, 9.18, 9.12, 9.2, 9.16, 9.19, 9.14, 9.17, 9.15])
        volumes = [100.0] * len(closes)
        volumes[-4] = 180.0
        scored = score_tip(_frame("000006", closes, volumes))
        self.assertFalse(scored["matched"])

    def test_tip_on_the_far_wing_does_not_count(self):
        frame = _rounding(tip_at=30)
        scored = score_tip(frame)
        self.assertFalse(scored["matched"])

    def test_straight_decline_has_not_started_the_arc(self):
        closes = [9.0] * 25 + [10.0]
        closes.extend(list(np.linspace(9.9, 8.0, 40)))
        volumes = [100.0] * len(closes)
        volumes[-1] = 180.0
        scored = score_tip(_frame("000002", closes, volumes))
        self.assertFalse(scored["matched"])

    def test_right_wing_that_pulls_back_has_flown(self):
        frame = _rounding()
        frame.loc[frame.index[-3], "close"] = 9.90
        scored = score_tip(frame)
        self.assertFalse(scored["matched"])

    def test_rebound_off_the_low_has_flown(self):
        closes = [9.0] * 25 + [10.0]
        closes.extend(list(np.linspace(9.8, 8.0, 20)))
        closes.extend(list(np.linspace(8.1, 9.3, 15)))
        volumes = [100.0] * len(closes)
        volumes[-8] = 170.0
        scored = score_tip(_frame("000003", closes, volumes))
        self.assertFalse(scored["matched"])

    def test_flat_tape_does_not_match(self):
        scored = score_tip(_frame("000004", [10.0] * 70, [100.0] * 70))
        self.assertFalse(scored["matched"])

    def test_rally_then_drop_is_not_this_wing(self):
        closes = [9.0] * 30 + [10.0]
        closes.extend(list(np.linspace(9.7, 7.6, 16)))
        closes.extend(list(np.linspace(7.8, 9.3, 14)))
        closes.extend(list(np.linspace(9.0, 7.5, 9)))
        volumes = [80.0] * len(closes)
        volumes[-1] = 300.0
        scored = score_tip(_frame("000005", closes, volumes))
        self.assertFalse(scored["matched"])


class TipPayloadTest(unittest.TestCase):
    def test_payload_lists_only_the_left_wing(self):
        wing = _rounding()
        wing["symbol"] = "000001"
        flat = _frame("000002", [10.0] * len(wing), [100.0] * len(wing))
        pasted = _rounding()
        pasted["symbol"] = "600001"
        ohlc = pd.concat([wing, flat, pasted], ignore_index=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch = root / "watch.csv"
            pd.DataFrame({"symbol": ["000001", "000002"], "stock_name": ["甲", "乙"]}).to_csv(watch, index=False)
            cache = root / "ohlc.csv"
            ohlc.to_csv(cache, index=False)
            payload = tip_payload(
                symbols="600001",
                ohlc_path=cache,
                watch_paths=(watch,),
                fetch_missing=False,
            )
        self.assertTrue(payload["ok"])
        report = payload["report"]
        symbols = [row["symbol"] for row in report["rows"]]
        self.assertEqual(symbols[0], "000001")
        self.assertIn("600001", symbols)
        self.assertNotIn("000002", symbols)
        self.assertEqual(report["unrelated_count"], 1)
        self.assertEqual(report["unrelated_pasted"], [])
        self.assertTrue(all(row["reason"] for row in report["rows"]))
        self.assertIn("不写观察池", " ".join(report["notes"]))


if __name__ == "__main__":
    unittest.main()
