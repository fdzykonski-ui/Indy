#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import zipfile
from collections import defaultdict
from datetime import datetime, timezone


def canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load(path: pathlib.Path, strategy_name: str):
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f"zip CRC failure: {bad}")
        names = [name for name in zf.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        if len(names) != 1:
            raise RuntimeError(f"result JSON count={len(names)}")
        obj = json.loads(zf.read(names[0]))
    if strategy_name not in obj.get("strategy", {}):
        raise KeyError(f"{strategy_name!r} missing; available={list(obj.get('strategy', {}))}")
    return obj["strategy"][strategy_name]


def finite(value):
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def month_from_timestamp(value) -> str:
    if value is None:
        return "unknown"
    number = float(value)
    seconds = number / 1000.0 if number > 10_000_000_000 else number
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m")


def aggregate(trades, key_fn):
    buckets = defaultdict(lambda: {"trades": 0, "wins": 0, "draws": 0, "losses": 0, "profit_usdc": 0.0, "gross_win": 0.0, "gross_loss": 0.0})
    for trade in trades:
        key = str(key_fn(trade))
        profit = float(trade.get("profit_abs", 0.0))
        bucket = buckets[key]
        bucket["trades"] += 1
        bucket["profit_usdc"] += profit
        if profit > 0:
            bucket["wins"] += 1
            bucket["gross_win"] += profit
        elif profit < 0:
            bucket["losses"] += 1
            bucket["gross_loss"] += abs(profit)
        else:
            bucket["draws"] += 1
    rows = []
    for key, bucket in buckets.items():
        count = bucket["trades"]
        loss = bucket["gross_loss"]
        rows.append({
            "key": key,
            **bucket,
            "winrate_pct": 100.0 * bucket["wins"] / count if count else 0.0,
            "profit_factor": bucket["gross_win"] / loss if loss > 0 else None,
        })
    return sorted(rows, key=lambda row: row["key"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--timerange", required=True)
    parser.add_argument("--pair-order", default="original")
    args = parser.parse_args()

    result = load(args.result, args.strategy)
    trades = list(result.get("trades", []))
    wins = sum(float(t.get("profit_ratio", 0.0)) > 0 for t in trades)
    losses = sum(float(t.get("profit_ratio", 0.0)) < 0 for t in trades)
    draws = len(trades) - wins - losses
    normalized = [
        {
            "pair": t.get("pair"), "open_timestamp": t.get("open_timestamp"),
            "close_timestamp": t.get("close_timestamp"), "enter_tag": t.get("enter_tag"),
            "exit_reason": t.get("exit_reason"), "profit_ratio": t.get("profit_ratio"),
            "profit_abs": t.get("profit_abs"), "stake_amount": t.get("stake_amount"),
        }
        for t in trades
    ]
    summary = {
        "contract": "FQT_V25_GENERIC_BACKTEST_SUMMARY_V2",
        "label": args.label,
        "strategy": args.strategy,
        "timerange": args.timerange,
        "pair_order": args.pair_order,
        "trades": len(trades), "wins": wins, "draws": draws, "losses": losses,
        "winrate_pct": 100.0 * wins / len(trades) if trades else 0.0,
        "profit_usdc": result.get("profit_total_abs"),
        "profit_pct": 100.0 * float(result.get("profit_total", 0.0)),
        "profit_factor": finite(result.get("profit_factor")),
        "max_drawdown_abs": result.get("max_drawdown_abs"),
        "max_drawdown_pct": 100.0 * float(result.get("max_drawdown_account", 0.0)),
        "starting_balance": result.get("starting_balance"),
        "final_balance": result.get("final_balance"),
        "rejected_signals": result.get("rejected_signals"),
        "result_zip_sha256": hashlib.sha256(args.result.read_bytes()).hexdigest(),
        "semantic_trade_ledger_sha256": canonical_sha(normalized),
        "monthly_metrics": aggregate(trades, lambda t: month_from_timestamp(t.get("close_timestamp"))),
        "pair_metrics": aggregate(trades, lambda t: t.get("pair") or "<none>"),
        "tag_metrics": aggregate(trades, lambda t: t.get("enter_tag") or "<none>"),
        "exit_metrics": aggregate(trades, lambda t: t.get("exit_reason") or "<none>"),
        "status": "EXECUTED",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ["label", "strategy", "trades", "winrate_pct", "profit_pct", "profit_factor", "max_drawdown_pct", "semantic_trade_ledger_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
