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
from risk_return.correlation import TOP_LEVEL_KEYS as CORR_KEYS
from risk_return.regime import TOP_LEVEL_KEYS as REGIME_KEYS
from risk_return.regime import build_regime_report
from risk_return.budget import TOP_LEVEL_KEYS as BUDGET_KEYS
from risk_return.budget import build_budget_report
from risk_return.budget import estimate_quarter_kelly
from risk_return.copula import TOP_LEVEL_KEYS as COPULA_KEYS
from risk_return.copula import build_copula_report, norm_ppf
from risk_return.decision import TOP_LEVEL_KEYS as DECISION_KEYS
from risk_return.decision import build_decision_report, choose_action, rotate_weights
from risk_return.service import (
    budget_payload,
    copula_payload,
    correlation_payload,
    decision_payload,
    latest_payload,
    regime_payload,
    run_payload,
    walkforward_payload,
)
from risk_return.walkforward import TOP_LEVEL_KEYS as WF_KEYS
from risk_return.walkforward import build_walkforward_report
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

    def test_correlation_route_exists(self) -> None:
        paths = [getattr(route, "path", "") for route in router.routes]
        self.assertIn("/api/risk-return/correlation", paths)
        self.assertIn("/api/risk-return/regime", paths)
        self.assertIn("/api/risk-return/budget", paths)
        self.assertIn("/api/risk-return/walkforward", paths)
        self.assertIn("/api/risk-return/copula", paths)
        self.assertIn("/api/risk-return/decision", paths)


class CorrelationTests(unittest.TestCase):
    def _write_pair(self, root: Path, values: list[float]) -> tuple[Path, Path]:
        dates = pd.bdate_range("2024-01-02", periods=len(values))
        group = root / "group_returns.csv"
        sleeve = root / "sleeve_returns.csv"
        pd.DataFrame(
            {"date": dates, "W2+W3": values, "W4+W6": values}
        ).to_csv(group, index=False)
        pd.DataFrame(
            {"date": dates, "M+": values, "Q": values, "G": values}
        ).to_csv(sleeve, index=False)
        return group, sleeve

    def test_coupled_sleeves_fail_together(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            values = [-0.08, 0.02] * 20
            group, sleeve = self._write_pair(root, values)
            before_group = group.read_bytes()
            before_sleeve = sleeve.read_bytes()
            payload = correlation_payload(
                n_paths=4000,
                horizon_days=10,
                seed=7,
                group_path=group,
                sleeve_path=sleeve,
                output_path=root / "risk_return" / "output" / "correlation_v2.json",
            )
            self.assertTrue(payload["ok"], payload.get("error"))
            report = payload["report"]
            self.assertEqual(tuple(report.keys()), CORR_KEYS)
            self.assertEqual(report["sleeves"], ["W2+W3", "W4+W6", "M+", "Q", "G"])
            self.assertAlmostEqual(report["correlation"][0][1], 1.0, places=6)
            self.assertAlmostEqual(report["historical_all_negative"], 0.5, places=6)
            self.assertAlmostEqual(report["joint_all_negative"], 0.5, delta=0.04)
            self.assertLess(report["independent_all_negative"], 0.08)
            self.assertGreater(report["joint_all_negative"], report["independent_all_negative"])
            self.assertGreaterEqual(report["joint_prob_dd_gt_20"], 0.0)
            self.assertLessEqual(report["independent_prob_dd_gt_20"], 1.0)
            self.assertEqual(group.read_bytes(), before_group)
            self.assertEqual(sleeve.read_bytes(), before_sleeve)

    def test_missing_return_table(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "missing.csv"
            payload = correlation_payload(
                group_path=missing,
                sleeve_path=missing,
                output_path=Path(tmp) / "risk_return" / "output" / "correlation_v2.json",
            )
            self.assertTrue(payload["empty"])
            self.assertIn("缺少已有收益表", payload["message"])


class RegimeTests(unittest.TestCase):
    def test_return_day_uses_earlier_temperature_only(self) -> None:
        aligned = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-03", "2024-01-04"]),
                "W2+W3": [0.01, -0.02],
                "W4+W6": [0.01, -0.02],
                "M+": [0.01, -0.02],
                "Q": [0.01, -0.02],
                "G": [0.01, -0.02],
            }
        )
        temperature = pd.DataFrame(
            {
                "temp_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "position_label": ["轻仓 20%", "满仓 100%"],
                "position_pct": [20.0, 100.0],
                "total_score": [30.0, 90.0],
            }
        )
        report = build_regime_report(aligned, temperature)
        self.assertEqual(tuple(report.keys()), REGIME_KEYS)
        by_label = {row["label"]: row for row in report["states"]}
        self.assertEqual(list(by_label), ["轻仓 20%", "满仓 100%"])
        self.assertEqual(by_label["轻仓 20%"]["n_days"], 1)
        self.assertAlmostEqual(by_label["轻仓 20%"]["means"]["M+"], 0.01)
        self.assertEqual(by_label["满仓 100%"]["n_days"], 1)
        self.assertAlmostEqual(by_label["满仓 100%"]["means"]["M+"], -0.02)
        self.assertTrue(by_label["轻仓 20%"]["small_sample"])

    def test_missing_temperature_does_not_write_returns(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = pd.bdate_range("2024-01-02", periods=4)
            values = [0.01, -0.02, 0.01, -0.02]
            group = root / "group_returns.csv"
            sleeve = root / "sleeve_returns.csv"
            pd.DataFrame({"date": dates, "W2+W3": values, "W4+W6": values}).to_csv(group, index=False)
            pd.DataFrame({"date": dates, "M+": values, "Q": values, "G": values}).to_csv(sleeve, index=False)
            before_group = group.read_bytes()
            before_sleeve = sleeve.read_bytes()
            payload = regime_payload(
                group_path=group,
                sleeve_path=sleeve,
                temperature_path=root / "missing_temperature.csv",
                output_path=root / "risk_return" / "output" / "regime_v3.json",
            )
            self.assertTrue(payload["empty"])
            self.assertIn("市场温度", payload["message"])
            self.assertEqual(group.read_bytes(), before_group)
            self.assertEqual(sleeve.read_bytes(), before_sleeve)


class BudgetTests(unittest.TestCase):
    def test_tighter_budget_uses_prior_temperature(self) -> None:
        aligned = pd.DataFrame(
            {
                "date": pd.to_datetime(["2024-01-03", "2024-01-04"]),
                "W2+W3": [0.10, -0.20],
                "W4+W6": [0.10, -0.20],
                "M+": [0.10, -0.20],
                "Q": [0.10, -0.20],
                "G": [0.10, -0.20],
            }
        )
        temperature = pd.DataFrame(
            {
                "temp_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                "position_label": ["轻仓 20%", "满仓 100%"],
                "position_pct": [20.0, 100.0],
                "total_score": [30.0, 90.0],
            }
        )
        report = build_budget_report(aligned, temperature)
        self.assertEqual(tuple(report.keys()), BUDGET_KEYS)
        by_name = {row["name"]: row for row in report["budgets"]}
        self.assertAlmostEqual(by_name["温度仓位"]["average_position"], 0.6)
        self.assertLessEqual(
            by_name["取更小"]["average_position"],
            by_name["温度仓位"]["average_position"] + 1e-12,
        )
        self.assertLessEqual(
            by_name["取更小"]["average_position"],
            by_name["四分之一凯利"]["average_position"] + 1e-12,
        )
        self.assertAlmostEqual(by_name["始终满仓"]["terminal_wealth"], 0.88)

    def test_missing_temperature_leaves_returns_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = pd.bdate_range("2024-01-02", periods=4)
            values = [0.01, -0.02, 0.01, -0.02]
            group = root / "group_returns.csv"
            sleeve = root / "sleeve_returns.csv"
            pd.DataFrame({"date": dates, "W2+W3": values, "W4+W6": values}).to_csv(group, index=False)
            pd.DataFrame({"date": dates, "M+": values, "Q": values, "G": values}).to_csv(sleeve, index=False)
            before_group = group.read_bytes()
            payload = budget_payload(
                group_path=group,
                sleeve_path=sleeve,
                temperature_path=root / "missing_temperature.csv",
                output_path=root / "risk_return" / "output" / "budget_v4.json",
            )
            self.assertTrue(payload["empty"])
            self.assertIn("市场温度", payload["message"])
            self.assertEqual(group.read_bytes(), before_group)


class WalkForwardTests(unittest.TestCase):
    def test_test_window_does_not_change_train_position(self) -> None:
        values = [0.02, -0.01, 0.02, -0.01, 0.50, 0.50, -0.04, 0.01, -0.04, 0.01, -0.02, -0.02]
        dates = pd.bdate_range("2024-01-02", periods=len(values))
        aligned = pd.DataFrame(
            {
                "date": dates,
                "W2+W3": values,
                "W4+W6": values,
                "M+": values,
                "Q": values,
                "G": values,
            }
        )
        temperature = pd.DataFrame(
            {
                "temp_date": pd.to_datetime(["2023-12-29", *dates.strftime("%Y-%m-%d")]),
                "position_label": ["中仓 40%"] * (len(values) + 1),
                "position_pct": [40.0] * (len(values) + 1),
                "total_score": [50.0] * (len(values) + 1),
            }
        )
        report = build_walkforward_report(
            aligned,
            temperature,
            train_days=4,
            test_days=2,
            step_days=4,
        )
        self.assertEqual(tuple(report.keys()), WF_KEYS)
        expected = estimate_quarter_kelly(np.array([0.02, -0.01, 0.02, -0.01]))
        self.assertAlmostEqual(report["folds"][0]["position"], expected["quarter_position"])
        self.assertEqual(report["folds"][0]["test_start"], "2024-01-08")
        later = estimate_quarter_kelly(np.array([0.50, 0.50, -0.04, 0.01]))
        self.assertAlmostEqual(report["folds"][1]["position"], later["quarter_position"] )
        self.assertNotAlmostEqual(report["folds"][0]["position"], report["folds"][1]["position"])
        by_fraction = {row["fraction"]: row for row in report["perturbations"]}
        self.assertLess(by_fraction[0.15]["total_return"], by_fraction[0.35]["total_return"])

    def test_missing_temperature_leaves_returns_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = pd.bdate_range("2024-01-02", periods=8)
            values = [0.01, -0.02, 0.01, -0.02, 0.01, -0.02, 0.01, -0.02]
            group = root / "group_returns.csv"
            sleeve = root / "sleeve_returns.csv"
            pd.DataFrame({"date": dates, "W2+W3": values, "W4+W6": values}).to_csv(group, index=False)
            pd.DataFrame({"date": dates, "M+": values, "Q": values, "G": values}).to_csv(sleeve, index=False)
            before_group = group.read_bytes()
            payload = walkforward_payload(
                group_path=group,
                sleeve_path=sleeve,
                temperature_path=root / "missing_temperature.csv",
                output_path=root / "risk_return" / "output" / "walkforward_v5.json",
            )
            self.assertTrue(payload["empty"])
            self.assertIn("市场温度", payload["message"])
            self.assertEqual(group.read_bytes(), before_group)


class CopulaTests(unittest.TestCase):
    def test_norm_ppf_known_value(self) -> None:
        self.assertAlmostEqual(float(norm_ppf(np.array([0.975]))[0]), 1.959964, places=4)
        self.assertAlmostEqual(float(norm_ppf(np.array([0.5]))[0]), 0.0, places=6)

    def test_locked_series_exceeds_independence(self) -> None:
        values = [0.02 if i % 2 == 0 else -0.01 for i in range(40)]
        dates = pd.bdate_range("2024-01-02", periods=len(values))
        aligned = pd.DataFrame(
            {
                "date": dates,
                "W2+W3": values,
                "W4+W6": values,
                "M+": values,
                "Q": values,
                "G": values,
            }
        )
        report = build_copula_report(aligned, n_paths=4000, seed=7)
        self.assertEqual(tuple(report.keys()), COPULA_KEYS)
        self.assertAlmostEqual(report["historical_all_negative"], 0.5, places=6)
        self.assertLess(report["independent_all_negative"], 0.05)
        self.assertGreater(report["gaussian_all_negative"], 0.35)
        self.assertGreater(report["historical_all_negative"], report["independent_all_negative"])

    def test_missing_return_table_leaves_nothing_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.csv"
            payload = copula_payload(
                group_path=missing,
                sleeve_path=missing,
                output_path=root / "risk_return" / "output" / "copula_v6.json",
            )
            self.assertTrue(payload["empty"])
            self.assertIn("缺少已有收益表", payload["message"])
            self.assertFalse((root / "risk_return" / "output" / "copula_v6.json").exists())


class DecisionTests(unittest.TestCase):
    def _frame(self, values: list[float], label: str, position_pct: float) -> tuple[pd.DataFrame, pd.DataFrame]:
        dates = pd.bdate_range("2024-01-02", periods=len(values))
        aligned = pd.DataFrame(
            {
                "date": dates,
                "W2+W3": values,
                "W4+W6": values,
                "M+": values,
                "Q": values,
                "G": values,
            }
        )
        temperature = pd.DataFrame(
            {
                "temp_date": pd.to_datetime(["2023-12-29", *dates.strftime("%Y-%m-%d")]),
                "position_label": [label] * (len(values) + 1),
                "position_pct": [position_pct] * (len(values) + 1),
                "total_score": [70.0] * (len(values) + 1),
            }
        )
        return aligned, temperature

    def test_same_day_return_does_not_change_that_days_position(self) -> None:
        values = [0.02, -0.005] * 16
        aligned, temperature = self._frame(values, "空仓", 0.0)
        report = build_decision_report(aligned, temperature, n_paths=300, horizon=5, seed=7)
        self.assertEqual(tuple(report.keys()), DECISION_KEYS)
        day = report["ledger"][30]
        self.assertEqual(day["n_prior"], 30)
        prior = np.array(values[:30], dtype=float)
        sleeves = np.column_stack([prior, prior, prior, prior, prior])
        expected = choose_action(prior, 0.0, sleeves=sleeves, n_paths=300, horizon=5, seed=7 + 30)
        self.assertIn("posterior_win_rate", report["next_action"]["estimate"])
        self.assertAlmostEqual(day["position"], expected["position"])
        shocked = list(values)
        shocked[30] = -0.80
        shocked_frame, _ = self._frame(shocked, "空仓", 0.0)
        shocked_report = build_decision_report(shocked_frame, temperature, n_paths=300, horizon=5, seed=7)
        self.assertAlmostEqual(shocked_report["ledger"][30]["position"], day["position"])
        self.assertNotAlmostEqual(shocked_report["ledger"][31]["n_prior"], day["n_prior"])

    def test_short_history_and_steady_loss_stay_in_cash(self) -> None:
        values = [-0.02] * 40
        aligned, temperature = self._frame(values, "满仓 100%", 100.0)
        report = build_decision_report(aligned, temperature, n_paths=200, horizon=5, seed=3)
        self.assertTrue(all(row["position"] == 0.0 for row in report["ledger"][:30]))
        self.assertEqual(report["ledger"][30]["action"], "空仓")
        self.assertEqual(report["ledger"][30]["position"], 0.0)
        self.assertEqual(report["next_action"]["action"], "空仓")
        self.assertTrue(all(weight == 0.0 for weight in report["next_action"]["weights"].values()))

    def test_flat_temperature_can_still_take_quarter_kelly(self) -> None:
        values = [0.02, -0.005] * 20
        aligned, temperature = self._frame(values, "空仓", 0.0)
        report = build_decision_report(aligned, temperature, n_paths=400, horizon=8, seed=11)
        self.assertEqual(report["ledger"][30]["action"], "四分之一凯利")
        self.assertGreater(report["ledger"][30]["position"], 0.0)
        self.assertEqual(report["next_action"]["state"], "空仓")

    def test_negative_sleeve_is_dropped_from_rotation(self) -> None:
        n_days = 40
        good = [0.02, -0.004] * (n_days // 2)
        bad = [-0.02, -0.01] * (n_days // 2)
        dates = pd.bdate_range("2024-01-02", periods=n_days)
        aligned = pd.DataFrame(
            {
                "date": dates,
                "W2+W3": good,
                "W4+W6": good,
                "M+": good,
                "Q": good,
                "G": bad,
            }
        )
        temperature = pd.DataFrame(
            {
                "temp_date": pd.to_datetime(["2023-12-29", *dates.strftime("%Y-%m-%d")]),
                "position_label": ["中仓 40%"] * (n_days + 1),
                "position_pct": [40.0] * (n_days + 1),
                "total_score": [70.0] * (n_days + 1),
            }
        )
        prior = np.column_stack([good[:30], good[:30], good[:30], good[:30], bad[:30]])
        weights = rotate_weights(prior)
        self.assertEqual(float(weights[-1]), 0.0)
        self.assertGreater(float(weights[0]), 0.0)
        report = build_decision_report(aligned, temperature, n_paths=200, horizon=5, seed=5)
        self.assertEqual(report["ledger"][30]["weights"]["G"], 0.0)
        shocked = aligned.copy()
        shocked.loc[30, "G"] = 0.50
        shocked_report = build_decision_report(shocked, temperature, n_paths=200, horizon=5, seed=5)
        self.assertEqual(shocked_report["ledger"][30]["weights"]["G"], 0.0)

    def test_missing_temperature_leaves_returns_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dates = pd.bdate_range("2024-01-02", periods=8)
            values = [0.01, -0.02] * 4
            group = root / "group_returns.csv"
            sleeve = root / "sleeve_returns.csv"
            pd.DataFrame({"date": dates, "W2+W3": values, "W4+W6": values}).to_csv(group, index=False)
            pd.DataFrame({"date": dates, "M+": values, "Q": values, "G": values}).to_csv(sleeve, index=False)
            before_group = group.read_bytes()
            payload = decision_payload(
                group_path=group,
                sleeve_path=sleeve,
                temperature_path=root / "missing_temperature.csv",
                output_path=root / "risk_return" / "output" / "decision_v1.json",
                n_paths=100,
            )
            self.assertTrue(payload["empty"])
            self.assertIn("市场温度", payload["message"])
            self.assertEqual(group.read_bytes(), before_group)
            self.assertFalse((root / "risk_return" / "output" / "decision_v1.json").exists())


if __name__ == "__main__":
    unittest.main()
