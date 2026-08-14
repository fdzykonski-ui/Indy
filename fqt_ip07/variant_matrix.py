#!/usr/bin/env python3
"""One-factor-at-a-time diagnosis of Freqtrade lookahead execution overrides."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd


def parse_result(path: Path, requested_strategy: str) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        names = [
            name
            for name in zf.namelist()
            if name.endswith(".json")
            and not name.endswith("_config.json")
            and not name.endswith(".meta.json")
        ]
        candidates = []
        for name in names:
            try:
                obj = json.loads(zf.read(name))
            except Exception:
                continue
            if isinstance(obj, dict) and "strategy" in obj:
                candidates.append((name, obj))
        if len(candidates) != 1:
            raise RuntimeError(f"{path}: expected one result JSON, found {len(candidates)}")
        _, obj = candidates[0]
    strategy_map = obj["strategy"]
    if requested_strategy in strategy_map:
        result = strategy_map[requested_strategy]
    elif len(strategy_map) == 1:
        result = next(iter(strategy_map.values()))
    else:
        raise RuntimeError(f"{path}: strategy {requested_strategy!r} absent")
    trades = list(result.get("trades", []))
    exits = Counter(str(row.get("exit_reason")) for row in trades)
    return {
        "trades": int(result.get("total_trades", len(trades))),
        "wins": int(result.get("wins", 0)),
        "draws": int(result.get("draws", 0)),
        "losses": int(result.get("losses", 0)),
        "winrate_pct": float(result.get("winrate", 0.0)) * 100.0,
        "profit_usdc": float(result.get("profit_total_abs", 0.0)),
        "profit_pct": float(result.get("profit_total", 0.0)) * 100.0,
        "profit_factor": float(result.get("profit_factor", 0.0) or 0.0),
        "rejected_signals": int(result.get("rejected_signals", 0)),
        "max_drawdown_account_pct": float(result.get("max_drawdown_account", 0.0)) * 100.0,
        "exit_reasons": dict(exits),
        "result_zip": str(path),
    }


def make_config(base: dict[str, Any], variant: dict[str, Any], path: Path) -> dict[str, Any]:
    cfg = json.loads(json.dumps(base))
    cfg["strategy"] = variant["strategy"]
    cfg["max_open_trades"] = variant["max_open_trades"]
    cfg["dry_run_wallet"] = variant["dry_run_wallet"]
    cfg["stake_amount"] = variant["stake_amount"]
    cfg["dry_run"] = True
    cfg["initial_state"] = "stopped"
    cfg["enable_protections"] = False
    cfg["lookahead_allow_limit_orders"] = variant["order_mode"] == "limit"
    if variant["order_mode"] == "market":
        cfg["order_types"] = {
            "entry": "market",
            "exit": "market",
            "stoploss": "market",
            "stoploss_on_exchange": False,
            "emergency_exit": "market",
        }
        cfg.setdefault("entry_pricing", {})["price_side"] = "other"
        cfg.setdefault("exit_pricing", {})["price_side"] = "other"
    else:
        cfg.pop("order_types", None)
        cfg.setdefault("entry_pricing", {})["price_side"] = "same"
        cfg.setdefault("exit_pricing", {})["price_side"] = "same"
    path.write_text(json.dumps(cfg, indent=2) + "\n")
    return cfg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-config", required=True)
    ap.add_argument("--offline-wrapper", required=True)
    ap.add_argument("--timerange", default="20260101-20260201")
    ap.add_argument("--outdir", required=True)
    args = ap.parse_args()

    root = Path.cwd()
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    configs = outdir / "configs"
    logs = outdir / "logs"
    results = outdir / "results"
    for path in (configs, logs, results):
        path.mkdir(parents=True, exist_ok=True)
    backtest_results = root / "user_data/backtest_results"
    backtest_results.mkdir(parents=True, exist_ok=True)

    base = json.loads(Path(args.base_config).read_text())
    variants = [
        {"label": "champion_contract", "strategy": "M4PioneerValidationV14", "max_open_trades": 2, "dry_run_wallet": 1000, "stake_amount": "unlimited", "order_mode": "limit"},
        {"label": "wallet_1b_only", "strategy": "M4PioneerValidationV14", "max_open_trades": 2, "dry_run_wallet": 1_000_000_000, "stake_amount": "unlimited", "order_mode": "limit"},
        {"label": "stake_10k_after_wallet", "strategy": "M4PioneerValidationV14", "max_open_trades": 2, "dry_run_wallet": 1_000_000_000, "stake_amount": 10000, "order_mode": "limit"},
        {"label": "helper_all_limit", "strategy": "M4PioneerValidationV14", "max_open_trades": -1, "dry_run_wallet": 1_000_000_000, "stake_amount": 10000, "order_mode": "limit"},
        {"label": "helper_all_market", "strategy": "M4PioneerValidationV14", "max_open_trades": -1, "dry_run_wallet": 1_000_000_000, "stake_amount": 10000, "order_mode": "market"},
        {"label": "stake_neutral_limit", "strategy": "M4PioneerValidationV14LookaheadStakeNeutral", "max_open_trades": -1, "dry_run_wallet": 1_000_000_000, "stake_amount": 10000, "order_mode": "limit"},
        {"label": "stake_neutral_market", "strategy": "M4PioneerValidationV14LookaheadStakeNeutral", "max_open_trades": -1, "dry_run_wallet": 1_000_000_000, "stake_amount": 10000, "order_mode": "market"},
        {"label": "execution_neutral_limit", "strategy": "M4PioneerValidationV14LookaheadExecutionNeutral", "max_open_trades": -1, "dry_run_wallet": 1_000_000_000, "stake_amount": 10000, "order_mode": "limit"},
        {"label": "execution_neutral_market", "strategy": "M4PioneerValidationV14LookaheadExecutionNeutral", "max_open_trades": -1, "dry_run_wallet": 1_000_000_000, "stake_amount": 10000, "order_mode": "market"},
    ]

    rows: list[dict[str, Any]] = []
    for variant in variants:
        label = variant["label"]
        cfg_path = configs / f"{label}.json"
        make_config(base, variant, cfg_path)
        for old in backtest_results.glob("*"):
            if old.is_file() or old.is_symlink():
                old.unlink()
            elif old.is_dir():
                shutil.rmtree(old)
        cmd = [
            sys.executable,
            args.offline_wrapper,
            "backtesting",
            "-c",
            str(cfg_path),
            "--strategy-path",
            "user_data/strategies",
            "-s",
            variant["strategy"],
            "-i",
            "1m",
            "--timerange",
            args.timerange,
            "--fee",
            "0.001",
            "--export",
            "trades",
            "--cache",
            "none",
            "--no-color",
        ]
        started = time.perf_counter()
        cp = subprocess.run(
            cmd,
            cwd=root,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        elapsed = time.perf_counter() - started
        log_path = logs / f"{label}.log"
        log_path.write_text(cp.stdout)
        row: dict[str, Any] = {**variant, "timerange": args.timerange, "exit_code": cp.returncode, "elapsed_seconds": elapsed, "command": cmd}
        result_zips = sorted(backtest_results.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime)
        if cp.returncode == 0 and result_zips:
            result_copy = results / f"{label}.zip"
            shutil.copy2(result_zips[-1], result_copy)
            row.update(parse_result(result_copy, variant["strategy"]))
            row["status"] = "EXECUTED"
        else:
            row.update({"trades": 0, "status": "ERROR", "error_tail": cp.stdout[-4000:]})
        rows.append(row)
        Path(outdir / "VARIANT_MATRIX_PARTIAL.json").write_text(json.dumps(rows, indent=2, default=str) + "\n")
        print(json.dumps({"label": label, "status": row["status"], "trades": row["trades"], "elapsed_seconds": round(elapsed, 1)}))

    by_label = {row["label"]: row for row in rows}
    baseline = int(by_label["champion_contract"]["trades"])
    # Freqtrade rejects max_open_trades=-1 together with stake_amount=unlimited.
    # Diagnose the helper's overrides as a valid sequential ablation instead:
    # champion -> wallet 1B -> static stake 10k -> max_open -1 -> market orders.
    sequence = [
        ("champion_contract", "baseline"),
        ("wallet_1b_only", "wallet_1b"),
        ("stake_10k_after_wallet", "static_stake_10k"),
        ("helper_all_limit", "max_open_unlimited_pairs"),
        ("helper_all_market", "market_order_override"),
    ]
    root_cause = "not_reproduced_in_matrix_window"
    stage_deltas = []
    previous_label, previous_stage = sequence[0]
    previous_trades = int(by_label[previous_label]["trades"])
    for label, stage in sequence[1:]:
        current_trades = int(by_label[label]["trades"])
        stage_deltas.append({
            "from": previous_label,
            "to": label,
            "stage": stage,
            "from_trades": previous_trades,
            "to_trades": current_trades,
            "delta_trades": current_trades - previous_trades,
        })
        if root_cause == "not_reproduced_in_matrix_window" and previous_trades >= 10 > current_trades:
            root_cause = "sequential_stage:" + stage
        previous_label = label
        previous_trades = current_trades

    diagnostic_priority = [
        "stake_neutral_market",
        "stake_neutral_limit",
        "execution_neutral_market",
        "execution_neutral_limit",
    ]
    selected = next(
        (label for label in diagnostic_priority if int(by_label[label]["trades"]) >= 10),
        None,
    )
    summary = {
        "contract": "FQT_V23_IP07_LOOKAHEAD_OVERRIDE_MATRIX_V1",
        "timerange": args.timerange,
        "baseline_trades": baseline,
        "helper_all_limit_trades": int(by_label["helper_all_limit"]["trades"]),
        "helper_all_market_trades": int(by_label["helper_all_market"]["trades"]),
        "likely_root_cause": root_cause,
        "sequential_stage_deltas": stage_deltas,
        "selected_diagnostic_variant": selected,
        "selected_strategy": by_label[selected]["strategy"] if selected else None,
        "selected_order_mode": by_label[selected]["order_mode"] if selected else None,
        "diagnostic_sufficient_trades": bool(selected),
        "rows": rows,
    }
    Path(outdir / "VARIANT_MATRIX.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    pd.DataFrame(
        [
            {k: v for k, v in row.items() if k not in {"command", "exit_reasons", "error_tail"}}
            for row in rows
        ]
    ).to_csv(outdir / "VARIANT_MATRIX.csv", index=False)
    print(json.dumps({k: summary[k] for k in ["baseline_trades", "helper_all_limit_trades", "helper_all_market_trades", "likely_root_cause", "selected_diagnostic_variant"]}, indent=2))
    return 0 if baseline >= 10 and selected else 2


if __name__ == "__main__":
    raise SystemExit(main())
