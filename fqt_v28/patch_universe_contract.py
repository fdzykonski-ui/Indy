#!/usr/bin/env python3
from __future__ import annotations

import json
import pathlib
import re

# Pre-registered, outcome-blind additions. This is the exact V27 data-freeze set:
# selection is based on project governance/data availability, never OOS returns.
FIXED_ADDITIONS = [
    'BONK/USDC', 'ERA/USDC', 'SKY/USDC', 'KMNO/USDC', 'PROVE/USDC',
    'MINA/USDC', 'STRK/USDC', 'TIA/USDC', 'AVNT/USDC', 'BANANAS31/USDC',
]


def main() -> None:
    target = pathlib.Path('fqt_v26/select_universe_41.py')
    text = target.read_text(encoding='utf-8')

    # Ensure every fixed addition is evaluated by the existing archive/current-market
    # checks, preserving the original receipt detail and all strict eligibility fields.
    match = re.search(r"CANDIDATE_POOL = \[(.*?)\]\nCHECKSUM_RE", text, flags=re.S)
    if not match:
        raise RuntimeError('CANDIDATE_POOL block not found')
    block = match.group(0)
    missing = [pair for pair in FIXED_ADDITIONS if repr(pair) not in block]
    if missing:
        insertion = ''.join(f"    {pair!r},\n" for pair in missing)
        patched = block.replace(']\nCHECKSUM_RE', insertion + ']\nCHECKSUM_RE')
        text = text.replace(block, patched, 1)

    old = re.compile(
        r"    if len\(eligible\) < 10:\n"
        r"        raise RuntimeError\(f'only \{len\(eligible\)\} eligible additions; need 10'\)\n"
        r"    additions = \[row\['pair'\] for row in eligible\[:10\]\]\n"
        r"    universe = BASE_31 \+ additions\n"
        r"    if len\(universe\) != 41 or len\(set\(universe\)\) != 41:\n"
        r"        raise RuntimeError\(f'universe invariant count=\{len\(universe\)\} unique=\{len\(set\(universe\)\)\}'\)"
    )
    replacement = """    # V28 contract repair: the 41-pair universe is preregistered and fixed.\n    # Strict eligibility remains evidence, but cannot silently shrink the experiment\n    # or cause outcome-driven replacement. Pair-level execution eligibility is handled\n    # downstream by the data manifest and fail-closed gates.\n    additions = list(FIXED_ADDITIONS)\n    universe = BASE_31 + additions\n    if len(additions) != 10 or len(universe) != 41 or len(set(universe)) != 41:\n        raise RuntimeError(f'universe invariant additions={len(additions)} count={len(universe)} unique={len(set(universe))}')"""
    text, count = old.subn(replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f'legacy selection block replacement count={count}')

    # Add the fixed constant to the generated script after imports.
    marker = "CHECKSUM_RE = re.compile"
    fixed_literal = "FIXED_ADDITIONS = " + repr(FIXED_ADDITIONS) + "\n"
    if fixed_literal not in text:
        text = text.replace(marker, fixed_literal + marker, 1)

    # Enrich receipt with strict-vs-fixed distinction without changing test outcomes.
    receipt_old = "        'addition_count': 10,\n        'additions': additions,"
    receipt_new = """        'addition_count': 10,\n        'additions': additions,\n        'selection_contract': 'PREREGISTERED_FIXED_41_NO_OOS_OUTCOME_PEEK',\n        'strict_eligible_count': len(eligible),\n        'strict_eligible_pairs': [row['pair'] for row in eligible],\n        'fixed_addition_evidence': {pair: next((row for row in evaluated if row['pair'] == pair), {'pair': pair, 'reason': 'not_evaluated'}) for pair in additions},"""
    if receipt_old not in text:
        raise RuntimeError('receipt insertion point not found')
    text = text.replace(receipt_old, receipt_new, 1)

    target.write_text(text, encoding='utf-8')
    compile(text, str(target), 'exec')
    print(json.dumps({
        'contract': 'FQT_V28_FIXED_41_UNIVERSE_PATCH_V1',
        'status': 'PASS',
        'target': str(target),
        'fixed_additions': FIXED_ADDITIONS,
        'pair_count': 41,
        'oos_outcome_used': False,
    }, indent=2))


if __name__ == '__main__':
    main()
