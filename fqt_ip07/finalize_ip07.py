#!/usr/bin/env python3
"""Assemble IP07 gate/CAPA/funnel receipts and next iteration contract."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text())


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parity", required=True)
    ap.add_argument("--matrix", required=True)
    ap.add_argument("--lookahead", required=True)
    ap.add_argument("--recursive", required=True)
    ap.add_argument("--instrumentation", required=True)
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    parity = load(args.parity)
    matrix = load(args.matrix)
    lookahead = load(args.lookahead)
    recursive = load(args.recursive)
    instrumentation = load(args.instrumentation)

    same_candle_violations = int(
        parity.get("aggregate", {}).get("same_candle_collision_violations", 0)
    )
    parity_pass = parity.get("status") == "PASS"
    lookahead_pass = (
        lookahead.get("diagnostic_equivalence_pass") is True
        and lookahead.get("bias_detected_in_any_valid_run") is False
    )
    recursive_pass = recursive.get("status") == "PASS"
    matrix_pass = (
        int(matrix.get("baseline_trades", 0)) >= 10
        and matrix.get("diagnostic_sufficient_trades") is True
    )
    overall_pass = (
        parity_pass
        and lookahead_pass
        and recursive_pass
        and matrix_pass
        and same_candle_violations == 0
    )

    gates = [
        {
            "gate_id": "IP07-G01",
            "gate": "31-pair signal-hash parity",
            "status": "PASS" if parity_pass else "FAIL",
            "evidence": args.parity,
            "next_action": "freeze hashes" if parity_pass else "repair diagnostic equivalence",
        },
        {
            "gate_id": "IP07-G02",
            "gate": "future-append causality",
            "status": "PASS" if parity_pass and not parity.get("hard_failures") else "FAIL",
            "evidence": args.parity,
            "next_action": "native lifecycle triangulation",
        },
        {
            "gate_id": "IP07-G03",
            "gate": "native diagnostic-equivalent lookahead",
            "status": "PASS_EQUIVALENT" if lookahead_pass else "BLOCKED",
            "evidence": args.lookahead,
            "next_action": "close CAPA" if lookahead_pass else "continue helper isolation",
        },
        {
            "gate_id": "IP07-G04",
            "gate": "31-pair recursive matrix",
            "status": "PASS" if recursive_pass else recursive.get("status", "BLOCKED"),
            "evidence": args.recursive,
            "next_action": "freeze startup-candle contract" if recursive_pass else "repair pair failures",
        },
        {
            "gate_id": "IP07-G05",
            "gate": "same-candle collision contract",
            "status": "PASS" if same_candle_violations == 0 else "FAIL",
            "evidence": args.parity,
            "next_action": "none" if same_candle_violations == 0 else "repair collision arbitration",
        },
        {
            "gate_id": "IP07-G06",
            "gate": "helper override root-cause matrix",
            "status": "PASS" if matrix_pass else "FAIL",
            "evidence": args.matrix,
            "next_action": matrix.get("likely_root_cause", "unknown"),
        },
    ]
    with (outdir / "GATE_MATRIX.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(gates[0]))
        writer.writeheader()
        writer.writerows(gates)

    capa = {
        "contract": "FQT_V23_IP07_CAPA_DEF_LOOKAHEAD_001_V1",
        "defect_id": "DEF-LOOKAHEAD-001",
        "status": "CLOSED_WITH_EQUIVALENT_HARNESS" if overall_pass else "REOPENED",
        "utc": now(),
        "direct_champion_native_status": lookahead.get("champion_direct_native_status"),
        "root_cause": matrix.get("likely_root_cause"),
        "corrective_actions": [
            "instrument helper config before/after override",
            "instrument full result row/pair/exit counts",
            "remove found_signals off-by-one +1",
            "align CSV minimum boundary from > to >=",
            "neutralize execution callbacks in non-tradable diagnostic subclasses",
            "prove exact 31-pair signal parity before accepting diagnostic result",
        ],
        "verification": {
            "signal_parity": parity.get("status"),
            "lookahead": lookahead.get("decision"),
            "recursive": recursive.get("status"),
            "same_candle_violations": same_candle_violations,
        },
        "scope_limit": (
            "Equivalent-harness closure certifies vectorized causal signal generation, not champion "
            "capital allocation, custom-exit economics, limit-order fills or live execution."
        ),
        "rollback": "Champion V14 remains unchanged and not promoted.",
        "evidence_sha256": {
            "parity": sha(Path(args.parity)),
            "matrix": sha(Path(args.matrix)),
            "lookahead": sha(Path(args.lookahead)),
            "recursive": sha(Path(args.recursive)),
            "instrumentation": sha(Path(args.instrumentation)),
        },
    }
    (outdir / "CAPA_DEF_LOOKAHEAD_001.json").write_text(json.dumps(capa, indent=2) + "\n")

    baseline_row = next(
        (row for row in matrix.get("rows", []) if row.get("label") == "champion_contract"),
        {},
    )
    funnel = {
        "contract": "FQT_V23_IP07_FULL_UNIVERSE_FUNNEL_V1",
        "status": "PASS_INSTRUMENTED" if parity_pass else "FAIL",
        "utc": now(),
        "candles": parity.get("aggregate", {}).get("candles"),
        "raw_path_candidates": parity.get("aggregate", {}).get("raw_path_candidates"),
        "entry_allowed": parity.get("aggregate", {}).get("entry_allowed"),
        "final_entries_after_collision": parity.get("aggregate", {}).get("final_entries"),
        "vector_exits": parity.get("aggregate", {}).get("vector_exits"),
        "same_candle_collisions": parity.get("aggregate", {}).get("same_candle_collisions"),
        "same_candle_collision_violations": same_candle_violations,
        "backtest_closed_trades_matrix_window": baseline_row.get("trades"),
        "backtest_rejected_signals_matrix_window": baseline_row.get("rejected_signals"),
        "gate_pass_counts": parity.get("aggregate_gate_counts"),
        "veto_reason_counts": parity.get("aggregate_veto_counts"),
        "interpretation": (
            "Vectorized funnel is now observable. Pair-slot/capital competition and limit fill rejection "
            "remain backtester-level aggregates and require the next execution challenger pipeline."
        ),
    }
    (outdir / "FUNNEL_RECEIPT.json").write_text(json.dumps(funnel, indent=2) + "\n")

    final = {
        "contract": "FQT_V23_IP07_CORRECTNESS_GATE_CLOSURE_V1",
        "status": "PASS_WITH_EQUIVALENT_HARNESS" if overall_pass else "BLOCKED",
        "utc": now(),
        "champion": "M4PioneerValidationV14",
        "alpha_change": False,
        "diagnostic_only_classes": [
            "M4PioneerValidationV14LookaheadStakeNeutral",
            "M4PioneerValidationV14LookaheadExecutionNeutral",
        ],
        "gates": gates,
        "overall_pass": overall_pass,
        "decision": "KEEP_CHAMPION",
        "oos": "DO_NOT_OPEN",
        "dry_run": "DO_NOT_START",
        "live": "FORBIDDEN",
        "next_work_package": (
            "IP08_MINIMAL_EXECUTION_GUARD_CHALLENGER"
            if overall_pass
            else "DEF_LOOKAHEAD_001_CONTINUATION"
        ),
    }
    (outdir / "IP07_FINAL_STATUS.json").write_text(json.dumps(final, indent=2) + "\n")

    if overall_pass:
        next_prompt = """PLSGO FQT-RND-V2.3 IP08 | MODE=FAIL_CLOSED | CHAMPION=M4PioneerValidationV14 | WIP_LIMIT=1 | FIRST=MINIMAL_EXECUTION_GUARD_CHALLENGER | USE_IP07_FUNNEL=true | CHANGE_CLASS=one causal exit/tail-loss repair only | REQUIRE=signal_hash_delta_declared + Dev ablation + rolling/anchored nested WF + pair holdout + LOPO/top-N-removal + fee_0.10..0.30 + spread/slippage + delay_+1/+2 + bootstrap/MC | PROMOTE_ONLY_IF=practical_uplift_and_all_gates | OOS=DO_NOT_OPEN | DRY_RUN=DO_NOT_START | LIVE=FORBIDDEN"""
    else:
        next_prompt = """PLSGO FQT-RND-V2.3 IP07R2 | MODE=FAIL_CLOSED | CHAMPION=M4PioneerValidationV14 | WIP_LIMIT=1 | FIRST=DEF-LOOKAHEAD-001 | USE=IP07_VARIANT_MATRIX_AND_INSTRUMENTED_LOGS | REPAIR=smallest failing helper override or diagnostic callback | REQUIRE=31-pair signal parity + >=10 native analyzed trades + explicit no-bias verdict + 31-pair recursive matrix | OOS=DO_NOT_OPEN | DRY_RUN=DO_NOT_START | LIVE=FORBIDDEN"""
    (outdir / "NEXT_ITERATION_PROMPT.md").write_text(next_prompt + "\n")

    report = f"""# IP07 Correctness Gate Closure

- Status: **{final['status']}**
- Champion: `M4PioneerValidationV14` — unchanged
- Helper root cause: `{matrix.get('likely_root_cause')}`
- Signal parity: `{parity.get('status')}` across {parity.get('pair_count_executed')} pairs
- Diagnostic native lookahead: `{lookahead.get('decision')}`
- Recursive matrix: `{recursive.get('status')}` — {recursive.get('pair_count_passed', 0)}/{recursive.get('pair_count_executed', 0)} pairs
- Same-candle violations: {same_candle_violations}
- Decision: **KEEP_CHAMPION**
- OOS: DO_NOT_OPEN · Dry-run: DO_NOT_START · Live: FORBIDDEN

The diagnostic subclasses are evidence harnesses, not strategy candidates. Their
acceptance requires exact inherited populate-method identity and full-universe
signal hashes equal to V14.
"""
    (outdir / "CORRECTNESS_REPORT.md").write_text(report)
    print(json.dumps(final, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
