#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import pathlib
import tarfile
import zipfile
from typing import Any


def walk_blob(data: bytes, name: str, depth: int = 0):
    if depth > 5:
        return
    bio = io.BytesIO(data)
    if zipfile.is_zipfile(bio):
        with zipfile.ZipFile(bio) as zf:
            for member in zf.infolist():
                if member.is_dir():
                    continue
                yield from walk_blob(zf.read(member), f'{name}::{member.filename}', depth + 1)
        return
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:*') as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                handle = tf.extractfile(member)
                if handle is not None:
                    yield from walk_blob(handle.read(), f'{name}::{member.name}', depth + 1)
            return
    except tarfile.TarError:
        pass
    lower = name.lower()
    if lower.endswith('.json'):
        try:
            yield name, 'json', json.loads(data.decode('utf-8'))
        except Exception:
            return
    elif lower.endswith('.csv'):
        try:
            rows = list(csv.DictReader(io.StringIO(data.decode('utf-8-sig'))))
            yield name, 'csv', rows
        except Exception:
            return
    elif lower.endswith(('.log', '.txt')):
        try:
            yield name, 'text', data.decode('utf-8', errors='replace')
        except Exception:
            return


def bool_value(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {'true','yes','1','pass','passed','ok'}:
        return True
    if text in {'false','no','0','fail','failed'}:
        return False
    return None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--artifact', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    args = parser.parse_args()
    records = list(walk_blob(args.artifact.read_bytes(), args.artifact.name))
    lookahead_candidates: list[dict[str, Any]] = []
    recursive_candidates: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []

    for source, kind, obj in records:
        low = source.lower()
        if kind == 'json':
            contract = str(obj.get('contract', '')).lower() if isinstance(obj, dict) else ''
            if isinstance(obj, dict) and ('lookahead' in low or 'lookahead' in contract):
                valid = bool_value(obj.get('valid_verdict'))
                bias = bool_value(obj.get('has_bias'))
                rows = obj.get('row_count', obj.get('rows', obj.get('csv_rows', 0)))
                lookahead_candidates.append({'source': source, 'valid_verdict': valid, 'has_bias': bias, 'row_count': rows, 'object': obj})
            if isinstance(obj, dict) and ('recursive' in low or 'recursive' in contract):
                passed = bool_value(obj.get('pass', obj.get('passed', obj.get('valid_verdict', obj.get('status')))))
                max_dev = obj.get('max_deviation_pct', obj.get('max_abs_deviation_pct', obj.get('max_indicator_deviation_pct')))
                recursive_candidates.append({'source': source, 'pass': passed, 'max_deviation_pct': max_dev, 'object': obj})
        elif kind == 'csv' and 'lookahead' in low:
            bias_values: list[bool] = []
            for row in obj:
                normalized = {str(key).strip().lower().replace(' ', '_'): value for key, value in row.items()}
                value = bool_value(normalized.get('has_bias'))
                if value is not None:
                    bias_values.append(value)
            if bias_values:
                lookahead_candidates.append({'source': source, 'valid_verdict': True, 'has_bias': any(bias_values), 'row_count': len(obj), 'object': obj})
        elif kind == 'text' and ('lookahead' in low or 'recursive' in low):
            logs.append({'source': source, 'tail': '\n'.join(obj.splitlines()[-40:])})

    valid_lookahead = [row for row in lookahead_candidates if row.get('valid_verdict') is True and row.get('has_bias') is not None and int(row.get('row_count') or 0) > 0]
    chosen_lookahead = sorted(valid_lookahead, key=lambda row: int(row.get('row_count') or 0), reverse=True)[0] if valid_lookahead else None
    recursive_pass = [row for row in recursive_candidates if row.get('pass') is True]
    chosen_recursive = recursive_pass[0] if recursive_pass else None

    result = {
        'contract': 'FQT_V26_ITERATION3B_CAPA_NORMALIZATION_V1',
        'artifact': args.artifact.name,
        'record_count': len(records),
        'lookahead': {
            'status': 'PASS' if chosen_lookahead and not chosen_lookahead['has_bias'] else ('FAIL' if chosen_lookahead else 'BLOCKED'),
            'valid_verdict': bool(chosen_lookahead),
            'has_bias': chosen_lookahead['has_bias'] if chosen_lookahead else None,
            'row_count': chosen_lookahead['row_count'] if chosen_lookahead else 0,
            'source': chosen_lookahead['source'] if chosen_lookahead else None,
            'candidate_count': len(lookahead_candidates),
        },
        'recursive': {
            'status': 'PASS_LIMITED' if chosen_recursive else 'BLOCKED',
            'pass': bool(chosen_recursive),
            'max_deviation_pct': chosen_recursive.get('max_deviation_pct') if chosen_recursive else None,
            'source': chosen_recursive['source'] if chosen_recursive else None,
            'candidate_count': len(recursive_candidates),
        },
        'raw_lookahead_candidates': lookahead_candidates,
        'raw_recursive_candidates': recursive_candidates,
        'relevant_log_tails': logs,
        'decision': 'CAPA_CLOSED' if chosen_lookahead and not chosen_lookahead['has_bias'] else 'CAPA_REMAINS_OPEN',
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, default=str) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ['lookahead','recursive','decision']}, indent=2))


if __name__ == '__main__':
    main()
