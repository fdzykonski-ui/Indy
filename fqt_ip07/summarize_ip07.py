#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import pathlib
import zipfile
from typing import Any


def load_result(path: pathlib.Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(names) != 1:
            raise RuntimeError(f"{path}: expected one result JSON, found {len(names)}")
        obj = json.loads(archive.read(names[0]))
    if len(obj["strategy"]) != 1:
        raise RuntimeError(f"{path}: expected one strategy result")
    result = next(iter(obj["strategy"].values()))
    return {
        "zip": path.name,
        "zip_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "trades": result.get("total_trades"),
        "wins": result.get("wins"),
        "draws": result.get("draws"),
        "losses": result.get("losses"),
        "winrate_pct": float(result.get("winrate", 0.0)) * 100.0,
        "profit_pct": float(result.get("profit_total", 0.0)) * 100.0,
        "profit_usdc": result.get("profit_total_abs"),
        "profit_factor": result.get("profit_factor"),
        "max_drawdown_account_pct": float(
            result.get("max_drawdown_account", 0.0)
        )
        * 100.0,
    }


def parse_bool_values(rows: list[dict[str, str]], field: str) -> list[bool]:
    values: list[bool] = []
    for row in rows:
        value = str(row.get(field, "")).strip().lower()
        if value in ("yes", "true", "1"):
            values.append(True)
        elif value in ("no", "false", "0"):
            values.append(False)
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    root = pathlib.Path(args.root)
    evidence = root / "evidence"
    lookahead_csv = evidence / "ip07_lookahead.csv"
    rows = (
        list(csv.DictReader(lookahead_csv.open())) if lookahead_csv.exists() else []
    )
    bias_values = parse_bool_values(rows, "has_bias")
    lookahead_log = (evidence / "ip07_lookahead.log").read_text(
        errors="replace"
    )
    parity = json.loads((evidence / "IP07_SIGNAL_PARITY.json").read_text())
    recursive = json.loads((evidence / "IP07_RECURSIVE_MATRIX.json").read_text())

    result_zips = sorted(
        (root / "user_data/backtest_results").glob("backtest-result-*.zip"),
        key=lambda path: path.stat().st_mtime,
    )
    diagnostic_result = load_result(result_zips[-1]) if result_zips else None
    official_recursive_rc_path = evidence / "ip07_official_recursive.rc"
    official_recursive_rc = (
        int(official_recursive_rc_path.read_text().strip())
        if official_recursive_rc_path.exists()
        else None
    )

    signal_generation_gate_pass = (
        bool(parity["pass"])
        and bool(recursive["signal_gate_pass"])
        and bool(bias_values)
        and not any(bias_values)
    )
    output = {
        "contract": "FQT_IP07_DIAGNOSTIC_LOOKAHEAD_GATE_V1",
        "classification": "EXECUTION_NEUTRAL_SIGNAL_GENERATION_CORRECTNESS_HARNESS",
        "diagnostic_execution_only": True,
        "alpha_change": False,
        "alpha_signal_parity": parity["pass"],
        "parity_pairs_passed": parity["pairs_passed"],
        "parity_pair_count": parity["pair_count"],
        "recursive_signal_gate_pass": recursive["signal_gate_pass"],
        "recursive_pairs_passed": recursive["pairs_passed"],
        "recursive_pair_count": recursive["pair_count"],
        "recursive_indicator_drift_gate_closed": recursive[
            "indicator_drift_gate_closed"
        ],
        "official_recursive_analysis_rc": official_recursive_rc,
        "lookahead_csv_rows": len(rows),
        "lookahead_valid_verdict": bool(bias_values),
        "lookahead_has_bias": any(bias_values) if bias_values else None,
        "too_few_trades": "too few trades" in lookahead_log.lower(),
        "diagnostic_backtest": diagnostic_result,
        "signal_generation_gate_pass": signal_generation_gate_pass,
        "champion_execution_callback_gate_closed": False,
        "champion_execution_callback_gate_reason": (
            "The diagnostic overrides execution-only callbacks, ROI, stoploss and "
            "order types.  The frozen champion execution path remains a separate gate."
        ),
        "promotion_authorized": False,
        "oos_authorized": False,
        "dry_run_authorized": False,
        "live_authorized": False,
        "rows": rows,
    }
    pathlib.Path(args.out).write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    return 0 if signal_generation_gate_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
