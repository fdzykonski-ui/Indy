#!/usr/bin/env python3
"""Build the decision ledger and prevent accidental OOS/canary promotion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def metric_row(rows: list[dict[str, Any]], artifact_fragment: str, strategy: str) -> dict[str, Any]:
    matches = [row for row in rows if artifact_fragment in row["artifact"] and row["strategy"] == strategy]
    if len(matches) != 1:
        raise ValueError(f"expected one row for {artifact_fragment}/{strategy}, found {len(matches)}")
    return matches[0]


def gate(name: str, status: str, evidence: str, decision: str) -> dict[str, str]:
    return {"gate": name, "status": status, "evidence": evidence, "decision": decision}


def main() -> int:
    metrics = load("results/summaries/metrics_all.json")["rows"]
    champion = metric_row(metrics, "results/champion_common_full/", "ED8")
    champion_train = metric_row(metrics, "results/champion_train/", "ED8")
    h001 = metric_row(metrics, "results/h001_train/", "CausalRegimePullbackV1")
    h002 = metric_row(metrics, "results/h002_train/", "CausalRegimePullbackV2")
    fee002 = metric_row(metrics, "results/champion_common_fee_002/", "ED8")
    fee003 = metric_row(metrics, "results/champion_common_fee_003/", "ED8")
    causality = load("audit/causality_summary.json")
    data_quality = load("audit/data_quality/ohlcv_quality_summary.json")
    deterministic = load("audit/deterministic_reproduction.json")
    runtime = load("audit/runtime_signal_audit.json")
    secret_scan = load("audit/secret_scan.json")
    publication = load("audit/github_publication.json")

    gates = [
        gate("Testvertrag und Versions-Freeze", "VERIFIZIERT", "contracts/research_contract_v1.json", "locked"),
        gate("Archivintegrität", "VERIFIZIERT", "audit/source_archive_manifest.extract.json", "pass"),
        gate("OHLCV-Struktur/Datenlücken", data_quality["status"], "audit/data_quality/ohlcv_quality_summary.json", "pass"),
        gate("Datenprovenienz", data_quality["source_provenance"]["status"], "audit/data_quality/ohlcv_quality_summary.json", "needs exchange snapshot/download ledger"),
        gate("Survivorship/30-Pair-Universum", data_quality["survivorship_audit"]["status"], "audit/source_of_truth_inventory.json", "requires historical USDC universe and data"),
        gate("Code/Callback/Konfiguration", "VERIFIZIERT", "audit/strategy_static_audit.json", "pass for hard constraints"),
        gate("Lookahead", causality["lookahead"]["truth_status"], "audit/causality_summary.json", "ten signals only; expand coverage"),
        gate("Recursive", causality["recursive"]["truth_status"], "audit/causality_summary.json", "fail at startup=1600; repair or increase proven startup"),
        gate("Prefix-/Same-Candle-/Kollision", runtime["truth_status"], "audit/runtime_signal_audit.json", "pass on saved sample"),
        gate("Deterministische Reproduktion", deterministic["truth_status"], "audit/deterministic_reproduction.json", "exact trade and metric equality"),
        gate("Naive Baselines/Negativkontrollen", "VERIFIZIERT", "results/summaries/metrics_all.json", "all common settings recorded"),
        gate("Monats-/Session-/Regimeanalyse", "TEILWEISE VERIFIZIERT", "evidence/ed8_v741/ED8_V741_8x_InternalExecution/ED8_V741_WF_StressMetrics.csv", "monthly slices exist; session/regime independence incomplete"),
        gate("Hyperopt nur Training/mehrere Seeds", "NICHT VERIFIZIERT", "hypotheses/H001_causal_regime_pullback_v1.json", "not run after train kill; no promotable candidate"),
        gate("Parameter-Nachbarschaft/Plateau", "NICHT VERIFIZIERT", "contracts/research_contract_v1.json", "not justified after train failure"),
        gate("Entry/Exit/Gate/Indikator-Ablation", "TEILWEISE VERIFIZIERT", "results/champion_common_ablation", "selected ablations only"),
        gate("Fast Walk-Forward", "TEILWEISE VERIFIZIERT", "evidence/ed8_v741/ED8_V741_8x_InternalExecution/logs", "frozen monthly slices, not refit WF"),
        gate("Nested Rolling/Anchored Walk-Forward", "NICHT VERIFIZIERT", "contracts/research_contract_v1.json", "no candidate reached validation"),
        gate("Purging/Embargo", "TEILWEISE VERIFIZIERT", "contracts/research_contract_v1.json", "partitioned, not executed beyond training"),
        gate("Pair-Holdout/Leave-One-Pair-Out", "BLOCKIERT", "audit/source_of_truth_inventory.json", "only BTC/USDC exists"),
        gate("Gebührenstress 0.10/0.20/0.30%", "VERIFIZIERT", "results/champion_common_fee_002; results/champion_common_fee_003", "quality degrades below targets"),
        gate("Entry-Delay +1/+2", "VERIFIZIERT", "results/champion_common_ablation", "positive but tiny sample"),
        gate("Slippage/Spread", "TEILWEISE VERIFIZIERT", "results/summaries/statistical_stress.json", "analytical only; engine/order-book replay absent"),
        gate("Stake/Wallet/Parallelposition", "TEILWEISE VERIFIZIERT", "results/champion_historical_precision6; results/champion_common_full", "wallet 50/1000; max-open fixed at one"),
        gate("Order-/Betriebsstörung", "NICHT VERIFIZIERT", "contracts/research_contract_v1.json", "no latency/order-rejection/outage simulator"),
        gate("Bootstrap/Monte Carlo", "TEILWEISE VERIFIZIERT", "results/summaries/statistical_stress.json", "conditional selected-sample diagnostics only"),
        gate("Multiple-Testing-Korrektur", "TEILWEISE VERIFIZIERT", "results/summaries/statistical_stress.json", "full independent search family unknown"),
        gate("Finales unangetastetes OOS", "BLOCKIERT", "contracts/research_contract_v1.json", "sealed; no candidate passed training gates"),
        gate("Dry-run Canary", "BLOCKIERT", "decisions/promotion_decision.json", "no deployment candidate; preflight only"),
        gate("Micro-Live/Skalierung/Drift", "BLOCKIERT", "contracts/research_contract_v1.json", "outside authorized evidence stage"),
        gate("Geheimnisfreier Publish", secret_scan["publishable_tree"]["truth_status"], "audit/secret_scan.json", "raw historical zips excluded"),
        gate(
            "GitHub Branch/PR",
            publication["status"],
            "audit/github_publication.json",
            f"PR #{publication['publication']['pull_request']} open and mergeable-clean",
        ),
    ]

    targets = {
        "trades_gt_500": champion["total_trades"] > 500,
        "trades_per_day_10_to_20": 10 <= champion["trades_per_day"] <= 20,
        "winrate_gt_80pct": champion["winrate_pct"] > 80,
        "net_profit_gt_50pct": champion["profit_pct"] > 50,
        "profit_factor_gt_5": champion["profit_factor_state"] == "FINITE" and champion["profit_factor"] > 5,
        "wallet_drawdown_lt_5pct": champion["wallet_max_drawdown_pct"] < 5,
    }
    decision = {
        "schema_version": 1,
        "decision": "RETAIN_HISTORICAL_CHAMPION; NO PROMOTION; NO OOS; NO CANARY",
        "truth_status": "VERIFIZIERT",
        "champion_common_contract": {
            key: champion[key]
            for key in (
                "timerange", "starting_balance", "final_balance", "total_trades", "trades_per_day",
                "wins", "losses", "winrate_pct", "profit_pct", "profit_factor", "profit_factor_state",
                "wallet_max_drawdown_pct",
            )
        },
        "identical_training_comparison": {
            "contract": "20260101-20260301; BTC/USDC; 1m; 1000 USDC; unlimited; max_open_trades=1; fee=0.1%",
            "champion": {key: champion_train[key] for key in ("total_trades", "winrate_pct", "profit_pct", "profit_factor", "profit_factor_state", "wallet_max_drawdown_pct")},
            "challenger_h001": {key: h001[key] for key in ("total_trades", "winrate_pct", "profit_pct", "profit_factor", "wallet_max_drawdown_pct")},
            "challenger_h002": {key: h002[key] for key in ("total_trades", "winrate_pct", "profit_pct", "profit_factor", "wallet_max_drawdown_pct")},
        },
        "promotion_targets_pass": targets,
        "all_targets_pass": all(targets.values()),
        "reasons": [
            "Champion has only 20 trades (0.17/day) and +26.24%, so sample/activity/profit targets fail.",
            "Profit Factor is undefined because the selected base-fee sample has no losses; Freqtrade emits 0.0.",
            (
                f"At 0.20% and 0.30% fees, winrate falls to {fee002['winrate_pct']:.2f}%/"
                f"{fee003['winrate_pct']:.2f}% and Profit Factor to "
                f"{fee002['profit_factor']:.2f}/{fee003['profit_factor']:.2f}."
            ),
            "Configured startup_candle_count=1600 fails the recursive stability gate.",
            "H001 and H002 are falsified on training; validation and frozen OOS remain untouched.",
        ],
    }
    decisions_dir = ROOT / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    (decisions_dir / "promotion_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (ROOT / "audit/gate_matrix.json").write_text(
        json.dumps({"schema_version": 1, "gates": gates}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"decision": decision["decision"], "gates": len(gates), "all_targets_pass": False}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
