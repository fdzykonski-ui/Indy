#!/usr/bin/env python3
"""Full-universe signal parity, future-append causality and funnel audit."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def frame_hash(frame: pd.DataFrame) -> str:
    normalized = frame.copy()
    for col in normalized.columns:
        series = normalized[col]
        if pd.api.types.is_object_dtype(series) or pd.api.types.is_string_dtype(series):
            normalized[col] = series.astype("string").fillna("<NA>")
    digest = pd.util.hash_pandas_object(normalized, index=True, categorize=True).values.tobytes()
    return hashlib.sha256(digest).hexdigest()


def compare_frames(left: pd.DataFrame, right: pd.DataFrame) -> dict[str, Any]:
    if list(left.columns) != list(right.columns):
        return {
            "equal": False,
            "left_columns": list(left.columns),
            "right_columns": list(right.columns),
            "reason": "column_mismatch",
        }
    if left.shape != right.shape:
        return {
            "equal": False,
            "left_shape": list(left.shape),
            "right_shape": list(right.shape),
            "reason": "shape_mismatch",
        }
    equal = left.equals(right)
    differing_columns: dict[str, int] = {}
    max_abs = 0.0
    if not equal:
        for col in left.columns:
            a, b = left[col], right[col]
            if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
                av = pd.to_numeric(a, errors="coerce").to_numpy(dtype=float)
                bv = pd.to_numeric(b, errors="coerce").to_numpy(dtype=float)
                finite = np.isfinite(av) & np.isfinite(bv)
                diff = float(np.max(np.abs(av[finite] - bv[finite]))) if finite.any() else 0.0
                nan_mismatch = int(np.count_nonzero(np.isnan(av) != np.isnan(bv)))
                count = int(np.count_nonzero((av != bv) & finite)) + nan_mismatch
                if count:
                    differing_columns[col] = count
                    max_abs = max(max_abs, diff)
            else:
                av = a.astype("string").fillna("<NA>").to_numpy()
                bv = b.astype("string").fillna("<NA>").to_numpy()
                count = int(np.count_nonzero(av != bv))
                if count:
                    differing_columns[col] = count
    return {
        "equal": bool(equal),
        "left_hash": frame_hash(left),
        "right_hash": frame_hash(right),
        "differing_columns": differing_columns,
        "max_abs_numeric_difference": max_abs,
    }


def data_path(datadir: Path, pair: str) -> Path:
    base, quote = pair.split("/")
    return datadir / f"{base}_{quote}-1m.parquet"


def pipeline(strategy: Any, frame: pd.DataFrame, pair: str):
    indicators = strategy.populate_indicators(frame.copy(), {"pair": pair})
    entries = strategy.populate_entry_trend(indicators.copy(), {"pair": pair})
    final = strategy.populate_exit_trend(entries.copy(), {"pair": pair})
    return indicators, entries, final


def bool_count(frame: pd.DataFrame, col: str) -> int | None:
    if col not in frame:
        return None
    return int(pd.to_numeric(frame[col], errors="coerce").fillna(0).astype(bool).sum())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--datadir", required=True)
    ap.add_argument("--strategy-path", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-csv", required=True)
    args = ap.parse_args()

    strategy_path = Path(args.strategy_path).resolve()
    sys.path.insert(0, str(strategy_path))
    from M4PioneerValidationV14Diagnostic import (  # type: ignore
        M4PioneerValidationV14,
        M4PioneerValidationV14LookaheadExecutionNeutral,
        M4PioneerValidationV14LookaheadStakeNeutral,
    )

    config = json.loads(Path(args.config).read_text())
    pairs = list(config["exchange"]["pair_whitelist"])
    datadir = Path(args.datadir)
    champion = M4PioneerValidationV14()
    candidates = {
        "stake_neutral": M4PioneerValidationV14LookaheadStakeNeutral(),
        "execution_neutral": M4PioneerValidationV14LookaheadExecutionNeutral(),
    }

    methods = ["populate_indicators", "populate_entry_trend", "populate_exit_trend"]
    method_identity = {
        name: {
            method: (
                getattr(candidate, method).__func__ is getattr(champion, method).__func__
            )
            for method in methods
        }
        for name, candidate in candidates.items()
    }

    callbacks = {}
    for name, strategy in {"champion": champion, **candidates}.items():
        callbacks[name] = {
            callback: {
                "defined_by": getattr(strategy, callback).__func__.__qualname__,
                "source_file": inspect.getsourcefile(getattr(strategy, callback).__func__),
            }
            for callback in [
                "custom_stake_amount",
                "custom_exit",
                "custom_stoploss",
                "confirm_trade_exit",
            ]
        }

    rows: list[dict[str, Any]] = []
    aggregate_veto = Counter()
    aggregate_gates = Counter()
    aggregate = Counter()
    hard_failures: list[str] = []

    for pair in pairs:
        path = data_path(datadir, pair)
        if not path.exists():
            hard_failures.append(f"missing_data:{pair}:{path}")
            continue
        raw = pd.read_parquet(path).sort_values("date").reset_index(drop=True)
        ind, entry, champion_final = pipeline(champion, raw, pair)

        parity: dict[str, Any] = {}
        for name, candidate in candidates.items():
            _, _, candidate_final = pipeline(candidate, raw, pair)
            cmp = compare_frames(champion_final, candidate_final)
            parity[name] = cmp
            if not cmp["equal"]:
                hard_failures.append(f"signal_parity:{pair}:{name}")

        # Future-append test at a long, pair-specific prefix.
        cut = max(champion.startup_candle_count + 1000, int(len(raw) * 0.65))
        cut = min(cut, len(raw) - 1)
        _, _, prefix_final = pipeline(champion, raw.iloc[:cut].copy(), pair)
        prefix_cmp = compare_frames(
            prefix_final.reset_index(drop=True),
            champion_final.iloc[:cut].reset_index(drop=True),
        )
        if not prefix_cmp["equal"]:
            hard_failures.append(f"future_append:{pair}")

        pre_entry = pd.to_numeric(entry.get("enter_long", 0), errors="coerce").fillna(0).astype(bool)
        final_entry = pd.to_numeric(champion_final.get("enter_long", 0), errors="coerce").fillna(0).astype(bool)
        final_exit = pd.to_numeric(champion_final.get("exit_long", 0), errors="coerce").fillna(0).astype(bool)
        collisions = pre_entry & final_exit
        collision_violations = collisions & final_entry
        if int(collision_violations.sum()) > 0:
            hard_failures.append(f"same_candle_collision:{pair}")

        veto_counts = (
            entry["veto_reason"].astype("string").fillna("<NA>").value_counts().to_dict()
            if "veto_reason" in entry
            else {}
        )
        aggregate_veto.update({str(k): int(v) for k, v in veto_counts.items()})

        gate_cols = [
            "data_valid",
            "structure_preentry_entry_ok",
            "hard_gate_pass",
            "entry_score_floor_ok",
            "entry_score_ceiling_ok",
            "path_context_allowed",
            "path_active_status_ok",
            "risk_action_ok",
            "entry_allowed",
            "preentry_tail_risk_veto",
        ]
        gate_counts = {col: bool_count(entry, col) for col in gate_cols}
        for col, count in gate_counts.items():
            if count is not None:
                aggregate_gates[col] += count

        raw_path_candidates = None
        if "selected_entry_candidate" in entry:
            raw_path_candidates = int(
                entry["selected_entry_candidate"].astype("string").fillna("none").ne("none").sum()
            )
        aggregate.update(
            {
                "candles": len(raw),
                "raw_path_candidates": raw_path_candidates or 0,
                "entry_allowed": int(pre_entry.sum()),
                "final_entries": int(final_entry.sum()),
                "vector_exits": int(final_exit.sum()),
                "same_candle_collisions": int(collisions.sum()),
                "same_candle_collision_violations": int(collision_violations.sum()),
            }
        )

        rows.append(
            {
                "pair": pair,
                "rows": len(raw),
                "start": str(raw["date"].iloc[0]),
                "end": str(raw["date"].iloc[-1]),
                "champion_hash": frame_hash(champion_final),
                "stake_neutral_equal": parity["stake_neutral"]["equal"],
                "execution_neutral_equal": parity["execution_neutral"]["equal"],
                "future_append_equal": prefix_cmp["equal"],
                "future_append_cut": cut,
                "raw_path_candidates": raw_path_candidates,
                "entry_allowed": int(pre_entry.sum()),
                "final_entries": int(final_entry.sum()),
                "vector_exits": int(final_exit.sum()),
                "same_candle_collisions": int(collisions.sum()),
                "collision_violations": int(collision_violations.sum()),
                "parity": parity,
                "future_append": prefix_cmp,
                "gate_counts": gate_counts,
                "veto_counts": veto_counts,
            }
        )
        del raw, ind, entry, champion_final, prefix_final

    status = "PASS" if not hard_failures and len(rows) == len(pairs) else "FAIL"
    out = {
        "contract": "FQT_V23_IP07_FULL_UNIVERSE_SIGNAL_PARITY_V1",
        "status": status,
        "pair_count_expected": len(pairs),
        "pair_count_executed": len(rows),
        "method_identity": method_identity,
        "callback_ownership": callbacks,
        "aggregate": dict(aggregate),
        "aggregate_gate_counts": dict(aggregate_gates),
        "aggregate_veto_counts": dict(aggregate_veto.most_common()),
        "hard_failures": hard_failures,
        "rows": rows,
        "interpretation": (
            "PASS proves exact vectorized signal parity for diagnostic subclasses and "
            "future-append invariance at one long prefix per pair. It does not by itself "
            "replace Freqtrade native trade-lifecycle lookahead-analysis."
        ),
    }
    Path(args.out_json).write_text(
        json.dumps(json_safe(out), indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )
    pd.DataFrame(
        [
            {
                k: v
                for k, v in row.items()
                if k
                not in {"parity", "future_append", "gate_counts", "veto_counts"}
            }
            for row in rows
        ]
    ).to_csv(args.out_csv, index=False)
    print(json.dumps({k: out[k] for k in ["contract", "status", "pair_count_executed", "aggregate", "hard_failures"]}, indent=2))
    return 0 if status == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
