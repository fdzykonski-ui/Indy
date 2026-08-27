#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def pf(value):
    return float(value) if value is not None else 999.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=pathlib.Path, required=True)
    parser.add_argument("--baseline", type=pathlib.Path, required=True)
    parser.add_argument("--candidate", type=pathlib.Path, required=True)
    parser.add_argument("--fee20", type=pathlib.Path, required=True)
    parser.add_argument("--data-manifest", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    selection = load(args.selection)
    baseline = load(args.baseline)
    candidate = load(args.candidate)
    fee20 = load(args.fee20)
    data_manifest = load(args.data_manifest)
    improvement = float(candidate["profit_usdc"]) - float(baseline["profit_usdc"])
    relative = improvement / max(abs(float(baseline["profit_usdc"])), 1e-12)
    checks = {
        "selection_pass": bool(selection.get("selection_pass")),
        "correctness_predecessors": bool(selection.get("oos_pre_authorized")),
        "data_integrity": bool(data_manifest.get("integrity_pass")),
        "execution_universe_complete": bool(data_manifest.get("all_execution_eligible")),
        "candidate_trades": int(candidate["trades"]) >= 350,
        "candidate_winrate": float(candidate["winrate_pct"]) >= 80.0,
        "candidate_profit": float(candidate["profit_usdc"]) > 0,
        "candidate_pf": pf(candidate.get("profit_factor")) >= 1.50,
        "candidate_mdd": float(candidate["max_drawdown_pct"]) <= 5.0,
        "fee20_positive": float(fee20["profit_usdc"]) > 0 and pf(fee20.get("profit_factor")) > 1.0,
        "beats_baseline": improvement > 0 and relative >= 0.05,
    }
    authorized = all(checks.values())
    receipt = {
        "contract": "FQT_V25_ONE_SHOT_OOS_AUTHORIZATION_V2",
        "selection_sha256": selection.get("selection_sha256"),
        "dataset_root_sha256": data_manifest.get("dataset_root_sha256"),
        "chosen_system": selection.get("chosen_system"),
        "chosen_strategy": selection.get("chosen_strategy"),
        "known_range": candidate.get("timerange"),
        "fresh_oos_range": "20260623-20260811",
        "fresh_oos_opened": False,
        "checks": checks,
        "data_quality": {
            "integrity_pass": data_manifest.get("integrity_pass"),
            "all_execution_eligible": data_manifest.get("all_execution_eligible"),
            "execution_ineligible_pairs": data_manifest.get("execution_ineligible_pairs", []),
            "total_official_gap_minutes": data_manifest.get("total_official_gap_minutes", 0),
        },
        "baseline_known": baseline,
        "candidate_known": candidate,
        "candidate_fee20": fee20,
        "known_profit_improvement_usdc": improvement,
        "known_profit_improvement_relative": relative,
        "authorized": authorized,
        "decision": "OPEN_OOS_ONCE" if authorized else "BLOCK_OOS_KEEP_CHAMPION",
    }
    receipt["authorization_sha256"] = hashlib.sha256(
        json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "authorized": authorized,
        "checks": checks,
        "data_quality": receipt["data_quality"],
        "improvement_usdc": improvement,
        "improvement_relative": relative,
        "authorization_sha256": receipt["authorization_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
