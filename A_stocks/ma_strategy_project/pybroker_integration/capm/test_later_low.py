# -*- coding: utf-8 -*-
"""稍后低点贴近 20%。不改百亚启动段。"""
from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from capm.later_low import (
    LIFT_SCALE,
    LIFT_TARGET,
    RELATED_MIN,
    later_low_index,
    later_low_payload,
    lift_score,
    score_later_low,
)
from capm.launch_match import score_frame, measure_template


def _frame(symbol: str, closes, lows, start="2026-01-05") -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    lows = np.asarray(lows, dtype=float)
    dates = pd.bdate_range(start, periods=len(closes))
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": closes * 0.995,
            "high": np.maximum(closes, lows) * 1.01,
            "low": lows,
            "close": closes,
            "volume": np.full(len(closes), 100.0),
        }
    )


def _feet(second: float, last_close: float, third: float | None = None) -> pd.DataFrame:
    """一根 12.00 的螺旋低点，之后一根附近低点，再走到给定收盘。"""
    count = 90
    closes = [18.0] * count
    lows = [17.0] * count
    closes[40] = 12.2
    lows[40] = 12.0
    for index in list(range(35, 40)) + list(range(41, 46)):
        lows[index] = 14.0
        closes[index] = 14.2
    closes[60] = second + 0.2
    lows[60] = second
    for index in list(range(55, 60)) + list(range(61, 66)):
        lows[index] = second + 1.2
        closes[index] = second + 1.4
    if third is not None:
        closes[75] = third + 0.2
        lows[75] = third
        for index in list(range(70, 75)) + list(range(76, 81)):
            lows[index] = third + 1.2
            closes[index] = third + 1.4
    closes[-1] = last_close
    lows[-1] = min(lows[-1], last_close * 0.99)
    return _frame("000001", closes, lows)


class LaterLowTest(unittest.TestCase):
    def test_score_peaks_at_20_percent(self):
        self.assertAlmostEqual(lift_score(LIFT_TARGET), 1.0)
        self.assertGreater(lift_score(0.20), lift_score(0.10))
        self.assertGreater(lift_score(0.20), lift_score(0.40))
        edge = LIFT_TARGET + LIFT_SCALE * math.log(2)
        self.assertAlmostEqual(lift_score(edge), 0.5, places=6)

    def test_uses_the_later_nearby_low(self):
        frame = _feet(12.36, 12.48 * 1.20, third=12.48)
        index = later_low_index(frame)
        self.assertIsNotNone(index)
        self.assertAlmostEqual(float(frame["low"].iloc[index]), 12.48)
        scored = score_later_low(frame)
        self.assertAlmostEqual(scored["gain"], 0.20, places=4)
        self.assertAlmostEqual(scored["similarity"], 1.0, places=4)
        self.assertTrue(scored["related"])

    def test_far_above_20_percent_is_not_listed(self):
        frame = _feet(12.36, 12.36 * 1.40)
        scored = score_later_low(frame)
        self.assertGreater(scored["gain"], 0.30)
        self.assertFalse(scored["related"])
        self.assertLess(scored["similarity"], RELATED_MIN)

    def test_without_a_later_low_scores_zero(self):
        closes = [20.0 - i * 0.05 for i in range(90)]
        lows = [value * 0.99 for value in closes]
        frame = _frame("000002", closes, lows)
        self.assertIsNone(later_low_index(frame))
        scored = score_later_low(frame)
        self.assertEqual(scored["similarity"], 0.0)
        self.assertFalse(scored["related"])

    def test_payload_lists_only_the_near_20_name(self):
        near = _feet(12.36, 12.36 * 1.20)
        far = _feet(12.36, 12.36 * 1.50)
        far["symbol"] = "000002"
        quiet = _frame("000003", [20.0 - i * 0.02 for i in range(90)], [19.0] * 90)
        ohlc = pd.concat([near, far, quiet], ignore_index=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch = root / "watch.csv"
            pd.DataFrame(
                {"symbol": ["000001", "000002", "000003"], "stock_name": ["甲", "乙", "丙"]}
            ).to_csv(watch, index=False)
            cache = root / "ohlc.csv"
            ohlc.to_csv(cache, index=False)
            payload = later_low_payload(
                symbols="000001",
                ohlc_path=cache,
                watch_paths=(watch,),
                fetch_missing=False,
            )
        self.assertTrue(payload["ok"])
        report = payload["report"]
        self.assertEqual([row["symbol"] for row in report["rows"]], ["000001"])
        self.assertIn("贴近 20%", report["rows"][0]["reason"])
        self.assertEqual(report["unrelated_count"], 2)
        self.assertIn("不并入百亚启动段", " ".join(report["notes"]))

    def test_launch_similarity_stays_on_four_factors(self):
        frame = _feet(12.36, 12.36 * 1.20)
        launch = score_frame(frame, measure_template(None))
        self.assertEqual(set(launch), {
            "similarity",
            "spiral",
            "price",
            "volume",
            "yang",
            "yang_n",
            "vr",
            "related",
            "reason",
        })
        self.assertNotIn("gain", launch)


if __name__ == "__main__":
    unittest.main()
