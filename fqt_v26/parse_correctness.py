#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import pathlib
from typing import Any


def read_rc(path: pathlib.Path) -> int:
    try:
        return int(path.read_text(encoding='utf-8').strip())
    except Exception:
        return 999


def bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {'true','yes','1','pass','passed','ok'}:
        return True
    if text in {'false','no','0','fail','failed'}:
        return False
    return None


def parse_lookahead(path: pathlib.Path, rc_path: pathlib.Path) -> dict[str, Any]:
    rc = read_rc(rc_path)
    if rc != 0 or not path.exists() or path.stat().st_size == 0:
        return {'status': 'BLOCKED', 'pass': False, 'has_bias': None, 'row_count': 0, 'exit_code': rc}
    rows = list(csv.DictReader(path.open(newline='', encoding='utf-8-sig')))
    values: list[bool] = []
    for row in rows:
        normalized = {str(key).strip().lower().replace(' ', '_'): value for key, value in row.items()}
        parsed = bool_value(normalized.get('has_bias'))
        if parsed is not None:
            values.append(parsed)
    if not values:
        return {'status': 'BLOCKED', 'pass': False, 'has_bias': None, 'row_count': len(rows), 'exit_code': rc}
    has_bias = any(values)
    return {'status': 'FAIL' if has_bias else 'PASS', 'pass': not has_bias, 'has_bias': has_bias, 'row_count': len(rows), 'exit_code': rc}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--lookahead-csv', type=pathlib.Path, required=True)
    parser.add_argument('--lookahead-rc', type=pathlib.Path, required=True)
    parser.add_argument('--recursive-receipt', type=pathlib.Path, required=True)
    parser.add_argument('--metamorphic-receipt', type=pathlib.Path, required=True)
    parser.add_argument('--iteration3b', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    lookahead = parse_lookahead(args.lookahead_csv, args.lookahead_rc)
    recursive = json.loads(args.recursive_receipt.read_text(encoding='utf-8')) if args.recursive_receipt.exists() else {'status': 'BLOCKED', 'pass': False}
    metamorphic = json.loads(args.metamorphic_receipt.read_text(encoding='utf-8')) if args.metamorphic_receipt.exists() else {'status': 'BLOCKED', 'pass': False}
    prior = json.loads(args.iteration3b.read_text(encoding='utf-8')) if args.iteration3b.exists() else {}
    recursive_pass = bool(recursive.get('pass') and metamorphic.get('pass'))
    result = {
        'contract': 'FQT_V26_CORRECTNESS_SUMMARY_V1',
        'lookahead': lookahead,
        'recursive': {
            'status': 'PASS' if recursive_pass else 'BLOCKED',
            'pass': recursive_pass,
            'native_representative': recursive,
            'full_universe_metamorphic': metamorphic,
        },
        'iteration3b_capa': prior,
        'pass': bool(lookahead.get('pass') and recursive_pass),
        'decision': 'CORRECTNESS_PASS' if lookahead.get('pass') and recursive_pass else 'BLOCK_OOS_CORRECTNESS',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'lookahead': result['lookahead'], 'recursive_status': result['recursive']['status'], 'pass': result['pass'], 'decision': result['decision']}, indent=2))


if __name__ == '__main__':
    main()
