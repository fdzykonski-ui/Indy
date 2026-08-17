#!/usr/bin/env python3
"""Collect Freqtrade result archives without copying embedded credentials.

Only the backtest result payload and a narrow allow-list from its config are
read.  No secret-bearing config is ever emitted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import zipfile
from pathlib import Path
from typing import Any


METRIC_KEYS = (
    "strategy_name",
    "timerange",
    "backtest_start",
    "backtest_end",
    "backtest_days",
    "timeframe",
    "trading_mode",
    "stake_currency",
    "stake_amount",
    "starting_balance",
    "final_balance",
    "max_open_trades",
    "total_trades",
    "trades_per_day",
    "wins",
    "draws",
    "losses",
    "winrate",
    "profit_total",
    "profit_total_abs",
    "profit_factor",
    "max_drawdown_account",
    "market_change",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def payload_names(archive: zipfile.ZipFile) -> tuple[str, str | None]:
    result_names = [
        name
        for name in archive.namelist()
        if name.endswith(".json")
        and not name.endswith("_config.json")
        and not name.endswith(".meta.json")
    ]
    if len(result_names) != 1:
        raise ValueError(f"expected one result JSON, found {result_names}")
    config_names = [name for name in archive.namelist() if name.endswith("_config.json")]
    return result_names[0], config_names[0] if len(config_names) == 1 else None


def safe_config_fields(archive: zipfile.ZipFile, config_name: str | None) -> dict[str, Any]:
    if not config_name:
        return {}
    config = json.loads(archive.read(config_name))
    return {
        "fee": config.get("fee"),
        "dry_run": config.get("dry_run"),
        "exchange_name": (config.get("exchange") or {}).get("name"),
        "pair_whitelist": (config.get("exchange") or {}).get("pair_whitelist"),
    }


def normalize_number(value: Any) -> Any:
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def archive_rows(root: Path, archive_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with zipfile.ZipFile(archive_path) as archive:
        result_name, config_name = payload_names(archive)
        payload = json.loads(archive.read(result_name))
        safe_config = safe_config_fields(archive, config_name)

    relative = archive_path.relative_to(root).as_posix()
    raw_sensitive = relative.startswith("evidence/") and "/backtests/" in relative
    rows: list[dict[str, Any]] = []
    for strategy_name, result in payload.get("strategy", {}).items():
        wallet = result.get("wallet_stats") or {}
        losses = int(result.get("losses") or 0)
        profit_factor = normalize_number(result.get("profit_factor"))
        total_trades = int(result.get("total_trades") or 0)
        if total_trades == 0:
            pf_state = "UNDEFINED_NO_TRADES"
        elif losses == 0 and (profit_factor is None or float(profit_factor) == 0.0):
            pf_state = "UNDEFINED_NO_LOSSES"
        else:
            pf_state = "FINITE"
        trades = result.get("trades") or []
        row = {
            "run_id": f"{archive_path.parent.name}:{strategy_name}",
            "artifact": relative,
            "artifact_sha256": sha256_file(archive_path),
            "raw_sensitive_archive": raw_sensitive,
            "result_member": result_name,
            "strategy": strategy_name,
            "fee": safe_config.get("fee") if safe_config.get("fee") is not None else (
                trades[0].get("fee_open") if trades else None
            ),
            "exchange": safe_config.get("exchange_name"),
            "pairlist": result.get("pairlist") or safe_config.get("pair_whitelist"),
            "wallet_max_drawdown_pct": normalize_number(
                float(wallet.get("max_drawdown_account", 0.0)) * 100.0
            ),
            "closed_trade_max_drawdown_pct": normalize_number(
                float(result.get("max_drawdown_account", 0.0)) * 100.0
            ),
            "winrate_pct": normalize_number(float(result.get("winrate", 0.0)) * 100.0),
            "profit_pct": normalize_number(float(result.get("profit_total", 0.0)) * 100.0),
            "profit_factor_state": pf_state,
            "trades_sha256": canonical_sha256(trades),
            "truth_status": "NICHT VERIFIZIERT"
            if relative.startswith("results/champion_historical/")
            else "VERIFIZIERT",
            "result_role": "FAILED_REPRODUCTION_ATTEMPT"
            if relative.startswith("results/champion_historical/")
            else (
                "HISTORICAL_EVIDENCE"
                if relative.startswith("evidence/")
                else "LOCAL_RESEARCH_RUN"
            ),
        }
        for key in METRIC_KEYS:
            row[key] = normalize_number(result.get(key))
        rows.append(row)
    return rows, payload


def read_single_strategy(root: Path, archive_path: Path, strategy: str = "ED8") -> dict[str, Any]:
    rows, payload = archive_rows(root, archive_path)
    if strategy not in payload.get("strategy", {}):
        raise KeyError(f"{strategy} not in {archive_path}")
    result = payload["strategy"][strategy]
    return {
        "archive": archive_path.relative_to(root).as_posix(),
        "archive_sha256": sha256_file(archive_path),
        "trades": result.get("trades") or [],
        "metrics": {key: normalize_number(result.get(key)) for key in METRIC_KEYS},
        "row": next(row for row in rows if row["strategy"] == strategy),
    }


def compare_runs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    metric_differences = {
        key: {"left": left["metrics"].get(key), "right": right["metrics"].get(key)}
        for key in METRIC_KEYS
        if left["metrics"].get(key) != right["metrics"].get(key)
    }
    return {
        "left": left["archive"],
        "right": right["archive"],
        "trade_count_left": len(left["trades"]),
        "trade_count_right": len(right["trades"]),
        "trades_sha256_left": canonical_sha256(left["trades"]),
        "trades_sha256_right": canonical_sha256(right["trades"]),
        "trades_exactly_equal": left["trades"] == right["trades"],
        "selected_metrics_exactly_equal": not metric_differences,
        "metric_differences": metric_differences,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            serialized = {
                key: json.dumps(value, sort_keys=True) if isinstance(value, (list, dict)) else value
                for key, value in row.items()
            }
            writer.writerow(serialized)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()

    local_archives = sorted((root / "results").glob("**/*.zip"))
    historical_archives = sorted(
        (root / "evidence" / "ed8_v741").glob("**/backtests/V741_Final_*_Backtest.zip")
    )
    rows: list[dict[str, Any]] = []
    for archive in [*local_archives, *historical_archives]:
        archive_result, _ = archive_rows(root, archive)
        rows.extend(archive_result)

    results_dir = root / "results" / "summaries"
    results_dir.mkdir(parents=True, exist_ok=True)
    rows.sort(key=lambda row: (row["artifact"], row["strategy"]))
    (results_dir / "metrics_all.json").write_text(
        json.dumps({"schema_version": 1, "rows": rows}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    write_csv(results_dir / "metrics_all.csv", rows)

    historical = read_single_strategy(root, historical_archives[0])
    precision6 = read_single_strategy(
        root, next((root / "results" / "champion_historical_precision6").glob("*.zip"))
    )
    repeat = read_single_strategy(
        root, next((root / "results" / "champion_determinism_repeat").glob("*.zip"))
    )
    wrong_precision = read_single_strategy(
        root, next((root / "results" / "champion_historical").glob("*.zip"))
    )
    historical_comparison = compare_runs(historical, precision6)
    repeat_comparison = compare_runs(precision6, repeat)
    wrong_precision_comparison = compare_runs(historical, wrong_precision)
    determinism = {
        "schema_version": 1,
        "truth_status": "VERIFIZIERT"
        if historical_comparison["trades_exactly_equal"]
        and historical_comparison["selected_metrics_exactly_equal"]
        and repeat_comparison["trades_exactly_equal"]
        and repeat_comparison["selected_metrics_exactly_equal"]
        else "NICHT VERIFIZIERT",
        "historical_vs_precision6": historical_comparison,
        "precision6_vs_repeat": repeat_comparison,
        "failed_attempt_wrong_amount_precision": {
            **wrong_precision_comparison,
            "expected_result": "must differ; retained as root-cause evidence",
            "diagnosis": "offline catalog used 1e-8 BTC amount precision instead of historical 1e-6",
        },
        "scope_limit": "Exact equality proves deterministic reproduction of this artifact, not future profitability.",
    }
    audit_dir = root / "audit"
    (audit_dir / "deterministic_reproduction.json").write_text(
        json.dumps(determinism, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"rows": len(rows), "determinism": determinism["truth_status"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
