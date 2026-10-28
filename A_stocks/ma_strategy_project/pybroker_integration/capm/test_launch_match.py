# -*- coding: utf-8 -*-
"""百亚启动段四项距离。不改观察池。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from capm.launch_match import (
    RELATED_MIN,
    find_ignition,
    launch_payload,
    measure_template,
    score_frame,
    yang_count,
)


def _frame(symbol: str, closes, volumes, lows=None, opens=None, start="2026-01-05") -> pd.DataFrame:
    closes = np.asarray(closes, dtype=float)
    volumes = np.asarray(volumes, dtype=float)
    dates = pd.bdate_range(start, periods=len(closes))
    low = closes * 0.99 if lows is None else np.asarray(lows, dtype=float)
    high = np.maximum(closes, low) * 1.01
    opened = closes * 0.995 if opens is None else np.asarray(opens, dtype=float)
    return pd.DataFrame(
        {
            "date": dates,
            "symbol": symbol,
            "open": opened,
            "high": high,
            "low": low,
            "close": closes,
            "volume": volumes,
        }
    )


def _sawtooth(steps: int = 6, span: int = 14) -> tuple[list[float], list[float]]:
    """逐级更低的低点，中间有反弹，方便摆动低点被识别。"""
    closes: list[float] = []
    lows: list[float] = []
    price = 50.0
    trough = 50.0
    for step in range(steps):
        trough = 50.0 * (1 - 0.08 * (step + 1))
        for i in range(span):
            if i < span - 4:
                value = price + (trough - price) * (i + 1) / (span - 4)
            else:
                value = trough + (price * 0.97 - trough) * (i - (span - 5)) / 4
            closes.append(value)
            lows.append(min(value, trough if i >= span - 5 else value))
        price = closes[-1]
    return closes, lows


class LaunchMatchTest(unittest.TestCase):
    def test_descending_launch_is_related_and_explained(self):
        closes, lows = _sawtooth()
        base = closes[-1]
        for i, pct in enumerate((0.04, 0.03, 0.05)):
            base = base * (1 + pct)
            closes.append(base)
            lows.append(base * 0.985)
        volumes = [100.0] * (len(closes) - 3) + [380.0, 320.0, 360.0]
        opens = [value * 0.99 for value in closes]
        frame = _frame("000001", closes, volumes, lows, opens)
        template = measure_template(None)
        scored = score_frame(frame, template)
        self.assertGreaterEqual(scored["similarity"], RELATED_MIN)
        self.assertTrue(scored["related"])
        self.assertGreaterEqual(scored["yang_n"], 1)
        self.assertIn("阳线", _reason_of(frame, template))

    def test_still_falling_has_no_reason(self):
        closes = []
        price = 40.0
        for _ in range(100):
            price *= 0.997
            closes.append(price)
        volumes = [100.0] * len(closes)
        frame = _frame("000002", closes, volumes)
        scored = score_frame(frame, measure_template(None))
        self.assertFalse(scored["related"])
        self.assertEqual(scored["reason"], "")
        self.assertIsNone(find_ignition(frame))

    def test_long_run_of_yang_is_not_related(self):
        closes, lows = _sawtooth()
        base = closes[-1]
        for _ in range(12):
            base *= 1.03
            closes.append(base)
            lows.append(base * 0.99)
        volumes = [100.0] * (len(closes) - 12) + [350.0] * 12
        opens = [value * 0.99 for value in closes]
        frame = _frame("000003", closes, volumes, lows, opens)
        scored = score_frame(frame, measure_template(None))
        self.assertGreater(scored["yang_n"], 6)
        self.assertFalse(scored["related"])
        self.assertEqual(scored["reason"], "")

    def test_template_reads_baiya_window(self):
        closes = [15.0] * 80
        volumes = [100.0] * 80
        # 业务日里放进 2026-09-09 和 2026-09-11
        dates = pd.bdate_range("2026-06-01", periods=90)
        day0 = list(dates).index(pd.Timestamp("2026-09-09"))
        day2 = list(dates).index(pd.Timestamp("2026-09-11"))
        closes = [14.0] * len(dates)
        lows = [13.6] * len(dates)
        volumes = [100.0] * len(dates)
        for offset, close, volume in ((0, 16.66, 375.0), (1, 17.1, 300.0), (2, 18.2, 340.0)):
            closes[day0 + offset] = close
            volumes[day0 + offset] = volume
        # 让 60 日均线落在 14 附近，低点留在 12.5
        for index in range(day0 - 40, day0):
            closes[index] = 14.1
            lows[index] = 12.51 if index == day0 - 30 else 13.8
        frame = pd.DataFrame(
            {
                "date": dates,
                "symbol": "003006",
                "open": [value * 0.99 for value in closes],
                "high": [value * 1.01 for value in closes],
                "low": lows,
                "close": closes,
                "volume": volumes,
            }
        )
        template = measure_template(frame)
        self.assertEqual(template["source"], "bars")
        self.assertGreater(template["volume"], 3.0)
        self.assertEqual(template["yang"], 3)
        self.assertLess(day2, len(frame))

    def test_payload_merges_paste_and_skips_unrelated_reasons(self):
        match_c, match_l = _sawtooth()
        base = match_c[-1]
        for pct in (0.04, 0.03, 0.05):
            base *= 1 + pct
            match_c.append(base)
            match_l.append(base * 0.985)
        match_v = [100.0] * (len(match_c) - 3) + [380.0, 320.0, 360.0]
        quiet = [20.0 * (0.998 ** i) for i in range(len(match_c))]
        frames = [
            _frame("000001", match_c, match_v, match_l, [v * 0.99 for v in match_c]),
            _frame("000002", quiet, [100.0] * len(quiet)),
            _frame("600001", match_c, match_v, match_l, [v * 0.99 for v in match_c]),
        ]
        ohlc = pd.concat(frames, ignore_index=True)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            watch = root / "watch.csv"
            pd.DataFrame({"symbol": ["000001", "000002"], "stock_name": ["甲", "乙"]}).to_csv(watch, index=False)
            cache = root / "ohlc.csv"
            ohlc.to_csv(cache, index=False)
            payload = launch_payload(
                symbols="600001 003006",
                ohlc_path=cache,
                watch_paths=(watch,),
                fetch_missing=False,
            )
        self.assertTrue(payload["ok"])
        report = payload["report"]
        symbols = [row["symbol"] for row in report["rows"]]
        self.assertIn("000001", symbols)
        self.assertIn("600001", symbols)
        self.assertNotIn("003006", symbols)
        self.assertNotIn("000002", symbols)
        self.assertTrue(all(row["reason"] for row in report["rows"]))
        self.assertEqual(report["unrelated_count"], 1)
        self.assertEqual(report["unrelated_pasted"], [])
        self.assertIn("不参与对照", " ".join(report["notes"]))
        for row in report["rows"]:
            self.assertNotIn("没有相关性", row["reason"])


def _reason_of(frame, template) -> str:
    from capm.launch_match import _reason, score_frame

    row = score_frame(frame, template)
    row["related"] = True
    return _reason(row)


class IgnitionTest(unittest.TestCase):
    def test_counts_yang_from_the_volume_bar(self):
        closes, lows = _sawtooth(steps=4, span=16)
        base = closes[-1]
        opens = [value * 0.99 for value in closes]
        volumes = [100.0] * len(closes)
        for pct, volume, up in ((0.05, 400.0, True), (0.02, 280.0, True), (-0.01, 120.0, False), (0.04, 300.0, True)):
            base = base * (1 + pct)
            closes.append(base)
            lows.append(base * 0.99)
            opens.append(base * (0.99 if up else 1.01))
            volumes.append(volume)
        frame = _frame("000009", closes, volumes, lows, opens)
        start = find_ignition(frame)
        self.assertIsNotNone(start)
        self.assertEqual(yang_count(frame, start), 3)


if __name__ == "__main__":
    unittest.main()
