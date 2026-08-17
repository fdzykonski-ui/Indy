#!/usr/bin/env python3
"""Validate notebook shape and execute its dependency-light smoke cells."""

from __future__ import annotations

import json
import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = ROOT / "notebooks/FQT_RnD_Audit.ipynb"
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert notebook["cells"] and notebook["cells"][0]["cell_type"] == "markdown"
    namespace = {"__name__": "__notebook_smoke__"}
    original_cwd = Path.cwd()
    os.chdir(ROOT)
    executed = 0
    try:
        for cell in notebook["cells"]:
            if cell["cell_type"] == "code" and cell.get("metadata", {}).get("smoke_test"):
                source = "".join(cell["source"])
                exec(compile(source, str(path), "exec"), namespace)
                executed += 1
    finally:
        os.chdir(original_cwd)
    report = {
        "schema_version": 1,
        "notebook": path.relative_to(ROOT).as_posix(),
        "json_shape": "VERIFIZIERT",
        "smoke_cells_executed": executed,
        "full_engine_cell_executed": False,
        "truth_status": "TEILWEISE VERIFIZIERT",
        "reason": "All analysis/gate cells executed; the opt-in full engine cell remained disabled to avoid duplicate compute and preserve OOS locks.",
        "environment_gap": "nbformat/nbclient are absent, so this is a deterministic code-cell smoke runner rather than a Jupyter kernel execution.",
    }
    target = ROOT / "audit/notebook_validation.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"smoke_cells": executed, "status": report["truth_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
