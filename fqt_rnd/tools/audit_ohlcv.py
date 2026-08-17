#!/usr/bin/env python3
"""Deterministic OHLCV integrity checks for one-minute Freqtrade parquet data."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd


REQUIRED_COLUMNS = ["date", "open", "high", "low", "close", "volume"]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.read_parquet(args.input)
    present = list(frame.columns)
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(present))
    if missing_columns:
        raise ValueError(f"missing required columns: {missing_columns}")

    frame = frame[REQUIRED_COLUMNS].copy()
    frame["date"] = pd.to_datetime(frame["date"], utc=True)
    frame = frame.sort_values("date", kind="stable").reset_index(drop=True)
    row_count = int(len(frame))
    sha = file_sha256(args.input)

    deltas = frame["date"].diff().dropna()
    gaps = frame.loc[deltas[deltas > pd.Timedelta(minutes=1)].index, ["date"]].copy()
    if not gaps.empty:
        gap_indices = gaps.index
        gaps["previous_date"] = frame.loc[gap_indices - 1, "date"].to_numpy()
        gaps["missing_minutes"] = (
            (gaps["date"] - gaps["previous_date"]) / pd.Timedelta(minutes=1) - 1
        ).astype("int64")
        gaps = gaps[["previous_date", "date", "missing_minutes"]]
    else:
        gaps = pd.DataFrame(columns=["previous_date", "date", "missing_minutes"])

    high_valid = frame["high"] >= frame[["open", "close", "low"]].max(axis=1)
    low_valid = frame["low"] <= frame[["open", "close", "high"]].min(axis=1)
    positive_prices = (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
    nonnegative_volume = frame["volume"] >= 0
    minute_aligned = (
        (frame["date"].dt.second == 0)
        & (frame["date"].dt.microsecond == 0)
        & (frame["date"].dt.nanosecond == 0)
    )

    per_day = frame.assign(day=frame["date"].dt.floor("D")).groupby("day").size()
    daily = per_day.rename("candles").reset_index()
    daily["complete_1440"] = daily["candles"] == 1440

    first = frame["date"].iloc[0] if row_count else None
    last = frame["date"].iloc[-1] if row_count else None
    expected_rows = (
        int((last - first) / pd.Timedelta(minutes=1)) + 1 if row_count else 0
    )
    null_counts = {key: int(value) for key, value in frame.isna().sum().items()}
    summary = {
        "status": "VERIFIZIERT",
        "dataset": str(args.input),
        "grain": "one row per BTC/USDC UTC minute",
        "sha256": sha,
        "expected_sha256": args.expected_sha256,
        "hash_matches_contract": (
            sha == args.expected_sha256 if args.expected_sha256 is not None else None
        ),
        "row_count": row_count,
        "column_count": len(present),
        "columns": present,
        "dtypes": {key: str(value) for key, value in frame.dtypes.items()},
        "first_timestamp_utc": first.isoformat() if first is not None else None,
        "last_timestamp_utc": last.isoformat() if last is not None else None,
        "expected_contiguous_rows": expected_rows,
        "missing_minutes": int(gaps["missing_minutes"].sum()) if not gaps.empty else 0,
        "gap_count": int(len(gaps)),
        "duplicate_timestamps": int(frame["date"].duplicated().sum()),
        "exact_duplicate_rows": int(frame.duplicated().sum()),
        "monotonic_increasing": bool(frame["date"].is_monotonic_increasing),
        "minute_alignment_violations": int((~minute_aligned).sum()),
        "null_counts": null_counts,
        "nonpositive_price_rows": int((~positive_prices).sum()),
        "negative_volume_rows": int((~nonnegative_volume).sum()),
        "invalid_high_rows": int((~high_valid).sum()),
        "invalid_low_rows": int((~low_valid).sum()),
        "zero_volume_rows": int((frame["volume"] == 0).sum()),
        "complete_calendar_days": int(daily["complete_1440"].sum()),
        "partial_calendar_days": int((~daily["complete_1440"]).sum()),
        "source_provenance": {
            "status": "TEILWEISE VERIFIZIERT",
            "reason": "archive and file bytes are hashed; original exchange download command and immutable Binance snapshot identifier are absent"
        },
        "survivorship_audit": {
            "status": "BLOCKIERT",
            "reason": "only BTC/USDC is present; historical exchange universe/listing metadata is absent"
        },
    }

    hard_fail_fields = [
        summary["hash_matches_contract"] is False,
        summary["missing_minutes"] > 0,
        summary["duplicate_timestamps"] > 0,
        any(null_counts.values()),
        summary["nonpositive_price_rows"] > 0,
        summary["negative_volume_rows"] > 0,
        summary["invalid_high_rows"] > 0,
        summary["invalid_low_rows"] > 0,
    ]
    if any(hard_fail_fields):
        summary["status"] = "TEILWEISE VERIFIZIERT"

    (args.output_dir / "ohlcv_quality_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    gaps.to_csv(args.output_dir / "ohlcv_gaps.csv", index=False)
    daily.to_csv(args.output_dir / "ohlcv_daily_counts.csv", index=False)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["status"] == "VERIFIZIERT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
