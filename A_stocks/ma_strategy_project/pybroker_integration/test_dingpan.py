# -*- coding: utf-8 -*-
"""盯盘对照思源电气 2026-11-06。不写观察池。"""
from __future__ import annotations

import unittest

import pandas as pd

from dingpan import analyze_frame


# 日期从新到旧，与行情导出一致。分析前会反转成时间顺序。
_DATES = [
    "2026-11-06", "2026-11-05", "2026-11-04", "2026-11-03", "2026-11-02",
    "2026-10-30", "2026-10-29", "2026-10-28", "2026-10-27", "2026-10-26",
    "2026-10-23", "2026-10-22", "2026-10-21", "2026-10-20", "2026-10-19",
    "2026-10-16", "2026-10-15", "2026-10-14", "2026-10-13", "2026-10-12",
    "2026-10-09", "2026-10-08", "2026-09-30", "2026-09-29", "2026-09-28",
    "2026-09-24", "2026-09-23", "2026-09-22", "2026-09-21", "2026-09-18",
    "2026-09-17", "2026-09-16", "2026-09-15",
]
_OPEN = [
    116.8, 115.6, 108.8, 105.67, 101.57, 102.09, 106.99, 106.58, 106.79, 107.24,
    106.83, 110.8, 110.34, 125, 117.92, 118.03, 113.96, 118.7, 118.6, 118.52,
    116, 120.4, 120.43, 122.8, 125.79, 128.27, 129.68, 139.02, 138, 135.01,
    134.3, 138.65, 133.01,
]
_HIGH = [
    123.78, 125.45, 114.54, 111.9, 107.95, 104.91, 106.99, 107.59, 108.5, 109.18,
    109.76, 112.75, 113.88, 125.09, 125.95, 120.08, 117.5, 120.08, 120.33, 123.38,
    120.88, 120.76, 122.97, 123, 125.79, 129.68, 129.68, 139.39, 139.6, 138.16,
    136.46, 139, 139.5,
]
_LOW = [
    113.44, 114.98, 105.03, 105.25, 101.57, 101.22, 103.91, 104.4, 104.93, 103,
    104, 107.7, 109.03, 112.59, 117.3, 116.65, 112.02, 115.6, 116.78, 118.35,
    114, 116.53, 119.5, 119.02, 120.04, 125.17, 125.7, 127.07, 137, 133.03,
    133.8, 134.61, 132.69,
]
_CLOSE = [
    113.9, 120.8, 114.45, 108.91, 105.67, 101.97, 104.33, 106.74, 105.42, 106.81,
    109.42, 107.9, 110.81, 112.59, 125.1, 118.03, 116.58, 116.5, 118.7, 120.65,
    120.09, 117.11, 120.46, 120.81, 121.07, 125.22, 128.56, 128.4, 138.89, 138,
    134.42, 135.08, 138.67,
]


def _siyuan() -> pd.DataFrame:
    order = slice(None, None, -1)
    volume = [1_000_000.0] * len(_DATES)
    amount = [0.0] * len(_DATES)
    volume[1] = 22_270_000.0
    volume[13] = 20_000_000.0
    amount[1] = 2_694_000_000.0
    return pd.DataFrame(
        {
            "date": _DATES[order],
            "open": _OPEN[order],
            "high": _HIGH[order],
            "low": _LOW[order],
            "close": _CLOSE[order],
            "volume": volume[order],
            "amount": amount[order],
        }
    )


class DingpanSiyuanTest(unittest.TestCase):
    def test_levels_match_2026_11_06(self) -> None:
        report = analyze_frame(_siyuan())
        self.assertEqual(report["asof"], "2026-11-06")
        self.assertEqual(report["close"], 113.9)
        self.assertEqual(report["stage"], "回调")
        lows = report["lows"]
        self.assertEqual(lows["kind"], "高换手")
        self.assertEqual(lows["first"], 112.59)
        self.assertEqual(lows["first_date"], "2026-10-20")
        self.assertEqual(lows["second"], 114.98)
        self.assertEqual(lows["second_date"], "2026-11-05")
        self.assertEqual(lows["zone_low"], 112.59)
        self.assertEqual(lows["zone_high"], 114.98)
        pullback = report["pullback"]
        self.assertEqual(pullback["lower"], 113.44)
        self.assertEqual(pullback["upper"], 123.78)
        self.assertEqual(pullback["low_date"], "2026-11-06")
        self.assertEqual(pullback["high_date"], "2026-11-06")
        pressure = report["pressure"]
        self.assertEqual(pressure["vwap"], 120.97)
        self.assertEqual(pressure["close"], 120.8)
        self.assertEqual(pressure["high"], 125.45)
        self.assertEqual(pressure["date"], "2026-11-05")
        self.assertEqual(pressure["distance_vwap"], -5.84)
        self.assertEqual(pressure["distance_close"], -5.71)
        self.assertEqual(pressure["distance_high"], -9.21)
        self.assertNotIn("zone_low", pressure)
        self.assertNotIn("upper", pressure)
        breakout = report["breakout"]
        self.assertEqual(breakout["price"], 125.45)
        self.assertFalse(breakout["confirmed"])
        self.assertEqual(breakout["retest"], "未突破")
        self.assertNotEqual(breakout["price"], 125.95)


if __name__ == "__main__":
    unittest.main()
