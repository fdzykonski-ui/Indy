#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
from typing import Any

import pandas as pd


def load(path: pathlib.Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding='utf-8'))


def metric(obj: dict[str, Any] | None, key: str, default: float = float('-inf')) -> float:
    if not obj:
        return default
    try:
        return float(obj.get(key))
    except Exception:
        return default


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def row(label: str, period: str, obj: dict[str, Any] | None) -> dict[str, Any]:
    if not obj:
        return {'Version/Test': label, 'Zeitraum': period, 'Start→Ende': 'N/V', 'Trades': 'NOT_RUN', 'W/L/D': 'N/V', 'WR': 'N/V', 'Profit': 'N/V', 'PF / DD': 'N/V'}
    return {
        'Version/Test': label,
        'Zeitraum': period,
        'Start→Ende': f"{metric(obj,'starting_balance',0):,.2f}→{metric(obj,'final_balance',0):,.2f}",
        'Trades': int(obj.get('trades', 0)),
        'W/L/D': f"{int(obj.get('wins',0))}/{int(obj.get('losses',0))}/{int(obj.get('draws',0))}",
        'WR': f"{metric(obj,'winrate_pct',0):.2f}%",
        'Profit': f"{metric(obj,'profit_usdc',0):+,.2f} / {metric(obj,'profit_pct',0):+.2f}%",
        'PF / DD': f"{metric(obj,'profit_factor',0):.3f} / {metric(obj,'max_drawdown_pct',0):.2f}%",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--selection', type=pathlib.Path, required=True)
    parser.add_argument('--correctness', type=pathlib.Path, required=True)
    parser.add_argument('--summaries', type=pathlib.Path, required=True)
    parser.add_argument('--factory-strategy', type=pathlib.Path, required=True)
    parser.add_argument('--config', type=pathlib.Path, required=True)
    parser.add_argument('--out-dir', type=pathlib.Path, required=True)
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    selection = load(args.selection, {})
    correctness = load(args.correctness, {})
    selected = selection.get('chosen_candidate') or 'M4PioneerValidationV14'
    baseline_oos = load(args.summaries / 'M4PioneerValidationV14__oos.json')
    candidate_oos = load(args.summaries / f'{selected}__oos.json')
    baseline_full = load(args.summaries / 'M4PioneerValidationV14__full.json')
    candidate_full = load(args.summaries / f'{selected}__full.json')
    candidate_oos_fee15 = load(args.summaries / f'{selected}__oos_fee15.json')
    selected_validation = None
    for candidate in selection.get('candidates', []):
        if candidate.get('candidate') == selected:
            selected_validation = candidate
            break

    oos_opened = bool(candidate_oos and baseline_oos)
    promotion_checks = {
        'correctness_pass': bool(correctness.get('pass')),
        'selection_pass': bool(selection.get('selection_pass')),
        'oos_opened': oos_opened,
        'oos_profit_gt_50': metric(candidate_oos, 'profit_pct') > 50,
        'oos_winrate_gt_80': metric(candidate_oos, 'winrate_pct') > 80,
        'oos_pf_gt_1_5': metric(candidate_oos, 'profit_factor') > 1.5,
        'oos_dd_lt_5': metric(candidate_oos, 'max_drawdown_pct', 1e99) < 5,
        'oos_fee15_positive': metric(candidate_oos_fee15, 'profit_usdc') > 0 and metric(candidate_oos_fee15, 'profit_factor') > 1,
        'oos_beats_baseline': metric(candidate_oos, 'profit_usdc') > metric(baseline_oos, 'profit_usdc'),
        'full_trades_gt_500': metric(candidate_full, 'trades', 0) > 500,
        'full_wr_gt_80': metric(candidate_full, 'winrate_pct') > 80,
        'full_profit_gt_80': metric(candidate_full, 'profit_pct') > 80,
        'full_pf_gt_5': metric(candidate_full, 'profit_factor') > 5,
        'full_dd_lt_5': metric(candidate_full, 'max_drawdown_pct', 1e99) < 5,
    }
    promotion_pass = all(promotion_checks.values())
    decision = 'PROMOTE_RESEARCH_CANDIDATE_NO_LIVE' if promotion_pass else ('KEEP_RESEARCH_CHAMPION_OOS_FAIL' if oos_opened else 'KEEP_CHAMPION_OOS_BLOCKED')

    final_strategy = args.out_dir / 'M4PioneerV26Final.py'
    text = args.factory_strategy.read_text(encoding='utf-8')
    text += f'''\n\nclass M4PioneerV26Final({selected}):\n    \"\"\"Machine-selected FQT V26 artifact. Live trading remains forbidden.\"\"\"\n    release_decision = {decision!r}\n    selected_parent = {selected!r}\n    oos_opened = {oos_opened!r}\n    promotion_pass = {promotion_pass!r}\n    live_allowed = False\n\n    @staticmethod\n    def version() -> str:\n        return \"26.final-{selected}\"\n'''
    final_strategy.write_text(text, encoding='utf-8')
    config = load(args.config, {})
    config['strategy'] = 'M4PioneerV26Final'
    config['dry_run'] = True
    config['initial_state'] = 'stopped'
    config['force_entry_enable'] = False
    config.setdefault('api_server', {})['enabled'] = False
    config.setdefault('telegram', {})['enabled'] = False
    config.setdefault('exchange', {})['key'] = ''
    config['exchange']['secret'] = ''
    config['evidence_status'] = decision
    config['validation_contract'] = {
        'selected_parent': selected,
        'selection_pass': bool(selection.get('selection_pass')),
        'correctness_pass': bool(correctness.get('pass')),
        'oos_opened': oos_opened,
        'promotion_pass': promotion_pass,
        'live_allowed': False,
        'timestamp_replay': False,
    }
    final_config = args.out_dir / 'config_M4PioneerV26Final.json'
    final_config.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')

    comparison = pd.DataFrame([
        row('V14 Anchor · OOS', '20260623–20260815', baseline_oos),
        row(f'{selected} · OOS', '20260623–20260815', candidate_oos),
        row('V14 Anchor · Gesamt', '20260101–20260815', baseline_full),
        row(f'{selected} · Gesamt', '20260101–20260815', candidate_full),
        row(f'{selected} · Fee 0,15% OOS', '20260623–20260815', candidate_oos_fee15),
    ])
    comparison.to_csv(args.out_dir / 'COMPARISON_5x8.csv', index=False)
    gates = pd.DataFrame([{'Gate': key, 'Status': 'PASS' if value else ('NOT_RUN' if not oos_opened and key.startswith('oos_') else 'FAIL')} for key, value in promotion_checks.items()])
    gates.to_csv(args.out_dir / 'GATE_MATRIX.csv', index=False)

    summary = {
        'contract': 'FQT_V26_FINAL_SUMMARY_V1',
        'decision': decision,
        'selected_system': selected,
        'selected_strategy': 'M4PioneerV26Final',
        'correctness': correctness,
        'selection': selection,
        'selected_validation': selected_validation,
        'oos_opened': oos_opened,
        'baseline_oos': baseline_oos,
        'candidate_oos': candidate_oos,
        'candidate_oos_fee15': candidate_oos_fee15,
        'baseline_full_period': baseline_full,
        'candidate_full_period': candidate_full,
        'promotion_checks': promotion_checks,
        'promotion_pass': promotion_pass,
        'dry_run_started': False,
        'live_allowed': False,
        'strategy_sha256': sha256(final_strategy),
        'config_sha256': sha256(final_config),
    }
    (args.out_dir / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    (args.out_dir / 'NEXT_ITERATION_PROMPT.md').write_text(
        'PLSGO FQT-V26 NEXT | READ=summary.json+GATE_MATRIX.csv | MODE=FAIL_CLOSED | '
        'FIRST=lowest_failed_predecessor_gate | NO_OOS_REOPEN=TRUE | DRY_RUN=ONLY_IF_PROMOTION_PASS | '
        'LIVE=FORBIDDEN_WITHOUT_NEW_EXPLICIT_AUTHORIZATION\n', encoding='utf-8')
    print(json.dumps({'decision': decision, 'selected': selected, 'oos_opened': oos_opened, 'promotion_pass': promotion_pass, 'promotion_checks': promotion_checks}, indent=2))


if __name__ == '__main__':
    main()
