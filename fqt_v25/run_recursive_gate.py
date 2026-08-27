#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import subprocess

PAIRS = ["BTC/USDC", "ETH/USDC", "SOL/USDC", "SHIB/USDC"]
STARTUP = [800, 1100, 1600, 2400]


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config_mot1_ranked.json")
    parser.add_argument("--strategy", default="M4PioneerValidationV14")
    parser.add_argument("--timerange", default="20260101-20260116")
    parser.add_argument("--out", type=pathlib.Path, default=pathlib.Path("evidence/V25_RECURSIVE_SUMMARY.json"))
    args = parser.parse_args()

    rows = []
    for pair in PAIRS:
        key = pair.replace("/", "_")
        log_path = pathlib.Path("logs") / f"V25_RECURSIVE_{key}.log"
        command = [
            "python", "fqt_ip04a/freqtrade_offline.py", "recursive-analysis",
            "-c", args.config, "--strategy-path", "user_data/strategies",
            "-s", args.strategy, "-i", "1m", "--timerange", args.timerange,
            "-p", pair, "--startup-candle", *map(str, STARTUP), "--no-color",
        ]
        with log_path.open("wb") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, env=os.environ.copy())
        text = log_path.read_text(encoding="utf-8", errors="replace")
        values = []
        for line in text.splitlines():
            if ("│" in line or "|" in line) and "%" in line:
                values.extend(float(value) for value in re.findall(r"-?\d+(?:\.\d+)?(?=%)", line))
        max_abs = max((abs(value) for value in values), default=0.0)
        rows.append({
            "pair": pair,
            "exit_code": result.returncode,
            "startup_candles": STARTUP,
            "percent_values": values,
            "max_abs_deviation_pct": max_abs,
            "pass": result.returncode == 0 and max_abs <= 0.10,
            "log": str(log_path),
            "log_sha256": sha256(log_path),
        })

    summary = {
        "contract": "FQT_V25_NATIVE_RECURSIVE_4PAIR_V1",
        "strategy": args.strategy,
        "timerange": args.timerange,
        "startup_candles": STARTUP,
        "rows": rows,
        "max_indicator_deviation_pct": max((row["max_abs_deviation_pct"] for row in rows), default=None),
        "pass": all(row["pass"] for row in rows),
        "status": "PASS_LIMITED_4PAIR" if all(row["pass"] for row in rows) else "FAIL",
        "scope": "Indicator last-row startup stability only; not performance or full-universe proof.",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
