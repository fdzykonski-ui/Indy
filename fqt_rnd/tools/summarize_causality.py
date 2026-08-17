#!/usr/bin/env python3
"""Normalize Freqtrade lookahead/recursive output into one audit artifact."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def parse_percent(value: str) -> float | None:
    value = value.strip()
    if value in {"-", "NaN", ""}:
        return None
    return float(value.removesuffix("%"))


def main() -> int:
    with (ROOT / "results/causality/champion_lookahead.csv").open(newline="", encoding="utf-8") as handle:
        lookahead_rows = list(csv.DictReader(handle))
    lookahead = lookahead_rows[0]
    total_signals = int(lookahead["total_signals"])
    no_bias = lookahead["has_bias"].lower() == "false"

    log_text = (ROOT / "logs/champion_recursive_current.log").read_text(encoding="utf-8")
    startup_counts_match = re.search(r"Startup candle.*\[(.*?)\]", log_text)
    startup_counts = [int(value) for value in re.findall(r"[0-9]+", startup_counts_match.group(1))]
    rows: list[dict[str, object]] = []
    for line in log_text.splitlines():
        if not line.startswith("│"):
            continue
        parts = [part.strip() for part in line.strip("│").split("│")]
        if len(parts) != 8 or parts[0].lower() == "indicators":
            continue
        values = [parse_percent(value) for value in parts[1:]]
        rows.append({"indicator": parts[0], **{str(k): v for k, v in zip(startup_counts, values)}})

    strategy_startup = 1600
    material_at_strategy_startup = sorted(
        [
            {"indicator": row["indicator"], "variance_pct": row[str(strategy_startup)]}
            for row in rows
            if row[str(strategy_startup)] is not None and abs(float(row[str(strategy_startup)])) >= 0.1
        ],
        key=lambda row: abs(float(row["variance_pct"])),
        reverse=True,
    )
    recursive_indicator_lookahead_clear = "No lookahead bias on indicators found." in log_text
    recursive_pass = not material_at_strategy_startup
    report = {
        "schema_version": 1,
        "lookahead": {
            "has_bias": not no_bias,
            "total_signals": total_signals,
            "biased_entry_signals": int(lookahead["biased_entry_signals"]),
            "biased_exit_signals": int(lookahead["biased_exit_signals"]),
            "truth_status": "TEILWEISE VERIFIZIERT" if no_bias and total_signals < 20 else (
                "VERIFIZIERT" if no_bias else "NICHT VERIFIZIERT"
            ),
            "scope_limit": "Only triggered signals are checked; ten signals are below the default twenty-signal target.",
        },
        "recursive": {
            "startup_candles": startup_counts,
            "strategy_startup_candles": strategy_startup,
            "indicator_only_lookahead_clear": recursive_indicator_lookahead_clear,
            "material_variances_at_strategy_startup": material_at_strategy_startup,
            "truth_status": "VERIFIZIERT" if recursive_pass else "NICHT VERIFIZIERT",
            "reason": "Material long-window/quantile variance remains at the configured 1600-candle startup.",
            "full_rows": rows,
        },
        "overall_truth_status": "TEILWEISE VERIFIZIERT"
        if no_bias and recursive_indicator_lookahead_clear
        else "NICHT VERIFIZIERT",
    }
    target = ROOT / "audit/causality_summary.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"lookahead": report["lookahead"]["truth_status"], "recursive": report["recursive"]["truth_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
