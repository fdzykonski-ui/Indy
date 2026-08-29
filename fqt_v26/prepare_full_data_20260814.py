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
from typing import Iterable

import numpy as np
import pandas as pd

CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")
MONTHS = ("2026-05", "2026-06", "2026-07")
DAILY_START = date(2026, 8, 1)
DAILY_END = date(2026, 8, 14)
STEP_US = 60_000_000
COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "trades", "taker_base", "taker_quote", "ignore",
]


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def normalize_epoch_to_us(values: Iterable[int] | pd.Series | np.ndarray, *, label: str) -> np.ndarray:
    """Normalize epoch timestamps in seconds/ms/us/ns to integer microseconds.

    Pandas 2.x and 3.x preserve different datetime resolutions when converting
    timezone-aware series to int64. Binance public data also changed kline
    timestamp precision from milliseconds to microseconds. Unit inference is
    therefore performed per value rather than assuming one library/source unit.
    """
    raw = pd.to_numeric(pd.Series(values), errors="raise").astype("int64").to_numpy(copy=True)
    if raw.size == 0:
        return raw
    magnitude = np.abs(raw)
    if (magnitude < 100_000_000).any():
        raise RuntimeError(f"{label}: implausibly small/zero epoch timestamp")
    seconds = magnitude < 100_000_000_000
    milliseconds = (magnitude >= 100_000_000_000) & (magnitude < 100_000_000_000_000)
    microseconds = (magnitude >= 100_000_000_000_000) & (magnitude < 100_000_000_000_000_000)
    nanoseconds = magnitude >= 100_000_000_000_000_000
    result = raw.copy()
    result[seconds] *= 1_000_000
    result[milliseconds] *= 1_000
    result[microseconds] = raw[microseconds]
    result[nanoseconds] //= 1_000
    normalized = np.abs(result)
    if (normalized < 1_000_000_000_000_000).any() or (normalized > 10_000_000_000_000_000).any():
        lo, hi = int(normalized.min()), int(normalized.max())
        raise RuntimeError(f"{label}: normalized timestamp outside supported epoch range: {lo}..{hi}")
    return result.astype("int64", copy=False)


def download(url: str, out: pathlib.Path, retries: int = 6) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists() and out.stat().st_size:
        return
    last: Exception | None = None
    for attempt in range(retries):
        tmp = out.with_suffix(out.suffix + ".part")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "FQT-V29-DATA-CAPA/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response, tmp.open("wb") as target:
                status = int(getattr(response, "status", 200))
                if status != 200:
                    raise RuntimeError(f"HTTP {status}")
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
                time.sleep(min(2**attempt, 20))
    raise RuntimeError(f"download failed {url}: {last!r}")


def expected_checksum(path: pathlib.Path, archive_name: str) -> str:
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) != 1:
        raise RuntimeError(f"checksum line count {path}: {len(lines)}")
    match = CHECKSUM_RE.match(lines[0])
    if not match or pathlib.Path(match.group(2)).name != archive_name:
        raise RuntimeError(f"invalid checksum {path}: {lines[0]!r}")
    return match.group(1).lower()


def period_bounds(period: str, kind: str) -> tuple[int, int, int]:
    if kind == "monthly":
        year, month = map(int, period.split("-"))
        rows = calendar.monthrange(year, month)[1] * 1440
        start = datetime(year, month, 1, tzinfo=timezone.utc)
    elif kind == "daily":
        day = date.fromisoformat(period)
        rows = 1440
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    else:
        raise ValueError(f"unsupported archive kind: {kind}")
    first_us = int(start.timestamp() * 1_000_000)
    return first_us, first_us + (rows - 1) * STEP_US, rows


def compress_missing(values: Iterable[int]) -> list[dict[str, object]]:
    ordered = sorted(set(int(value) for value in values))
    if not ordered:
        return []
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
    if int(values[0]) > first_us:
        missing.extend(range(first_us, int(values[0]), STEP_US))
    for left, right in zip(values[:-1], values[1:]):
        delta = int(right - left)
        if delta > STEP_US:
            missing.extend(range(int(left + STEP_US), int(right), STEP_US))
        elif delta <= 0:
            raise RuntimeError("timestamps are not strictly increasing")
    if int(values[-1]) < last_us:
        missing.extend(range(int(values[-1] + STEP_US), last_us + STEP_US, STEP_US))
    return missing


def validate_ohlcv(frame: pd.DataFrame, *, label: str) -> None:
    if frame.empty:
        raise RuntimeError(f"{label}: empty frame")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError(f"{label}: non-positive OHLC")
    if (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any():
        raise RuntimeError(f"{label}: impossible high")
    if (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any():
        raise RuntimeError(f"{label}: impossible low")
    if (frame[["volume", "quote_volume"]] < 0).any().any():
        raise RuntimeError(f"{label}: negative volume")


def parse_archive(path: pathlib.Path, period: str, kind: str) -> tuple[pd.DataFrame, dict[str, object]]:
    first_us, last_us, expected_rows = period_bounds(period, kind)
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise RuntimeError(f"CRC error {path}: {bad}")
        members = [name for name in archive.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise RuntimeError(f"archive member count {path}: {members}")
        with archive.open(members[0]) as handle:
            frame = pd.read_csv(handle, header=None, names=COLS)
    if frame.shape[1] != 12 or frame.empty or len(frame) > expected_rows:
        raise RuntimeError(
            f"archive schema {path.name}: rows={len(frame)} cols={frame.shape[1]} max={expected_rows}/12"
        )
    for column in ["open_time", "close_time", "trades"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    for column in ["open", "high", "low", "close", "volume", "quote_volume", "taker_base", "taker_quote"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
    frame["open_time"] = normalize_epoch_to_us(frame["open_time"], label=f"{path.name}:open_time")
    frame["close_time"] = normalize_epoch_to_us(frame["close_time"], label=f"{path.name}:close_time")
    frame = frame.sort_values("open_time").reset_index(drop=True)
    if frame["open_time"].duplicated().any():
        raise RuntimeError(f"duplicate timestamps in {path.name}")
    if int(frame["open_time"].iloc[0]) < first_us or int(frame["open_time"].iloc[-1]) > last_us:
        raise RuntimeError(f"timestamp outside requested period in {path.name}")
    close_delta = frame["close_time"] - frame["open_time"]
    valid_delta = close_delta.isin([59_999_000, 59_999_999])
    if not valid_delta.all():
        sample = sorted(set(map(int, close_delta[~valid_delta].head(10))))
        raise RuntimeError(f"invalid close_time delta in {path.name}: {sample}")
    validate_ohlcv(frame, label=path.name)
    missing = missing_open_times(frame["open_time"].to_numpy(dtype="int64"), first_us, last_us)
    return frame, {
        "expected_rows": expected_rows,
        "actual_rows": int(len(frame)),
        "missing_minutes": int(len(missing)),
        "missing_ranges": compress_missing(missing),
        "missing_open_times": missing,
    }


def archive_descriptor(
    symbol: str, period: str, kind: str, raw: pathlib.Path
) -> tuple[str, pathlib.Path, pathlib.Path]:
    name = f"{symbol}-1m-{period}.zip"
    base = f"https://data.binance.vision/data/spot/{kind}/klines/{symbol}/1m/{name}"
    directory = raw / symbol
    return base, directory / name, directory / f"{name}.CHECKSUM"


def acquire_archive(
    symbol: str, period: str, kind: str, raw: pathlib.Path
) -> tuple[pd.DataFrame, dict[str, object], list[int]]:
    base, archive_path, checksum_path = archive_descriptor(symbol, period, kind, raw)
    download(base + ".CHECKSUM", checksum_path)
    download(base, archive_path)
    official = expected_checksum(checksum_path, archive_path.name)
    actual = sha256(archive_path)
    if actual != official:
        raise RuntimeError(f"hash mismatch {archive_path.name}: {actual} != {official}")
    frame, diagnostics = parse_archive(archive_path, period, kind)
    missing = [int(value) for value in diagnostics.pop("missing_open_times")]
    return frame, {
        "period": period,
        "kind": kind,
        "archive": archive_path.name,
        "rows": len(frame),
        "sha256": actual,
        "bytes": archive_path.stat().st_size,
        **diagnostics,
    }, missing


def repair_month_from_daily(
    symbol: str,
    period: str,
    frame: pd.DataFrame,
    receipt: dict[str, object],
    monthly_missing: list[int],
    raw: pathlib.Path,
) -> tuple[pd.DataFrame, dict[str, object], list[int]]:
    if not monthly_missing:
        receipt.update({"repair_status": "NOT_REQUIRED", "repaired_minutes": 0, "official_gap_minutes": 0})
        return frame, receipt, []
    days = sorted({pd.to_datetime(value, unit="us", utc=True).date().isoformat() for value in monthly_missing})
    daily_frames: list[pd.DataFrame] = []
    daily_receipts: list[dict[str, object]] = []
    daily_available: set[int] = set()
    for day in days:
        daily_frame, daily_receipt, daily_missing = acquire_archive(symbol, day, "daily", raw)
        daily_receipt["official_missing_minutes"] = len(daily_missing)
        daily_frames.append(daily_frame)
        daily_receipts.append(daily_receipt)
        daily_available.update(map(int, daily_frame["open_time"].to_numpy(dtype="int64")))
    repaired = sorted(value for value in monthly_missing if value in daily_available)
    official_gaps = sorted(value for value in monthly_missing if value not in daily_available)
    if repaired:
        candidates = pd.concat(daily_frames, ignore_index=True)
        candidates = candidates[candidates["open_time"].isin(repaired)]
        frame = pd.concat([frame, candidates], ignore_index=True)
        frame = frame.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
    receipt.update({
        "repair_status": (
            "REPAIRED_FROM_OFFICIAL_DAILY" if repaired and not official_gaps
            else "OFFICIAL_GAP_RETAINED" if official_gaps
            else "NOT_REQUIRED"
        ),
        "repaired_minutes": len(repaired),
        "official_gap_minutes": len(official_gaps),
        "official_gap_ranges": compress_missing(official_gaps),
        "daily_cross_checks": daily_receipts,
        "actual_rows_after_daily_repair": int(len(frame)),
    })
    return frame, receipt, official_gaps


def prior_to_frame(prior: pd.DataFrame, *, path: pathlib.Path) -> pd.DataFrame:
    required = {"date", "open", "high", "low", "close", "volume"}
    missing = sorted(required - set(prior.columns))
    if missing:
        raise RuntimeError(f"{path}: missing columns {missing}")
    dates = pd.to_datetime(prior["date"], utc=True, errors="raise")
    date_ints = dates.astype("int64")
    open_time = normalize_epoch_to_us(date_ints, label=f"{path.name}:prior_date")
    frame = pd.DataFrame({
        "open_time": open_time,
        "open": pd.to_numeric(prior["open"], errors="raise").astype(float),
        "high": pd.to_numeric(prior["high"], errors="raise").astype(float),
        "low": pd.to_numeric(prior["low"], errors="raise").astype(float),
        "close": pd.to_numeric(prior["close"], errors="raise").astype(float),
        "volume": pd.to_numeric(prior["volume"], errors="raise").astype(float),
        "quote_volume": np.nan,
    })
    frame = frame.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
    validate_ohlcv(frame.assign(quote_volume=frame["quote_volume"].fillna(0)), label=path.name)
    return frame


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
    days: list[str] = []
    cursor = DAILY_START
    while cursor <= DAILY_END:
        days.append(cursor.isoformat())
        cursor += timedelta(days=1)

    first_expected = int(pd.Timestamp("2025-12-01T00:00:00Z").timestamp() * 1_000_000)
    last_expected = int(pd.Timestamp("2026-08-14T23:59:00Z").timestamp() * 1_000_000)

    for pair in pairs:
        symbol = pair.replace("/", "")
        output_path = args.datadir / f"{pair.replace('/', '_')}-1m.parquet"
        if not output_path.exists():
            raise FileNotFoundError(output_path)
        prior = pd.read_parquet(output_path)
        prior_frame = prior_to_frame(prior, path=output_path)
        chunks = [prior_frame]
        archive_receipts: list[dict[str, object]] = []
        official_gap_times: set[int] = set()

        for period in MONTHS:
            frame, receipt, monthly_missing = acquire_archive(symbol, period, "monthly", args.raw)
            frame, receipt, official_gaps = repair_month_from_daily(
                symbol, period, frame, receipt, monthly_missing, args.raw
            )
            official_gap_times.update(official_gaps)
            chunks.append(frame[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].copy())
            archive_receipts.append(receipt)

        for period in days:
            frame, receipt, daily_missing = acquire_archive(symbol, period, "daily", args.raw)
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
        times = combined["open_time"].to_numpy(dtype="int64")
        duplicates = int(len(times) - len(set(map(int, times))))
        missing_combined = missing_open_times(times, first_expected, last_expected)
        unresolved = sorted(value for value in missing_combined if value not in official_gap_times)
        official_retained = sorted(value for value in missing_combined if value in official_gap_times)
        boundary_ok = int(times[0]) == first_expected and int(times[-1]) == last_expected
        if duplicates or unresolved or not boundary_ok:
            raise RuntimeError(
                f"invariant {pair}: duplicates={duplicates} unresolved_missing={len(unresolved)} "
                f"first={times[0]} expected_first={first_expected} "
                f"last={times[-1]} expected_last={last_expected}"
            )

        out = pd.DataFrame({
            "date": pd.to_datetime(combined["open_time"], unit="us", utc=True),
            "open": combined["open"].astype(float),
            "high": combined["high"].astype(float),
            "low": combined["low"].astype(float),
            "close": combined["close"].astype(float),
            "volume": combined["volume"].astype(float),
        })
        out.to_parquet(output_path, index=False)
        quote = pd.to_numeric(combined["quote_volume"], errors="coerce").dropna()
        row: dict[str, object] = {
            "pair": pair,
            "rows": len(out),
            "expected_rows_if_gap_free": int((last_expected - first_expected) // STEP_US + 1),
            "first": out["date"].iloc[0].isoformat(),
            "last": out["date"].iloc[-1].isoformat(),
            "gaps": len(official_retained),
            "official_gap_minutes": len(official_retained),
            "official_gap_ranges": compress_missing(official_retained),
            "unresolved_gap_minutes": len(unresolved),
            "duplicates": duplicates,
            "research_eligible": True,
            "execution_eligible": not official_retained,
            "zero_volume_ratio": float((out["volume"] == 0).mean()),
            "median_quote_volume_1m_extended": float(statistics.median(quote)) if len(quote) else None,
            "parquet": str(output_path),
            "parquet_sha256": sha256(output_path),
            "archives_added": archive_receipts,
        }
        records.append(row)
        print(json.dumps({
            "pair": pair,
            "rows": row["rows"],
            "official_gap_minutes": row["official_gap_minutes"],
            "execution_eligible": row["execution_eligible"],
            "sha256": row["parquet_sha256"],
        }), flush=True)

    leaves = [{"pair": row["pair"], "sha256": row["parquet_sha256"], "rows": row["rows"]} for row in records]
    ineligible = [str(row["pair"]) for row in records if not bool(row["execution_eligible"])]
    manifest = {
        "contract": "FQT_V29_FULL_DATASET_20251201_20260814_V2",
        "source": "official Binance monthly/daily klines plus CHECKSUM",
        "timestamp_policy": "per-value epoch unit normalization to microseconds; seconds/ms/us/ns accepted",
        "missing_candle_policy": (
            "never synthesize; repair monthly omissions only from checksummed daily archives; "
            "retain and disclose corroborated exchange-native gaps"
        ),
        "pair_count": len(records),
        "timerange_available": "[2025-12-01,2026-08-15)",
        "development_range": "[2026-01-01,2026-06-23)",
        "sealed_oos_range": "[2026-06-23,2026-08-15)",
        "sealed_oos_opened_for_alpha": False,
        "integrity_pass": all(
            int(row["unresolved_gap_minutes"]) == 0 and int(row["duplicates"]) == 0 for row in records
        ),
        "all_execution_eligible": not ineligible,
        "execution_ineligible_pairs": ineligible,
        "total_official_gap_minutes": sum(int(row["official_gap_minutes"]) for row in records),
        "records": records,
        "dataset_root_sha256": hashlib.sha256(
            json.dumps(leaves, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
