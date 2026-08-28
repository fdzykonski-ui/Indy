#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import zipfile


def strict(value):
    if isinstance(value, dict):
        return {str(k): strict(v) for k, v in value.items()}
    if isinstance(value, list):
        return [strict(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return "Infinity" if value > 0 else "-Infinity"
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--result", type=pathlib.Path, required=True)
    ap.add_argument("--out", type=pathlib.Path, required=True)
    ap.add_argument("--label", required=True)
    args = ap.parse_args()
    with zipfile.ZipFile(args.result) as zf:
        result_names = [n for n in zf.namelist() if n.endswith(".json") and not n.endswith("_config.json")]
        if len(result_names) != 1:
            raise SystemExit(f"expected one result JSON, found {result_names}")
        payload = json.loads(zf.read(result_names[0]))
    if len(payload.get("strategy", {})) != 1:
        raise SystemExit("expected one strategy result")
    strategy_name, s = next(iter(payload["strategy"].items()))
    trades = s.get("trades", [])
    wins = sum(float(t.get("profit_ratio", 0.0)) > 0 for t in trades)
    losses = sum(float(t.get("profit_ratio", 0.0)) < 0 for t in trades)
    draws = len(trades) - wins - losses
    trade_fields = (
        "pair", "open_timestamp", "close_timestamp", "enter_tag", "exit_reason",
        "is_short", "leverage", "stake_amount", "amount", "open_rate", "close_rate",
        "profit_ratio", "profit_abs", "fee_open", "fee_close", "trade_duration",
        "min_rate", "max_rate",
    )
    canonical = [{k: t.get(k) for k in trade_fields} for t in trades]
    ledger_sha = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    out = {
        "contract": "FQT_M6R36_NATIVE_RESULT_V1",
        "label": args.label,
        "strategy": strategy_name,
        "trades": len(trades),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "winrate_pct": 100.0 * wins / len(trades) if trades else 0.0,
        "profit_usdc": s.get("profit_total_abs"),
        "profit_pct": 100.0 * float(s.get("profit_total", 0.0)),
        "profit_factor": s.get("profit_factor"),
        "max_drawdown_abs": s.get("max_drawdown_abs"),
        "max_drawdown_pct": 100.0 * float(s.get("max_drawdown_account", 0.0)),
        "starting_balance": s.get("starting_balance"),
        "final_balance": s.get("final_balance"),
        "max_open_trades": s.get("max_open_trades"),
        "max_open_trades_setting": s.get("max_open_trades_setting"),
        "stake_amount": s.get("stake_amount"),
        "timerange": s.get("timerange"),
        "backtest_start": s.get("backtest_start"),
        "backtest_end": s.get("backtest_end"),
        "periodic_breakdown": s.get("periodic_breakdown"),
        "results_per_pair": s.get("results_per_pair"),
        "results_per_enter_tag": s.get("results_per_enter_tag"),
        "exit_reason_summary": s.get("exit_reason_summary"),
        "trade_ledger_sha256": ledger_sha,
        "result_zip_sha256": hashlib.sha256(args.result.read_bytes()).hexdigest(),
        "result_member": result_names[0],
        "status": "EXECUTED",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(strict(out), indent=2, allow_nan=False) + "\n")
    print(json.dumps(strict(out), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
