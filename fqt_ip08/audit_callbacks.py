#!/usr/bin/env python3
"""Static inventory for the frozen champion execution-callback causality gate.

The output is evidence and test planning, not a causal PASS.  It maps effective
callbacks, state reads/writes, dataframe access, call edges and suspicious
future/state patterns so IP08 can construct callback-specific executable tests.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
from collections import defaultdict
from typing import Any

EXECUTION_CALLBACKS = {
    "custom_stake_amount",
    "custom_exit",
    "custom_entry_price",
    "custom_exit_price",
    "confirm_trade_entry",
    "confirm_trade_exit",
    "custom_stoploss",
    "custom_roi",
    "adjust_trade_position",
    "leverage",
    "bot_start",
    "bot_loop_start",
    "order_filled",
}
RISK_PATTERNS = {
    "negative_shift": "shift(-",
    "last_row_access": "iloc[-1]",
    "centered_window": "center=True",
    "expanding_window": ".expanding(",
    "open_trade_query": "Trade.get_",
    "wall_clock": "datetime.now(",
    "utc_wall_clock": "datetime.utcnow(",
    "randomness": "random.",
}


def dotted_name(node: ast.AST) -> str | None:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


class MethodAudit(ast.NodeVisitor):
    def __init__(self) -> None:
        self.self_reads: set[str] = set()
        self.self_writes: set[str] = set()
        self.calls: set[str] = set()
        self.subscript_columns: set[str] = set()
        self.metadata_pairs = False
        self.trade_attributes: set[str] = set()

    def visit_Attribute(self, node: ast.Attribute) -> None:
        name = dotted_name(node)
        if name:
            if name.startswith("self."):
                target = name.removeprefix("self.")
                if isinstance(node.ctx, ast.Store):
                    self.self_writes.add(target)
                else:
                    self.self_reads.add(target)
            if name.startswith("trade."):
                self.trade_attributes.add(name.removeprefix("trade."))
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        name = dotted_name(node.func)
        if name:
            self.calls.add(name)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        value_name = dotted_name(node.value)
        if value_name in {"dataframe", "df", "row", "last_candle"}:
            key = node.slice
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                self.subscript_columns.add(key.value)
        if isinstance(node.value, ast.Name) and node.value.id == "metadata":
            key = node.slice
            if isinstance(key, ast.Constant) and key.value == "pair":
                self.metadata_pairs = True
        self.generic_visit(node)


def source_segment(source: str, node: ast.AST) -> str:
    return ast.get_source_segment(source, node) or ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    strategy_path = pathlib.Path(args.strategy)
    source = strategy_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(strategy_path))

    classes: dict[str, dict[str, Any]] = {}
    method_nodes: dict[tuple[str, str], ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = [dotted_name(base) or source_segment(source, base) for base in node.bases]
        methods = []
        class_attrs = []
        for child in node.body:
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(child.name)
                method_nodes[(node.name, child.name)] = child
            elif isinstance(child, (ast.Assign, ast.AnnAssign)):
                targets = child.targets if isinstance(child, ast.Assign) else [child.target]
                for target in targets:
                    if isinstance(target, ast.Name):
                        class_attrs.append(target.id)
        classes[node.name] = {
            "bases": bases,
            "methods": sorted(methods),
            "class_attributes": sorted(set(class_attrs)),
        }

    def lineage(name: str) -> list[str]:
        output: list[str] = []
        seen: set[str] = set()
        current = name
        while current in classes and current not in seen:
            seen.add(current)
            output.append(current)
            local_bases = [base for base in classes[current]["bases"] if base in classes]
            current = local_bases[0] if local_bases else ""
        return output

    target = "M4PioneerValidationV14" if "M4PioneerValidationV14" in classes else "M4PioneerStableExposureV10"
    target_lineage = lineage(target)
    effective_callbacks: dict[str, str] = {}
    for callback in sorted(EXECUTION_CALLBACKS):
        for class_name in target_lineage:
            if (class_name, callback) in method_nodes:
                effective_callbacks[callback] = class_name
                break

    methods: list[dict[str, Any]] = []
    call_edges: list[dict[str, str]] = []
    state_readers: dict[str, list[str]] = defaultdict(list)
    state_writers: dict[str, list[str]] = defaultdict(list)
    for (class_name, method_name), node in sorted(method_nodes.items()):
        audit = MethodAudit()
        audit.visit(node)
        text = source_segment(source, node)
        risks = [name for name, pattern in RISK_PATTERNS.items() if pattern in text]
        for attr in audit.self_reads:
            state_readers[attr].append(f"{class_name}.{method_name}")
        for attr in audit.self_writes:
            state_writers[attr].append(f"{class_name}.{method_name}")
        for call in audit.calls:
            if call.startswith("self."):
                call_edges.append(
                    {
                        "from": f"{class_name}.{method_name}",
                        "to": call.removeprefix("self."),
                    }
                )
        methods.append(
            {
                "class": class_name,
                "method": method_name,
                "is_execution_callback": method_name in EXECUTION_CALLBACKS,
                "arguments": [arg.arg for arg in node.args.args],
                "self_reads": sorted(audit.self_reads),
                "self_writes": sorted(audit.self_writes),
                "calls": sorted(audit.calls),
                "dataframe_columns": sorted(audit.subscript_columns),
                "uses_metadata_pair": audit.metadata_pairs,
                "trade_attributes": sorted(audit.trade_attributes),
                "risk_patterns": risks,
                "lineno": node.lineno,
                "end_lineno": getattr(node, "end_lineno", None),
            }
        )

    state_graph = []
    for attribute in sorted(set(state_readers) | set(state_writers)):
        state_graph.append(
            {
                "attribute": attribute,
                "writers": sorted(state_writers.get(attribute, [])),
                "readers": sorted(state_readers.get(attribute, [])),
                "cross_method_state": bool(state_writers.get(attribute))
                and bool(state_readers.get(attribute)),
            }
        )

    prioritized_tests = [
        {
            "priority": 1,
            "callback": "custom_stake_amount",
            "test": "timestamp-prefix and shuffled-pair-order invariance at fixed wallet/slot state",
            "kill": "stake depends on future candles, later pair rows or mutable cross-pair state",
        },
        {
            "priority": 2,
            "callback": "custom_exit",
            "test": "prefix replay over every trade timestamp with frozen analyzed dataframe",
            "kill": "exit reason/rate changes when future candles are appended",
        },
        {
            "priority": 3,
            "callback": "confirm_trade_entry/exit",
            "test": "same-candle, order-state and pair-order metamorphic matrix",
            "kill": "decision depends on future order/trade state",
        },
        {
            "priority": 4,
            "callback": "custom_entry_price/custom_exit_price",
            "test": "proposed-rate parity and no future dataframe access",
            "kill": "price differs under future append or pair-order permutation",
        },
        {
            "priority": 5,
            "callback": "custom_stoploss/custom_roi/adjust_trade_position",
            "test": "explicit disabled-path assertion or timestamp-prefix replay",
            "kill": "nominally disabled callback mutates execution",
        },
    ]

    output = {
        "contract": "FQT_IP08_CALLBACK_STATIC_CAUSALITY_INVENTORY_V1",
        "classification": "STATIC_INVENTORY_NOT_CAUSAL_PASS",
        "strategy": strategy_path.name,
        "target_class": target,
        "lineage": target_lineage,
        "effective_execution_callbacks": effective_callbacks,
        "classes": classes,
        "methods": methods,
        "state_dependency_graph": state_graph,
        "call_edges": call_edges,
        "prioritized_executable_tests": prioritized_tests,
        "gate_closed": False,
        "next_action": "build callback-specific timestamp-prefix and portfolio-state harnesses",
    }
    pathlib.Path(args.out).write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                "contract": output["contract"],
                "target_class": target,
                "lineage": target_lineage,
                "effective_callback_count": len(effective_callbacks),
                "state_nodes": len(state_graph),
                "gate_closed": False,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
