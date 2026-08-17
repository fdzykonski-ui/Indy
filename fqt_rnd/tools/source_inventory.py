#!/usr/bin/env python3
"""Create the bounded Source-of-Truth inventory for the supplied checkout."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "reconstruction/freqtrade"
USER_DATA = UPSTREAM / "user_data"


def run(*args: str) -> str:
    return subprocess.run(args, cwd=UPSTREAM, check=True, text=True, capture_output=True).stdout.strip()


def count(paths: Iterable[Path]) -> int:
    return sum(1 for path in paths if path.is_file())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    strategy_files = sorted((USER_DATA / "strategies").rglob("*.py"))
    strategy_backup_files = sorted((USER_DATA / "strategy_Backups").rglob("*.py"))
    config_files = sorted(USER_DATA.glob("*.json")) + sorted((USER_DATA / "configs").rglob("*.json"))
    data_files = sorted((USER_DATA / "data").rglob("*"))
    backtest_files = sorted((USER_DATA / "backtest_results").rglob("*"))
    hyperopt_files = sorted((USER_DATA / "hyperopt_results").rglob("*"))
    log_files = sorted((USER_DATA / "logs").rglob("*"))
    usdc_one_minute = [p for p in data_files if p.is_file() and "_USDC-1m." in p.name]

    archive_manifest = json.loads((ROOT / "audit/source_archive_manifest.inspect.json").read_text())
    extraction_manifest = json.loads((ROOT / "audit/source_archive_manifest.extract.json").read_text())
    quality = json.loads((ROOT / "audit/data_quality/ohlcv_quality_summary.json").read_text())
    champion_manifest = json.loads((ROOT / "champion/CHAMPION_MANIFEST.json").read_text())
    inventory = {
        "schema_version": 1,
        "generated_from": "immutable supplied reconstruction plus secret-free research layer",
        "upstream_checkout": {
            "path": "reconstruction/freqtrade",
            "branch": run("git", "branch", "--show-current"),
            "commit": run("git", "rev-parse", "HEAD"),
            "describe": run("git", "describe", "--tags", "--always", "--dirty"),
            "dirty": bool(run("git", "status", "--porcelain")),
            "remote": run("git", "remote", "get-url", "origin"),
            "truth_status": "VERIFIZIERT",
            "policy": "read-only; user-owned dirty checkout is never modified or published",
        },
        "source_archive": {
            "combined_sha256": archive_manifest.get("combined_sha256"),
            "combined_bytes": archive_manifest.get("combined_bytes"),
            "entry_count": int(extraction_manifest.get("regular_files", 0))
            + int(extraction_manifest.get("directories", 0)),
            "regular_files": extraction_manifest.get("regular_files"),
            "directories": extraction_manifest.get("directories"),
            "truth_status": "VERIFIZIERT",
        },
        "inventories": {
            "active_strategy_python_files": count(strategy_files),
            "strategy_backup_python_files": count(strategy_backup_files),
            "config_json_files": count(config_files),
            "market_data_files": count(data_files),
            "backtest_result_files_in_supplied_user_data": count(backtest_files),
            "hyperopt_result_files_in_supplied_user_data": count(hyperopt_files),
            "normal_log_files_in_supplied_user_data": count(log_files),
            "research_result_archives_created_locally": count((ROOT / "results").glob("**/*.zip")),
            "truth_status": "VERIFIZIERT",
        },
        "eligible_market_data": {
            "files": [
                {"path": path.relative_to(UPSTREAM).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
                for path in usdc_one_minute
            ],
            "available_pairs": ["BTC/USDC"] if usdc_one_minute else [],
            "requested_multi_pair_universe_status": "BLOCKIERT",
            "blocker": "Only BTC/USDC 1m USDC-quoted OHLCV is present; no 30-pair USDC universe exists.",
            "data_quality_reference": "audit/data_quality/ohlcv_quality_summary.json",
            "quality_truth_status": quality.get("status", "TEILWEISE VERIFIZIERT"),
            "provenance_truth_status": "TEILWEISE VERIFIZIERT",
        },
        "historical_champion": {
            "strategy": "ED8",
            "version": "V741",
            "frozen_strategy_sha256": champion_manifest.get("strategy_sha256"),
            "selection_status": "VERIFIZIERT",
            "deployment_status": "NICHT VERIFIZIERT",
        },
        "missing_primary_evidence": [
            {
                "item": "normal supplied backtest result directory",
                "status": "BLOCKIERT",
                "reason": "directory exists but contains no result files; only separately attached V741 evidence is available",
            },
            {
                "item": "supplied Hyperopt trials/seeds",
                "status": "BLOCKIERT",
                "reason": "hyperopt_results contains no result artifacts",
            },
            {
                "item": "30-pair USDC market universe and delisting history",
                "status": "BLOCKIERT",
                "reason": "not supplied, so survivorship and pair-holdout claims cannot be tested",
            },
        ],
    }
    target = ROOT / "audit/source_of_truth_inventory.json"
    target.write_text(json.dumps(inventory, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": target.relative_to(ROOT).as_posix(), "active_strategies": len(strategy_files)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
