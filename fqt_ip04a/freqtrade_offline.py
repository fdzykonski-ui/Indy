#!/usr/bin/env python3
"""Run local Freqtrade with deterministic offline Binance spot market metadata."""
from __future__ import annotations
import sys
from typing import Any

PAIRS = [
    'BTC/USDC','ETH/USDC','SOL/USDC','XRP/USDC','BNB/USDC','DOGE/USDC','ENA/USDC','HBAR/USDC',
    'LTC/USDC','AAVE/USDC','XPL/USDC','LINK/USDC','BCH/USDC','DOT/USDC','PUMP/USDC','TRX/USDC',
    'AVAX/USDC','UNI/USDC','ARB/USDC','PENDLE/USDC','SYRUP/USDC','ALGO/USDC','ZK/USDC','WLFI/USDC',
    'FIL/USDC','ASTER/USDC','SHIB/USDC','SEI/USDC','DASH/USDC','2Z/USDC','ATOM/USDC'
]

def make_markets() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for symbol in PAIRS:
        base, quote = symbol.split('/')
        market = {
            'id': f'{base}{quote}', 'lowercaseId': f'{base}{quote}'.lower(), 'symbol': symbol,
            'base': base, 'quote': quote, 'settle': None,
            'baseId': base, 'quoteId': quote, 'settleId': None,
            'type': 'spot', 'spot': True, 'margin': False, 'swap': False,
            'future': False, 'option': False, 'index': False, 'active': True,
            'contract': False, 'linear': None, 'inverse': None, 'subType': None,
            'taker': 0.001, 'maker': 0.001, 'percentage': True, 'tierBased': False,
            'contractSize': None, 'expiry': None, 'expiryDatetime': None,
            'strike': None, 'optionType': None,
            'precision': {'amount': 1e-8, 'price': 1e-8, 'cost': 1e-8, 'base': 1e-8, 'quote': 1e-8},
            'limits': {
                'amount': {'min': 1e-8, 'max': None},
                'price': {'min': 1e-8, 'max': None},
                'cost': {'min': 5.0, 'max': None},
                'leverage': {'min': None, 'max': None},
            },
            'created': None, 'info': {},
        }
        out[symbol] = market
    return out

MARKETS = make_markets()

def install(exchange: Any) -> dict[str, dict[str, Any]]:
    markets = {k: dict(v) for k, v in MARKETS.items()}
    exchange.precisionMode = 4  # ccxt.TICK_SIZE
    exchange.markets = markets
    exchange.symbols = list(markets)
    exchange.ids = [m['id'] for m in markets.values()]
    exchange.markets_by_id = {m['id']: [m] for m in markets.values()}
    currencies: dict[str, dict[str, Any]] = {}
    for m in markets.values():
        for code in (m['base'], m['quote']):
            currencies.setdefault(code, {
                'id': code, 'code': code, 'name': code, 'active': True,
                'deposit': True, 'withdraw': True, 'fee': None,
                'precision': 1e-8,
                'limits': {'amount': {'min': None, 'max': None}, 'withdraw': {'min': None, 'max': None}},
                'networks': {}, 'info': {},
            })
    exchange.currencies = currencies
    exchange.currencies_by_id = {v['id']: v for v in currencies.values()}
    return markets

import ccxt  # type: ignore
import ccxt.async_support as ccxt_async  # type: ignore

def sync_load_markets(self: Any, reload: bool = False, params: dict | None = None):
    return install(self)

async def async_load_markets(self: Any, reload: bool = False, params: dict | None = None):
    return install(self)

ccxt.binance.load_markets = sync_load_markets
ccxt_async.binance.load_markets = async_load_markets

# No remote currency/market calls should be necessary after load_markets is replaced.
from freqtrade.main import main
raise SystemExit(main())
