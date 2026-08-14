#!/usr/bin/env python3
"""Run Freqtrade recursive-analysis once per pair to avoid first-pair-only coverage."""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import pandas as pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--offline-wrapper", required=True)
    ap.add_argument("--lookahead-summary", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--timerange", default="20260420-20260501")
    ap.add_argument("--threshold-pct", type=float, default=0.1)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    logs = outdir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    lookahead = json.loads(Path(args.lookahead_summary).read_text())
    config = json.loads(Path(args.config).read_text())
    pairs = list(config["exchange"]["pair_whitelist"])

    if not lookahead.get("diagnostic_equivalence_pass", False):
        summary = {
            "contract": "FQT_V23_IP07_FULL_31PAIR_RECURSIVE_MATRIX_V1",
            "status": "BLOCKED",
            "reason": "Diagnostic-equivalent lookahead predecessor did not pass.",
            "rows": [],
        }
        (outdir / "RECURSIVE_MATRIX.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        return 0

    startup = [199, 499, 799, 800, 999, 1100, 1600, 1999, 2400]
    rows: list[dict[str, Any]] = []
    for pair in pairs:
        safe = pair.replace("/", "_")
        cmd = [
            sys.executable,
            args.offline_wrapper,
            "recursive-analysis",
            "-c",
            args.config,
            "--strategy-path",
            "user_data/strategies",
            "-s",
            "M4PioneerValidationV14",
            "-i",
            "1m",
            "--timerange",
            args.timerange,
            "--data-format-ohlcv",
            "parquet",
            "-p",
            pair,
            "--startup-candle",
            *[str(value) for value in startup],
            "--no-color",
        ]
        started = time.perf_counter()
        cp = subprocess.run(
            cmd,
            cwd=Path.cwd(),
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        elapsed = time.perf_counter() - started
        log_path = logs / f"{safe}.log"
        log_path.write_text(cp.stdout)
        values = [abs(float(value)) for value in re.findall(r"(-?\d+(?:\.\d+)?)%", cp.stdout)]
        max_abs = max(values) if values else 0.0
        nan_present = bool(re.search(r"\bNaN\b|\bnan%\b", cp.stdout, flags=re.IGNORECASE))
        indicator_lookahead = re.findall(r"=> found lookahead in indicator\s+([^\r\n]+)", cp.stdout)
        used_match = re.search(r"Using pair\s+([^\s]+)\s+only for recursive analysis", cp.stdout)
        used_pair = used_match.group(1) if used_match else None
        passed = (
            cp.returncode == 0
            and used_pair == pair
            and not nan_present
            and not indicator_lookahead
            and max_abs <= args.threshold_pct + 1e-12
        )
        row = {
            "pair": pair,
            "used_pair": used_pair,
            "exit_code": cp.returncode,
            "elapsed_seconds": elapsed,
            "percent_values": len(values),
            "max_abs_percent": max_abs,
            "nan_present": nan_present,
            "indicator_lookahead_findings": indicator_lookahead,
            "threshold_percent": args.threshold_pct,
            "pass": passed,
            "command": cmd,
        }
        rows.append(row)
        (outdir / "RECURSIVE_MATRIX_PARTIAL.json").write_text(
            json.dumps(rows, indent=2, default=str) + "\n"
        )
        print(json.dumps({"pair": pair, "pass": passed, "max_abs_percent": max_abs, "elapsed_seconds": round(elapsed, 1)}))

    failures = [row for row in rows if not row["pass"]]
    summary = {
        "contract": "FQT_V23_IP07_FULL_31PAIR_RECURSIVE_MATRIX_V1",
        "status": "PASS" if not failures and len(rows) == len(pairs) else "FAIL",
        "timerange": args.timerange,
        "startup_candles": startup,
        "material_drift_threshold_percent": args.threshold_pct,
        "pair_count_expected": len(pairs),
        "pair_count_executed": len(rows),
        "pair_count_passed": sum(bool(row["pass"]) for row in rows),
        "maximum_abs_percent": max((row["max_abs_percent"] for row in rows), default=0.0),
        "failures": failures,
        "rows": rows,
        "note": "Freqtrade recursive-analysis uses only the first pair; this matrix invokes it once per pair.",
    }
    (outdir / "RECURSIVE_MATRIX.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    pd.DataFrame([{k: v for k, v in row.items() if k != "command"} for row in rows]).to_csv(
        outdir / "RECURSIVE_MATRIX.csv", index=False
    )
    print(json.dumps({k: summary[k] for k in ["status", "pair_count_executed", "pair_count_passed", "maximum_abs_percent"]}, indent=2))
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
