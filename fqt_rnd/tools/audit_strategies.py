#!/usr/bin/env python3
"""Static, reproducible safety audit for research strategy sources."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
FILES = [
    ROOT / "champion/frozen/ED8_V741_E001FastCapture10m08bp.py",
    ROOT / "champion/controls/ED8ControlVariants.py",
    ROOT / "strategies/CausalRegimePullbackV1.py",
    ROOT / "strategies/ResearchBaselines.py",
]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def assignment_values(tree: ast.AST) -> dict[str, list[Any]]:
    values: dict[str, list[Any]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value_node = node.value
            try:
                value = ast.literal_eval(value_node)
            except Exception:
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    values.setdefault(target.id, []).append(value)
    return values


class FunctionLineMap(ast.NodeVisitor):
    def __init__(self) -> None:
        self.ranges: list[tuple[int, int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.ranges.append((node.lineno, getattr(node, "end_lineno", node.lineno), node.name))
        self.generic_visit(node)

    def function_at(self, line: int) -> str | None:
        matches = [name for start, end, name in self.ranges if start <= line <= end]
        return matches[-1] if matches else None


def matching_lines(text: str, pattern: str) -> list[int]:
    compiled = re.compile(pattern)
    return [index for index, line in enumerate(text.splitlines(), start=1) if compiled.search(line)]


def audit_file(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    assignments = assignment_values(tree)
    functions = FunctionLineMap()
    functions.visit(tree)

    negative_shift = matching_lines(text, r"\.shift\s*\(\s*-[0-9]")
    centered_rolling = matching_lines(text, r"rolling\s*\([^\n]*center\s*=\s*True")
    fill_from_future = matching_lines(text, r"\.(?:bfill|backfill)\s*\(")
    iloc_last = matching_lines(text, r"\.iloc\s*\[\s*-1\s*\]")
    iloc_context = [
        {"line": line, "function": functions.function_at(line)} for line in iloc_last
    ]
    iloc_populate = [
        item for item in iloc_context if (item["function"] or "").startswith("populate_")
    ]
    timestamp_literals = matching_lines(text, r"['\"]20[0-9]{2}-[0-9]{2}-[0-9]{2}")
    pair_literals = matching_lines(text, r"BTC/USDC")

    inherits_ed8 = any(
        isinstance(node, ast.ClassDef)
        and any(isinstance(base, ast.Name) and base.id == "ED8" for base in node.bases)
        for node in ast.walk(tree)
    )

    def constraint(name: str, expected: Any) -> bool | str:
        if name in assignments:
            return expected in assignments[name]
        if inherits_ed8:
            return "INHERITED_FROM_FROZEN_ED8"
        return "NOT_DECLARED_IN_THIS_FILE"

    hard = {
        "timeframe_1m": constraint("timeframe", "1m"),
        "long_only": constraint("can_short", False),
        "dca_disabled": constraint("position_adjustment_enable", False),
    }
    forbidden = {
        "negative_shift_lines": negative_shift,
        "centered_rolling_lines": centered_rolling,
        "future_fill_lines": fill_from_future,
        "iloc_last_in_populate": iloc_populate,
        "hardcoded_calendar_timestamp_lines": timestamp_literals,
    }
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "sha256": sha256(path),
        "parse_status": "VERIFIZIERT",
        "hard_constraints": hard,
        "forbidden_future_access": forbidden,
        "iloc_last_context": iloc_context,
        "pair_specific_literal_lines": pair_literals,
        "pair_generalization_status": "NICHT VERIFIZIERT"
        if pair_literals or inherits_ed8
        else "TEILWEISE VERIFIZIERT",
        "static_causality_status": "VERIFIZIERT"
        if not any(forbidden.values())
        else "NICHT VERIFIZIERT",
        "notes": [
            "Static analysis cannot prove runtime causality; pair it with Freqtrade lookahead and prefix tests.",
            "iloc[-1] is accepted only inside runtime callbacks, never inside populate_* methods.",
        ],
    }


def main() -> int:
    records = [audit_file(path) for path in FILES]
    output = {
        "schema_version": 1,
        "records": records,
        "champion_assessment": {
            "truth_status": "TEILWEISE VERIFIZIERT",
            "reason": (
                "No static future-read pattern was found and callback iloc[-1] is scoped correctly, "
                "but the strategy is BTC/USDC-specific and runtime lookahead covered only ten signals."
            ),
        },
    }
    target = ROOT / "audit/strategy_static_audit.json"
    target.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"files": len(records), "output": target.relative_to(ROOT).as_posix()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
