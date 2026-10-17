# -*- coding: utf-8 -*-
"""收益归因的回归、窗口和接口契约。不改观察池文件。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capm.model import align_returns, attribute_frame, classify_quadrant, fit_window, scenario_label
from capm.service import sleeves_payload, stocks_payload
from capm.sources import WATCH_FILES, load_books, load_market
from capm_api import router


def _market_and_asset(n: int = 300, alpha: float = 0.0002, beta: float = 1.2):
    dates = pd.bdate_range("2024-01-02", periods=n + 1)
    market = np.linspace(-0.02, 0.03, n)
    asset = alpha + beta * market
    equity = np.empty(n + 1)
    equity[0] = 1.0
    for i, ret in enumerate(market):
        equity[i + 1] = equity[i] * (1.0 + ret)
    bench = pd.DataFrame({"date": dates, "variant": "沪深300", "equity": equity})
    book_dates = dates[1:]
    return bench, book_dates, asset, market


class ModelTests(unittest.TestCase):
    def test_exact_line_recovers_beta_and_alpha(self) -> None:
        _, book_dates, asset, market = _market_and_asset()
        both = pd.DataFrame({"asset": asset, "market": market}, index=book_dates)
        fitted = fit_window(both, 250)
        self.assertIsNotNone(fitted)
        assert fitted is not None
        self.assertEqual(fitted["n"], 250)
        self.assertAlmostEqual(fitted["beta"], 1.2, places=8)
        self.assertAlmostEqual(fitted["alpha_ann"], 0.0002 * 252, places=8)
        self.assertAlmostEqual(fitted["r2"], 1.0, places=8)
        self.assertGreater(fitted["t_alpha"], 1.0)

    def test_short_window_stays_empty(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=50)
        both = pd.DataFrame(
            {"asset": np.linspace(-0.01, 0.01, 50), "market": np.linspace(-0.02, 0.02, 50)},
            index=dates,
        )
        self.assertIsNone(fit_window(both, 120))
        self.assertIsNone(fit_window(both, 250))

    def test_window_uses_the_tail(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=200)
        market = np.linspace(-0.01, 0.02, 200)
        asset = np.concatenate([np.zeros(80), 0.5 * market[80:]])
        both = pd.DataFrame({"asset": asset, "market": market}, index=dates)
        fitted = fit_window(both, 120)
        assert fitted is not None
        self.assertAlmostEqual(fitted["beta"], 0.5, places=6)
        self.assertEqual(fitted["start"], pd.Timestamp(dates[-120]).date().isoformat())

    def test_flat_market_is_not_a_beta(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=80)
        both = pd.DataFrame(
            {"asset": np.linspace(-0.01, 0.01, 80), "market": np.zeros(80)},
            index=dates,
        )
        self.assertIsNone(fit_window(both, 80))

    def test_labels(self) -> None:
        self.assertEqual(scenario_label(0.08, 2.0), "跑赢市场风险基准")
        self.assertEqual(scenario_label(0.08, 0.2), "收益基本可由市场风险解释")
        self.assertEqual(scenario_label(-0.04, 2.0), "跌幅小于模型预期")
        self.assertEqual(scenario_label(0.08, -2.0), "涨幅低于模型预期")

    def test_quadrant_uses_beta_one_and_t_one(self) -> None:
        self.assertEqual(
            classify_quadrant({"beta": 1.0, "t_alpha": 2.0, "alpha_ann": 0.1})["id"],
            "high_alpha_low_beta",
        )
        self.assertEqual(
            classify_quadrant({"beta": 1.01, "t_alpha": 2.0, "alpha_ann": 0.1})["id"],
            "high_alpha_high_beta",
        )
        self.assertEqual(
            classify_quadrant({"beta": -0.2, "t_alpha": 3.0, "alpha_ann": 0.2})["id"],
            "high_alpha_low_beta",
        )
        self.assertEqual(
            classify_quadrant({"beta": 1.2, "t_alpha": 0.99, "alpha_ann": 0.05})["id"],
            "low_alpha_high_beta",
        )
        self.assertEqual(
            classify_quadrant({"beta": 0.4, "t_alpha": -2.0, "alpha_ann": -0.1})["id"],
            "low_alpha_low_beta",
        )
        self.assertEqual(
            classify_quadrant({"beta": 0.4, "t_alpha": 2.0, "alpha_ann": 0.0})["id"],
            "low_alpha_low_beta",
        )
        self.assertEqual(classify_quadrant(None)["id"], "insufficient")

    def test_quadrant_follows_recent_120_not_250(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=250)
        market = np.linspace(-0.02, 0.03, 250)
        asset = np.empty(250)
        asset[:130] = 2.2 * market[:130]
        asset[130:] = 0.001 + 0.4 * market[130:]
        both = pd.DataFrame({"asset": asset, "market": market}, index=dates)
        out = attribute_frame(both)
        assert out["w120"] is not None and out["w250"] is not None
        self.assertAlmostEqual(out["w120"]["beta"], 0.4, places=6)
        self.assertGreater(out["w250"]["beta"], 1.0)
        self.assertEqual(out["quadrant"]["id"], "high_alpha_low_beta")
        self.assertEqual(classify_quadrant(out["w250"])["id"], "low_alpha_high_beta")


class ServiceTests(unittest.TestCase):
    def test_sleeves_match_known_line(self) -> None:
        bench, book_dates, asset, _market = _market_and_asset()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench_path = root / "benchmark_nav.csv"
            group_path = root / "group_returns.csv"
            sleeve_path = root / "sleeve_returns.csv"
            bench.to_csv(bench_path, index=False)
            group = pd.DataFrame({"date": book_dates, "W2+W3": asset, "W4+W6": asset * 0})
            sleeve = pd.DataFrame(
                {
                    "date": book_dates,
                    "M+": asset,
                    "Q": asset,
                    "G": asset,
                }
            )
            group.to_csv(group_path, index=False)
            sleeve.to_csv(sleeve_path, index=False)
            payload = sleeves_payload(
                bench_path=bench_path,
                group_path=group_path,
                sleeve_path=sleeve_path,
            )
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["empty"])
        rows = {row["key"]: row for row in payload["report"]["rows"]}
        self.assertEqual(set(rows), {"W2+W3", "W4+W6", "M+", "Q", "G"})
        self.assertAlmostEqual(rows["W2+W3"]["w250"]["beta"], 1.2, places=6)
        self.assertEqual(rows["W2+W3"]["quadrant_id"], "high_alpha_high_beta")
        self.assertAlmostEqual(rows["W4+W6"]["w250"]["beta"], 0.0, places=6)
        self.assertEqual(rows["W4+W6"]["quadrant_id"], "low_alpha_low_beta")
        self.assertEqual(payload["report"]["rf"], 0)
        self.assertEqual(payload["report"]["benchmark"], "沪深300")

    def test_stocks_do_not_rewrite_watch_and_refresh_is_explicit(self) -> None:
        bench, book_dates, _asset, market = _market_and_asset(n=300)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench_path = root / "benchmark_nav.csv"
            bench.to_csv(bench_path, index=False)
            watch4 = root / "watch4.csv"
            watch6 = root / "watch6.csv"
            watch4.write_text("symbol,stock_name\n000001,平安\n", encoding="utf-8")
            watch6.write_text("symbol,stock_name\n600000,浦发\n", encoding="utf-8")
            before = watch4.read_text(encoding="utf-8")
            closes = pd.DataFrame(
                {
                    "date": book_dates,
                    "symbol": "000001",
                    "close": 10 * np.cumprod(1.0 + (0.0001 + 0.8 * market)),
                }
            )
            bars = root / "bars.csv"
            closes.to_csv(bars, index=False)
            cache = root / "cache" / "bars.csv"
            called = {"n": 0}

            def _boom(symbols, start, end):
                called["n"] += 1
                raise AssertionError("未要求补齐时不应拉行情")

            quiet = stocks_payload(
                universe="watch46",
                refresh=False,
                bench_path=bench_path,
                watch_paths=(watch4, watch6),
                cache_path=cache,
                fallback_path=bars,
                fetcher=_boom,
            )
            self.assertEqual(called["n"], 0)
            self.assertEqual(watch4.read_text(encoding="utf-8"), before)
            by_symbol = {row["symbol"]: row for row in quiet["report"]["rows"]}
            self.assertAlmostEqual(by_symbol["000001"]["w250"]["beta"], 0.8, places=5)
            self.assertEqual(by_symbol["000001"]["quadrant_id"], "high_alpha_low_beta")
            self.assertAlmostEqual(by_symbol["000001"]["w120"]["beta"], 0.8, places=5)
            self.assertEqual(by_symbol["600000"]["quadrant_id"], "insufficient")
            self.assertIn("少于", by_symbol["600000"]["reason"])

            def _fill(symbols, start, end):
                self.assertEqual(symbols, ["600000"])
                long_dates = pd.bdate_range("2024-01-03", periods=260)
                shock = np.linspace(-0.01, 0.02, 260)
                return pd.DataFrame(
                    {
                        "date": long_dates,
                        "symbol": "600000",
                        "close": 8 * np.cumprod(1.0 + shock),
                    }
                )

            refreshed = stocks_payload(
                universe="watch46",
                refresh=True,
                bench_path=bench_path,
                watch_paths=(watch4, watch6),
                cache_path=cache,
                fallback_path=bars,
                fetcher=_fill,
            )
            self.assertTrue(cache.is_file())
            self.assertEqual(watch4.read_text(encoding="utf-8"), before)
            self.assertTrue(any("写入缓存" in note for note in refreshed["report"]["notes"]))


class ApiTests(unittest.TestCase):
    def test_routes_do_not_refresh_on_get(self) -> None:
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        sleeves = client.get("/api/capm/sleeves")
        stocks = client.get("/api/capm/stocks")
        self.assertEqual(sleeves.status_code, 200)
        self.assertEqual(stocks.status_code, 200)
        body = sleeves.json()
        self.assertIn("report", body)
        paths = {getattr(route, "path", "") for route in app.routes}
        self.assertIn("/api/capm/sleeves", paths)
        self.assertIn("/api/capm/stocks", paths)

    def test_live_sleeves_beta_near_existing_report(self) -> None:
        market = load_market()
        books = load_books()
        series = pd.Series(books["W2+W3"].to_numpy(), index=pd.to_datetime(books["date"]))
        both = align_returns(series, market)
        fitted = fit_window(both, len(both))
        assert fitted is not None
        self.assertAlmostEqual(fitted["beta"], 0.777, places=2)


class WatchUntouchedTests(unittest.TestCase):
    def test_real_watch_files_stay_put(self) -> None:
        snapshots = [(path, path.read_bytes()) for path in WATCH_FILES if path.is_file()]
        self.assertTrue(snapshots)
        stocks_payload(universe="watch46", refresh=False)
        for path, raw in snapshots:
            self.assertEqual(path.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
