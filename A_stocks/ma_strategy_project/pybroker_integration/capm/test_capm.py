# -*- coding: utf-8 -*-
"""收益归因的回归、窗口和接口契约。不改观察池文件。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from capm.act import assess_act
from capm.model import align_returns, attribute_frame, classify_quadrant, fit_window, scenario_label
from capm.service import sleeves_payload, stocks_payload
from capm.sources import WATCH_FILES, latest_trading_day, load_books, load_market, load_theme_universe
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
            self.assertAlmostEqual(by_symbol["000001"]["session_return"], 0.0001 + 0.8 * market[-1], places=8)
            self.assertIsNone(by_symbol["600000"]["session_return"])
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

    def test_refresh_rolls_window_to_later_session(self) -> None:
        bench, book_dates, _asset, market = _market_and_asset(n=260)
        old_end = pd.Timestamp(book_dates[-1]).normalize()
        extra = pd.bdate_range(old_end + pd.Timedelta(days=1), periods=4)
        session_end = extra[-1].date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench_path = root / "benchmark_nav.csv"
            bench.to_csv(bench_path, index=False)
            before = bench_path.read_bytes()
            watch4 = root / "watch4.csv"
            watch6 = root / "watch6.csv"
            watch4.write_text("symbol,stock_name\n000001,平安\n", encoding="utf-8")
            watch6.write_text("symbol,stock_name\n", encoding="utf-8")
            closes = pd.DataFrame(
                {
                    "date": book_dates,
                    "symbol": "000001",
                    "close": 10 * np.cumprod(1.0 + (0.0001 + 0.8 * market)),
                }
            )
            bars = root / "bars.csv"
            closes.to_csv(bars, index=False)

            def _bench(start, end):
                self.assertEqual(start, old_end.date().isoformat())
                self.assertEqual(end, session_end)
                level = float(bench["equity"].iloc[-1])
                equity = [level]
                for _ in extra:
                    equity.append(equity[-1] * 1.01)
                return pd.DataFrame(
                    {"date": [old_end, *list(extra)], "equity": equity, "variant": "沪深300"}
                )

            def _fill(symbols, start, end):
                self.assertEqual(symbols, ["000001"])
                self.assertEqual(end, session_end)
                dates = list(book_dates) + list(extra)
                shock = np.resize(0.001, len(dates))
                return pd.DataFrame(
                    {
                        "date": dates,
                        "symbol": symbols[0],
                        "close": 10 * np.cumprod(1.0 + shock),
                    }
                )

            payload = stocks_payload(
                universe="watch46",
                refresh=True,
                session_end=session_end,
                bench_path=bench_path,
                bench_fetcher=_bench,
                bench_cache=root / "benchmark.csv",
                watch_paths=(watch4, watch6),
                cache_path=root / "bars_cache.csv",
                fallback_path=bars,
                fetcher=_fill,
            )
            self.assertEqual(bench_path.read_bytes(), before)
            self.assertEqual(payload["report"]["rows"][0]["w250"]["end"], session_end)
            self.assertIn("沪深300补到", payload["message"])

    def test_failed_benchmark_extension_keeps_the_old_end(self) -> None:
        bench, book_dates, _asset, market = _market_and_asset(n=260)
        old_end = pd.Timestamp(book_dates[-1]).date().isoformat()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench_path = root / "benchmark_nav.csv"
            bench.to_csv(bench_path, index=False)
            watch4 = root / "watch4.csv"
            watch6 = root / "watch6.csv"
            watch4.write_text("symbol,stock_name\n000001,平安\n", encoding="utf-8")
            watch6.write_text("symbol,stock_name\n", encoding="utf-8")
            pd.DataFrame(
                {
                    "date": book_dates,
                    "symbol": "000001",
                    "close": 10 * np.cumprod(1.0 + market),
                }
            ).to_csv(root / "bars.csv", index=False)

            def _empty(_start, _end):
                return pd.DataFrame(columns=["date", "equity"])

            def _fill(symbols, _start, end):
                self.assertEqual(end, "2026-10-20")
                return pd.DataFrame(
                    {
                        "date": list(book_dates),
                        "symbol": symbols[0],
                        "close": 10 * np.cumprod(1.0 + np.resize(0.001, len(book_dates))),
                    }
                )

            payload = stocks_payload(
                universe="watch46",
                refresh=True,
                session_end="2026-10-20",
                bench_path=bench_path,
                bench_fetcher=_empty,
                bench_cache=root / "benchmark.csv",
                watch_paths=(watch4, watch6),
                cache_path=root / "bars_cache.csv",
                fallback_path=root / "bars.csv",
                fetcher=_fill,
            )
            self.assertEqual(payload["report"]["rows"][0]["w250"]["end"], old_end)
            self.assertIn("窗口仍停在", payload["message"])


class SessionTests(unittest.TestCase):
    def test_latest_session_uses_last_close(self) -> None:
        self.assertEqual(latest_trading_day(datetime(2026, 10, 17, 16, 0), opens=[]), "2026-10-16")
        self.assertEqual(
            latest_trading_day(datetime(2026, 10, 20, 10, 0), opens=["2026-10-19", "2026-10-20"]),
            "2026-10-19",
        )
        self.assertEqual(
            latest_trading_day(datetime(2026, 10, 20, 16, 0), opens=["2026-10-19", "2026-10-20"]),
            "2026-10-20",
        )
        self.assertEqual(
            latest_trading_day(datetime(2026, 10, 8, 16, 0), opens=["2026-09-30", "2026-10-09"]),
            "2026-09-30",
        )

    def test_benchmark_cache_does_not_jump_at_the_join(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.csv"
            cache = root / "cache.csv"
            pd.DataFrame(
                {"date": ["2026-09-23", "2026-09-24"], "equity": [1.0, 1.1], "variant": "沪深300"}
            ).to_csv(base, index=False)
            pd.DataFrame(
                {"date": ["2026-09-24", "2026-09-25"], "equity": [4000.0, 4040.0], "variant": "沪深300"}
            ).to_csv(cache, index=False)
            series = load_market(base, cache_path=cache)
            self.assertAlmostEqual(float(series.loc[pd.Timestamp("2026-09-24")]), 0.1, places=8)
            self.assertAlmostEqual(float(series.loc[pd.Timestamp("2026-09-25")]), 0.01, places=8)


class ActTests(unittest.TestCase):
    def test_wash_completes_on_first_three_and_uses_three_day_return(self) -> None:
        found = assess_act([4, 4, 4, 3, 1, 1, 1], [10, 10, 10, 10, 11, 12, 13])
        self.assertEqual(found["label"], "震仓洗盘")
        self.assertAlmostEqual(found["ret"], 0.3)
        self.assertEqual(found["end_index"], 3)

    def test_release_returns_to_shrink_after_one_risk_day(self) -> None:
        found = assess_act([4, 5, 3, 1, 1, 1], [10, 10, 10, 10, 10, 12])
        self.assertEqual(found["label"], "释放套牢盘")
        self.assertEqual(found["end_index"], 2)
        self.assertAlmostEqual(found["ret"], 0.2)

    def test_two_risk_days_break_the_path(self) -> None:
        self.assertEqual(assess_act([4, 5, 6], [10, 10, 9])["label"], "打断")
        self.assertEqual(assess_act([2, 3, 5, 6], [10, 10, 10, 9])["label"], "打断")
        self.assertIsNone(assess_act([3, 5, 6], [10, 10, 9])["ret"])

    def test_open_path_has_no_return(self) -> None:
        found = assess_act([2, 2, 4], [10, 10, 10])
        self.assertEqual(found["label"], "未走完")
        self.assertIsNone(found["ret"])

    def test_quiet_tape_is_empty(self) -> None:
        self.assertEqual(assess_act([1, 1, 1], [10, 10, 10])["label"], "无")

    def test_single_risk_day_between_two_and_three_is_release(self) -> None:
        self.assertEqual(assess_act([2, 5, 3], [10, 9, 10])["label"], "释放套牢盘")

    def test_return_stays_empty_until_three_sessions(self) -> None:
        found = assess_act([4, 3], [10, 10])
        self.assertEqual(found["label"], "震仓洗盘")
        self.assertIsNone(found["ret"])

    def test_only_the_latest_ten_sessions_count(self) -> None:
        ids = [4, 3, 1, 1, 1] + [1] * 10
        found = assess_act(ids, [10.0] * len(ids))
        self.assertEqual(found["label"], "无")


class Vp6UniverseTests(unittest.TestCase):
    def test_scan_universe_keeps_paste_and_does_not_touch_watch(self) -> None:
        bench, book_dates, _asset, market = _market_and_asset(n=80)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench_path = root / "benchmark_nav.csv"
            bench.to_csv(bench_path, index=False)
            watch4 = root / "watch4.csv"
            watch6 = root / "watch6.csv"
            watch4.write_text("symbol,stock_name\n000001,平安\n", encoding="utf-8")
            watch6.write_text("symbol,stock_name\n600000,浦发\n", encoding="utf-8")
            before = watch4.read_bytes()
            mplus = root / "mplus.csv"
            growth = root / "g46.csv"
            quality = root / "q.csv"
            pd.DataFrame(
                {"symbol": ["000001", "000001"], "stock_name": ["平安", "被覆盖"]}
            ).to_csv(mplus, index=False, encoding="utf-8-sig")
            pd.DataFrame(
                {"股票代码": ["600000", "000001"], "股票名称": ["浦发", "另一名"], "排名": [20, 1]}
            ).to_csv(growth, index=False, encoding="utf-8-sig")
            quality.write_text("", encoding="utf-8")
            scan = root / "scan.csv"
            pd.DataFrame(
                {
                    "symbol": ["000001", "300001", "300002"],
                    "stock_name": ["平安", "未确认", "量能"],
                    "state_code": ["entry", "watch", "entry"],
                }
            ).to_csv(scan, index=False, encoding="utf-8-sig")
            theme_ranks = (mplus, growth, quality, root / "missing_g23.csv")
            dates = list(book_dates[-7:])
            ohlc = pd.DataFrame(
                {
                    "date": dates + dates,
                    "symbol": ["000001"] * 7 + ["600000"] * 7,
                    "high": [10] * 14,
                    "low": [9] * 14,
                    "close": [10, 10, 10, 10, 11, 12, 13, 8, 8, 8, 8, 8, 8, 8],
                    "volume": [100] * 14,
                    "combo_id": [4, 4, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
                }
            )
            ohlc_path = root / "ohlc.csv"
            ohlc.drop(columns=["combo_id"]).to_csv(ohlc_path, index=False)

            def _classify(hist: pd.DataFrame) -> int:
                day = pd.Timestamp(hist.iloc[-1]["date"]).normalize()
                code = str(hist.iloc[-1]["symbol"])
                matched = ohlc[(ohlc["symbol"] == code) & (pd.to_datetime(ohlc["date"]).dt.normalize() == day)]
                return int(matched.iloc[-1]["combo_id"])

            payload = stocks_payload(
                universe="vp6",
                bench_path=bench_path,
                watch_paths=(watch4, watch6),
                scan_path=scan,
                theme_rank_paths=theme_ranks,
                cache_path=root / "bars.csv",
                fallback_path=root / "missing.csv",
                ohlc_path=ohlc_path,
                classify=_classify,
            )
            self.assertEqual(watch4.read_bytes(), before)
            self.assertEqual(payload["report"]["universe"], "vp6")
            self.assertEqual(payload["report"]["requested"], 3)
            by_symbol = {row["symbol"]: row for row in payload["report"]["rows"]}
            self.assertEqual([row["symbol"] for row in payload["report"]["rows"]], ["000001", "600000", "300002"])
            self.assertEqual(by_symbol["000001"]["name"], "平安")
            self.assertEqual(by_symbol["000001"]["act_label"], "震仓洗盘")
            self.assertAlmostEqual(by_symbol["000001"]["act_return"], 0.2)
            self.assertEqual(by_symbol["600000"]["act_label"], "无")
            self.assertEqual(by_symbol["300002"]["act_label"], "无日线")
            self.assertTrue(any("missing_g23.csv" in note for note in payload["report"]["notes"]))

            pasted = stocks_payload(
                universe="paste",
                symbols="000001",
                bench_path=bench_path,
                watch_paths=(watch4, watch6),
                scan_path=scan,
                theme_rank_paths=theme_ranks,
                cache_path=root / "bars.csv",
                fallback_path=root / "missing.csv",
                ohlc_path=ohlc_path,
                classify=_classify,
            )
            self.assertEqual(pasted["report"]["universe"], "paste")
            self.assertEqual(pasted["report"]["rows"][0]["symbol"], "000001")
            self.assertEqual(pasted["report"]["rows"][0]["act_label"], "震仓洗盘")
            self.assertEqual(watch4.read_bytes(), before)

    def test_theme_tables_keep_every_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            codes = [f"{i:06d}" for i in range(1, 21)]
            rank = root / "q.csv"
            pd.DataFrame({"symbol": codes, "stock_name": codes, "rank": list(range(1, 21))}).to_csv(
                rank, index=False, encoding="utf-8-sig"
            )
            rows, missing = load_theme_universe((rank,), root / "no_scan.csv")
            self.assertEqual([item["symbol"] for item in rows], codes)
            self.assertEqual(missing, ["no_scan.csv"])

    def test_missing_theme_tables_fail_clearly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError):
                load_theme_universe((root / "mplus.csv",), root / "scan.csv")


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
