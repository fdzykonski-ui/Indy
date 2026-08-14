#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(".")
EVIDENCE = ROOT / "evidence"
TABLES = ROOT / "tables"
RECEIPTS = ROOT / "receipts"
REPORTS = ROOT / "reports"
for p in (EVIDENCE, TABLES, RECEIPTS, REPORTS):
    p.mkdir(parents=True, exist_ok=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=False, allow_nan=False) + "\n")


def load_result(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.endswith(".json") and not n.endswith("_config.json")]
        if len(names) != 1:
            raise RuntimeError(f"{path}: expected one result JSON, got {names}")
        obj = json.loads(zf.read(names[0]))
    if len(obj.get("strategy", {})) != 1:
        raise RuntimeError(f"{path}: expected one strategy result")
    result = next(iter(obj["strategy"].values()))
    return result, result.get("trades", [])


def canonical_trade_hash(trades: list[dict[str, Any]]) -> str:
    keys = [
        "pair", "open_timestamp", "close_timestamp", "enter_tag", "exit_reason",
        "is_short", "leverage", "stake_amount", "amount", "open_rate", "close_rate",
        "profit_ratio", "profit_abs", "fee_open", "fee_close", "trade_duration",
        "min_rate", "max_rate",
    ]
    rows = [{k: t.get(k) for k in keys} for t in trades]
    return hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def equal(a: Any, b: Any) -> bool:
    if isinstance(a, (int, float)) or isinstance(b, (int, float)):
        try:
            return math.isclose(float(a), float(b), rel_tol=0.0, abs_tol=1e-12)
        except Exception:
            return False
    return a == b


def compare_ledgers(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = [
        "pair", "open_timestamp", "close_timestamp", "enter_tag", "exit_reason",
        "is_short", "leverage", "stake_amount", "amount", "open_rate", "close_rate",
        "profit_ratio", "profit_abs", "fee_open", "fee_close", "trade_duration",
    ]
    diffs: list[dict[str, Any]] = []
    if len(a) != len(b):
        diffs.append({"field": "trade_count", "left": len(a), "right": len(b)})
    for idx, (x, y) in enumerate(zip(a, b)):
        for key in keys:
            if not equal(x.get(key), y.get(key)):
                diffs.append({"trade_index": idx, "field": key, "left": x.get(key), "right": y.get(key)})
                if len(diffs) >= 100:
                    return diffs
    return diffs


def summarize_result(label: str, path: Path) -> dict[str, Any]:
    result, trades = load_result(path)
    return {
        "scenario": label,
        "result_zip": str(path),
        "result_sha256": sha(path),
        "trade_ledger_sha256": canonical_trade_hash(trades),
        "trades": int(result.get("total_trades", len(trades))),
        "wins": int(result.get("wins", 0)),
        "draws": int(result.get("draws", 0)),
        "losses": int(result.get("losses", 0)),
        "winrate_pct": float(result.get("winrate", 0.0)) * 100,
        "profit_usdc": float(result.get("profit_total_abs", 0.0)),
        "profit_pct": float(result.get("profit_total", 0.0)) * 100,
        "profit_factor": float(result.get("profit_factor", 0.0)),
        "max_drawdown_account_pct": float(result.get("max_drawdown_account", 0.0)) * 100,
        "final_balance": float(result.get("final_balance", 0.0)),
    }


def parse_lookahead(label: str) -> dict[str, Any]:
    csv_path = EVIDENCE / f"lookahead_{label}.csv"
    log_path = EVIDENCE / f"lookahead_{label}.log"
    rc_path = EVIDENCE / f"lookahead_{label}.exit_code"
    rows: list[dict[str, str]] = []
    if csv_path.exists() and csv_path.stat().st_size:
        with csv_path.open(newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
    log = log_path.read_text(errors="replace") if log_path.exists() else ""
    found = None
    for pattern in [r"Found\s+(\d+)\s+trades", r"found\s+(\d+)\s+trades"]:
        matches = re.findall(pattern, log, flags=re.I)
        if matches:
            found = int(matches[-1])
            break
    vals: list[bool] = []
    checked = 0
    for row in rows:
        raw = str(row.get("has_bias", "")).strip().lower()
        if raw in {"true", "yes", "1"}:
            vals.append(True)
        elif raw in {"false", "no", "0"}:
            vals.append(False)
        try:
            checked = max(checked, int(float(row.get("total_signals", 0))))
        except Exception:
            pass
    rc = int(rc_path.read_text().strip()) if rc_path.exists() else None
    valid = bool(rows) and bool(vals) and checked >= 10 and rc == 0
    return {
        "lane": label,
        "exit_code": rc,
        "csv_exists": csv_path.exists(),
        "row_count": len(rows),
        "found_trades_from_log": found,
        "checked_signals": checked,
        "valid_verdict": valid,
        "has_bias": any(vals) if vals else None,
        "helper_positive_paircount": "positive pair count" in log,
        "preserved_production_contract": "preserving production portfolio contract" in log,
        "rows": rows,
        "log_sha256": sha(log_path) if log_path.exists() else None,
        "csv_sha256": sha(csv_path) if csv_path.exists() else None,
    }


v10_path = EVIDENCE / "IP04A_CONTINUOUS_RUN1.zip"
v14_path = EVIDENCE / "V14_CONTINUOUS_MAIN.zip"
v10_summary = summarize_result("V10_main", v10_path)
v14_summary = summarize_result("V14_main", v14_path)
_, v10_trades = load_result(v10_path)
_, v14_trades = load_result(v14_path)
v14_diffs = compare_ledgers(v10_trades, v14_trades)

callback_rows: list[dict[str, Any]] = []
for path in sorted(EVIDENCE.glob("CALLBACK_*.zip")):
    label = path.stem.replace("CALLBACK_", "")
    row = summarize_result(label, path)
    ledger_path = EVIDENCE / f"callback_{label}.json"
    row["callback_ledger_exists"] = ledger_path.exists()
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text())
        row["callback_counts"] = ledger.get("counts", {})
        row["callback_ledger_sha256"] = sha(ledger_path)
    callback_rows.append(row)

jan_plain = next((r for r in callback_rows if r["scenario"] == "plain_mot2_wallet1000"), None)
jan_ledger = next((r for r in callback_rows if r["scenario"] == "ledger_mot2_wallet1000"), None)
callback_instrumentation_diffs: list[dict[str, Any]] = []
if jan_plain and jan_ledger:
    _, a = load_result(Path(jan_plain["result_zip"]))
    _, b = load_result(Path(jan_ledger["result_zip"]))
    callback_instrumentation_diffs = compare_ledgers(a, b)

lookahead_lanes = [parse_lookahead(x) for x in ("paircount", "production", "signal_harness")]
by_lane = {x["lane"]: x for x in lookahead_lanes}
paircount_pass = by_lane["paircount"]["valid_verdict"] and by_lane["paircount"]["has_bias"] is False
production_pass = by_lane["production"]["valid_verdict"] and by_lane["production"]["has_bias"] is False
harness_pass = by_lane["signal_harness"]["valid_verdict"] and by_lane["signal_harness"]["has_bias"] is False

if paircount_pass and production_pass:
    lookahead_gate = "PASS"
    classification = "NATIVE_PRODUCTION_AND_GENERIC_LANES_NO_BIAS"
elif production_pass or paircount_pass:
    lookahead_gate = "TEILWEISE"
    classification = "ONE_NATIVE_LANE_VALID_OTHER_INCOMPLETE_OR_INVALID"
elif harness_pass:
    lookahead_gate = "BLOCKIERT"
    classification = "SIGNAL_HARNESS_PASS_ONLY_NATIVE_PRODUCTION_INVALID"
else:
    lookahead_gate = "INVALID"
    classification = "NO_VALID_NATIVE_OR_SIGNAL_HARNESS_VERDICT"

recursive_summary_path = EVIDENCE / "RECURSIVE_31PAIR_SUMMARY.json"
recursive_summary = json.loads(recursive_summary_path.read_text()) if recursive_summary_path.exists() else {
    "status": "NOT_RUN",
    "reason": "Lookahead predecessor did not PASS in both native lanes.",
}

# CSV tables.
with (TABLES / "LOOKAHEAD_LANES.csv").open("w", newline="") as f:
    fields = ["lane", "exit_code", "row_count", "found_trades_from_log", "checked_signals", "valid_verdict", "has_bias", "helper_positive_paircount", "preserved_production_contract"]
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    for row in lookahead_lanes:
        w.writerow({k: row.get(k) for k in fields})

callback_fields = [
    "scenario", "trades", "wins", "draws", "losses", "winrate_pct", "profit_usdc",
    "profit_pct", "profit_factor", "max_drawdown_account_pct", "final_balance",
    "trade_ledger_sha256", "callback_ledger_exists", "callback_ledger_sha256",
]
with (TABLES / "CALLBACK_SCENARIOS.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=callback_fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(callback_rows)

claims = [
    {
        "claim_id": "CLM-I3-001",
        "claim": "V14 trading semantics are identical to the V10 anchor in the continuous development run.",
        "maturity": "REPLICATED" if not v14_diffs else "WIDERLEGT",
        "primary_evidence": "ART-V10-MAIN; ART-V14-MAIN",
        "hash": v14_summary["trade_ledger_sha256"],
        "alternative": "Class boundary changed resolver or callback behavior.",
        "falsifier": "Any semantic trade-ledger difference.",
        "verdict": "VERIFIZIERT" if not v14_diffs else "WIDERLEGT",
    },
    {
        "claim_id": "CLM-I3-002",
        "claim": "Callback instrumentation is non-invasive under the baseline January contract.",
        "maturity": "CONFIRMATORY" if not callback_instrumentation_diffs else "WIDERLEGT",
        "primary_evidence": "ART-CALLBACK-PLAIN; ART-CALLBACK-LEDGER",
        "hash": jan_ledger.get("trade_ledger_sha256") if jan_ledger else None,
        "alternative": "Instrumentation changes timing or state.",
        "falsifier": "Any semantic ledger difference.",
        "verdict": "VERIFIZIERT" if jan_plain and jan_ledger and not callback_instrumentation_diffs else "NICHT_VERIFIZIERT",
    },
    {
        "claim_id": "CLM-I3-003",
        "claim": "Native production-contract lookahead yields an explicit no-bias verdict covering at least ten signals.",
        "maturity": "CONFIRMATORY" if production_pass else "EXPLORATORY",
        "primary_evidence": "ART-LOOKAHEAD-PRODUCTION",
        "hash": by_lane["production"].get("csv_sha256"),
        "alternative": "Helper execution contract cannot reproduce strategy trades.",
        "falsifier": "Invalid verdict, fewer than ten signals or any bias flag.",
        "verdict": "VERIFIZIERT" if production_pass else "NICHT_VERIFIZIERT",
    },
    {
        "claim_id": "CLM-I3-004",
        "claim": "Official-like positive-pair-count lookahead yields an explicit no-bias verdict covering at least ten signals.",
        "maturity": "CONFIRMATORY" if paircount_pass else "EXPLORATORY",
        "primary_evidence": "ART-LOOKAHEAD-PAIRCOUNT",
        "hash": by_lane["paircount"].get("csv_sha256"),
        "alternative": "The -1 sentinel was not the only incompatibility.",
        "falsifier": "Invalid verdict, fewer than ten signals or any bias flag.",
        "verdict": "VERIFIZIERT" if paircount_pass else "NICHT_VERIFIZIERT",
    },
]
with (TABLES / "CLAIM_EVIDENCE_MATRIX.csv").open("w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=list(claims[0]))
    w.writeheader()
    w.writerows(claims)

contradictions = []
if v10_summary["trades"] != v14_summary["trades"] or v14_diffs:
    contradictions.append({"id": "CON-I3-001", "claim": "V14=V10 parity", "status": "OPEN", "details": v14_diffs[:20]})
if production_pass != paircount_pass:
    contradictions.append({"id": "CON-I3-002", "claim": "Lookahead verdict stable across helper contracts", "status": "OPEN", "details": lookahead_lanes})
with (EVIDENCE / "CONTRADICTION_REGISTER.jsonl").open("w") as f:
    for row in contradictions:
        f.write(json.dumps(row) + "\n")

anomalies = []
for lane in lookahead_lanes:
    if not lane["valid_verdict"]:
        anomalies.append({"id": f"ANOM-{lane['lane']}", "status": "OPEN", "lane": lane["lane"], "reason": "invalid_or_insufficient_lookahead_verdict", "metrics": lane})
with (EVIDENCE / "ANOMALY_LEDGER.jsonl").open("w") as f:
    for row in anomalies:
        f.write(json.dumps(row) + "\n")

summary = {
    "contract": "FQT_STRATEGY_RND_V24_ITERATION3_SUMMARY_V1",
    "utc_finished": now(),
    "classification": classification,
    "lookahead_gate": lookahead_gate,
    "paircount_pass": paircount_pass,
    "production_pass": production_pass,
    "signal_harness_pass": harness_pass,
    "v14_v10_exact_parity": not v14_diffs,
    "v14_v10_differences": v14_diffs[:100],
    "callback_instrumentation_exact_parity": bool(jan_plain and jan_ledger and not callback_instrumentation_diffs),
    "callback_instrumentation_differences": callback_instrumentation_diffs[:100],
    "lookahead_lanes": lookahead_lanes,
    "recursive": recursive_summary,
    "v10_main": v10_summary,
    "v14_main": v14_summary,
    "callback_scenarios": callback_rows,
    "decision": "KEEP_CHAMPION",
    "research_maturity": "CONFIRMATORY" if production_pass and paircount_pass else "EXPLORATORY_OR_PARTIAL",
    "oos": "UNTOUCHED_NOT_OPENED",
    "dry_run": "BLOCKED",
    "live": "FORBIDDEN",
    "next_action": "Proceed to full recursive and funnel only after both native lookahead lanes PASS; otherwise isolate helper/callback mismatch.",
}
write_json(EVIDENCE / "FINAL_ITERATION3_SUMMARY.json", summary)

receipt = {
    "id": "EVAL-I3-LOOKAHEAD-001",
    "status": "PASS" if lookahead_gate == "PASS" else "INVALID",
    "utc_started": None,
    "utc_finished": now(),
    "inputs": [
        {"artifact_id": "ART-V10-MAIN", "sha256": v10_summary["result_sha256"]},
        {"artifact_id": "ART-V14-MAIN", "sha256": v14_summary["result_sha256"]},
    ],
    "command": "see COMMAND_LEDGER.jsonl and native logs",
    "exit_code": 0 if lookahead_gate == "PASS" else 2,
    "primary_metrics": {
        "lookahead_gate": lookahead_gate,
        "paircount_checked_signals": by_lane["paircount"]["checked_signals"],
        "production_checked_signals": by_lane["production"]["checked_signals"],
        "paircount_has_bias": by_lane["paircount"]["has_bias"],
        "production_has_bias": by_lane["production"]["has_bias"],
    },
    "uncertainty_or_tolerance": {
        "minimum_checked_signals_per_lane": 10,
        "limit_order_false_positive_risk": True,
        "signal_harness_is_not_production_evidence": True,
    },
    "evidence": ["ART-LOOKAHEAD-PRODUCTION", "ART-LOOKAHEAD-PAIRCOUNT", "ART-CALLBACK-LEDGER"],
    "decision": "KEEP_CHAMPION",
    "blocker_or_next_action": summary["next_action"],
}
write_json(RECEIPTS / "LOOKAHEAD_AND_CALLBACK_EVALUATION_RECEIPT.json", receipt)

print(json.dumps({
    "classification": classification,
    "lookahead_gate": lookahead_gate,
    "v14_v10_exact_parity": not v14_diffs,
    "callback_instrumentation_exact_parity": summary["callback_instrumentation_exact_parity"],
    "paircount": {k: by_lane["paircount"][k] for k in ("valid_verdict", "has_bias", "checked_signals", "found_trades_from_log")},
    "production": {k: by_lane["production"][k] for k in ("valid_verdict", "has_bias", "checked_signals", "found_trades_from_log")},
    "harness": {k: by_lane["signal_harness"][k] for k in ("valid_verdict", "has_bias", "checked_signals", "found_trades_from_log")},
    "recursive": recursive_summary.get("status"),
}, indent=2))
