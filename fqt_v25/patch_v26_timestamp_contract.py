#!/usr/bin/env python3
"""Fail-closed runtime patch for the FQT V25 extended-data/OOS contract.

Repairs pandas-resolution-dependent timestamp conversion, normalizes Binance
archive timestamps to microseconds, and extends the one-shot data/OOS horizon
through 2026-08-14 (timerange end 2026-08-15, exclusive).
"""
from __future__ import annotations

from pathlib import Path

PREPARE = Path("fqt_v25/prepare_extended_data.py")
RUNNER = Path("fqt_v25/run_v25.sh")
MARKER = "FQT_V26_TIMESTAMP_NORMALIZATION_V1"


def replace_exact(text: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = text.count(old)
    if count == expected:
        return text.replace(old, new)
    if count == 0 and text.count(new) == expected:
        return text
    raise SystemExit(f"{label}: expected exactly {expected} anchors, found {count}")


def patch_prepare() -> None:
    text = PREPARE.read_text(encoding="utf-8")
    if MARKER not in text:
        helper = f'''\n\n# {MARKER}\ndef normalize_epoch_us(series: pd.Series, label: str) -> pd.Series:\n    """Normalize epoch timestamps in seconds/ms/us/ns to signed microseconds.\n\n    Binance Vision changed timestamp precision, while pandas may expose a\n    datetime column as ms, us, or ns depending on its version and parquet\n    metadata. Magnitude detection plus a 2000-2100 range invariant prevents\n    silent mixed-unit joins.\n    """\n    values = pd.to_numeric(series, errors="raise").astype("int64")\n    if values.empty:\n        return values\n    absolute = values.abs()\n    maximum = int(absolute.max())\n    if maximum >= 10**17:       # nanoseconds\n        normalized = values // 1_000\n    elif maximum >= 10**14:     # microseconds\n        normalized = values\n    elif maximum >= 10**11:     # milliseconds\n        normalized = values * 1_000\n    elif maximum >= 10**9:      # seconds\n        normalized = values * 1_000_000\n    else:\n        raise RuntimeError(f"{{label}}: unsupported epoch magnitude {{maximum}}")\n    lower = 946_684_800_000_000      # 2000-01-01 UTC in us\n    upper = 4_102_444_800_000_000    # 2100-01-01 UTC in us\n    if int(normalized.min()) < lower or int(normalized.max()) >= upper:\n        raise RuntimeError(\n            f"{{label}}: mixed/invalid timestamp units after normalization "\n            f"min={{int(normalized.min())}} max={{int(normalized.max())}}"\n        )\n    return normalized.astype("int64")\n\n\ndef datetime_to_epoch_us(series: pd.Series, label: str) -> pd.Series:\n    dates = pd.to_datetime(series, utc=True, errors="raise")\n    epoch = pd.Timestamp("1970-01-01T00:00:00Z")\n    values = ((dates - epoch).dt.total_seconds() * 1_000_000).round().astype("int64")\n    return normalize_epoch_us(values, label)\n'''
        text = replace_exact(text, "\n\ndef sha256(", helper + "\n\ndef sha256(", "helper insertion")

    text = replace_exact(
        text,
        "DAILY_END = date(2026, 8, 10)",
        "DAILY_END = date(2026, 8, 14)",
        "daily horizon",
    )
    text = replace_exact(
        text,
        '    for column in ["open_time", "close_time", "trades"]:\n'
        '        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")',
        '    frame["open_time"] = normalize_epoch_us(frame["open_time"], f"{path.name}:open_time")\n'
        '    frame["close_time"] = normalize_epoch_us(frame["close_time"], f"{path.name}:close_time")\n'
        '    frame["trades"] = pd.to_numeric(frame["trades"], errors="raise").astype("int64")',
        "archive timestamp normalization",
    )
    text = replace_exact(
        text,
        '        existing["date"] = pd.to_datetime(existing["date"], utc=True)\n'
        '        existing["open_time"] = existing["date"].astype("int64") // 1000',
        '        existing["date"] = pd.to_datetime(existing["date"], utc=True, errors="raise")\n'
        '        existing["open_time"] = datetime_to_epoch_us(existing["date"], f"{pair}:existing_date")',
        "existing parquet timestamp normalization",
    )
    text = replace_exact(
        text,
        '        last_expected = int(pd.Timestamp("2026-08-10T23:59:00Z").timestamp() * 1_000_000)',
        '        last_expected = int(pd.Timestamp("2026-08-14T23:59:00Z").timestamp() * 1_000_000)',
        "combined data horizon",
    )
    PREPARE.write_text(text, encoding="utf-8")


def patch_runner() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    text = replace_exact(text, "20260623-20260811", "20260623-20260815", "OOS timerange", expected=2)
    text = replace_exact(text, "20260101-20260811", "20260101-20260815", "full timerange", expected=2)
    RUNNER.write_text(text, encoding="utf-8")


def main() -> None:
    patch_prepare()
    patch_runner()
    compile(PREPARE.read_text(encoding="utf-8"), str(PREPARE), "exec")
    print(f"{MARKER}: PASS")
    print("data_end=2026-08-14T23:59:00Z oos_end_exclusive=2026-08-15")


if __name__ == "__main__":
    main()
