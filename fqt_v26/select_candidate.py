#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import pathlib
from typing import Any

CANDIDATES = [
    'M4PioneerValidationV14',
    'M4PioneerV26FullStake',
    'M4PioneerV26VWAPPrune',
    'M4PioneerV26CausalQuality',
    'M4PioneerV26PathQuality',
    'M4PioneerV26TailBrake',
    'M4PioneerV26Balanced',
]
DELAY = {name: name.replace('M4PioneerV26', 'M4PioneerV26') + 'Delay1' for name in CANDIDATES if name != 'M4PioneerValidationV14'}


def load(path: pathlib.Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding='utf-8'))


def finite(value: Any, default: float = -1e99) -> float:
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) else default
    except Exception:
        return default


def scenario(directory: pathlib.Path, candidate: str, label: str) -> dict[str, Any] | None:
    path = directory / f'{candidate}__{label}.json'
    return load(path) if path.exists() else None


def metric_pass(obj: dict[str, Any] | None, *, min_trades: int = 1, min_wr: float = 0.0,
                min_profit: float = 0.0, min_pf: float = 1.0, max_dd: float = 5.0) -> bool:
    if not obj:
        return False
    return bool(
        int(obj.get('trades', 0)) >= min_trades
        and finite(obj.get('winrate_pct')) >= min_wr
        and finite(obj.get('profit_usdc')) > min_profit
        and finite(obj.get('profit_factor')) > min_pf
        and finite(obj.get('max_drawdown_pct'), 1e99) <= max_dd
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--summaries', type=pathlib.Path, required=True)
    parser.add_argument('--correctness', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    correctness = load(args.correctness)
    rows: list[dict[str, Any]] = []

    for candidate in CANDIDATES:
        train = scenario(args.summaries, candidate, 'train')
        validation = scenario(args.summaries, candidate, 'validation')
        fee15 = scenario(args.summaries, candidate, 'fee15')
        fee20 = scenario(args.summaries, candidate, 'fee20')
        reverse = scenario(args.summaries, candidate, 'reverse')
        delay_name = DELAY.get(candidate)
        delay1 = scenario(args.summaries, delay_name, 'delay1') if delay_name else scenario(args.summaries, candidate, 'delay1')
        monthly = (validation or {}).get('monthly', {})
        monthly_positive = all(finite((monthly.get(month) or {}).get('profit_usdc')) > 0 for month in ['2026-04','2026-05','2026-06'])
        checks = {
            'train_positive': metric_pass(train, min_trades=100, min_wr=75, min_profit=0, min_pf=1.1, max_dd=7),
            'validation_core': metric_pass(validation, min_trades=120, min_wr=80, min_profit=0, min_pf=1.25, max_dd=5),
            'validation_monthly_positive': monthly_positive,
            'fee15': metric_pass(fee15, min_trades=80, min_wr=70, min_profit=0, min_pf=1.10, max_dd=7),
            'fee20': metric_pass(fee20, min_trades=60, min_wr=65, min_profit=0, min_pf=1.00, max_dd=8),
            'delay1': metric_pass(delay1, min_trades=80, min_wr=70, min_profit=0, min_pf=1.00, max_dd=8),
            'reverse_order': metric_pass(reverse, min_trades=100, min_wr=75, min_profit=0, min_pf=1.00, max_dd=7),
        }
        hard_pass = all(checks.values())
        stress_pfs = [finite((obj or {}).get('profit_factor'), 0.0) for obj in [validation, fee15, fee20, delay1, reverse]]
        stress_profits = [finite((obj or {}).get('profit_usdc'), -1e99) for obj in [validation, fee15, fee20, delay1, reverse]]
        score = (
            sum(checks.values()),
            min(stress_pfs) if stress_pfs else 0.0,
            min(stress_profits) if stress_profits else -1e99,
            finite((validation or {}).get('profit_usdc')),
            finite((validation or {}).get('profit_factor')),
        )
        rows.append({
            'candidate': candidate,
            'train': train,
            'validation': validation,
            'fee15': fee15,
            'fee20': fee20,
            'delay1': delay1,
            'reverse': reverse,
            'checks': checks,
            'hard_pass': hard_pass,
            'score': score,
        })

    complete = [row for row in rows if all(row[key] is not None for key in ['train','validation','fee15','fee20','delay1','reverse'])]
    if not complete:
        selected = None
    else:
        selected = sorted(complete, key=lambda row: tuple(row['score']), reverse=True)[0]
    lookahead = correctness.get('lookahead', {})
    recursive = correctness.get('recursive', {})
    correctness_pass = bool(
        lookahead.get('status') == 'PASS'
        and lookahead.get('has_bias') is False
        and recursive.get('status') in {'PASS','PASS_LIMITED'}
    )
    selection_pass = bool(selected and selected['hard_pass'])
    authorized = bool(correctness_pass and selection_pass)
    output = {
        'contract': 'FQT_V26_CANDIDATE_SELECTION_AND_OOS_AUTHORIZATION_V1',
        'correctness': correctness,
        'correctness_pass': correctness_pass,
        'candidates': rows,
        'chosen_candidate': selected['candidate'] if selected else None,
        'chosen_score': selected['score'] if selected else None,
        'selection_pass': selection_pass,
        'oos_authorized': authorized,
        'oos_range': '[2026-06-23,2026-08-15)',
        'oos_open_policy': 'single execution only; no threshold or pair-order revision after open',
        'decision': 'OPEN_ONE_SHOT_OOS' if authorized else ('KEEP_RESEARCH_CHAMPION_BLOCK_OOS' if selected else 'NO_COMPLETE_CANDIDATE_BLOCK_OOS'),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({
        'chosen_candidate': output['chosen_candidate'],
        'selection_pass': selection_pass,
        'correctness_pass': correctness_pass,
        'oos_authorized': authorized,
        'decision': output['decision'],
    }, indent=2))


if __name__ == '__main__':
    main()
