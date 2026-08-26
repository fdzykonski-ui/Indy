#!/usr/bin/env python3
"""Run Freqtrade with deterministic, file-backed Binance Spot market metadata."""
from __future__ import annotations

import json
import os
import pathlib
import sys
from typing import Any


def argument_value(flag: str) -> str | None:
    for index, item in enumerate(sys.argv[:-1]):
        if item == flag:
            return sys.argv[index + 1]
    return None


def load_config() -> dict[str, Any]:
    path = os.environ.get('FQT_CONFIG_PATH') or argument_value('-c') or argument_value('--config')
    if not path:
        raise SystemExit('FQT_CONFIG_PATH or -c/--config is required')
    return json.loads(pathlib.Path(path).read_text(encoding='utf-8'))


def filter_map(symbol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row.get('filterType'): row for row in symbol.get('filters', [])}


def positive_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
        return parsed if parsed > 0 else default
    except Exception:
        return default


CONFIG = load_config()
PAIR_WHITELIST = list(CONFIG.get('exchange', {}).get('pair_whitelist', []))
SNAPSHOT_PATH = pathlib.Path(os.environ.get('FQT_EXCHANGE_INFO_PATH', 'evidence/exchangeInfo.json'))
if not SNAPSHOT_PATH.exists():
    raise SystemExit(f'missing exchange-info snapshot: {SNAPSHOT_PATH}')
SNAPSHOT = json.loads(SNAPSHOT_PATH.read_text(encoding='utf-8'))
SYMBOL_INFO = {row['symbol']: row for row in SNAPSHOT.get('symbols', [])}


def make_markets() -> dict[str, dict[str, Any]]:
    markets: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    for pair in PAIR_WHITELIST:
        base, quote = pair.split('/')
        symbol_id = f'{base}{quote}'
        info = SYMBOL_INFO.get(symbol_id)
        if not info:
            missing.append(symbol_id)
            continue
        filters = filter_map(info)
        price_filter = filters.get('PRICE_FILTER', {})
        lot_filter = filters.get('LOT_SIZE', {})
        notional_filter = filters.get('NOTIONAL') or filters.get('MIN_NOTIONAL') or {}
        tick = positive_float(price_filter.get('tickSize'), 1e-8)
        step = positive_float(lot_filter.get('stepSize'), 1e-8)
        min_amount = positive_float(lot_filter.get('minQty'), step)
        max_amount = positive_float(lot_filter.get('maxQty'), float('inf'))
        min_cost = positive_float(notional_filter.get('minNotional'), 5.0)
        max_cost = positive_float(notional_filter.get('maxNotional'), float('inf'))
        market = {
            'id': symbol_id,
            'lowercaseId': symbol_id.lower(),
            'symbol': pair,
            'base': base,
            'quote': quote,
            'settle': None,
            'baseId': base,
            'quoteId': quote,
            'settleId': None,
            'type': 'spot',
            'spot': True,
            'margin': False,
            'swap': False,
            'future': False,
            'option': False,
            'index': False,
            'active': bool(info.get('status') == 'TRADING' and info.get('isSpotTradingAllowed', True)),
            'contract': False,
            'linear': None,
            'inverse': None,
            'subType': None,
            'taker': 0.001,
            'maker': 0.001,
            'percentage': True,
            'tierBased': False,
            'contractSize': None,
            'expiry': None,
            'expiryDatetime': None,
            'strike': None,
            'optionType': None,
            'precision': {'amount': step, 'price': tick, 'cost': tick, 'base': step, 'quote': tick},
            'limits': {
                'amount': {'min': min_amount, 'max': None if max_amount == float('inf') else max_amount},
                'price': {'min': positive_float(price_filter.get('minPrice'), tick), 'max': None},
                'cost': {'min': min_cost, 'max': None if max_cost == float('inf') else max_cost},
                'leverage': {'min': None, 'max': None},
            },
            'created': None,
            'info': info,
        }
        markets[pair] = market
    if missing:
        raise SystemExit(f'missing metadata for symbols: {missing}')
    return markets


MARKETS = make_markets()


def install(exchange: Any) -> dict[str, dict[str, Any]]:
    markets = {key: dict(value) for key, value in MARKETS.items()}
    exchange.precisionMode = 4  # ccxt.TICK_SIZE
    exchange.markets = markets
    exchange.symbols = list(markets)
    exchange.ids = [market['id'] for market in markets.values()]
    exchange.markets_by_id = {market['id']: [market] for market in markets.values()}
    currencies: dict[str, dict[str, Any]] = {}
    for market in markets.values():
        for code in (market['base'], market['quote']):
            currencies.setdefault(code, {
                'id': code, 'code': code, 'name': code, 'active': True,
                'deposit': True, 'withdraw': True, 'fee': None,
                'precision': 1e-8,
                'limits': {'amount': {'min': None, 'max': None}, 'withdraw': {'min': None, 'max': None}},
                'networks': {}, 'info': {},
            })
    exchange.currencies = currencies
    exchange.currencies_by_id = {value['id']: value for value in currencies.values()}
    return markets


import ccxt  # type: ignore
import ccxt.async_support as ccxt_async  # type: ignore


def sync_load_markets(self: Any, reload: bool = False, params: dict | None = None):
    return install(self)


async def async_load_markets(self: Any, reload: bool = False, params: dict | None = None):
    return install(self)


ccxt.binance.load_markets = sync_load_markets
ccxt_async.binance.load_markets = async_load_markets

from freqtrade.main import main
raise SystemExit(main())
