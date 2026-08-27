#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import pathlib
import re
import shutil
import statistics
import time
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")
MONTHS = ("2026-05", "2026-06", "2026-07")
DAILY_START = date(2026, 8, 1)
DAILY_END = date(2026, 8, 10)
STEP_US = 60_000_000
COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
]


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, out: pathlib.Path, retries: int = 6) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size:
        return
    last: Exception | None = None
    for attempt in range(retries):
        tmp = out.with_suffix(out.suffix + ".part")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "FQT-V25-OOS50/2.0"})
            with urllib.request.urlopen(req, timeout=90) as response, tmp.open("wb") as target:
                if getattr(response, "status", 200) != 200:
                    raise RuntimeError(f"HTTP {getattr(response, 'status', None)}")
                shutil.copyfileobj(response, target, 1 << 20)
            if not tmp.stat().st_size:
                raise RuntimeError("empty remote object")
            tmp.replace(out)
            return
        except Exception as exc:
            last = exc
            tmp.unlink(missing_ok=True)
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {403, 404}:
                break
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 20))
    raise RuntimeError(f"download failed {url}: {last!r}")


def checksum(path: pathlib.Path, archive_name: str) -> str:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError(f"checksum line count {path}: {len(lines)}")
    match = CHECKSUM_RE.match(lines[0])
    if not match:
        raise RuntimeError(f"invalid checksum format {path}")
    if pathlib.Path(match.group(2)).name != archive_name:
        raise RuntimeError(f"checksum filename mismatch {path}: {match.group(2)!r}")
    return match.group(1).lower()


def period_bounds(period: str, kind: str) -> tuple[int, int, int]:
    if kind == "monthly":
        year, month = map(int, period.split("-"))
        days = calendar.monthrange(year, month)[1]
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        rows = days * 1440
    else:
        day = date.fromisoformat(period)
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        rows = 1440
    first_us = int(start.timestamp() * 1_000_000)
    last_us = first_us + (rows - 1) * STEP_US
    return first_us, last_us, rows


def compress_missing(values: list[int]) -> list[dict[str, object]]:
    if not values:
        return []
    ordered = sorted(set(int(value) for value in values))
    ranges: list[dict[str, object]] = []
    start = previous = ordered[0]
    for value in ordered[1:]:
        if value != previous + STEP_US:
            ranges.append({
                "start": pd.to_datetime(start, unit="us", utc=True).isoformat(),
                "end": pd.to_datetime(previous, unit="us", utc=True).isoformat(),
                "minutes": int((previous - start) // STEP_US + 1),
            })
            start = value
        previous = value
    ranges.append({
        "start": pd.to_datetime(start, unit="us", utc=True).isoformat(),
        "end": pd.to_datetime(previous, unit="us", utc=True).isoformat(),
        "minutes": int((previous - start) // STEP_US + 1),
    })
    return ranges


def missing_open_times(open_times: np.ndarray, first_us: int, last_us: int) -> list[int]:
    values = np.asarray(open_times, dtype="int64")
    if values.size == 0:
        return list(range(first_us, last_us + STEP_US, STEP_US))
    missing: list[int] = []
    if values[0] > first_us:
        missing.extend(range(first_us, int(values[0]), STEP_US))
    for left, right in zip(values[:-1], values[1:]):
        delta = int(right - left)
        if delta > STEP_US:
            missing.extend(range(int(left + STEP_US), int(right), STEP_US))
    if values[-1] < last_us:
        missing.extend(range(int(values[-1] + STEP_US), last_us + STEP_US, STEP_US))
    return missing


def read_archive(path: pathlib.Path, period: str, kind: str) -> tuple[pd.DataFrame, dict[str, object]]:
    first_us, last_us, expected_rows = period_bounds(period, kind)
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f"zip CRC error {path}: {bad}")
        members = [name for name in zf.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise RuntimeError(f"zip member count {path}: {members}")
        with zf.open(members[0]) as handle:
            frame = pd.read_csv(handle, header=None, names=COLS)
    if frame.empty or len(frame) > expected_rows:
        raise RuntimeError(f"row count {path.name}: maximum {expected_rows}, got {len(frame)}")
    for column in ["open_time", "close_time", "trades"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    for column in ["open", "high", "low", "close", "volume", "quote_volume", "taker_base", "taker_quote"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
    frame = frame.sort_values("open_time").reset_index(drop=True)
    if frame["open_time"].duplicated().any():
        raise RuntimeError(f"duplicate timestamps in {path.name}")
    if int(frame["open_time"].iloc[0]) < first_us or int(frame["open_time"].iloc[-1]) > last_us:
        raise RuntimeError(f"timestamp outside period in {path.name}")
    if (np.diff(frame["open_time"].to_numpy(dtype="int64")) <= 0).any():
        raise RuntimeError(f"non-monotonic timestamps in {path.name}")
    if not (frame["close_time"] == frame["open_time"] + 59_999_999).all():
        raise RuntimeError(f"invalid close_time contract in {path.name}")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError(f"non-positive OHLC in {path.name}")
    if (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any():
        raise RuntimeError(f"impossible high in {path.name}")
    if (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any():
        raise RuntimeError(f"impossible low in {path.name}")
    if (frame[["volume", "quote_volume", "taker_base", "taker_quote"]] < 0).any().any():
        raise RuntimeError(f"negative volume in {path.name}")
    missing = missing_open_times(frame["open_time"].to_numpy(dtype="int64"), first_us, last_us)
    diagnostics = {
        "expected_rows": expected_rows,
        "actual_rows": int(len(frame)),
        "missing_minutes": int(len(missing)),
        "missing_ranges": compress_missing(missing),
        "missing_open_times": missing,
    }
    return frame, diagnostics


def archive_descriptor(symbol: str, period: str, kind: str, raw: pathlib.Path) -> tuple[str, pathlib.Path, pathlib.Path]:
    name = f"{symbol}-1m-{period}.zip"
    url = f"https://data.binance.vision/data/spot/{kind}/klines/{symbol}/1m/{name}"
    directory = raw / symbol
    return url, directory / name, directory / f"{name}.CHECKSUM"


def acquire_archive(symbol: str, period: str, kind: str, raw: pathlib.Path) -> tuple[pd.DataFrame, dict[str, object]]:
    url, archive_path, checksum_path = archive_descriptor(symbol, period, kind, raw)
    download(url + ".CHECKSUM", checksum_path)
    download(url, archive_path)
    official = checksum(checksum_path, archive_path.name)
    actual = sha256(archive_path)
    if official != actual:
        raise RuntimeError(f"sha256 mismatch {archive_path.name}: {actual} != {official}")
    frame, diagnostics = read_archive(archive_path, period, kind)
    receipt = {
        "period": period,
        "kind": kind,
        "archive": archive_path.name,
        "sha256": actual,
        "bytes": archive_path.stat().st_size,
        **{key: value for key, value in diagnostics.items() if key != "missing_open_times"},
    }
    return frame, receipt | {"_missing_open_times": diagnostics["missing_open_times"]}


def repair_month_from_daily(symbol: str, period: str, frame: pd.DataFrame, receipt: dict[str, object], raw: pathlib.Path) -> tuple[pd.DataFrame, dict[str, object], list[int]]:
    missing = [int(value) for value in receipt.pop("_missing_open_times", [])]
    if not missing:
        receipt.update({"repair_status": "NOT_REQUIRED", "repaired_minutes": 0, "official_gap_minutes": 0})
        return frame, receipt, []
    missing_days = sorted({pd.to_datetime(value, unit="us", utc=True).date().isoformat() for value in missing})
    daily_frames: list[pd.DataFrame] = []
    daily_receipts: list[dict[str, object]] = []
    daily_available: set[int] = set()
    for day in missing_days:
        daily_frame, daily_receipt = acquire_archive(symbol, day, "daily", raw)
        daily_missing = [int(value) for value in daily_receipt.pop("_missing_open_times", [])]
        daily_receipt["official_missing_minutes"] = len(daily_missing)
        daily_frames.append(daily_frame)
        daily_receipts.append(daily_receipt)
        daily_available.update(map(int, daily_frame["open_time"].to_numpy(dtype="int64")))
    repaired = sorted(value for value in missing if value in daily_available)
    official_gaps = sorted(value for value in missing if value not in daily_available)
    if repaired:
        candidates = pd.concat(daily_frames, ignore_index=True)
        candidates = candidates[candidates["open_time"].isin(repaired)]
        frame = pd.concat([frame, candidates], ignore_index=True)
        frame = frame.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
    receipt.update({
        "repair_status": "REPAIRED_FROM_OFFICIAL_DAILY" if repaired and not official_gaps else ("OFFICIAL_GAP_RETAINED" if official_gaps else "NOT_REQUIRED"),
        "repaired_minutes": len(repaired),
        "official_gap_minutes": len(official_gaps),
        "official_gap_ranges": compress_missing(official_gaps),
        "daily_cross_checks": daily_receipts,
        "actual_rows_after_daily_repair": int(len(frame)),
    })
    return frame, receipt, official_gaps


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--datadir", type=pathlib.Path, required=True)
    parser.add_argument("--raw", type=pathlib.Path, required=True)
    parser.add_argument("--manifest", type=pathlib.Path, required=True)
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    pairs = list(config["exchange"]["pair_whitelist"])
    args.datadir.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []

    daily_periods: list[str] = []
    cursor = DAILY_START
    while cursor <= DAILY_END:
        daily_periods.append(cursor.isoformat())
        cursor += timedelta(days=1)

    for pair in pairs:
        symbol = pair.replace("/", "")
        existing_path = args.datadir / f"{pair.replace('/', '_')}-1m.parquet"
        if not existing_path.exists():
            raise FileNotFoundError(existing_path)
        existing = pd.read_parquet(existing_path)
        if "date" not in existing.columns:
            raise RuntimeError(f"missing date column {existing_path}")
        existing["date"] = pd.to_datetime(existing["date"], utc=True)
        existing["open_time"] = existing["date"].astype("int64") // 1000
        if "quote_volume" not in existing.columns:
            existing["quote_volume"] = np.nan
        chunks = [existing[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].copy()]
        archive_receipts: list[dict[str, object]] = []
        official_gap_times: set[int] = set()

        for period in MONTHS:
            frame, receipt = acquire_archive(symbol, period, "monthly", args.raw)
            frame, receipt, official_gaps = repair_month_from_daily(symbol, period, frame, receipt, args.raw)
            official_gap_times.update(official_gaps)
            chunks.append(frame[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].copy())
            archive_receipts.append(receipt)

        for period in daily_periods:
            frame, receipt = acquire_archive(symbol, period, "daily", args.raw)
            daily_missing = [int(value) for value in receipt.pop("_missing_open_times", [])]
            receipt.update({
                "repair_status": "OFFICIAL_GAP_RETAINED" if daily_missing else "NOT_REQUIRED",
                "official_gap_minutes": len(daily_missing),
                "official_gap_ranges": compress_missing(daily_missing),
            })
            official_gap_times.update(daily_missing)
            chunks.append(frame[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].copy())
            archive_receipts.append(receipt)

        combined = pd.concat(chunks, ignore_index=True)
        combined = combined.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
        open_times = combined["open_time"].to_numpy(dtype="int64")
        duplicates = int(len(open_times) - len(set(map(int, open_times))))
        first_expected = int(pd.Timestamp("2025-12-01T00:00:00Z").timestamp() * 1_000_000)
        last_expected = int(pd.Timestamp("2026-08-10T23:59:00Z").timestamp() * 1_000_000)
        missing_combined = missing_open_times(open_times, first_expected, last_expected)
        unresolved = sorted(value for value in missing_combined if value not in official_gap_times)
        official_retained = sorted(value for value in missing_combined if value in official_gap_times)
        if duplicates or unresolved or open_times[0] != first_expected or open_times[-1] != last_expected:
            raise RuntimeError(
                f"invariant {pair}: duplicates={duplicates} unresolved_missing={len(unresolved)} "
                f"first={open_times[0]} expected={first_expected} last={open_times[-1]} expected_last={last_expected}"
            )

        out = pd.DataFrame({
            "date": pd.to_datetime(combined["open_time"], unit="us", utc=True),
            "open": combined["open"].astype(float),
            "high": combined["high"].astype(float),
            "low": combined["low"].astype(float),
            "close": combined["close"].astype(float),
            "volume": combined["volume"].astype(float),
        })
        out.to_parquet(existing_path, index=False)
        quote = pd.to_numeric(combined["quote_volume"], errors="coerce").dropna()
        record: dict[str, object] = {
            "pair": pair,
            "rows": len(out),
            "first": out["date"].iloc[0].isoformat(),
            "last": out["date"].iloc[-1].isoformat(),
            "unresolved_gap_minutes": len(unresolved),
            "official_gap_minutes": len(official_retained),
            "official_gap_ranges": compress_missing(official_retained),
            "duplicates": duplicates,
            "research_eligible": True,
            "execution_eligible": not official_retained,
            "zero_volume_ratio": float((out["volume"] == 0).mean()),
            "median_quote_volume": float(statistics.median(quote)) if len(quote) else None,
            "parquet": str(existing_path),
            "parquet_sha256": sha256(existing_path),
            "archives_added": archive_receipts,
        }
        records.append(record)
        print(json.dumps({
            "pair": pair,
            "rows": record["rows"],
            "official_gap_minutes": record["official_gap_minutes"],
            "execution_eligible": record["execution_eligible"],
            "sha256": record["parquet_sha256"],
        }), flush=True)

    leaf = [{"pair": row["pair"], "sha256": row["parquet_sha256"], "rows": row["rows"]} for row in records]
    ineligible = [str(row["pair"]) for row in records if not bool(row["execution_eligible"])]
    manifest = {
        "contract": "FQT_V25_EXTENDED_DATASET_20251201_20260810_V2",
        "source": "official Binance monthly/daily klines plus CHECKSUM",
        "missing_candle_policy": "never synthesize; repair monthly omissions only from checksummed daily archives; retain corroborated exchange-native gaps",
        "pair_count": len(records),
        "development_range": "[2026-01-01,2026-06-23)",
        "fresh_oos_range": "[2026-06-23,2026-08-11)",
        "fresh_oos_opened_for_alpha": False,
        "integrity_pass": all(int(row["unresolved_gap_minutes"]) == 0 and int(row["duplicates"]) == 0 for row in records),
        "all_execution_eligible": not ineligible,
        "execution_ineligible_pairs": ineligible,
        "total_official_gap_minutes": sum(int(row["official_gap_minutes"]) for row in records),
        "records": records,
        "dataset_root_sha256": hashlib.sha256(
            json.dumps(leaf, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "pair_count": len(records),
        "integrity_pass": manifest["integrity_pass"],
        "all_execution_eligible": manifest["all_execution_eligible"],
        "execution_ineligible_pairs": ineligible,
        "total_official_gap_minutes": manifest["total_official_gap_minutes"],
        "dataset_root_sha256": manifest["dataset_root_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
