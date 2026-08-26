#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--selection', type=pathlib.Path, required=True)
    parser.add_argument('--extended', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text(encoding='utf-8'))
    extended = json.loads(args.extended.read_text(encoding='utf-8'))
    checks = {
        'correctness_pass': bool(selection.get('correctness_pass')),
        'selection_pass': bool(selection.get('selection_pass')),
        'data_integrity_pass': bool(extended.get('data_integrity_pass')),
        'determinism_pass': bool(extended.get('determinism_pass')),
        'lopo_pass': bool(extended.get('lopo_pass')),
        'same_candle_pass': bool(extended.get('same_candle_pass')),
        'fault_injection_pass': bool(extended.get('fault_injection_pass')),
    }
    authorized = all(checks.values())
    selection['extended_gates'] = extended
    selection['authorization_checks'] = checks
    selection['oos_authorized'] = authorized
    selection['decision'] = 'OPEN_ONE_SHOT_OOS' if authorized else 'KEEP_RESEARCH_CHAMPION_BLOCK_OOS'
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(selection, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
    print(json.dumps({'checks': checks, 'oos_authorized': authorized, 'decision': selection['decision']}, indent=2))


if __name__ == '__main__':
    main()
