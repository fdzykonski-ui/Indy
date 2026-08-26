#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re

PERCENT = re.compile(r'([-+]?\d+(?:\.\d+)?)\s*%')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--logs-dir', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--tolerance-pct', type=float, default=0.01)
    args = parser.parse_args()
    rows = []
    for rc_path in sorted(args.logs_dir.glob('recursive_*.rc')):
        stem = rc_path.stem.replace('recursive_', '')
        log_path = args.logs_dir / f'recursive_{stem}.log'
        rc = int(rc_path.read_text(encoding='utf-8').strip())
        text = log_path.read_text(encoding='utf-8', errors='replace') if log_path.exists() else ''
        values: list[float] = []
        table_seen = False
        for line in text.splitlines():
            low = line.lower()
            if 'indicator' in low and ('startup' in low or '%' in line or 'recursive' in low):
                table_seen = True
            if table_seen and ('|' in line or '│' in line):
                values.extend(float(match.group(1)) for match in PERCENT.finditer(line))
        max_abs = max((abs(value) for value in values), default=None)
        errors = any(token in text for token in ['Traceback (most recent call last)', 'OperationalException', 'ERROR -'])
        passed = bool(rc == 0 and not errors and values and max_abs is not None and max_abs <= args.tolerance_pct)
        rows.append({
            'pair_token': stem,
            'exit_code': rc,
            'table_seen': table_seen,
            'percentage_values': len(values),
            'max_abs_deviation_pct': max_abs,
            'error_marker': errors,
            'pass': passed,
            'log': str(log_path),
        })
    output = {
        'contract': 'FQT_V26_NATIVE_RECURSIVE_REPRESENTATIVE_MATRIX_V1',
        'pair_count': len(rows),
        'tolerance_pct': args.tolerance_pct,
        'rows': rows,
        'failed': [row['pair_token'] for row in rows if not row['pass']],
        'pass': bool(rows and all(row['pass'] for row in rows)),
        'status': 'PASS' if rows and all(row['pass'] for row in rows) else 'BLOCKED',
        'scope': 'Native recursive-analysis on representative high-price, high-liquidity, low-price and newly-added pairs.',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'pair_count': len(rows), 'failed': output['failed'], 'pass': output['pass']}, indent=2))
    if not output['pass']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
