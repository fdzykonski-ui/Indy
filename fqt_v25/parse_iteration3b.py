#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import re
import shutil
import tarfile
import zipfile


def expand(path: pathlib.Path, target: pathlib.Path, depth: int = 0) -> None:
    if depth > 5:
        return
    target.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        for child in path.iterdir():
            if child.is_dir():
                expand(child, target / child.name, depth + 1)
            elif zipfile.is_zipfile(child):
                with zipfile.ZipFile(child) as zf:
                    zf.extractall(target / (child.stem + "_zip"))
                expand(target / (child.stem + "_zip"), target / (child.stem + "_expanded"), depth + 1)
            elif child.name.endswith((".tar.gz", ".tgz")):
                out = target / (child.name.replace(".tar.gz", "").replace(".tgz", "") + "_tar")
                out.mkdir(parents=True, exist_ok=True)
                with tarfile.open(child, "r:gz") as tf:
                    tf.extractall(out, filter="data")
                expand(out, target / (out.name + "_expanded"), depth + 1)
            else:
                destination = target / child.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(child, destination)


def normalize_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "yes", "1", "pass", "clean"}:
        return True
    if text in {"false", "no", "0", "fail", "biased"}:
        return False
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact", type=pathlib.Path, required=True)
    parser.add_argument("--work", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    if args.work.exists():
        shutil.rmtree(args.work)
    args.work.mkdir(parents=True)
    expand(args.artifact, args.work / "expanded")

    json_records = []
    csv_records = []
    logs = []
    for path in sorted((args.work / "expanded").rglob("*")):
        if not path.is_file():
            continue
        low = path.name.lower()
        if path.suffix.lower() == ".json":
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
                json_records.append((str(path), obj))
            except Exception:
                pass
        elif path.suffix.lower() == ".csv" and ("lookahead" in low or "recursive" in low):
            try:
                rows = list(csv.DictReader(io.StringIO(path.read_text(encoding="utf-8-sig"))))
                csv_records.append((str(path), rows))
            except Exception:
                pass
        elif path.suffix.lower() in {".log", ".txt"}:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
                if "lookahead" in low or "recursive" in low or "lookahead" in text.lower() or "recursive" in text.lower():
                    logs.append((str(path), text))
            except Exception:
                pass

    lookahead_candidates = []
    recursive_candidates = []
    for source, obj in json_records:
        contract = str(obj.get("contract", "")).lower()
        name = pathlib.Path(source).name.lower()
        if "lookahead" in contract or "lookahead" in name or "lookahead" in json.dumps(obj).lower()[:1000]:
            valid = normalize_bool(obj.get("valid_verdict"))
            has_bias = normalize_bool(obj.get("has_bias"))
            rows = obj.get("row_count", obj.get("rows", obj.get("csv_rows", 0)))
            baseline = obj.get("baseline_trades", obj.get("found_trades", obj.get("trades")))
            lookahead_candidates.append({
                "source": source,
                "contract": obj.get("contract"),
                "valid_verdict": valid,
                "has_bias": has_bias,
                "row_count": rows,
                "baseline_trades": baseline,
                "status": obj.get("status"),
                "decision": obj.get("decision"),
                "raw": obj,
            })
        if "recursive" in contract or "recursive" in name:
            recursive_candidates.append({"source": source, "raw": obj})

    for source, rows in csv_records:
        if "lookahead" not in source.lower():
            continue
        bias_values = []
        for row in rows:
            normalized = {str(key).strip().lower().replace(" ", "_"): value for key, value in row.items()}
            for key in ("has_bias", "bias", "is_biased"):
                if key in normalized:
                    value = normalize_bool(normalized[key])
                    if value is not None:
                        bias_values.append(value)
        if rows:
            lookahead_candidates.append({
                "source": source,
                "contract": "FREQTRADE_LOOKAHEAD_CSV",
                "valid_verdict": bool(bias_values),
                "has_bias": any(bias_values) if bias_values else None,
                "row_count": len(rows),
                "baseline_trades": None,
                "status": "PARSED",
                "decision": None,
                "raw": rows,
            })

    # Prefer a valid explicit verdict with the largest coverage.
    valid = [item for item in lookahead_candidates if item.get("valid_verdict") is True and item.get("has_bias") is not None]
    valid.sort(key=lambda item: int(item.get("row_count") or 0), reverse=True)
    chosen_lookahead = valid[0] if valid else None

    recursive_summary = None
    for item in recursive_candidates:
        obj = item["raw"]
        status = str(obj.get("status", obj.get("decision", ""))).upper()
        max_dev = obj.get("max_indicator_deviation_pct", obj.get("max_deviation_pct", obj.get("max_abs_deviation_pct")))
        pass_flag = status.startswith("PASS") or normalize_bool(obj.get("pass")) is True
        candidate = {
            "source": item["source"],
            "status": status or None,
            "pass": pass_flag,
            "max_indicator_deviation_pct": max_dev,
            "raw": obj,
        }
        if recursive_summary is None or (candidate["pass"] and not recursive_summary["pass"]):
            recursive_summary = candidate

    combined_log = "\n".join(text for _, text in logs)
    found_trades = [int(value) for value in re.findall(r"found\s+(\d+)\s+trades", combined_log, flags=re.I)]
    double_signal_patch = "double signal" in combined_log.lower() or "indicator-only frames" in combined_log.lower()

    summary = {
        "contract": "FQT_V25_ITERATION3B_NORMALIZED_SUMMARY_V1",
        "artifact": str(args.artifact),
        "json_record_count": len(json_records),
        "csv_record_count": len(csv_records),
        "lookahead_candidates": lookahead_candidates,
        "lookahead": {
            "valid_verdict": chosen_lookahead is not None,
            "has_bias": chosen_lookahead.get("has_bias") if chosen_lookahead else None,
            "row_count": chosen_lookahead.get("row_count") if chosen_lookahead else 0,
            "baseline_trades": chosen_lookahead.get("baseline_trades") if chosen_lookahead else (max(found_trades) if found_trades else None),
            "source": chosen_lookahead.get("source") if chosen_lookahead else None,
            "pass": bool(chosen_lookahead and chosen_lookahead.get("has_bias") is False),
        },
        "recursive": recursive_summary or {"pass": False, "status": "NOT_FOUND", "source": None},
        "double_signal_patch_observed": double_signal_patch,
        "found_trade_mentions": found_trades,
        "decision": "PASS_CORRECTNESS_PREDECESSOR" if chosen_lookahead and chosen_lookahead.get("has_bias") is False else "BLOCKED_LOOKAHEAD",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "decision": summary["decision"],
        "lookahead": summary["lookahead"],
        "recursive": {key: summary["recursive"].get(key) for key in ["pass", "status", "max_indicator_deviation_pct", "source"]},
        "double_signal_patch_observed": summary["double_signal_patch_observed"],
    }, indent=2))


if __name__ == "__main__":
    main()
