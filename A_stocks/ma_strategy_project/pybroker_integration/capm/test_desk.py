# -*- coding: utf-8 -*-
"""交易部门的状态机、价格确认和收敛速度分组。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from capm.alpha_state import (
    classify_state,
    collect_speed_observations,
    forward_excess,
    gap_admits,
    price_gates,
    rolling_ols,
    snapshot_factors,
    summarize_speed_groups,
)
from capm.desk import desk_payload
from capm.model import fit_window
from capm.sources import backfill_benchmark, backfill_earlier_closes, backfill_opens


def _series(values: np.ndarray, start: str = "2024-01-02") -> pd.Series:
    dates = pd.bdate_range(start, periods=len(values))
    return pd.Series(values, index=dates)


def _line(n: int = 280, alpha: float = -0.001, beta: float = 0.3, seed: int = 1):
    rng = np.random.default_rng(seed)
    market = rng.normal(0, 0.01, n)
    asset = alpha + beta * market
    return _series(asset), _series(market)


def _market(n: int) -> np.ndarray:
    return 0.01 * np.sin(np.arange(n) / 3.0)


def _in_pool_improving(n: int = 280, beta: float = 0.3):
    """近端抬升，且 120 日 α 比 250 日 α 高出 40% 以上。"""
    market = _market(n)
    alpha = np.full(n, -0.001)
    alpha[n - 250 : n - 120] = -0.008
    alpha[n - 120 : n - 20] = -0.002
    alpha[n - 20 :] = 0.0
    return _series(alpha + beta * market), _series(market)


def _in_pool_worsening(n: int = 280, beta: float = 0.3):
    """α 持续走低，120 日与 250 日之差为负，但仍在候选里。"""
    market = _market(n)
    alpha = np.linspace(-0.0004, -0.003, n)
    return _series(alpha + beta * market), _series(market)


def _bars(dates: pd.DatetimeIndex, *, opened: float | None, close: float, high: float, low: float, volume: float) -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "date": dates,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )
    if opened is not None:
        frame["open"] = opened
    return frame


def _confirming_bars(dates: pd.DatetimeIndex) -> pd.DataFrame:
    prior = dates[:-1]
    last = dates[-1:]
    old = _bars(prior, opened=10.0, close=10.0, high=10.2, low=9.4, volume=100.0)
    new = _bars(last, opened=10.4, close=10.8, high=10.9, low=10.3, volume=200.0)
    return pd.concat([old, new], ignore_index=True)


class StateTests(unittest.TestCase):
    def test_rolling_ols_matches_the_window_fit(self) -> None:
        asset, market = _line(alpha=0.0002, beta=1.2, seed=2)
        both = pd.DataFrame({"asset": asset, "market": market})
        fitted = fit_window(both, 250)
        alpha, beta = rolling_ols(asset.to_numpy(), market.to_numpy(), 250)
        assert fitted is not None
        self.assertAlmostEqual(float(beta[-1]), fitted["beta"], places=6)
        self.assertAlmostEqual(float(alpha[-1]) * 252, fitted["alpha_ann"], places=6)

    def test_forward_window_starts_the_day_after_the_signal(self) -> None:
        asset = np.zeros(30)
        market = np.zeros(30)
        asset[10] = 0.8
        asset[11:21] = 0.01
        excess = forward_excess(asset, market, 10, 10)
        assert excess is not None
        self.assertAlmostEqual(excess, float(np.prod(np.full(10, 1.01)) - 1), places=8)

    def test_flat_alpha_is_outside_the_gap_even_after_a_breakout(self) -> None:
        shock = _market(280)
        market = _series(shock)
        asset = _series(-0.001 + 0.3 * shock)
        bars = _confirming_bars(asset.index[-21:])
        row = snapshot_factors(asset, market, bars)
        assert row is not None
        self.assertLess(row["alpha120"], 0)
        self.assertAlmostEqual(row["alphaGap"], 0.0, places=6)
        self.assertFalse(gap_admits(row["alpha120"], row["alpha250"]))
        self.assertTrue(row["confirmed"])
        self.assertEqual(row["state"], "excluded")

    def test_missing_open_blocks_the_buy(self) -> None:
        asset, market = _in_pool_improving()
        bars = _confirming_bars(asset.index[-21:]).drop(columns=["open"])
        gates = price_gates(bars, asset.index[-1])
        self.assertTrue(gates["open_missing"])
        self.assertFalse(gates["close_above_open"])
        self.assertTrue(gates["breakout"])
        row = snapshot_factors(asset, market, bars)
        assert row is not None
        self.assertTrue(gap_admits(row["alpha120"], row["alpha250"]))
        self.assertEqual(row["state"], "S1")
        self.assertNotEqual(row["state"], "S2")

    def test_confirmed_improvement_is_a_buy(self) -> None:
        asset, market = _in_pool_improving()
        bars = _confirming_bars(asset.index[-21:])
        row = snapshot_factors(asset, market, bars)
        assert row is not None
        self.assertGreater(row["alphaGap"], 0.40)
        self.assertGreater(row["delta120"], 0)
        self.assertTrue(row["persisted"])
        self.assertEqual(row["state"], "S2")

    def test_states_follow_the_pool_and_the_price_gate(self) -> None:
        self.assertFalse(gap_admits(-0.10, -0.10))
        self.assertFalse(gap_admits(0.0, -0.40))
        self.assertFalse(gap_admits(-0.10, -0.20))
        self.assertTrue(gap_admits(-0.20, -0.10))
        self.assertTrue(gap_admits(0.0, -0.41))
        self.assertEqual(classify_state(0.8, -0.2, -0.1, 0.02, True, True), "excluded")
        self.assertEqual(classify_state(-0.1, -0.2, -0.1, 0.02, True, True), "excluded")
        self.assertEqual(classify_state(0.3, -0.1, -0.2, 0.02, True, True), "excluded")
        self.assertEqual(classify_state(0.3, -0.1, -0.1, 0.02, True, True), "excluded")
        self.assertEqual(classify_state(0.3, 0.0, -0.40, 0.02, True, True), "excluded")
        self.assertEqual(classify_state(float("nan"), -0.2, -0.1, 0.02, True, True), "insufficient")
        self.assertEqual(classify_state(0.0, -0.2, -0.1, 0.0, True, True), "S0")
        self.assertEqual(classify_state(0.5, -0.2, -0.1, -0.01, True, True), "S0")
        self.assertEqual(classify_state(0.3, -0.2, -0.1, 0.02, False, True), "S1")
        self.assertEqual(classify_state(0.3, -0.2, -0.1, 0.02, True, False), "S1")
        self.assertEqual(classify_state(0.3, -0.2, -0.1, 0.02, True, True), "S2")
        self.assertEqual(classify_state(0.3, 0.01, -0.40, 0.02, True, True), "S2")

    def test_quintiles_rise_from_slowest_to_fastest(self) -> None:
        speeds = [-0.02, -0.01, 0.0, 0.01, 0.02]
        excess = [-0.05, -0.02, 0.0, 0.03, 0.06]
        obs = [
            {"date": "2026-01-05", "symbol": f"{i:06d}", "speed": speed, "excess": value}
            for i, (speed, value) in enumerate(zip(speeds, excess))
        ]
        out = summarize_speed_groups(obs)
        self.assertTrue(out["supported"])
        self.assertEqual(out["groups"][0]["hit_rate"], 0.0)
        self.assertEqual(out["groups"][-1]["hit_rate"], 1.0)
        self.assertLess(out["groups"][0]["mean_excess"], out["groups"][-1]["mean_excess"])

    def test_a_dip_rejects_the_hypothesis(self) -> None:
        obs = [
            {"date": "2026-01-05", "symbol": f"{i:06d}", "speed": float(i), "excess": 0.01 if i < 4 else -0.05}
            for i in range(5)
        ]
        out = summarize_speed_groups(obs)
        self.assertFalse(out["hit_monotone"])
        self.assertFalse(out["supported"])
        self.assertIn("没有", out["verdict"])

    def test_four_names_are_not_enough_groups(self) -> None:
        obs = [
            {"date": "2026-01-05", "symbol": f"{i:06d}", "speed": float(i), "excess": 0.01}
            for i in range(4)
        ]
        out = summarize_speed_groups(obs)
        self.assertEqual(out["n_dates"], 0)
        self.assertIn("不够", out["verdict"])

    def test_a_missing_forward_day_drops_the_observation(self) -> None:
        asset, market = _in_pool_worsening()
        full = collect_speed_observations({"000001": asset}, market)
        self.assertTrue(full)
        day = pd.Timestamp(full[0]["date"])
        loc = asset.index.get_loc(day)
        hole = asset.drop(asset.index[int(loc) + 1])
        kept = collect_speed_observations({"000001": hole}, market)
        self.assertNotIn(full[0]["date"], {item["date"] for item in kept})


class DeskPayloadTests(unittest.TestCase):
    def test_payload_does_not_touch_the_watch_or_record_a_buy_without_open(self) -> None:
        asset, market = _in_pool_worsening(n=260)
        hot = pd.Series(1.4 * _market(len(asset)), index=asset.index)
        dates = list(asset.index)
        series = {"000001": asset.to_numpy(), "000002": hot.to_numpy()}
        first = dates[0] - pd.tseries.offsets.BDay(1)
        closes = []
        for code, rets in series.items():
            level = 10.0
            closes.append({"date": first, "symbol": code, "close": level})
            for day, ret in zip(dates, rets):
                level *= 1.0 + float(ret)
                closes.append({"date": day, "symbol": code, "close": level})
        equity = np.empty(len(dates) + 1)
        equity[0] = 1.0
        for i, ret in enumerate(market.to_numpy()):
            equity[i + 1] = equity[i] * (1.0 + float(ret))
        bench_dates = [first, *dates]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bench = pd.DataFrame({"date": bench_dates, "variant": "沪深300", "equity": equity})
            bench_path = root / "benchmark_nav.csv"
            bench.to_csv(bench_path, index=False)
            bars = root / "bars.csv"
            pd.DataFrame(closes).to_csv(bars, index=False)
            ohlc_rows = []
            for code in ("000001", "000002"):
                for day in dates[-30:]:
                    ohlc_rows.append(
                        {
                            "date": day,
                            "symbol": code,
                            "high": 10.2,
                            "low": 9.4,
                            "close": 10.0,
                            "volume": 100.0,
                        }
                    )
            ohlc = root / "ohlc.csv"
            pd.DataFrame(ohlc_rows).to_csv(ohlc, index=False)
            watch = root / "watch.csv"
            watch.write_text("symbol,stock_name\n000001,平安\n000003,空仓\n", encoding="utf-8")
            before = watch.read_bytes()
            payload = desk_payload(
                bench_path=bench_path,
                cache_path=bars,
                fallback_path=root / "missing.csv",
                ohlc_path=ohlc,
                watch_paths=(watch,),
            )
            self.assertEqual(watch.read_bytes(), before)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["empty"])
        rows = {row["symbol"]: row for row in payload["report"]["rows"]}
        self.assertEqual(set(rows), {"000001", "000003"})
        self.assertEqual(rows["000001"]["state"], "S0")
        self.assertLess(rows["000001"]["alphaGap"], 0)
        self.assertEqual(rows["000001"]["stock_name"], "平安")
        self.assertEqual(rows["000003"]["state"], "insufficient")
        self.assertEqual(payload["report"]["buys"], [])
        self.assertTrue(payload["report"]["open_missing"])
        self.assertIn("hypothesis", payload["report"])
        self.assertTrue(any("不止盈" in note for note in payload["report"]["notes"]))
        self.assertTrue(any("40%" in note for note in payload["report"]["notes"]))


class HistoryBackfillTests(unittest.TestCase):
    def test_earlier_closes_are_stored_once_and_a_failure_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "bars.csv"
            pd.DataFrame(
                {
                    "date": ["2024-01-02", "2025-06-03"],
                    "symbol": ["000002", "000001"],
                    "close": [9.0, 10.0],
                }
            ).to_csv(cache, index=False)
            ledger = root / "ledger.json"
            calls: list[tuple] = []

            def _fill(symbols, start, end):
                calls.append((list(symbols), start, end))
                self.assertEqual(symbols, ["000001"])
                self.assertEqual(start, "2024-01-02")
                self.assertEqual(end, "2025-06-03")
                return pd.DataFrame({"date": ["2024-02-01"], "symbol": ["000001"], "close": [8.0]})

            note = backfill_earlier_closes(
                cache_path=cache,
                fallback_path=root / "missing.csv",
                ledger_path=ledger,
                fetcher=_fill,
                end="2025-06-03",
            )
            self.assertIn("写入 1 只", note)
            saved = pd.read_csv(cache, dtype={"symbol": str})
            self.assertIn("2024-02-01", set(pd.to_datetime(saved["date"]).dt.strftime("%Y-%m-%d")))
            again = backfill_earlier_closes(
                cache_path=cache,
                fallback_path=root / "missing.csv",
                ledger_path=ledger,
                fetcher=_fill,
                end="2025-06-03",
            )
            self.assertEqual(again, "")
            self.assertEqual(len(calls), 1)

            empty_cache = root / "empty_bars.csv"
            pd.DataFrame({"date": ["2025-06-03"], "symbol": ["000003"], "close": [1.0]}).to_csv(empty_cache, index=False)
            misses = {"n": 0}

            def _miss(symbols, start, end):
                misses["n"] += 1
                return pd.DataFrame(columns=["date", "symbol", "close"])

            failed = backfill_earlier_closes(
                cache_path=empty_cache,
                fallback_path=root / "missing.csv",
                ledger_path=root / "empty_ledger.json",
                fetcher=_miss,
            )
            self.assertIn("下次会再试", failed)
            backfill_earlier_closes(
                cache_path=empty_cache,
                fallback_path=root / "missing.csv",
                ledger_path=root / "empty_ledger.json",
                fetcher=_miss,
            )
            self.assertEqual(misses["n"], 2)

    def test_benchmark_backfill_leaves_the_nav_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nav = root / "benchmark_nav.csv"
            pd.DataFrame(
                {"date": ["2025-06-03", "2025-06-04"], "equity": [1.0, 1.01], "variant": ["沪深300", "沪深300"]}
            ).to_csv(nav, index=False)
            before = nav.read_bytes()
            calls = {"n": 0}

            def _fill(start, end):
                calls["n"] += 1
                self.assertEqual(start, "2024-01-02")
                self.assertEqual(end, "2025-06-04")
                return pd.DataFrame({"date": ["2024-01-02"], "equity": [3000.0], "variant": ["沪深300"]})

            cache = root / "benchmark.csv"
            note = backfill_benchmark(bench_path=nav, cache_path=cache, fetcher=_fill)
            self.assertIn("沪深300", note)
            self.assertEqual(nav.read_bytes(), before)
            self.assertTrue(cache.is_file())
            second = backfill_benchmark(bench_path=nav, cache_path=cache, fetcher=_fill)
            self.assertEqual(second, "")
            self.assertEqual(calls["n"], 1)

    def test_missing_open_is_filled_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "ohlc.csv"
            dates = pd.bdate_range("2025-06-03", periods=2)
            pd.DataFrame(
                {
                    "date": list(dates) * 2,
                    "symbol": ["000001", "000001", "000002", "000002"],
                    "high": [10, 11, 8, 9],
                    "low": [9, 10, 7, 8],
                    "close": [9.5, 10.5, 7.5, 8.5],
                    "volume": [100, 120, 80, 90],
                }
            ).to_csv(cache, index=False)
            calls = {"n": 0}

            def _fill(symbols, start, end):
                calls["n"] += 1
                self.assertEqual(start, "2025-06-03")
                rows = []
                for code in symbols:
                    for day in dates:
                        rows.append(
                            {
                                "date": day,
                                "symbol": code,
                                "open": 9.0,
                                "high": 11,
                                "low": 8,
                                "close": 10,
                                "volume": 100,
                            }
                        )
                return pd.DataFrame(rows)

            note = backfill_opens(cache_path=cache, ledger_path=root / "open.json", fetcher=_fill)
            self.assertIn("写入 2 只", note)
            saved = pd.read_csv(cache)
            self.assertTrue(pd.to_numeric(saved["open"], errors="coerce").notna().all())
            again = backfill_opens(cache_path=cache, ledger_path=root / "open.json", fetcher=_fill)
            self.assertEqual(again, "")
            self.assertEqual(calls["n"], 1)


if __name__ == "__main__":
    unittest.main()
