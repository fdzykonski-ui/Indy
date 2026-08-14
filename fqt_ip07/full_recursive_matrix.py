#!/usr/bin/env python3
"""Full 31-pair recursive convergence workaround for the frozen alpha.

This complements Freqtrade's native recursive-analysis.  It evaluates five
chronological anchors per pair and four startup histories.  Signal/tag changes
are gate failures.  Indicator drift is measured and preserved explicitly; it is
not silently converted into a pass.
"""
from __future__ import annotations

import argparse
import gc
import importlib.util
import json
import pathlib
import sys
from typing import Any

import numpy as np
import pandas as pd

SIGNAL_COLUMNS = ("enter_long", "exit_long", "enter_tag", "exit_tag")


def load_module(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_strategy(cls: type):
    try:
        return cls({})
    except TypeError:
        return cls()


def pipeline(strategy: Any, dataframe: pd.DataFrame, pair: str) -> pd.DataFrame:
    result = strategy.populate_indicators(dataframe.copy(), {"pair": pair})
    result = strategy.populate_entry_trend(result, {"pair": pair})
    result = strategy.populate_exit_trend(result, {"pair": pair})
    return result


def scalar_difference(left: Any, right: Any) -> tuple[float, float, bool]:
    if pd.isna(left) and pd.isna(right):
        return 0.0, 0.0, True
    try:
        left_float = float(left)
        right_float = float(right)
        if np.isnan(left_float) and np.isnan(right_float):
            return 0.0, 0.0, True
        absolute = abs(left_float - right_float)
        relative = absolute / max(abs(left_float), abs(right_float), 1e-12)
        equal = absolute <= 1e-10 or relative <= 1e-8
        return absolute, relative, equal
    except (TypeError, ValueError):
        return 0.0, 0.0, str(left) == str(right)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument(
        "--startup", nargs="+", type=int, default=[800, 1100, 1600, 2400]
    )
    parser.add_argument("--anchors", type=int, default=5)
    parser.add_argument("--timerange-start", default="2026-01-01T00:00:00Z")
    parser.add_argument("--timerange-end", default="2026-05-01T00:00:00Z")
    args = parser.parse_args()

    strategy_path = pathlib.Path(args.strategy)
    module = load_module(strategy_path, "fqt_ip07_recursive_base")
    strategy = make_strategy(module.M4PioneerStableExposureV10)
    config = json.loads(pathlib.Path(args.config).read_text())
    datadir = pathlib.Path(config["datadir"])

    pair_rows: list[dict[str, Any]] = []
    global_large_drift_columns: dict[str, dict[str, float | int]] = {}

    for pair in config["exchange"]["pair_whitelist"]:
        parquet = datadir / f"{pair.replace('/', '_')}-1m.parquet"
        dataframe = pd.read_parquet(parquet).sort_values("date").reset_index(drop=True)
        dates = pd.to_datetime(dataframe["date"], utc=True)
        dataframe = dataframe.loc[
            (dates >= pd.Timestamp(args.timerange_start))
            & (dates < pd.Timestamp(args.timerange_end))
        ].reset_index(drop=True)

        minimum_anchor = max(args.startup) + 100
        if len(dataframe) <= minimum_anchor + 1:
            pair_rows.append(
                {
                    "pair": pair,
                    "rows": len(dataframe),
                    "pass": False,
                    "reason": "insufficient_rows",
                }
            )
            continue

        full_output = pipeline(strategy, dataframe, pair)
        anchors = np.linspace(
            minimum_anchor, len(dataframe) - 2, args.anchors, dtype=int
        )
        checks: list[dict[str, Any]] = []
        signal_changes = 0
        max_abs_difference = 0.0
        max_relative_difference = 0.0
        changed_examples: list[dict[str, Any]] = []
        per_column: dict[str, dict[str, float | int]] = {}

        for anchor in anchors:
            reference = full_output.iloc[int(anchor)]
            for startup in args.startup:
                short_input = dataframe.iloc[
                    int(anchor) - startup + 1 : int(anchor) + 1
                ].copy()
                short_output = pipeline(
                    strategy, short_input.reset_index(drop=True), pair
                )
                candidate = short_output.iloc[-1]
                changed_columns: list[dict[str, Any]] = []

                for column in reference.index.intersection(candidate.index):
                    absolute, relative, equal = scalar_difference(
                        reference[column], candidate[column]
                    )
                    max_abs_difference = max(max_abs_difference, absolute)
                    max_relative_difference = max(max_relative_difference, relative)
                    stats = per_column.setdefault(
                        column,
                        {
                            "comparisons": 0,
                            "changes": 0,
                            "max_abs_difference": 0.0,
                            "max_relative_difference": 0.0,
                        },
                    )
                    stats["comparisons"] = int(stats["comparisons"]) + 1
                    stats["max_abs_difference"] = max(
                        float(stats["max_abs_difference"]), absolute
                    )
                    stats["max_relative_difference"] = max(
                        float(stats["max_relative_difference"]), relative
                    )
                    if not equal:
                        stats["changes"] = int(stats["changes"]) + 1
                        if column in SIGNAL_COLUMNS:
                            signal_changes += 1
                        changed_columns.append(
                            {
                                "column": column,
                                "abs_difference": absolute,
                                "relative_difference": relative,
                                "reference": str(reference[column])[:160],
                                "candidate": str(candidate[column])[:160],
                            }
                        )

                checks.append(
                    {
                        "anchor": int(anchor),
                        "startup": startup,
                        "changed_count": len(changed_columns),
                    }
                )
                if changed_columns:
                    changed_examples.append(
                        {
                            "anchor": int(anchor),
                            "startup": startup,
                            "changed_count": len(changed_columns),
                            "changed": changed_columns[:50],
                        }
                    )
                del short_input, short_output
                gc.collect()

        large_drift_columns = {
            column: stats
            for column, stats in per_column.items()
            if int(stats["changes"]) > 0
            and float(stats["max_abs_difference"]) > 1e-8
            and float(stats["max_relative_difference"]) > 1e-5
            and column not in SIGNAL_COLUMNS
        }
        for column, stats in large_drift_columns.items():
            aggregate = global_large_drift_columns.setdefault(
                column,
                {
                    "pairs": 0,
                    "changes": 0,
                    "max_abs_difference": 0.0,
                    "max_relative_difference": 0.0,
                },
            )
            aggregate["pairs"] = int(aggregate["pairs"]) + 1
            aggregate["changes"] = int(aggregate["changes"]) + int(
                stats["changes"]
            )
            aggregate["max_abs_difference"] = max(
                float(aggregate["max_abs_difference"]),
                float(stats["max_abs_difference"]),
            )
            aggregate["max_relative_difference"] = max(
                float(aggregate["max_relative_difference"]),
                float(stats["max_relative_difference"]),
            )

        pair_rows.append(
            {
                "pair": pair,
                "rows": len(dataframe),
                "signal_changes": signal_changes,
                "max_abs_difference": max_abs_difference,
                "max_relative_difference": max_relative_difference,
                "large_indicator_drift_column_count": len(large_drift_columns),
                "large_indicator_drift_columns": large_drift_columns,
                "pass": signal_changes == 0,
                "checks": checks,
                "changed_examples": changed_examples[:20],
            }
        )
        del dataframe, full_output
        gc.collect()

    output = {
        "contract": "FQT_IP07_FULL_31PAIR_RECURSIVE_SIGNAL_MATRIX_V1",
        "classification": "FULL_UNIVERSE_SIGNAL_GATE_WITH_EXPLICIT_INDICATOR_DRIFT_REPORT",
        "pair_count": len(pair_rows),
        "pairs_passed": sum(bool(row.get("pass")) for row in pair_rows),
        "startup_candles": args.startup,
        "anchors_per_pair": args.anchors,
        "signal_gate_pass": all(bool(row.get("pass")) for row in pair_rows),
        "indicator_drift_gate_closed": False,
        "indicator_drift_gate_reason": (
            "Large drift is reported per column; causal use/dependency and an official "
            "Freqtrade recursive-analysis verdict remain separate requirements."
        ),
        "global_large_indicator_drift_columns": global_large_drift_columns,
        "rows": pair_rows,
    }
    pathlib.Path(args.out).write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: output[key]
                for key in (
                    "contract",
                    "pair_count",
                    "pairs_passed",
                    "signal_gate_pass",
                    "indicator_drift_gate_closed",
                )
            },
            indent=2,
        )
    )
    return 0 if output["signal_gate_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
