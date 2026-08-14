#!/usr/bin/env python3
"""Run Freqtrade recursive-analysis once per pair to avoid first-pair-only coverage.

Freqtrade's command emits a matrix of indicator variances for several startup
candle counts.  Values below the strategy's production startup count are kept
as diagnostic evidence, but the operational gate is evaluated only at the
frozen strategy startup (800) and larger buffers.
"""
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

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def parse_recursive_table(text: str) -> dict[str, Any]:
    """Parse Rich's Unicode recursive-analysis table without reading other % logs."""
    clean = ANSI_RE.sub("", text)
    lines = clean.splitlines()
    header_index = next(
        (idx for idx, line in enumerate(lines) if "┃" in line and "Indicators" in line),
        None,
    )
    if header_index is None:
        return {
            "table_parsed": False,
            "headers": [],
            "rows": [],
            "max_by_startup_percent": {},
            "nan_present": False,
        }

    header_cells = [cell.strip() for cell in lines[header_index].strip().strip("┃").split("┃")]
    startup_by_column: dict[int, int] = {}
    for col_idx, cell in enumerate(header_cells[1:], start=1):
        match = re.search(r"\d+", cell)
        if match:
            startup_by_column[col_idx] = int(match.group(0))

    parsed_rows: list[dict[str, Any]] = []
    nan_present = False
    for line in lines[header_index + 1 :]:
        stripped = line.strip()
        if stripped.startswith("└"):
            break
        if not stripped.startswith("│"):
            continue
        cells = [cell.strip() for cell in stripped.strip("│").split("│")]
        if len(cells) < 2:
            continue
        indicator = cells[0]
        values: dict[str, float | None] = {}
        for col_idx, startup in startup_by_column.items():
            cell = cells[col_idx] if col_idx < len(cells) else ""
            if re.search(r"\bnan\b", cell, flags=re.IGNORECASE):
                nan_present = True
                value = None
            elif cell in {"", "-"}:
                # Rich uses '-' when the command considers the variance zero/not material.
                value = 0.0
            else:
                match = re.search(r"(-?\d+(?:\.\d+)?)%", cell)
                value = abs(float(match.group(1))) if match else None
            values[str(startup)] = value
        parsed_rows.append({"indicator": indicator, "values_percent": values})

    max_by_startup: dict[str, float] = {}
    for startup in sorted(set(startup_by_column.values())):
        observed = [
            row["values_percent"].get(str(startup))
            for row in parsed_rows
            if row["values_percent"].get(str(startup)) is not None
        ]
        max_by_startup[str(startup)] = max(observed) if observed else 0.0

    return {
        "table_parsed": bool(parsed_rows) and bool(startup_by_column),
        "headers": header_cells,
        "rows": parsed_rows,
        "max_by_startup_percent": max_by_startup,
        "nan_present": nan_present,
    }


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
            "contract": "FQT_V23_IP07_FULL_31PAIR_RECURSIVE_MATRIX_V2",
            "status": "BLOCKED",
            "reason": "Diagnostic-equivalent lookahead predecessor did not pass.",
            "rows": [],
        }
        (outdir / "RECURSIVE_MATRIX.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        return 0

    startup = [199, 499, 799, 800, 999, 1100, 1600, 1999, 2400]
    production_startup = int(config.get("startup_candle_count", 800) or 800)
    production_startups = [value for value in startup if value >= production_startup]
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

        parsed = parse_recursive_table(cp.stdout)
        max_by_startup = parsed["max_by_startup_percent"]
        all_values = list(max_by_startup.values())
        production_values = [
            float(max_by_startup.get(str(value), 0.0)) for value in production_startups
        ]
        max_all = max(all_values) if all_values else 0.0
        max_production = max(production_values) if production_values else 0.0
        indicator_lookahead = re.findall(
            r"=> found lookahead in indicator\s+([^\r\n]+)", cp.stdout
        )
        used_match = re.search(
            r"Using pair\s+([^\s]+)\s+only for recursive analysis", cp.stdout
        )
        used_pair = used_match.group(1) if used_match else None
        passed = (
            cp.returncode == 0
            and used_pair == pair
            and parsed["table_parsed"]
            and not parsed["nan_present"]
            and not indicator_lookahead
            and max_production <= args.threshold_pct + 1e-12
        )
        row = {
            "pair": pair,
            "used_pair": used_pair,
            "exit_code": cp.returncode,
            "elapsed_seconds": elapsed,
            "table_parsed": parsed["table_parsed"],
            "indicator_rows": len(parsed["rows"]),
            "production_startup_candle_count": production_startup,
            "production_startups": production_startups,
            "max_by_startup_percent": max_by_startup,
            "max_abs_percent_all_startups": max_all,
            "max_abs_percent_production": max_production,
            # Backward-compatible alias consumed by the finalizer.
            "max_abs_percent": max_production,
            "nan_present": parsed["nan_present"],
            "indicator_lookahead_findings": indicator_lookahead,
            "threshold_percent": args.threshold_pct,
            "pass": passed,
            "table_rows": parsed["rows"],
            "command": cmd,
        }
        rows.append(row)
        (outdir / "RECURSIVE_MATRIX_PARTIAL.json").write_text(
            json.dumps(rows, indent=2, default=str) + "\n"
        )
        print(
            json.dumps(
                {
                    "pair": pair,
                    "pass": passed,
                    "max_abs_percent_all_startups": max_all,
                    "max_abs_percent_production": max_production,
                    "elapsed_seconds": round(elapsed, 1),
                }
            )
        )

    failures = [row for row in rows if not row["pass"]]
    summary = {
        "contract": "FQT_V23_IP07_FULL_31PAIR_RECURSIVE_MATRIX_V2",
        "status": "PASS" if not failures and len(rows) == len(pairs) else "FAIL",
        "timerange": args.timerange,
        "startup_candles_diagnostic": startup,
        "production_startup_candle_count": production_startup,
        "production_startups_gated": production_startups,
        "material_drift_threshold_percent": args.threshold_pct,
        "pair_count_expected": len(pairs),
        "pair_count_executed": len(rows),
        "pair_count_passed": sum(bool(row["pass"]) for row in rows),
        "maximum_abs_percent_all_startups": max(
            (row["max_abs_percent_all_startups"] for row in rows), default=0.0
        ),
        "maximum_abs_percent_production": max(
            (row["max_abs_percent_production"] for row in rows), default=0.0
        ),
        # Backward-compatible alias consumed by the finalizer.
        "maximum_abs_percent": max(
            (row["max_abs_percent_production"] for row in rows), default=0.0
        ),
        "failures": failures,
        "rows": rows,
        "note": (
            "Freqtrade recursive-analysis uses only the first pair, so this matrix invokes it once per pair. "
            "Sub-production startup counts are diagnostic; the gate applies only at the frozen strategy startup and larger buffers."
        ),
    }
    (outdir / "RECURSIVE_MATRIX.json").write_text(
        json.dumps(summary, indent=2, default=str) + "\n"
    )
    pd.DataFrame(
        [
            {k: v for k, v in row.items() if k not in {"command", "table_rows"}}
            for row in rows
        ]
    ).to_csv(outdir / "RECURSIVE_MATRIX.csv", index=False)
    print(
        json.dumps(
            {
                key: summary[key]
                for key in [
                    "status",
                    "pair_count_executed",
                    "pair_count_passed",
                    "maximum_abs_percent_all_startups",
                    "maximum_abs_percent_production",
                ]
            },
            indent=2,
        )
    )
    return 0 if summary["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
