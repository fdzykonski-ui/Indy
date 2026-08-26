#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import pathlib
import zipfile
from collections import defaultdict


def canonical_sha(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def load_result(path: pathlib.Path, strategy_name: str | None):
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f"zip CRC failure: {bad}")
        names = [name for name in zf.namelist() if name.endswith(".json") and not name.endswith("_config.json")]
        if len(names) != 1:
            raise RuntimeError(f"result JSON count {len(names)} in {path}")
        payload = json.loads(zf.read(names[0]))
    strategies = payload.get("strategy", {})
    if strategy_name:
        if strategy_name not in strategies:
            raise KeyError(f"strategy {strategy_name!r} not found; available={list(strategies)}")
        return strategies[strategy_name]
    if len(strategies) != 1:
        raise RuntimeError(f"strategy count {len(strategies)}; pass --strategy")
    return next(iter(strategies.values()))


def safe_pf(value):
    try:
        number = float(value)
    except Exception:
        return None
    return number if math.isfinite(number) else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", type=pathlib.Path, required=True)
    parser.add_argument("--out", type=pathlib.Path, required=True)
    parser.add_argument("--strategy")
    parser.add_argument("--label", default="")
    parser.add_argument("--timerange", default="")
    parser.add_argument("--pair-order", default="original")
    args = parser.parse_args()

    result = load_result(args.result, args.strategy)
    trades = list(result.get("trades", []))
    wins = sum(float(trade.get("profit_ratio", 0)) > 0 for trade in trades)
    losses = sum(float(trade.get("profit_ratio", 0)) < 0 for trade in trades)
    draws = len(trades) - wins - losses
    by_pair = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "profit_usdc": 0.0, "gross_win": 0.0, "gross_loss": 0.0})
    by_tag = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "profit_usdc": 0.0, "gross_win": 0.0, "gross_loss": 0.0})
    normalized = []
    for trade in trades:
        pair = str(trade.get("pair"))
        tag = str(trade.get("enter_tag") or "<none>")
        profit_abs = float(trade.get("profit_abs", 0.0))
        profit_ratio = float(trade.get("profit_ratio", 0.0))
        for bucket in (by_pair[pair], by_tag[tag]):
            bucket["trades"] += 1
            bucket["profit_usdc"] += profit_abs
            if profit_abs > 0:
                bucket["wins"] += 1
                bucket["gross_win"] += profit_abs
            elif profit_abs < 0:
                bucket["losses"] += 1
                bucket["gross_loss"] += abs(profit_abs)
        normalized.append({
            "pair": pair,
            "open_timestamp": trade.get("open_timestamp"),
            "close_timestamp": trade.get("close_timestamp"),
            "enter_tag": trade.get("enter_tag"),
            "exit_reason": trade.get("exit_reason"),
            "profit_ratio": profit_ratio,
            "profit_abs": profit_abs,
            "stake_amount": trade.get("stake_amount"),
        })

    def finish(mapping):
        rows = []
        for key, value in mapping.items():
            trades_n = int(value["trades"])
            gross_loss = float(value["gross_loss"])
            rows.append({
                "key": key,
                **value,
                "winrate_pct": 100.0 * value["wins"] / trades_n if trades_n else 0.0,
                "profit_factor": value["gross_win"] / gross_loss if gross_loss > 0 else None,
            })
        return sorted(rows, key=lambda row: (-row["profit_usdc"], row["key"]))

    summary = {
        "contract": "FQT_V25_GENERIC_BACKTEST_SUMMARY_V1",
        "label": args.label,
        "strategy": args.strategy,
        "timerange": args.timerange,
        "pair_order": args.pair_order,
        "trades": len(trades),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "winrate_pct": 100.0 * wins / len(trades) if trades else 0.0,
        "profit_usdc": result.get("profit_total_abs"),
        "profit_pct": 100.0 * float(result.get("profit_total", 0.0)),
        "profit_factor": safe_pf(result.get("profit_factor")),
        "max_drawdown_abs": result.get("max_drawdown_abs"),
        "max_drawdown_pct": 100.0 * float(result.get("max_drawdown_account", 0.0)),
        "starting_balance": result.get("starting_balance"),
        "final_balance": result.get("final_balance"),
        "rejected_signals": result.get("rejected_signals"),
        "result_zip_sha256": hashlib.sha256(args.result.read_bytes()).hexdigest(),
        "semantic_trade_ledger_sha256": canonical_sha(normalized),
        "pair_metrics": finish(by_pair),
        "tag_metrics": finish(by_tag),
        "status": "EXECUTED",
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ["label", "strategy", "trades", "wins", "losses", "winrate_pct", "profit_usdc", "profit_pct", "profit_factor", "max_drawdown_pct", "semantic_trade_ledger_sha256"]}, indent=2))


if __name__ == "__main__":
    main()
