#!/usr/bin/env python3
"""Dependency-light verification runner for environments without pytest."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_json(path: str, predicate: Callable[[dict], bool], description: str) -> None:
    data = json.loads((ROOT / path).read_text(encoding="utf-8"))
    assert predicate(data), description


def main() -> int:
    checks: list[tuple[str, Callable[[], None]]] = []
    for test_file in (ROOT / "tests/test_research_contract.py", ROOT / "tests/test_offline_catalog.py"):
        module = load_module(test_file)
        for name in sorted(dir(module)):
            candidate = getattr(module, name)
            if name.startswith("test_") and callable(candidate):
                checks.append((f"{test_file.name}::{name}", candidate))
    checks.extend(
        [
            ("deterministic reproduction", lambda: check_json("audit/deterministic_reproduction.json", lambda d: d["truth_status"] == "VERIFIZIERT", "determinism failed")),
            ("OHLCV integrity", lambda: check_json("audit/data_quality/ohlcv_quality_summary.json", lambda d: d["status"] == "VERIFIZIERT", "data quality failed")),
            ("runtime signal semantics", lambda: check_json("audit/runtime_signal_audit.json", lambda d: d["truth_status"] == "VERIFIZIERT", "signal timing failed")),
            ("publishable secret scan", lambda: check_json("audit/secret_scan.json", lambda d: d["publishable_tree"]["truth_status"] == "VERIFIZIERT", "secret scan failed")),
            (
                "portable report validation",
                lambda: check_json(
                    "report/delivery_receipt.json",
                    lambda d: d.get("ok") is True
                    and d.get("stages", {}).get("validation") == "passed"
                    and d.get("stages", {}).get("package") == "passed",
                    "portable report did not validate/package",
                ),
            ),
            ("OOS remains sealed", lambda: (_ for _ in ()).throw(AssertionError("OOS results unexpectedly exist")) if (ROOT / "results/oos").exists() else None),
            ("promotion is blocked", lambda: check_json("decisions/promotion_decision.json", lambda d: not d["all_targets_pass"] and "NO OOS" in d["decision"], "promotion gate opened")),
        ]
    )
    results = []
    for name, function in checks:
        try:
            function()
            results.append({"check": name, "status": "PASS"})
        except Exception as exc:
            results.append({"check": name, "status": "FAIL", "error": f"{type(exc).__name__}: {exc}"})

    py_files = [
        *sorted((ROOT / "tools").glob("*.py")),
        *sorted((ROOT / "strategies").glob("*.py")),
        *sorted((ROOT / "champion/controls").glob("*.py")),
    ]
    compile_run = subprocess.run([sys.executable, "-m", "py_compile", *map(str, py_files)], text=True, capture_output=True)
    results.append({"check": "python bytecode compilation", "status": "PASS" if compile_run.returncode == 0 else "FAIL", "error": compile_run.stderr.strip() or None})
    passed = sum(result["status"] == "PASS" for result in results)
    report = {
        "schema_version": 1,
        "runner": "tools/verify_project.py (pytest unavailable)",
        "checks": results,
        "passed": passed,
        "failed": len(results) - passed,
        "truth_status": "VERIFIZIERT" if passed == len(results) else "NICHT VERIFIZIERT",
    }
    target = ROOT / "audit/verification_results.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"passed": passed, "failed": len(results) - passed, "status": report["truth_status"]}))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
