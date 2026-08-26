#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

SYSTEMS = {
    "BASE_RANKED": {"strategy": "M4PioneerValidationV14", "delay_strategy": "M4PioneerValidationV14Delay1"},
    "V16_PRUNE": {"strategy": "M4PioneerOOS50V16VwapPrune", "delay_strategy": "M4PioneerOOS50V16VwapPruneDelay1"},
    "V16_VWAPQ": {"strategy": "M4PioneerOOS50V16VwapQuality", "delay_strategy": "M4PioneerOOS50V16VwapQualityDelay1"},
    "V16_TRENDQ": {"strategy": "M4PioneerOOS50V16TrendQuality", "delay_strategy": "M4PioneerOOS50V16TrendQualityDelay1"},
}


def load(path: pathlib.Path):
    return json.loads(path.read_text(encoding="utf-8"))


def monthly(summary):
    return {row["key"]: row for row in summary.get("monthly_metrics", [])}


def pf(value):
    return float(value) if value is not None else 999.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summaries", type=pathlib.Path, required=True)
    parser.add_argument("--correctness", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args()

    correctness = load(args.correctness)
    lookahead_pass = bool(correctness.get("lookahead", {}).get("pass"))
    recursive_pass = bool(correctness.get("recursive", {}).get("pass"))
    candidates = []
    for system, meta in SYSTEMS.items():
        scenarios = {}
        missing = []
        for scenario in ["known", "fee15", "delay1", "reversed"]:
            path = args.summaries / f"{system}__{scenario}.json"
            if not path.exists():
                missing.append(str(path))
            else:
                scenarios[scenario] = load(path)
        if missing:
            candidates.append({"system": system, "complete": False, "missing": missing, "pass": False})
            continue
        known = scenarios["known"]
        months = monthly(known)
        month_checks = {}
        for month in ["2026-04", "2026-05", "2026-06"]:
            row = months.get(month)
            month_checks[month] = bool(row and float(row.get("profit_usdc", 0)) > 0 and pf(row.get("profit_factor")) > 1.0)
        checks = {
            "known_trades": int(known["trades"]) >= 80,
            "known_winrate": float(known["winrate_pct"]) >= 80.0,
            "known_profit": float(known["profit_usdc"]) > 0,
            "known_pf": pf(known.get("profit_factor")) >= 1.25,
            "known_mdd": float(known["max_drawdown_pct"]) <= 5.0,
            "all_months_positive": all(month_checks.values()),
            "fee15": float(scenarios["fee15"]["profit_usdc"]) > 0 and pf(scenarios["fee15"].get("profit_factor")) > 1.0,
            "delay1": float(scenarios["delay1"]["profit_usdc"]) > 0 and pf(scenarios["delay1"].get("profit_factor")) > 1.0,
            "reversed": float(scenarios["reversed"]["profit_usdc"]) > 0 and pf(scenarios["reversed"].get("profit_factor")) > 1.0,
        }
        stress_pfs = [
            pf(known.get("profit_factor")),
            pf(scenarios["fee15"].get("profit_factor")),
            pf(scenarios["delay1"].get("profit_factor")),
            pf(scenarios["reversed"].get("profit_factor")),
        ]
        candidate_pass = all(checks.values())
        score = [
            sum(checks.values()),
            min(stress_pfs),
            float(known["profit_usdc"]),
            pf(known.get("profit_factor")),
            -float(known["max_drawdown_pct"]),
        ]
        candidates.append({
            "system": system,
            "complete": True,
            "strategy": meta["strategy"],
            "delay_strategy": meta["delay_strategy"],
            "checks": checks,
            "month_checks": month_checks,
            "pass": candidate_pass,
            "score": score,
            "scenarios": scenarios,
        })

    eligible = [row for row in candidates if row.get("pass")]
    eligible.sort(key=lambda row: tuple(row["score"]), reverse=True)
    chosen = eligible[0] if eligible else None
    receipt = {
        "contract": "FQT_V25_PREREGISTERED_SELECTION_V1",
        "selection_data": "known only: pair ranking Jan-Mar; validation Apr-Jun22",
        "fresh_oos_used": False,
        "correctness": {"lookahead_pass": lookahead_pass, "recursive_pass": recursive_pass},
        "candidates": candidates,
        "chosen_system": chosen["system"] if chosen else None,
        "chosen_strategy": chosen["strategy"] if chosen else None,
        "selection_pass": chosen is not None,
        "oos_pre_authorized": bool(chosen and lookahead_pass and recursive_pass),
        "decision": "RUN_FULL_KNOWN_CONFIRMATION" if chosen and lookahead_pass and recursive_pass else "KEEP_CHAMPION_BLOCK_OOS",
    }
    receipt["selection_sha256"] = hashlib.sha256(json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "lookahead_pass": lookahead_pass,
        "recursive_pass": recursive_pass,
        "eligible": [row["system"] for row in eligible],
        "chosen_system": receipt["chosen_system"],
        "decision": receipt["decision"],
        "selection_sha256": receipt["selection_sha256"],
    }, indent=2))


if __name__ == "__main__":
    main()
