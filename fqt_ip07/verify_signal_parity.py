#!/usr/bin/env python3
"""Prove dataframe-level alpha parity between the frozen V10/V14 alpha and IP07.

The diagnostic subclass is allowed to change execution-only hooks.  Indicator,
entry-signal, dataframe exit-signal and tag outputs must remain byte-identical
for every pair over the frozen development interval.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
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


def digest_series(series: pd.Series) -> str:
    digest = hashlib.sha256()
    digest.update(str(series.dtype).encode())
    if pd.api.types.is_numeric_dtype(series):
        values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=np.float64)
        digest.update(values.tobytes())
    else:
        for value in series.astype("string").fillna("<NA>"):
            encoded = str(value).encode("utf-8", errors="replace")
            digest.update(len(encoded).to_bytes(8, "little"))
            digest.update(encoded)
    return digest.hexdigest()


def compare(base: pd.DataFrame, diagnostic: pd.DataFrame) -> dict[str, Any]:
    if len(base) != len(diagnostic):
        return {
            "pass": False,
            "reason": "row_count",
            "base_rows": len(base),
            "diagnostic_rows": len(diagnostic),
        }
    if list(base.columns) != list(diagnostic.columns):
        return {
            "pass": False,
            "reason": "column_set",
            "only_base": sorted(set(base) - set(diagnostic)),
            "only_diagnostic": sorted(set(diagnostic) - set(base)),
        }

    differences: list[dict[str, Any]] = []
    max_abs_difference = 0.0
    signal_differences: dict[str, int] = {}
    for column in base.columns:
        left = base[column]
        right = diagnostic[column]
        left_hash = digest_series(left)
        right_hash = digest_series(right)
        if left_hash == right_hash:
            if column in SIGNAL_COLUMNS:
                signal_differences[column] = 0
            continue

        row: dict[str, Any] = {
            "column": column,
            "base_sha256": left_hash,
            "diagnostic_sha256": right_hash,
        }
        if pd.api.types.is_numeric_dtype(left) and pd.api.types.is_numeric_dtype(right):
            left_values = pd.to_numeric(left, errors="coerce").to_numpy(dtype=float)
            right_values = pd.to_numeric(right, errors="coerce").to_numpy(dtype=float)
            finite = np.isfinite(left_values) & np.isfinite(right_values)
            absolute = (
                float(np.max(np.abs(left_values[finite] - right_values[finite])))
                if finite.any()
                else 0.0
            )
            nan_mismatch = int(
                np.count_nonzero(np.isnan(left_values) != np.isnan(right_values))
            )
            row.update(max_abs_difference=absolute, nan_mismatch=nan_mismatch)
            max_abs_difference = max(max_abs_difference, absolute)
        else:
            left_values = left.astype("string").fillna("<NA>").to_numpy()
            right_values = right.astype("string").fillna("<NA>").to_numpy()
            row["differences"] = int(np.count_nonzero(left_values != right_values))
        differences.append(row)

        if column in SIGNAL_COLUMNS:
            left_values = left.astype("string").fillna("<NA>").to_numpy()
            right_values = right.astype("string").fillna("<NA>").to_numpy()
            signal_differences[column] = int(
                np.count_nonzero(left_values != right_values)
            )

    return {
        "pass": not differences,
        "changed_columns": differences,
        "max_abs_difference": max_abs_difference,
        "signal_differences": signal_differences,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy-dir", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timerange-start", default="2026-01-01T00:00:00Z")
    parser.add_argument("--timerange-end", default="2026-05-01T00:00:00Z")
    args = parser.parse_args()

    strategy_dir = pathlib.Path(args.strategy_dir)
    config = json.loads(pathlib.Path(args.config).read_text())
    datadir = pathlib.Path(config["datadir"])
    sys.path.insert(0, str(strategy_dir))

    base_module = load_module(
        strategy_dir / "M4PioneerStableExposureV10.py", "fqt_ip07_base"
    )
    diagnostic_module = load_module(
        strategy_dir / "M4PioneerV10LookaheadDiagnostic.py", "fqt_ip07_diagnostic"
    )
    base = make_strategy(base_module.M4PioneerStableExposureV10)
    diagnostic = make_strategy(
        diagnostic_module.M4PioneerV10LookaheadDiagnostic
    )

    pair_rows: list[dict[str, Any]] = []
    for pair in config["exchange"]["pair_whitelist"]:
        parquet = datadir / f"{pair.replace('/', '_')}-1m.parquet"
        dataframe = pd.read_parquet(parquet).sort_values("date").reset_index(drop=True)
        dates = pd.to_datetime(dataframe["date"], utc=True)
        mask = (dates >= pd.Timestamp(args.timerange_start)) & (
            dates < pd.Timestamp(args.timerange_end)
        )
        dataframe = dataframe.loc[mask].reset_index(drop=True)

        base_output = pipeline(base, dataframe, pair)
        diagnostic_output = pipeline(diagnostic, dataframe, pair)
        result = compare(base_output, diagnostic_output)
        result.update(
            pair=pair,
            rows=len(dataframe),
            input_sha256=hashlib.sha256(parquet.read_bytes()).hexdigest(),
        )
        pair_rows.append(result)
        del dataframe, base_output, diagnostic_output
        gc.collect()

    output = {
        "contract": "FQT_IP07_SIGNAL_PARITY_V1",
        "base": "M4PioneerStableExposureV10",
        "diagnostic": "M4PioneerV10LookaheadDiagnostic",
        "v14_relationship": "M4PioneerValidationV14 is the alpha-unchanged evidence wrapper around this frozen parent",
        "pair_count": len(pair_rows),
        "pairs_passed": sum(bool(row["pass"]) for row in pair_rows),
        "pass": all(bool(row["pass"]) for row in pair_rows),
        "rows": pair_rows,
    }
    pathlib.Path(args.out).write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                key: output[key]
                for key in ("contract", "pair_count", "pairs_passed", "pass")
            },
            indent=2,
        )
    )
    return 0 if output["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
