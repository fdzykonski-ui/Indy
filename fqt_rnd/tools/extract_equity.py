#!/usr/bin/env python3
"""Extract bounded daily equity curves from Freqtrade wallet feathers."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "Champion V741": ("results/champion_common_full", "ED8"),
    "Cash": ("results/baselines_full_development", "CashBaseline"),
    "Buy-and-hold": ("results/baselines_full_development", "BuyHoldBaseline"),
}


def portfolio_equity(frame: pd.DataFrame) -> pd.DataFrame:
    """Aggregate Freqtrade's per-currency wallet rows to one row per minute."""

    required = {"date", "currency", "total_quote"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"wallet feather missing columns: {sorted(missing)}")
    duplicates = frame.duplicated(["date", "currency"])
    if duplicates.any():
        raise ValueError("wallet feather has duplicate timestamp/currency rows")
    return (
        frame.sort_values(["date", "currency"], kind="stable")
        .groupby("date", as_index=False, sort=True)["total_quote"]
        .sum()
    )


def daily_curve(directory: str, strategy: str) -> list[dict[str, object]]:
    archive_path = next((ROOT / directory).glob("*.zip"))
    with zipfile.ZipFile(archive_path) as archive:
        member = next(name for name in archive.namelist() if name.endswith(f"_{strategy}_wallet.feather"))
        frame = pd.read_feather(io.BytesIO(archive.read(member)))
    frame = frame.sort_values("date").copy()
    # Freqtrade emits one wallet row per currency at each timestamp.  A
    # portfolio-equity observation is therefore the sum of all currency rows,
    # not whichever currency happens to be last in the feather ordering.
    minute = portfolio_equity(frame)
    minute["day"] = minute["date"].dt.floor("D")
    daily = minute.groupby("day", as_index=False).tail(1)
    return [
        {
            "date": row.day.date().isoformat(),
            "equity_usdc": float(row.total_quote),
            "source_archive": archive_path.relative_to(ROOT).as_posix(),
        }
        for row in daily.itertuples(index=False)
    ]


def main() -> int:
    rows: list[dict[str, object]] = []
    for label, (directory, strategy) in SOURCES.items():
        for row in daily_curve(directory, strategy):
            rows.append({"strategy": label, **row})
    target_dir = ROOT / "results/summaries"
    target_dir.mkdir(parents=True, exist_ok=True)
    with (target_dir / "daily_equity.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "strategy", "equity_usdc", "source_archive"])
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: (str(row["date"]), str(row["strategy"]))))
    summary = {
        "schema_version": 1,
        "grain": "last observed per-minute sum of all currency total_quote values per UTC calendar day",
        "rows": len(rows),
        "series": {
            label: {
                "observations": len(series := [row for row in rows if row["strategy"] == label]),
                "first_equity_usdc": series[0]["equity_usdc"],
                "last_equity_usdc": series[-1]["equity_usdc"],
            }
            for label in SOURCES
        },
        "truth_status": "VERIFIZIERT",
        "scope_limit": "Backtest wallet equity is simulated and is not exchange-account equity.",
    }
    (target_dir / "daily_equity_summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rows": len(rows), "series": len(SOURCES), "status": "VERIFIZIERT"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
