#!/usr/bin/env python3
"""Conditional bootstrap and Monte-Carlo diagnostics for saved trade results.

These calculations describe the observed, selected trade sample.  They do not
repair selection bias and are not a forecast.
"""

from __future__ import annotations

import json
import math
import zipfile
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
SEEDS = (17, 43, 97)
RESAMPLES = 10_000


def load_trades(directory: str, strategy: str = "ED8") -> tuple[Path, list[dict[str, Any]]]:
    archive_path = next((ROOT / "results" / directory).glob("*.zip"))
    with zipfile.ZipFile(archive_path) as archive:
        result_name = next(
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json") and not name.endswith(".meta.json")
        )
        result = json.loads(archive.read(result_name))["strategy"][strategy]
    return archive_path, result["trades"]


def wilson_interval(wins: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total == 0:
        return (math.nan, math.nan)
    p = wins / total
    denom = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denom
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denom
    return centre - half, centre + half


def max_drawdown(equity: np.ndarray) -> float:
    peaks = np.maximum.accumulate(equity)
    return float(np.max((peaks - equity) / np.maximum(peaks, 1e-12)))


def analyze(name: str, trades: list[dict[str, Any]], starting_balance: float) -> dict[str, Any]:
    returns = np.asarray([float(trade["profit_ratio"]) for trade in trades], dtype=float)
    profits = np.asarray([float(trade["profit_abs"]) for trade in trades], dtype=float)
    wins = int(np.sum(returns > 0))
    wilson = wilson_interval(wins, len(returns))
    seed_results: list[dict[str, Any]] = []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        sampled = rng.choice(profits, size=(RESAMPLES, len(profits)), replace=True)
        totals = sampled.sum(axis=1)
        permutation_dd = np.empty(RESAMPLES)
        for index in range(RESAMPLES):
            ordered = rng.permutation(profits)
            equity = starting_balance + np.concatenate(([0.0], np.cumsum(ordered)))
            permutation_dd[index] = max_drawdown(equity)
        seed_results.append(
            {
                "seed": seed,
                "bootstrap_total_profit_abs_p025": float(np.quantile(totals, 0.025)),
                "bootstrap_total_profit_abs_median": float(np.quantile(totals, 0.5)),
                "bootstrap_total_profit_abs_p975": float(np.quantile(totals, 0.975)),
                "bootstrap_probability_nonpositive": float(np.mean(totals <= 0)),
                "permutation_max_drawdown_pct_p50": float(np.quantile(permutation_dd, 0.5) * 100),
                "permutation_max_drawdown_pct_p95": float(np.quantile(permutation_dd, 0.95) * 100),
            }
        )

    slippage = []
    for bps_per_side in (0, 5, 10, 20):
        adjusted = returns - (2.0 * bps_per_side / 10_000.0)
        approximate_equity = starting_balance * float(np.prod(1.0 + adjusted))
        slippage.append(
            {
                "slippage_bps_per_side": bps_per_side,
                "approximate_final_balance": approximate_equity,
                "approximate_profit_pct": (approximate_equity / starting_balance - 1.0) * 100.0,
                "method_status": "TEILWEISE VERIFIZIERT",
            }
        )
    return {
        "sample": name,
        "trade_count": len(returns),
        "wins": wins,
        "losses": int(np.sum(returns < 0)),
        "observed_winrate_pct": wins / len(returns) * 100 if len(returns) else None,
        "wilson_95_winrate_pct": [wilson[0] * 100, wilson[1] * 100],
        "seeds": seed_results,
        "analytical_slippage_approximation": slippage,
    }


def main() -> int:
    samples = []
    for directory, name, starting_balance in (
        ("champion_common_full", "champion_fee_0.1pct", 1000.0),
        ("champion_common_fee_002", "champion_fee_0.2pct", 1000.0),
        ("champion_common_fee_003", "champion_fee_0.3pct", 1000.0),
    ):
        archive, trades = load_trades(directory)
        result = analyze(name, trades, starting_balance)
        result["source_archive"] = archive.relative_to(ROOT).as_posix()
        samples.append(result)

    one_sided_all_wins_p = 0.5 ** 20
    correction_sensitivity = [
        {
            "assumed_test_family_size": family_size,
            "bonferroni_adjusted_naive_all_wins_p": min(1.0, one_sided_all_wins_p * family_size),
            "status": status,
            "basis": basis,
        }
        for family_size, status, basis in (
            (8, "VERIFIZIERT", "eight explicitly recorded V735-V742 variants"),
            (2985, "TEILWEISE VERIFIZIERT", "rows in attached score90 candidate CSV; direct lineage/independence is not proven"),
            (810000, "NICHT VERIFIZIERT", "filename/stage label only; not established as independent tested candidates"),
        )
    ]
    report = {
        "schema_version": 1,
        "resamples_per_seed": RESAMPLES,
        "seeds": list(SEEDS),
        "truth_status": "TEILWEISE VERIFIZIERT",
        "samples": samples,
        "multiple_testing_sensitivity": {
            "naive_null": "independent Bernoulli wins with p=0.5",
            "uncorrected_one_sided_probability_of_20_wins": one_sided_all_wins_p,
            "corrections": correction_sensitivity,
            "interpretation": (
                "This is a sensitivity illustration, not a valid market-model p-value; trades are non-independent, "
                "the null win probability is unknown, and the full selection family is not reconstructable."
            ),
        },
        "limitations": [
            "Bootstrap resamples a selected twenty-trade sample and therefore cannot remove selection bias.",
            "Permutation Monte Carlo changes trade order only; it does not simulate new price paths.",
            "Analytical slippage is an approximation; Freqtrade engine fee runs are the primary stress evidence.",
            "Zero-loss samples cannot estimate a finite Profit Factor.",
        ],
    }
    target = ROOT / "results/summaries/statistical_stress.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"samples": len(samples), "resamples_per_seed": RESAMPLES, "status": report["truth_status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
