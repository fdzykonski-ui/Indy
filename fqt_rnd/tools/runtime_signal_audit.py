#!/usr/bin/env python3
"""Runtime prefix-causality, signal timing, and collision audit for frozen ED8.

Run with the supplied Freqtrade virtual environment and ``PYTHONPATH`` pointed
at the reconstructed checkout.  The script never writes to that checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from freqtrade.resolvers import StrategyResolver


ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = ROOT / "reconstruction/freqtrade/user_data/data/binance/BTC_USDC-1m.parquet"
STRATEGY_PATH = ROOT / "champion/frozen"


def load_strategy() -> Any:
    config = {
        "strategy": "ED8",
        "strategy_path": str(STRATEGY_PATH),
        "user_data_dir": ROOT,
        "dry_run": True,
        "trading_mode": "spot",
        "margin_mode": "",
    }
    return StrategyResolver.load_strategy(config)


def compute(frame: pd.DataFrame) -> pd.DataFrame:
    strategy = load_strategy()
    metadata = {"pair": "BTC/USDC"}
    result = strategy.populate_indicators(frame.copy(), metadata)
    result = strategy.populate_entry_trend(result, metadata)
    result = strategy.populate_exit_trend(result, metadata)
    return result


def series_mismatch(left: pd.Series, right: pd.Series) -> np.ndarray:
    if pd.api.types.is_numeric_dtype(left.dtype) and pd.api.types.is_numeric_dtype(right.dtype):
        return ~np.isclose(
            left.to_numpy(dtype=float, na_value=np.nan),
            right.to_numpy(dtype=float, na_value=np.nan),
            rtol=1e-12,
            atol=1e-12,
            equal_nan=True,
        )
    left_values = left.astype("string").fillna("<NA>").to_numpy()
    right_values = right.astype("string").fillna("<NA>").to_numpy()
    return left_values != right_values


def prefix_audit(data: pd.DataFrame, prefix_rows: int, extended_rows: int) -> dict[str, Any]:
    if extended_rows <= prefix_rows or len(data) < extended_rows:
        raise ValueError("extended_rows must exceed prefix_rows and fit inside data")
    prefix = compute(data.iloc[:prefix_rows])
    extended = compute(data.iloc[:extended_rows]).iloc[:prefix_rows]
    common_columns = sorted(set(prefix.columns) & set(extended.columns))
    column_mismatches: dict[str, int] = {}
    for column in common_columns:
        count = int(series_mismatch(prefix[column], extended[column]).sum())
        if count:
            column_mismatches[column] = count
    return {
        "prefix_rows": prefix_rows,
        "extended_rows": extended_rows,
        "shared_columns": len(common_columns),
        "column_set_exactly_equal": set(prefix.columns) == set(extended.columns),
        "columns_with_mismatches": column_mismatches,
        "prefix_stable": not column_mismatches and set(prefix.columns) == set(extended.columns),
        "truth_status": "VERIFIZIERT"
        if not column_mismatches and set(prefix.columns) == set(extended.columns)
        else "NICHT VERIFIZIERT",
        "interpretation": "Appending future rows did not change any already-computed indicator or signal cell."
        if not column_mismatches
        else "At least one historical cell changed after future rows were appended.",
    }


def load_trades() -> list[dict[str, Any]]:
    archive_path = next((ROOT / "results/champion_historical_precision6").glob("*.zip"))
    with zipfile.ZipFile(archive_path) as archive:
        result_name = next(
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json") and not name.endswith(".meta.json")
        )
        return json.loads(archive.read(result_name))["strategy"]["ED8"]["trades"]


def signal_timing_audit(data: pd.DataFrame) -> dict[str, Any]:
    start = pd.Timestamp("2025-12-30 21:20:00", tz="UTC")
    end = pd.Timestamp("2026-05-01 00:00:00", tz="UTC")
    frame = data.loc[(data["date"] >= start) & (data["date"] < end)].reset_index(drop=True)
    signals = compute(frame).set_index("date", drop=False)
    trades = load_trades()
    checks: list[dict[str, Any]] = []
    for trade in trades:
        open_time = pd.Timestamp(trade["open_date"])
        signal_time = open_time - pd.Timedelta(minutes=1)
        signal_row = signals.loc[signal_time]
        open_row = signals.loc[open_time]
        signal_present = int(signal_row.get("enter_long", 0) or 0) == 1
        tag_matches = str(signal_row.get("enter_tag", "")) == str(trade.get("enter_tag", ""))
        execution_at_next_open = bool(
            np.isclose(float(trade["open_rate"]), float(open_row["open"]), rtol=0.0, atol=1e-9)
        )
        checks.append(
            {
                "trade_open": open_time.isoformat(),
                "signal_time": signal_time.isoformat(),
                "signal_present_previous_candle": signal_present,
                "enter_tag_matches": tag_matches,
                "execution_rate_equals_next_candle_open": execution_at_next_open,
                "signal_exit_collision": bool(
                    signal_present and int(signal_row.get("exit_long", 0) or 0) == 1
                ),
            }
        )

    entries = signals.get("enter_long", pd.Series(0, index=signals.index)).fillna(0).astype(int) == 1
    exits = signals.get("exit_long", pd.Series(0, index=signals.index)).fillna(0).astype(int) == 1
    collisions = entries & exits
    all_previous = all(item["signal_present_previous_candle"] for item in checks)
    all_tags = all(item["enter_tag_matches"] for item in checks)
    all_next_open = all(item["execution_rate_equals_next_candle_open"] for item in checks)
    return {
        "data_start": start.isoformat(),
        "data_end_exclusive": end.isoformat(),
        "trade_count": len(checks),
        "all_trades_have_previous_candle_signal": all_previous,
        "all_enter_tags_match_previous_candle": all_tags,
        "all_entries_execute_at_next_candle_open": all_next_open,
        "entry_signal_count": int(entries.sum()),
        "exit_signal_count": int(exits.sum()),
        "entry_exit_collision_count": int(collisions.sum()),
        "trade_level_collision_count": sum(item["signal_exit_collision"] for item in checks),
        "truth_status": "VERIFIZIERT" if all_previous and all_tags and all_next_open else "NICHT VERIFIZIERT",
        "checks_sha256": hashlib.sha256(
            json.dumps(checks, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
        "checks": checks,
        "scope_limit": "Verifies saved trades and engine candle timing on this dataset; it is not live fill evidence.",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prefix-rows", type=int, default=20_000)
    parser.add_argument("--extended-rows", type=int, default=24_000)
    args = parser.parse_args()
    data = pd.read_parquet(DATA_PATH)
    report = {
        "schema_version": 1,
        "data_sha256": hashlib.sha256(DATA_PATH.read_bytes()).hexdigest(),
        "strategy_sha256": hashlib.sha256(
            (STRATEGY_PATH / "ED8_V741_E001FastCapture10m08bp.py").read_bytes()
        ).hexdigest(),
        "prefix_causality": prefix_audit(data, args.prefix_rows, args.extended_rows),
        "same_candle_and_collision": signal_timing_audit(data),
    }
    report["truth_status"] = (
        "VERIFIZIERT"
        if report["prefix_causality"]["truth_status"] == "VERIFIZIERT"
        and report["same_candle_and_collision"]["truth_status"] == "VERIFIZIERT"
        else "NICHT VERIFIZIERT"
    )
    target = ROOT / "audit/runtime_signal_audit.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["truth_status"], "output": target.relative_to(ROOT).as_posix()}))
    return 0 if report["truth_status"] == "VERIFIZIERT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
