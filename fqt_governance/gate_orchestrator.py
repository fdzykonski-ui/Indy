#!/usr/bin/env python3
"""Fail-closed FQT gate/WIP orchestrator.

The orchestrator never promotes a strategy.  It validates the registry, overlays
published diagnostic evidence and selects exactly one next work package while
preserving OOS/dry-run/live safety boundaries.
"""
from __future__ import annotations

import argparse
import json
import pathlib
from typing import Any

ALLOWED_STATES = {
    "VERIFIED",
    "VERIFIED_SIGNAL_GENERATION_ONLY",
    "PARTIAL",
    "PARTIAL_SIGNAL_STABLE_INDICATOR_GATE_OPEN",
    "NOT_RUN",
    "BLOCKED",
    "INVALID",
    "FAIL",
    "CONTAMINATED",
    "FORBIDDEN",
}

PREDECESSORS = {
    "G01_PROVENANCE_DATA": ["G00_CONTRACT"],
    "G02_STATIC_CAUSALITY": ["G01_PROVENANCE_DATA"],
    "G03_SIGNAL_LOOKAHEAD_NATIVE": ["G02_STATIC_CAUSALITY"],
    "G04_CHAMPION_EXECUTION_CAUSALITY": ["G03_SIGNAL_LOOKAHEAD_NATIVE"],
    "G05_RECURSIVE_INDICATORS": ["G03_SIGNAL_LOOKAHEAD_NATIVE"],
    "G06_DETERMINISTIC_BASELINE": ["G02_STATIC_CAUSALITY"],
    "G07_FUNNEL_INSTRUMENTATION": ["G04_CHAMPION_EXECUTION_CAUSALITY", "G05_RECURSIVE_INDICATORS"],
    "G08_EXECUTION_REALISM": ["G07_FUNNEL_INSTRUMENTATION"],
    "G09_NESTED_WALK_FORWARD": ["G08_EXECUTION_REALISM"],
    "G10_PAIR_HOLDOUT_LOPO": ["G09_NESTED_WALK_FORWARD"],
    "G11_STATISTICS": ["G09_NESTED_WALK_FORWARD", "G10_PAIR_HOLDOUT_LOPO"],
    "G12_FINAL_UNTOUCHED_OOS": ["G03_SIGNAL_LOOKAHEAD_NATIVE", "G04_CHAMPION_EXECUTION_CAUSALITY", "G05_RECURSIVE_INDICATORS", "G08_EXECUTION_REALISM", "G09_NESTED_WALK_FORWARD", "G10_PAIR_HOLDOUT_LOPO", "G11_STATISTICS"],
    "G13_PERSISTENT_DRY_RUN": ["G12_FINAL_UNTOUCHED_OOS"],
    "G14_INDEPENDENT_REVIEW": ["G13_PERSISTENT_DRY_RUN"],
    "G15_CANARY_LIVE": ["G14_INDEPENDENT_REVIEW"],
}

PASS_STATES = {"VERIFIED", "VERIFIED_SIGNAL_GENERATION_ONLY"}
WORK_PACKAGES = {
    "G03_SIGNAL_LOOKAHEAD_NATIVE": "WP-001_IP07_SIGNAL_GENERATION_CORRECTNESS",
    "G04_CHAMPION_EXECUTION_CAUSALITY": "WP-002_IP08_CHAMPION_CALLBACK_CAUSALITY",
    "G05_RECURSIVE_INDICATORS": "WP-003_OFFICIAL_FULL_UNIVERSE_RECURSIVE",
    "G07_FUNNEL_INSTRUMENTATION": "WP-004_SIGNAL_REJECTION_FILL_FUNNEL",
    "G08_EXECUTION_REALISM": "WP-005_EXECUTION_REALISM_REPAIR",
    "G09_NESTED_WALK_FORWARD": "WP-007_NESTED_WALK_FORWARD",
    "G10_PAIR_HOLDOUT_LOPO": "WP-008_PAIR_HOLDOUT_LOPO",
    "G11_STATISTICS": "WP-009_STATISTICAL_DECISION_PACKAGE",
    "G12_FINAL_UNTOUCHED_OOS": "WP-010_FINAL_UNTOUCHED_OOS",
    "G13_PERSISTENT_DRY_RUN": "WP-011_PERSISTENT_DRY_RUN",
    "G14_INDEPENDENT_REVIEW": "WP-012_INDEPENDENT_REVIEW",
    "G15_CANARY_LIVE": "WP-013_CANARY_LIVE_REQUIRES_EXPLICIT_AUTHORIZATION",
}


def read_json(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", required=True)
    parser.add_argument("--ip07-status")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    registry = read_json(pathlib.Path(args.registry))
    gates = {gate["id"]: dict(gate) for gate in registry["gates"]}
    errors: list[str] = []
    for gate_id, gate in gates.items():
        if gate.get("status") not in ALLOWED_STATES:
            errors.append(f"{gate_id}: invalid status {gate.get('status')}")
    if registry.get("live_trading_allowed") is not False:
        errors.append("registry must keep live_trading_allowed=false")
    if int(registry.get("wip_limit_alpha_challengers", 99)) > 1:
        errors.append("alpha challenger WIP limit exceeds one")

    overlay: dict[str, Any] = {}
    if args.ip07_status and pathlib.Path(args.ip07_status).exists():
        published = read_json(pathlib.Path(args.ip07_status))
        summary = published.get("summary") if isinstance(published.get("summary"), dict) else {}
        signal_pass = summary.get("signal_generation_gate_pass")
        if signal_pass is True:
            gates["G03_SIGNAL_LOOKAHEAD_NATIVE"]["status"] = "VERIFIED_SIGNAL_GENERATION_ONLY"
            gates["G04_CHAMPION_EXECUTION_CAUSALITY"]["status"] = "BLOCKED"
            if summary.get("recursive_signal_gate_pass") is True:
                gates["G05_RECURSIVE_INDICATORS"]["status"] = "PARTIAL_SIGNAL_STABLE_INDICATOR_GATE_OPEN"
            overlay = {
                "ip07_signal_generation_gate_pass": True,
                "parity_pairs_passed": summary.get("parity_pairs_passed"),
                "recursive_pairs_passed": summary.get("recursive_pairs_passed"),
                "lookahead_has_bias": summary.get("lookahead_has_bias"),
                "champion_execution_callback_gate_closed": False,
            }
        elif signal_pass is False:
            gates["G03_SIGNAL_LOOKAHEAD_NATIVE"]["status"] = "INVALID"
            overlay = {"ip07_signal_generation_gate_pass": False}

    # Select the first unresolved correctness/execution/validation gate whose
    # predecessors are sufficiently closed.  G04 remains eligible after the
    # scoped G03 signal-only pass; G03 does not imply G04.
    order = [
        "G03_SIGNAL_LOOKAHEAD_NATIVE",
        "G04_CHAMPION_EXECUTION_CAUSALITY",
        "G05_RECURSIVE_INDICATORS",
        "G07_FUNNEL_INSTRUMENTATION",
        "G08_EXECUTION_REALISM",
        "G09_NESTED_WALK_FORWARD",
        "G10_PAIR_HOLDOUT_LOPO",
        "G11_STATISTICS",
        "G12_FINAL_UNTOUCHED_OOS",
        "G13_PERSISTENT_DRY_RUN",
        "G14_INDEPENDENT_REVIEW",
        "G15_CANARY_LIVE",
    ]
    active_gate = None
    blocked_reasons: dict[str, list[str]] = {}
    for gate_id in order:
        state = gates[gate_id]["status"]
        if state in PASS_STATES:
            continue
        predecessors = PREDECESSORS.get(gate_id, [])
        missing = [
            predecessor
            for predecessor in predecessors
            if gates[predecessor]["status"] not in PASS_STATES
        ]
        # Scoped exception: the signal-only G03 pass is the intended predecessor
        # for G04, while full execution causality remains G04 itself.
        if not missing:
            active_gate = gate_id
            break
        blocked_reasons[gate_id] = missing

    active_work_package = WORK_PACKAGES.get(active_gate) if active_gate else None
    alpha_challenger_authorized = (
        gates["G04_CHAMPION_EXECUTION_CAUSALITY"]["status"] in PASS_STATES
        and gates["G05_RECURSIVE_INDICATORS"]["status"] in PASS_STATES
        and gates["G07_FUNNEL_INSTRUMENTATION"]["status"] in PASS_STATES
        and gates["G08_EXECUTION_REALISM"]["status"] in PASS_STATES
    )
    final_oos_authorized = all(
        gates[predecessor]["status"] in PASS_STATES
        for predecessor in PREDECESSORS["G12_FINAL_UNTOUCHED_OOS"]
    )
    dry_run_authorized = final_oos_authorized and gates[
        "G12_FINAL_UNTOUCHED_OOS"
    ]["status"] in PASS_STATES

    output = {
        "contract": "FQT_GATE_ORCHESTRATOR_V23",
        "valid": not errors,
        "errors": errors,
        "champion": registry["champion"],
        "alpha_parent": registry["alpha_parent"],
        "overlay": overlay,
        "gate_status": {gate_id: gate["status"] for gate_id, gate in gates.items()},
        "active_gate": active_gate,
        "active_work_package": active_work_package,
        "blocked_reasons": blocked_reasons,
        "alpha_challenger_authorized": alpha_challenger_authorized,
        "final_oos_authorized": final_oos_authorized,
        "persistent_dry_run_authorized": dry_run_authorized,
        "live_trading_authorized": False,
        "decision": "KEEP_CHAMPION",
    }
    pathlib.Path(args.out).write_text(json.dumps(output, indent=2) + "\n")
    print(json.dumps(output, indent=2))
    return 0 if output["valid"] and output["live_trading_authorized"] is False else 2


if __name__ == "__main__":
    raise SystemExit(main())
