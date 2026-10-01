# -*- coding: utf-8 -*-
"""M+ / T+3 研究模块的数值、隔离和契约测试。"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from market_neutral.factors.mud import compute_mud_panel
from risk_return.contract import (
    DECILE_KEYS,
    HOLD_TRADING_DAYS,
    NOTES,
    PROTECTED_OUTPUT_NAMES,
    SCHEMA_VERSION,
    SCENARIO_KEYS,
    TOP_LEVEL_KEYS,
)
from risk_return.distribution import beta_binomial_posterior, regularized_incomplete_beta, var_cvar_95
from risk_return.engine import report_from_samples, run_mplus_t3
from risk_return.io import read_bars_csv, write_json
from risk_return.monte_carlo import kelly_raw, simulate_wealth
from risk_return.samples import forward_return_exact
from risk_return.service import latest_payload, run_payload
from risk_return.system_samples import samples_from_mplus_panel
from risk_return_api import router


def _bars(n_symbols: int, n_days: int, seed: int) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2020-01-01", periods=n_days)
    out: dict[str, pd.DataFrame] = {}
    for i in range(n_symbols):
        drift = 0.0008 * (i - n_symbols / 2)
        close = 10.0 * np.exp(np.cumsum(rng.normal(drift, 0.02, size=n_days)))
        volume = rng.integers(1_000, 8_000, size=n_days).astype(float)
        out[f"{i + 1:06d}"] = pd.DataFrame({"date": dates, "close": close, "volume": volume})
    return out


class DistributionTests(unittest.TestCase):
    def test_incomplete_beta_known_values(self) -> None:
        self.assertAlmostEqual(regularized_incomplete_beta(0.2, 1, 1), 0.2, places=8)
        self.assertAlmostEqual(regularized_incomplete_beta(0.5, 2, 2), 0.5, places=8)
        # I_0.2(2,2) = 3*(0.2)^2 - 2*(0.2)^3 = 0.104
        self.assertAlmostEqual(regularized_incomplete_beta(0.2, 2, 2), 0.104, places=8)

    def test_beta_posterior_shrinks_small_sample(self) -> None:
        raw_small = 22 / 30
        post_small, prob_small = beta_binomial_posterior(22, 8)
        self.assertAlmostEqual(post_small, 23 / 32, places=10)
        self.assertLess(post_small, raw_small)
        self.assertGreater(prob_small, 0.5)

        raw_large = 2900 / 5000
        post_large, _ = beta_binomial_posterior(2900, 2100)
        self.assertAlmostEqual(post_large, 2901 / 5002, places=10)
        self.assertLess(abs(post_large - raw_large), abs(post_small - raw_small))

    def test_var_cvar_hand_calc(self) -> None:
        returns = [-0.10, -0.08] + [0.01] * 38
        var_95, cvar_95 = var_cvar_95(returns)
        self.assertAlmostEqual(var_95, -0.08, places=10)
        self.assertAlmostEqual(cvar_95, -0.09, places=10)


class MonteCarloTests(unittest.TestCase):
    def test_kelly_hand_calc(self) -> None:
        self.assertAlmostEqual(kelly_raw(0.6, 2.0), 0.4, places=10)

    def test_known_paths(self) -> None:
        up = simulate_wealth([0.10], 1.0, n_paths=4, n_trades=2, seed=1)
        self.assertAlmostEqual(up["median_terminal_wealth"], 1.21, places=10)
        self.assertAlmostEqual(up["prob_dd_gt_20"], 0.0, places=10)

        down = simulate_wealth([-0.25], 1.0, n_paths=6, n_trades=1, seed=3)
        self.assertAlmostEqual(down["median_terminal_wealth"], 0.75, places=10)
        self.assertAlmostEqual(down["median_max_drawdown"], 0.25, places=10)
        self.assertAlmostEqual(down["prob_dd_gt_20"], 1.0, places=10)
        self.assertAlmostEqual(down["prob_dd_gt_30"], 0.0, places=10)

    def test_same_seed_matches(self) -> None:
        sample = [0.04, -0.02, 0.01, -0.05, 0.03]
        first = simulate_wealth(sample, 0.2, n_paths=30, n_trades=8, seed=11)
        second = simulate_wealth(sample, 0.2, n_paths=30, n_trades=8, seed=11)
        self.assertEqual(first, second)


class SampleTests(unittest.TestCase):
    def test_forward_return_ignores_bars_after_exit(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=8)
        close = [10, 10, 10, 10, 11, 12, 20, 30]
        df = pd.DataFrame({"date": dates, "close": close, "volume": 1000})
        base = forward_return_exact(df, dates[1], 3)
        self.assertAlmostEqual(base, 11 / 10 - 1, places=10)
        bumped = df.copy()
        bumped.loc[5, "close"] = 99
        self.assertAlmostEqual(forward_return_exact(bumped, dates[1], 3), base, places=10)
        bumped.loc[4, "close"] = 15
        self.assertAlmostEqual(forward_return_exact(bumped, dates[1], 3), 15 / 10 - 1, places=10)

    def test_missing_signal_bar_is_nan(self) -> None:
        dates = pd.bdate_range("2024-01-01", periods=6)
        df = pd.DataFrame({"date": dates, "close": np.arange(6) + 10, "volume": 1})
        missing = dates[2] + pd.Timedelta(days=1)
        self.assertTrue(np.isnan(forward_return_exact(df, missing, 3)))

    def test_mud_plus_ignores_future_bars(self) -> None:
        bars = _bars(8, 120, seed=4)
        dt = pd.Timestamp(next(iter(bars.values()))["date"].iloc[100])
        before = compute_mud_panel(bars, [dt])
        extended = {}
        extra_dates = pd.bdate_range(dt + pd.Timedelta(days=1), periods=12)
        rng = np.random.default_rng(9)
        for code, df in bars.items():
            extra = pd.DataFrame(
                {
                    "date": extra_dates,
                    "close": rng.uniform(1, 50, size=len(extra_dates)),
                    "volume": rng.uniform(10, 1_000_000, size=len(extra_dates)),
                }
            )
            extended[code] = pd.concat([df, extra], ignore_index=True)
        after = compute_mud_panel(extended, [dt])
        self.assertFalse(before.empty)
        merged = before.merge(after, on="symbol", suffixes=("_b", "_a"))
        np.testing.assert_allclose(merged["mud_plus_b"], merged["mud_plus_a"])


class ContractTests(unittest.TestCase):
    def test_report_keys_and_reproducible_scenarios(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=40)
        rows = []
        rng = np.random.default_rng(2)
        for decile in range(1, 11):
            for i, day in enumerate(dates):
                rows.append(
                    {
                        "date": day,
                        "symbol": f"{decile:06d}",
                        "decile": decile,
                        "fwd_ret": float(rng.normal(0.001 * decile, 0.02)),
                    }
                )
        frame = pd.DataFrame(rows)
        first = report_from_samples(frame, n_paths=40, n_trades=12, seed=7)
        second = report_from_samples(frame, n_paths=40, n_trades=12, seed=7)
        self.assertEqual(tuple(first.keys()), TOP_LEVEL_KEYS)
        self.assertEqual(first["schema_version"], SCHEMA_VERSION)
        self.assertEqual(first["factor"], "M+")
        self.assertEqual(first["hold_trading_days"], HOLD_TRADING_DAYS)
        self.assertEqual(first["notes"], list(NOTES))
        self.assertEqual([row["label"] for row in first["deciles"]], [f"Q{i}" for i in range(1, 11)])
        focus = first["deciles"][9]
        self.assertEqual(tuple(focus.keys()), DECILE_KEYS)
        self.assertEqual(len(focus["scenarios"]), 4)
        self.assertEqual(tuple(focus["scenarios"][0].keys()), SCENARIO_KEYS)
        self.assertEqual(
            [row["scenarios"] for row in first["deciles"]],
            [row["scenarios"] for row in second["deciles"]],
        )
        self.assertGreaterEqual(focus["n"], 30)
        self.assertFalse(focus["small_sample"])

    def test_small_sample_flag(self) -> None:
        frame = pd.DataFrame(
            {
                "date": pd.bdate_range("2024-03-01", periods=10),
                "symbol": ["000001"] * 10,
                "decile": [10] * 10,
                "fwd_ret": [0.01] * 7 + [-0.02] * 3,
            }
        )
        report = report_from_samples(frame, n_paths=20, n_trades=10, seed=1)
        self.assertTrue(report["deciles"][9]["small_sample"])
        self.assertLess(
            report["deciles"][9]["posterior_win_rate"],
            report["deciles"][9]["win_rate"],
        )


class IsolationTests(unittest.TestCase):
    def test_refuse_protected_and_outside_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inside = root / "risk_return" / "output" / "latest.json"
            write_json({"schema_version": SCHEMA_VERSION}, inside)
            self.assertTrue(inside.is_file())
            blocked = root / "risk_return" / "output" / "pattern_entry_scan.csv"
            with self.assertRaises(RuntimeError):
                write_json({"schema_version": SCHEMA_VERSION}, blocked)
            outside = root / "vp_six_combo_scan.csv"
            with self.assertRaises(RuntimeError):
                write_json({"schema_version": SCHEMA_VERSION}, outside)
        self.assertIn("pattern_entry_kelly_positions.csv", PROTECTED_OUTPUT_NAMES)
        self.assertIn("vp_combo_23_vs_46_long_annual.csv", PROTECTED_OUTPUT_NAMES)

    def test_run_missing_snapshot_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "risk_return"
            snapshot = Path(tmp) / "missing_factor_snapshot.csv"
            dest = root / "output" / "latest.json"
            payload = run_payload(
                n_paths=100,
                n_trades=10,
                seed=1,
                snapshot_path=snapshot,
                output_path=dest,
            )
            self.assertTrue(payload["empty"])
            self.assertIn("factor_snapshot.csv", payload["message"])
            self.assertFalse(dest.exists())
            self.assertIsNone(latest_payload(dest)["report"])

    def test_snapshot_mud_is_kept_and_file_untouched(self) -> None:
        dates = pd.bdate_range("2024-01-02", periods=8)
        panel_rows = []
        bars: dict[str, pd.DataFrame] = {}
        for i in range(12):
            code = f"{i + 1:06d}"
            close = [10.0 + i] * len(dates)
            close[3] = close[0] * (1.0 + 0.01 * (i + 1))
            bars[code] = pd.DataFrame({"date": dates, "close": close, "volume": 1000.0})
            panel_rows.append(
                {"date": dates[0], "symbol": code, "mud_plus": (i + 1) / 12}
            )
        panel = pd.DataFrame(panel_rows)
        samples = samples_from_mplus_panel(panel, bars, hold_days=3)
        top = samples[samples["symbol"] == "000012"]
        self.assertEqual(int(top["decile"].iloc[0]), 10)
        self.assertAlmostEqual(float(top["fwd_ret"].iloc[0]), 0.12, places=8)

        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "factor_snapshot.csv"
            panel.to_csv(snapshot, index=False)
            before = snapshot.read_bytes()
            dest = Path(tmp) / "risk_return" / "output" / "latest.json"
            payload = run_payload(
                n_paths=40,
                n_trades=10,
                seed=3,
                snapshot_path=snapshot,
                output_path=dest,
                bars_by_symbol=bars,
            )
            self.assertTrue(payload["ok"], payload.get("error"))
            self.assertGreater(payload["report"]["n_rows"], 0)
            self.assertIsNone(payload["report"]["sample_step_trading_days"])
            self.assertEqual(payload["report"]["sample_source"], snapshot.name)
            self.assertEqual(snapshot.read_bytes(), before)

    def test_bars_csv_roundtrip_stays_inside_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "risk_return" / "input" / "bars.csv"
            path.parent.mkdir(parents=True)
            path.write_text("symbol,date,close,volume\n000001,2024-01-02,10,1000\n", encoding="utf-8")
            bars = read_bars_csv(path)
            self.assertIn("000001", bars)
            self.assertAlmostEqual(float(bars["000001"]["close"].iloc[0]), 10.0)


class PipelineTests(unittest.TestCase):
    def test_run_mplus_t3_uses_existing_factor(self) -> None:
        report = run_mplus_t3(_bars(12, 140, seed=5), n_paths=30, n_trades=10, seed=5)
        self.assertEqual(report["factor_field"], "mud_plus")
        self.assertEqual(report["hold_trading_days"], 3)
        self.assertGreater(report["n_rows"], 0)
        self.assertEqual(sum(row["n"] for row in report["deciles"]), report["n_rows"])


class ApiTests(unittest.TestCase):
    def test_latest_endpoint_empty(self) -> None:
        app = FastAPI()
        app.include_router(router)
        client = TestClient(app)
        response = client.get("/api/risk-return/latest")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertIn("empty", body)
        self.assertIn("report", body)


if __name__ == "__main__":
    unittest.main()
