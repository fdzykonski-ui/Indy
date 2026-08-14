#!/usr/bin/env python3
"""Run full 31-pair native lookahead on signal-equivalent diagnostic classes."""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def parse_bool(value: Any) -> bool | None:
    text = str(value).strip().lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def prepare_config(base: dict[str, Any], strategy: str, mode: str, path: Path) -> None:
    cfg = json.loads(json.dumps(base))
    cfg["strategy"] = strategy
    cfg["lookahead_allow_limit_orders"] = mode == "limit"
    cfg["dry_run"] = True
    cfg["initial_state"] = "stopped"
    cfg["enable_protections"] = False
    if mode == "market":
        cfg.setdefault("entry_pricing", {})["price_side"] = "other"
        cfg.setdefault("exit_pricing", {})["price_side"] = "other"
    else:
        cfg.setdefault("entry_pricing", {})["price_side"] = "same"
        cfg.setdefault("exit_pricing", {})["price_side"] = "same"
    path.write_text(json.dumps(cfg, indent=2) + "\n")


def parse_run(csv_path: Path, log: str, rc: int) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    if csv_path.exists():
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
    valid_rows = []
    for row in rows:
        try:
            total = int(float(str(row.get("total_signals", "0") or 0)))
        except Exception:
            total = 0
        bias = parse_bool(row.get("has_bias"))
        if total >= 10 and bias is not None:
            valid_rows.append({**row, "total_signals_int": total, "has_bias_bool": bias})
    found_matches = [int(x) for x in re.findall(r"(?:Found|found|Only found)\s+(\d+)\s+trades", log)]
    result = {
        "process_exit_code": rc,
        "csv_exists": csv_path.exists(),
        "rows": rows,
        "valid_rows": valid_rows,
        "valid_verdict": len(valid_rows) == 1,
        "has_bias": valid_rows[0]["has_bias_bool"] if len(valid_rows) == 1 else None,
        "total_signals": valid_rows[0]["total_signals_int"] if len(valid_rows) == 1 else 0,
        "found_trade_log_values": found_matches,
        "too_few_trades": "too few trades" in log.lower() or "less than minimum_trade_amount" in log,
    }
    if result["valid_verdict"] and result["has_bias"] is False:
        result["status"] = "PASS_NO_BIAS"
    elif result["valid_verdict"] and result["has_bias"] is True:
        result["status"] = "FAIL_BIAS"
    else:
        result["status"] = "INVALID"
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", required=True)
    ap.add_argument("--offline-wrapper", required=True)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--parity", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--timerange", default="20260101-20260501")
    ap.add_argument("--minimum", type=int, default=10)
    ap.add_argument("--target", type=int, default=50)
    args = ap.parse_args()

    root = Path.cwd()
    outdir = Path(args.outdir)
    configs = outdir / "configs"
    logs = outdir / "logs"
    csvs = outdir / "csv"
    for path in (outdir, configs, logs, csvs):
        path.mkdir(parents=True, exist_ok=True)

    base = json.loads(Path(args.base_config).read_text())
    matrix = json.loads(Path(args.matrix).read_text())
    parity = json.loads(Path(args.parity).read_text())
    selected = matrix.get("selected_diagnostic_variant")
    if selected and selected.startswith("stake_neutral"):
        strategy = "M4PioneerValidationV14LookaheadStakeNeutral"
    elif selected and selected.startswith("execution_neutral"):
        strategy = "M4PioneerValidationV14LookaheadExecutionNeutral"
    else:
        strategy = "M4PioneerValidationV14LookaheadStakeNeutral"

    preferred_mode = matrix.get("selected_order_mode") or "market"
    modes = [preferred_mode, "limit" if preferred_mode == "market" else "market"]
    runs = []
    for mode in modes:
        label = f"{strategy}__{mode}"
        cfg_path = configs / f"{label}.json"
        csv_path = csvs / f"{label}.csv"
        log_path = logs / f"{label}.log"
        prepare_config(base, strategy, mode, cfg_path)
        if csv_path.exists():
            csv_path.unlink()
        cmd = [
            sys.executable,
            args.offline_wrapper,
            "lookahead-analysis",
            "-c",
            str(cfg_path),
            "--strategy-path",
            "user_data/strategies",
            "-s",
            strategy,
            "-i",
            "1m",
            "--timerange",
            args.timerange,
            "--fee",
            "0.001",
            "--minimum-trade-amount",
            str(args.minimum),
            "--targeted-trade-amount",
            str(args.target),
            "--lookahead-analysis-exportfilename",
            str(csv_path),
            "--no-color",
        ]
        started = time.perf_counter()
        cp = subprocess.run(
            cmd,
            cwd=root,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        elapsed = time.perf_counter() - started
        log_path.write_text(cp.stdout)
        parsed = parse_run(csv_path, cp.stdout, cp.returncode)
        row = {
            "label": label,
            "strategy": strategy,
            "order_mode": mode,
            "timerange": args.timerange,
            "minimum_trade_amount": args.minimum,
            "targeted_trade_amount": args.target,
            "elapsed_seconds": elapsed,
            "command": cmd,
            **parsed,
        }
        runs.append(row)
        Path(outdir / "LOOKAHEAD_DIAGNOSTIC_PARTIAL.json").write_text(
            json.dumps(runs, indent=2, default=str) + "\n"
        )
        print(json.dumps({"label": label, "status": row["status"], "total_signals": row["total_signals"], "elapsed_seconds": round(elapsed, 1)}))
        # One valid no-bias market result plus full signal parity is sufficient to
        # stop the expensive second mode.  Limit mode is only a triangulation run.
        if mode == "market" and row["status"] == "PASS_NO_BIAS" and parity.get("status") == "PASS":
            break

    pass_runs = [row for row in runs if row["status"] == "PASS_NO_BIAS"]
    fail_runs = [row for row in runs if row["status"] == "FAIL_BIAS"]
    summary = {
        "contract": "FQT_V23_IP07_DIAGNOSTIC_EQUIVALENT_NATIVE_LOOKAHEAD_V1",
        "champion_direct_native_status": "INVALID_PREVIOUS_ZERO_RESULT_ROWS",
        "diagnostic_strategy": strategy,
        "signal_parity_status": parity.get("status"),
        "method_identity": parity.get("method_identity"),
        "runs": runs,
        "diagnostic_equivalence_pass": bool(pass_runs) and parity.get("status") == "PASS",
        "bias_detected_in_any_valid_run": bool(fail_runs),
        "decision": (
            "PASS_DIAGNOSTIC_EQUIVALENT"
            if bool(pass_runs) and parity.get("status") == "PASS"
            else "BLOCKED"
        ),
        "scope": (
            "Closes vectorized indicator/entry/exit causal-signal gate under exact signal parity. "
            "Does not certify champion capital allocation, custom-exit economics or live fills."
        ),
    }
    Path(outdir / "LOOKAHEAD_DIAGNOSTIC_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    print(json.dumps({k: summary[k] for k in ["signal_parity_status", "diagnostic_equivalence_pass", "bias_detected_in_any_valid_run", "decision"]}, indent=2))
    return 0 if summary["diagnostic_equivalence_pass"] and not summary["bias_detected_in_any_valid_run"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
