# -*- coding: utf-8 -*-
"""研究任务的读、算、写。失败只返回错误，不改日常链文件。"""
from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pandas as pd

from risk_return.contract import SNAPSHOT_RELATIVE
from risk_return.engine import report_from_samples
from risk_return.correlation import (
    GROUP_RETURNS,
    SLEEVE_RETURNS,
    build_correlation_report,
    load_aligned,
)
from risk_return.budget import build_budget_report
from risk_return.copula import build_copula_report
from risk_return.decision import build_decision_report
from risk_return.walkforward import build_walkforward_report
from risk_return.regime import TEMPERATURE_CSV, build_regime_report, load_temperature
from risk_return.io import DEFAULT_OUTPUT_PATH, read_json, write_json
from risk_return.system_samples import (
    DEFAULT_SNAPSHOT_PATH,
    PROJECT_ROOT,
    fetch_system_bars,
    load_mplus_panel,
    samples_from_mplus_panel,
)

_NO_RESULT = "还没有研究结果。运行研究将读取市场中性截面里的 M+，并用系统日线补 T+3。"
_NO_SNAPSHOT = (
    f"缺少系统样本 {SNAPSHOT_RELATIVE}。"
    "请先让已有的市场中性回测生成这份截面。研究任务不会改日常四步链的文件。"
)
_NO_MUD = f"{SNAPSHOT_RELATIVE} 里没有可用的 mud_plus。"


def latest_payload(output_path: Path | None = None) -> dict:
    path = output_path or DEFAULT_OUTPUT_PATH
    if not path.is_file():
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": _NO_RESULT,
            "report": None,
        }
    report = read_json(path)
    if not report:
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": _NO_RESULT,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}


def run_payload(
    *,
    n_paths: int,
    n_trades: int,
    seed: int,
    snapshot_path: Path | None = None,
    output_path: Path | None = None,
    bars_by_symbol: Mapping[str, pd.DataFrame] | None = None,
) -> dict:
    source = snapshot_path or DEFAULT_SNAPSHOT_PATH
    dest = output_path or DEFAULT_OUTPUT_PATH
    if not source.is_file():
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": _NO_SNAPSHOT,
            "report": None,
        }
    try:
        panel = load_mplus_panel(source)
        if panel.empty:
            return {
                "ok": True,
                "empty": True,
                "error": None,
                "message": _NO_MUD,
                "report": None,
            }
        bars = bars_by_symbol if bars_by_symbol is not None else fetch_system_bars(panel)
        samples = samples_from_mplus_panel(panel, bars)
        if samples.empty:
            return {
                "ok": False,
                "empty": False,
                "error": (
                    f"已读到 M+ 截面 {len(panel)} 行，但没有一条能配上 T+3 收盘。"
                    "系统日线未覆盖这些信号日。"
                ),
                "message": None,
                "report": None,
            }
        try:
            source_label = source.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            source_label = source.name
        report = report_from_samples(
            samples,
            n_paths=n_paths,
            n_trades=n_trades,
            seed=seed,
            sample_step=None,
            sample_source=source_label,
        )
        write_json(report, dest)
    except Exception as exc:
        return {
            "ok": False,
            "empty": False,
            "error": str(exc),
            "message": None,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}


CORRELATION_OUTPUT = DEFAULT_OUTPUT_PATH.parent / "correlation_v2.json"


def correlation_payload(
    *,
    n_paths: int = 10_000,
    horizon_days: int = 60,
    seed: int = 20261001,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    dest = output_path or CORRELATION_OUTPUT
    try:
        aligned = load_aligned(group_path, sleeve_path)
        report = build_correlation_report(
            aligned,
            n_paths=n_paths,
            horizon_days=horizon_days,
            seed=seed,
            group_path=group_path or GROUP_RETURNS,
            sleeve_path=sleeve_path or SLEEVE_RETURNS,
        )
        write_json(report, dest)
    except FileNotFoundError as exc:
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": str(exc),
            "report": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "empty": False,
            "error": str(exc),
            "message": None,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}


REGIME_OUTPUT = DEFAULT_OUTPUT_PATH.parent / "regime_v3.json"


def regime_payload(
    *,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    dest = output_path or REGIME_OUTPUT
    try:
        aligned = load_aligned(group_path, sleeve_path)
        temperature = load_temperature(temperature_path or TEMPERATURE_CSV)
        report = build_regime_report(
            aligned,
            temperature,
            temperature_path=temperature_path or TEMPERATURE_CSV,
        )
        write_json(report, dest)
    except FileNotFoundError as exc:
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": str(exc),
            "report": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "empty": False,
            "error": str(exc),
            "message": None,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}


BUDGET_OUTPUT = DEFAULT_OUTPUT_PATH.parent / "budget_v4.json"


def budget_payload(
    *,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    dest = output_path or BUDGET_OUTPUT
    try:
        aligned = load_aligned(group_path, sleeve_path)
        temperature = load_temperature(temperature_path or TEMPERATURE_CSV)
        report = build_budget_report(aligned, temperature)
        write_json(report, dest)
    except FileNotFoundError as exc:
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": str(exc),
            "report": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "empty": False,
            "error": str(exc),
            "message": None,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}


WALKFORWARD_OUTPUT = DEFAULT_OUTPUT_PATH.parent / "walkforward_v5.json"


def walkforward_payload(
    *,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
    output_path: Path | None = None,
) -> dict:
    dest = output_path or WALKFORWARD_OUTPUT
    try:
        aligned = load_aligned(group_path, sleeve_path)
        temperature = load_temperature(temperature_path or TEMPERATURE_CSV)
        report = build_walkforward_report(aligned, temperature)
        write_json(report, dest)
    except FileNotFoundError as exc:
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": str(exc),
            "report": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "empty": False,
            "error": str(exc),
            "message": None,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}


COPULA_OUTPUT = DEFAULT_OUTPUT_PATH.parent / "copula_v6.json"


def copula_payload(
    *,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    output_path: Path | None = None,
    n_paths: int = 10_000,
    seed: int = 20261001,
) -> dict:
    dest = output_path or COPULA_OUTPUT
    try:
        aligned = load_aligned(group_path, sleeve_path)
        report = build_copula_report(aligned, n_paths=n_paths, seed=seed)
        write_json(report, dest)
    except FileNotFoundError as exc:
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": str(exc),
            "report": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "empty": False,
            "error": str(exc),
            "message": None,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}


DECISION_OUTPUT = DEFAULT_OUTPUT_PATH.parent / "decision_v1.json"


def decision_payload(
    *,
    group_path: Path | None = None,
    sleeve_path: Path | None = None,
    temperature_path: Path | None = None,
    output_path: Path | None = None,
    n_paths: int = 4_000,
    seed: int = 20261001,
) -> dict:
    dest = output_path or DECISION_OUTPUT
    try:
        aligned = load_aligned(group_path, sleeve_path)
        temperature = load_temperature(temperature_path or TEMPERATURE_CSV)
        report = build_decision_report(aligned, temperature, n_paths=n_paths, seed=seed)
        write_json(report, dest)
    except FileNotFoundError as exc:
        return {
            "ok": True,
            "empty": True,
            "error": None,
            "message": str(exc),
            "report": None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "empty": False,
            "error": str(exc),
            "message": None,
            "report": None,
        }
    return {"ok": True, "empty": False, "error": None, "message": None, "report": report}
