#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import statistics
import time
import urllib.request
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd

CHECKSUM_RE = re.compile(r"^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$")
MONTHS = {
    "2026-05": 44_640,
    "2026-06": 43_200,
    "2026-07": 44_640,
}
DAILY_START = date(2026, 8, 1)
DAILY_END = date(2026, 8, 10)
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
            req = urllib.request.Request(url, headers={"User-Agent": "FQT-V25-OOS50/1.0"})
            with urllib.request.urlopen(req, timeout=90) as response, tmp.open("wb") as target:
                shutil.copyfileobj(response, target, 1 << 20)
            if not tmp.stat().st_size:
                raise RuntimeError("empty remote object")
            tmp.replace(out)
            return
        except Exception as exc:
            last = exc
            tmp.unlink(missing_ok=True)
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


def read_archive(path: pathlib.Path, expected_rows: int) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f"zip CRC error {path}: {bad}")
        members = [name for name in zf.namelist() if not name.endswith("/")]
        if len(members) != 1:
            raise RuntimeError(f"zip member count {path}: {members}")
        with zf.open(members[0]) as handle:
            frame = pd.read_csv(handle, header=None, names=COLS)
    if len(frame) != expected_rows:
        raise RuntimeError(f"row count {path.name}: expected {expected_rows}, got {len(frame)}")
    for column in ["open_time", "close_time", "trades"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("int64")
    for column in ["open", "high", "low", "close", "volume", "quote_volume", "taker_base", "taker_quote"]:
        frame[column] = pd.to_numeric(frame[column], errors="raise").astype("float64")
    if (frame[["open", "high", "low", "close"]] <= 0).any().any():
        raise RuntimeError(f"non-positive OHLC in {path.name}")
    if (frame["high"] < frame[["open", "low", "close"]].max(axis=1)).any():
        raise RuntimeError(f"impossible high in {path.name}")
    if (frame["low"] > frame[["open", "high", "close"]].min(axis=1)).any():
        raise RuntimeError(f"impossible low in {path.name}")
    if (frame[["volume", "quote_volume", "taker_base", "taker_quote"]] < 0).any().any():
        raise RuntimeError(f"negative volume in {path.name}")
    return frame


def archive_descriptor(symbol: str, period: str, kind: str, raw: pathlib.Path) -> tuple[str, pathlib.Path, pathlib.Path, int]:
    if kind == "monthly":
        name = f"{symbol}-1m-{period}.zip"
        url = f"https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/{name}"
        expected = MONTHS[period]
    else:
        name = f"{symbol}-1m-{period}.zip"
        url = f"https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{name}"
        expected = 1440
    directory = raw / symbol
    return url, directory / name, directory / f"{name}.CHECKSUM", expected


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
    records: list[dict] = []

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
        archive_receipts: list[dict] = []

        periods = [(month, "monthly") for month in MONTHS] + [(day, "daily") for day in daily_periods]
        for period, kind in periods:
            url, archive_path, checksum_path, expected_rows = archive_descriptor(symbol, period, kind, args.raw)
            download(url + ".CHECKSUM", checksum_path)
            download(url, archive_path)
            official = checksum(checksum_path, archive_path.name)
            actual = sha256(archive_path)
            if official != actual:
                raise RuntimeError(f"sha256 mismatch {archive_path.name}: {actual} != {official}")
            frame = read_archive(archive_path, expected_rows)
            chunks.append(frame[["open_time", "open", "high", "low", "close", "volume", "quote_volume"]].copy())
            archive_receipts.append({
                "period": period,
                "kind": kind,
                "archive": archive_path.name,
                "sha256": actual,
                "bytes": archive_path.stat().st_size,
                "rows": len(frame),
            })

        combined = pd.concat(chunks, ignore_index=True)
        combined = combined.sort_values("open_time").drop_duplicates("open_time", keep="last").reset_index(drop=True)
        open_times = combined["open_time"].to_numpy(dtype="int64")
        gaps = int(np.count_nonzero(np.diff(open_times) != 60_000_000))
        duplicates = int(len(open_times) - len(set(map(int, open_times))))
        first_expected = int(pd.Timestamp("2025-12-01T00:00:00Z").timestamp() * 1_000_000)
        last_expected = int(pd.Timestamp("2026-08-10T23:59:00Z").timestamp() * 1_000_000)
        if gaps or duplicates or open_times[0] != first_expected or open_times[-1] != last_expected:
            raise RuntimeError(
                f"invariant {pair}: gaps={gaps} duplicates={duplicates} "
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
        record = {
            "pair": pair,
            "rows": len(out),
            "first": out["date"].iloc[0].isoformat(),
            "last": out["date"].iloc[-1].isoformat(),
            "gaps": gaps,
            "duplicates": duplicates,
            "zero_volume_ratio": float((out["volume"] == 0).mean()),
            "median_quote_volume": float(statistics.median(quote)) if len(quote) else None,
            "parquet": str(existing_path),
            "parquet_sha256": sha256(existing_path),
            "archives_added": archive_receipts,
        }
        records.append(record)
        print(json.dumps({"pair": pair, "rows": record["rows"], "sha256": record["parquet_sha256"]}), flush=True)

    leaf = [{"pair": row["pair"], "sha256": row["parquet_sha256"], "rows": row["rows"]} for row in records]
    manifest = {
        "contract": "FQT_V25_EXTENDED_DATASET_20251201_20260810_V1",
        "source": "official Binance monthly/daily klines plus CHECKSUM",
        "pair_count": len(records),
        "development_range": "[2026-01-01,2026-06-23)",
        "fresh_oos_range": "[2026-06-23,2026-08-11)",
        "fresh_oos_opened_for_alpha": False,
        "records": records,
        "dataset_root_sha256": hashlib.sha256(
            json.dumps(leaf, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest(),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"pair_count": len(records), "dataset_root_sha256": manifest["dataset_root_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
