#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import pathlib
import sys
from typing import Any

import numpy as np
import pandas as pd

SIGNAL_COLUMNS = {'enter_long','exit_long','enter_short','exit_short','enter_tag','exit_tag'}


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_strategy(path: pathlib.Path, class_name: str):
    spec = importlib.util.spec_from_file_location('fqt_v26_strategy', path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f'cannot import {path}')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    cls = getattr(module, class_name)
    try:
        return cls({})
    except TypeError:
        return cls()


def pipeline(strategy, frame: pd.DataFrame, pair: str) -> pd.DataFrame:
    out = strategy.populate_indicators(frame.copy(), {'pair': pair})
    out = strategy.populate_entry_trend(out, {'pair': pair})
    out = strategy.populate_exit_trend(out, {'pair': pair})
    return out


def compare(left: pd.DataFrame, right: pd.DataFrame, tolerance: float) -> dict[str, Any]:
    common = [column for column in left.columns if column in right.columns]
    max_abs = 0.0
    changed: dict[str, Any] = {}
    signal_differences: dict[str, int] = {}
    for column in common:
        a = left[column]
        b = right[column]
        if pd.api.types.is_numeric_dtype(a) and pd.api.types.is_numeric_dtype(b):
            av = pd.to_numeric(a, errors='coerce').to_numpy(dtype=float)
            bv = pd.to_numeric(b, errors='coerce').to_numpy(dtype=float)
            finite = np.isfinite(av) & np.isfinite(bv)
            difference = float(np.max(np.abs(av[finite] - bv[finite]))) if finite.any() else 0.0
            nan_mismatch = int(np.count_nonzero(np.isnan(av) != np.isnan(bv)))
            max_abs = max(max_abs, difference)
            if difference > tolerance or nan_mismatch:
                changed[column] = {'max_abs': difference, 'nan_mismatch': nan_mismatch}
        else:
            av = a.astype('string').fillna('<NA>').to_numpy()
            bv = b.astype('string').fillna('<NA>').to_numpy()
            count = int(np.count_nonzero(av != bv))
            if count:
                changed[column] = {'differences': count}
        if column in SIGNAL_COLUMNS:
            av = a.astype('string').fillna('<NA>').to_numpy()
            bv = b.astype('string').fillna('<NA>').to_numpy()
            signal_differences[column] = int(np.count_nonzero(av != bv))
    return {
        'columns_compared': len(common),
        'max_abs_numeric_difference': max_abs,
        'changed_columns': changed,
        'signal_tag_differences': signal_differences,
        'pass': not changed and all(value == 0 for value in signal_differences.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--strategy-file', type=pathlib.Path, required=True)
    parser.add_argument('--strategy', required=True)
    parser.add_argument('--config', type=pathlib.Path, required=True)
    parser.add_argument('--datadir', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--rows', type=int, default=60000)
    parser.add_argument('--tolerance', type=float, default=1e-12)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8'))
    pairs = list(config['exchange']['pair_whitelist'])
    strategy = load_strategy(args.strategy_file, args.strategy)
    results: list[dict[str, Any]] = []
    cuts = [20000, 45000]
    for pair in pairs:
        path = args.datadir / f"{pair.replace('/', '_')}-1m.parquet"
        frame = pd.read_parquet(path).sort_values('date').reset_index(drop=True).iloc[:args.rows].copy()
        full = pipeline(strategy, frame, pair)
        checks = []
        for cut in cuts:
            if cut >= len(frame):
                continue
            prefix = pipeline(strategy, frame.iloc[:cut].copy(), pair)
            checks.append({'cut_rows': cut, **compare(prefix.reset_index(drop=True), full.iloc[:cut].reset_index(drop=True), args.tolerance)})
        row = {
            'pair': pair,
            'input_sha256': sha256(path),
            'rows_loaded': len(frame),
            'checks': checks,
            'pass': bool(checks and all(check['pass'] for check in checks)),
        }
        results.append(row)
        print(json.dumps({'pair': pair, 'pass': row['pass'], 'max_abs': max((c['max_abs_numeric_difference'] for c in checks), default=None)}), flush=True)
    failed = [row['pair'] for row in results if not row['pass']]
    output = {
        'contract': 'FQT_V26_FULL_UNIVERSE_FUTURE_APPEND_CAUSALITY_V1',
        'strategy': args.strategy,
        'strategy_sha256': sha256(args.strategy_file),
        'pair_count': len(pairs),
        'rows_per_pair': args.rows,
        'cuts': cuts,
        'tolerance': args.tolerance,
        'failed_pairs': failed,
        'max_abs_difference': max((check['max_abs_numeric_difference'] for row in results for check in row['checks']), default=0.0),
        'pass': not failed,
        'status': 'PASS' if not failed else 'FAIL',
        'scope_limit': 'Vectorized indicator/signal/tag causality; not portfolio fill/callback causality.',
        'rows': results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'strategy': args.strategy, 'pair_count': len(pairs), 'failed_pairs': failed, 'max_abs_difference': output['max_abs_difference'], 'pass': output['pass']}, indent=2))
    if failed:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
