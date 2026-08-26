#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import shutil
import statistics
import time
import urllib.error
import urllib.request
import zipfile

import pandas as pd

BASE_31 = [
    'BTC/USDC','ETH/USDC','SOL/USDC','XRP/USDC','BNB/USDC','DOGE/USDC','ENA/USDC','HBAR/USDC',
    'LTC/USDC','AAVE/USDC','XPL/USDC','LINK/USDC','BCH/USDC','DOT/USDC','PUMP/USDC','TRX/USDC',
    'AVAX/USDC','UNI/USDC','ARB/USDC','PENDLE/USDC','SYRUP/USDC','ALGO/USDC','ZK/USDC','WLFI/USDC',
    'FIL/USDC','ASTER/USDC','SHIB/USDC','SEI/USDC','DASH/USDC','2Z/USDC','ATOM/USDC'
]
CANDIDATE_POOL = [
    'ADA/USDC','SUI/USDC','NEAR/USDC','OP/USDC','INJ/USDC','PEPE/USDC','WIF/USDC','JUP/USDC',
    'FET/USDC','RENDER/USDC','TIA/USDC','ICP/USDC','STX/USDC','GALA/USDC','SAND/USDC','MANA/USDC',
    'APT/USDC','ETC/USDC','XLM/USDC','VET/USDC','POL/USDC','TON/USDC','FLOKI/USDC','BONK/USDC',
    'TAO/USDC','CRV/USDC','RUNE/USDC','IMX/USDC','GRT/USDC','LDO/USDC','ONDO/USDC','OM/USDC',
    'WLD/USDC','PYTH/USDC','JTO/USDC','ORDI/USDC','AR/USDC','EIGEN/USDC','JASMY/USDC','KAITO/USDC'
]
CHECKSUM_RE = re.compile(r'^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$')


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1 << 20), b''):
            h.update(block)
    return h.hexdigest()


def fetch_bytes(url: str, retries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'FQT-V26-UNIVERSE/1.0'})
            with urllib.request.urlopen(req, timeout=45) as response:
                return response.read()
        except Exception as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 404:
                raise
            if attempt + 1 < retries:
                time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f'fetch failed {url}: {last!r}')


def checksum_exists(symbol: str, period: str, kind: str) -> tuple[bool, str | None]:
    if kind == 'monthly':
        name = f'{symbol}-1m-{period}.zip'
        url = f'https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/{name}.CHECKSUM'
    else:
        name = f'{symbol}-1m-{period}.zip'
        url = f'https://data.binance.vision/data/spot/daily/klines/{symbol}/1m/{name}.CHECKSUM'
    try:
        text = fetch_bytes(url).decode('utf-8').strip()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False, None
        raise
    match = CHECKSUM_RE.match(text)
    if not match or pathlib.Path(match.group(2)).name != name:
        raise RuntimeError(f'invalid checksum receipt {url}: {text!r}')
    return True, match.group(1).lower()


def january_liquidity(symbol: str, raw: pathlib.Path) -> dict:
    name = f'{symbol}-1m-2026-01.zip'
    base = f'https://data.binance.vision/data/spot/monthly/klines/{symbol}/1m/{name}'
    directory = raw / symbol
    directory.mkdir(parents=True, exist_ok=True)
    archive = directory / name
    checksum_path = directory / f'{name}.CHECKSUM'
    if not checksum_path.exists():
        checksum_path.write_bytes(fetch_bytes(base + '.CHECKSUM'))
    text = checksum_path.read_text(encoding='utf-8').strip()
    match = CHECKSUM_RE.match(text)
    if not match or pathlib.Path(match.group(2)).name != name:
        raise RuntimeError(f'bad checksum {checksum_path}')
    if not archive.exists():
        archive.write_bytes(fetch_bytes(base))
    actual = sha256(archive)
    if actual != match.group(1).lower():
        raise RuntimeError(f'hash mismatch {name}: {actual} != {match.group(1).lower()}')
    with zipfile.ZipFile(archive) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise RuntimeError(f'CRC error {name}: {bad}')
        members = [m for m in zf.namelist() if not m.endswith('/')]
        if len(members) != 1:
            raise RuntimeError(f'member count {name}: {members}')
        with zf.open(members[0]) as handle:
            df = pd.read_csv(handle, header=None)
    if len(df) != 44_640 or df.shape[1] != 12:
        raise RuntimeError(f'January schema {name}: rows={len(df)} cols={df.shape[1]}')
    volume = pd.to_numeric(df.iloc[:, 5], errors='raise')
    quote_volume = pd.to_numeric(df.iloc[:, 7], errors='raise')
    return {
        'archive_sha256': actual,
        'rows': len(df),
        'zero_volume_ratio': float((volume == 0).mean()),
        'median_quote_volume_1m': float(statistics.median(quote_volume)),
        'sum_quote_volume': float(quote_volume.sum()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-config', type=pathlib.Path, required=True)
    parser.add_argument('--out-config', type=pathlib.Path, required=True)
    parser.add_argument('--receipt', type=pathlib.Path, required=True)
    parser.add_argument('--raw', type=pathlib.Path, required=True)
    args = parser.parse_args()

    exchange_info = json.loads(fetch_bytes(
        'https://data-api.binance.vision/api/v3/exchangeInfo?permissions=SPOT&showPermissionSets=true'
    ))
    symbols = {row['symbol']: row for row in exchange_info.get('symbols', [])}
    evaluated: list[dict] = []
    for pair in CANDIDATE_POOL:
        symbol = pair.replace('/', '')
        meta = symbols.get(symbol)
        row = {
            'pair': pair,
            'symbol': symbol,
            'current_trading': False,
            'complete_archive_contract': False,
            'eligible': False,
        }
        if not meta:
            row['reason'] = 'missing_current_exchange_info'
            evaluated.append(row)
            continue
        current_ok = bool(
            meta.get('status') == 'TRADING'
            and meta.get('quoteAsset') == 'USDC'
            and meta.get('isSpotTradingAllowed', False)
        )
        row['current_trading'] = current_ok
        if not current_ok:
            row['reason'] = 'not_current_spot_usdc_trading'
            evaluated.append(row)
            continue
        checks = []
        for period, kind in [('2025-12', 'monthly'), ('2026-01', 'monthly'), ('2026-07', 'monthly'), ('2026-08-14', 'daily')]:
            exists, digest = checksum_exists(symbol, period, kind)
            checks.append({'period': period, 'kind': kind, 'exists': exists, 'sha256': digest})
        row['archive_checks'] = checks
        row['complete_archive_contract'] = all(check['exists'] for check in checks)
        if not row['complete_archive_contract']:
            row['reason'] = 'incomplete_archive_contract'
            evaluated.append(row)
            continue
        liq = january_liquidity(symbol, args.raw)
        row.update(liq)
        row['eligible'] = bool(liq['zero_volume_ratio'] <= 0.10 and liq['median_quote_volume_1m'] > 0)
        row['reason'] = 'eligible' if row['eligible'] else 'liquidity_threshold_fail'
        evaluated.append(row)

    eligible = sorted(
        [row for row in evaluated if row['eligible']],
        key=lambda row: (row['median_quote_volume_1m'], row['sum_quote_volume']),
        reverse=True,
    )
    if len(eligible) < 10:
        raise RuntimeError(f'only {len(eligible)} eligible additions; need 10')
    additions = [row['pair'] for row in eligible[:10]]
    universe = BASE_31 + additions
    if len(universe) != 41 or len(set(universe)) != 41:
        raise RuntimeError(f'universe invariant count={len(universe)} unique={len(set(universe))}')

    config = json.loads(args.base_config.read_text(encoding='utf-8'))
    config['exchange']['pair_whitelist'] = universe
    config['max_open_trades'] = 1
    config['stake_amount'] = 'unlimited'
    config['dry_run_wallet'] = 1000
    config['tradable_balance_ratio'] = 0.99
    config['dry_run'] = True
    config['initial_state'] = 'stopped'
    config.setdefault('api_server', {})['enabled'] = False
    config.setdefault('telegram', {})['enabled'] = False
    config['evidence_status'] = 'FQT_V26_41PAIR_TRAINING_SELECTED_NO_PERFORMANCE_PEEK'
    args.out_config.parent.mkdir(parents=True, exist_ok=True)
    args.out_config.write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')

    receipt = {
        'contract': 'FQT_V26_41PAIR_UNIVERSE_SELECTION_V1',
        'base_31': BASE_31,
        'candidate_pool': CANDIDATE_POOL,
        'selection_data': 'January 2026 quote volume and zero-volume only; no trade outcomes; archive availability checks through 2026-08-14',
        'addition_count': 10,
        'additions': additions,
        'universe': universe,
        'universe_count': len(universe),
        'evaluated': evaluated,
        'config_sha256': sha256(args.out_config),
        'current_exchange_server_time': exchange_info.get('serverTime'),
        'survivorship_caveat': 'Current trading status is a present-time proxy; immutable archive availability is separately proven.',
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'additions': additions, 'universe_count': len(universe), 'config_sha256': receipt['config_sha256']}, indent=2))


if __name__ == '__main__':
    main()
