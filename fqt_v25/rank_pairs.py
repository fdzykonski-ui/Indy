#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import pathlib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--summary", type=pathlib.Path, required=True)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--out-config", type=pathlib.Path, required=True)
    parser.add_argument("--out-receipt", type=pathlib.Path, required=True)
    args = parser.parse_args()

    summary = json.loads(args.summary.read_text(encoding="utf-8"))
    config = json.loads(args.config.read_text(encoding="utf-8"))
    original = list(config["exchange"]["pair_whitelist"])
    metrics = {row["key"]: row for row in summary.get("pair_metrics", [])}
    ranked = []
    for original_index, pair in enumerate(original):
        row = metrics.get(pair, {})
        trades = int(row.get("trades", 0))
        profit = float(row.get("profit_usdc", 0.0))
        winrate = float(row.get("winrate_pct", 0.0))
        gross_win = float(row.get("gross_win", 0.0))
        gross_loss = float(row.get("gross_loss", 0.0))
        shrunk_pf = (gross_win + 1.0) / (gross_loss + 1.0)
        # Preregistered conservative ranking: profit normalized by sample size,
        # shrinkage-stabilized PF, winrate and a small coverage term.
        score = (
            profit / (math.sqrt(max(trades, 1)) + 1.0)
            + 2.0 * math.log(max(shrunk_pf, 0.05))
            + 0.02 * (winrate - 50.0)
            + 0.05 * math.log1p(trades)
        )
        ranked.append({
            "pair": pair,
            "original_index": original_index,
            "trades": trades,
            "profit_usdc": profit,
            "winrate_pct": winrate,
            "shrunk_profit_factor": shrunk_pf,
            "score": score,
        })
    ranked.sort(key=lambda row: (-row["score"], row["original_index"], row["pair"]))
    order = [row["pair"] for row in ranked]
    if set(order) != set(original) or len(order) != len(original):
        raise RuntimeError("Ranked order does not preserve the frozen pair universe.")
    config["exchange"]["pair_whitelist"] = order
    config["pair_order_contract"] = {
        "method": "TRAIN_ONLY_MOT31_SHRUNK_SCORE_V1",
        "source_timerange": summary.get("timerange"),
        "all_pairs_preserved": True,
        "fresh_oos_used": False,
    }
    args.out_config.parent.mkdir(parents=True, exist_ok=True)
    args.out_config.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    receipt = {
        "contract": "FQT_V25_TRAIN_ONLY_PAIR_PRIORITY_V1",
        "source_summary": str(args.summary),
        "source_timerange": summary.get("timerange"),
        "original_order": original,
        "ranked_order": order,
        "all_pairs_preserved": True,
        "fresh_oos_used": False,
        "ranking": ranked,
    }
    args.out_receipt.parent.mkdir(parents=True, exist_ok=True)
    args.out_receipt.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"pair_count": len(order), "top10": order[:10], "all_pairs_preserved": True}, indent=2))


if __name__ == "__main__":
    main()
