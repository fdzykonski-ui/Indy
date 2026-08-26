#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re


def as_bool(value):
    text = str(value).strip().lower()
    if text in {"yes", "true", "1"}:
        return True
    if text in {"no", "false", "0"}:
        return False
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", type=pathlib.Path, required=True)
    parser.add_argument("--log", type=pathlib.Path, required=True)
    parser.add_argument("--exit-code", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    exit_code = int(args.exit_code.read_text().strip()) if args.exit_code.exists() else 999
    rows = []
    if args.csv.exists() and args.csv.stat().st_size:
        with args.csv.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
    bias_values = []
    for row in rows:
        normalized = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
        for key in ("has_bias", "bias", "is_biased"):
            if key in normalized:
                value = as_bool(normalized[key])
                if value is not None:
                    bias_values.append(value)
    log = args.log.read_text(encoding="utf-8", errors="replace") if args.log.exists() else ""
    found = [int(value) for value in re.findall(r"found\s+(\d+)\s+trades", log, flags=re.I)]
    valid = exit_code == 0 and bool(rows) and bool(bias_values)
    has_bias = any(bias_values) if bias_values else None
    summary = {
        "contract": "FQT_V25_NATIVE_LOOKAHEAD_VERDICT_V1",
        "exit_code": exit_code,
        "row_count": len(rows),
        "bias_value_count": len(bias_values),
        "has_bias": has_bias,
        "valid_verdict": valid,
        "pass": bool(valid and has_bias is False),
        "found_trade_mentions": found,
        "baseline_trades": max(found) if found else None,
        "decision": "PASS_NO_BIAS" if valid and has_bias is False else ("FAIL_BIAS" if valid and has_bias else "INVALID"),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
