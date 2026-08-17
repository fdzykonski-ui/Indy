#!/usr/bin/env python3
"""Run the supplied Freqtrade checkout without exchange-network metadata calls.

This wrapper provides a minimal, explicit BTC/USDC Binance spot market catalog.
It is suitable only for deterministic OHLCV research against already downloaded
data. It is not evidence about live order filters, liquidity, or execution.
"""

from __future__ import annotations

import os
import sys
from copy import deepcopy


BTC_USDC_MARKET = {
    "id": "BTCUSDC",
    "symbol": "BTC/USDC",
    "base": "BTC",
    "quote": "USDC",
    "baseId": "BTC",
    "quoteId": "USDC",
    "active": True,
    "spot": True,
    "margin": False,
    "swap": False,
    "future": False,
    "option": False,
    "contract": False,
    "linear": None,
    "inverse": None,
    "type": "spot",
    "contractSize": None,
    "percentage": True,
    "tierBased": False,
    "taker": 0.001,
    "maker": 0.001,
    # Recovered from historical trade amounts: all exported BTC amounts were
    # quantized to six decimal places. Keeping this explicit is necessary for
    # exact stake/profit reproduction under unlimited staking.
    "precision": {"amount": 0.000001, "price": 0.01, "cost": 0.00000001},
    "limits": {
        "amount": {"min": 0.000001, "max": 9000.0},
        "price": {"min": 0.01, "max": 10000000.0},
        "cost": {"min": 0.00000001, "max": 90000000000.0},
        "leverage": {"min": 1.0, "max": 1.0},
    },
    "info": {"source": "FQT_RND_OFFLINE_SYNTHETIC_CATALOG"},
}


def offline_catalog() -> dict[str, dict]:
    return {"BTC/USDC": deepcopy(BTC_USDC_MARKET)}


def install_offline_market_patch() -> None:
    from freqtrade.exchange import Exchange

    def _load_async_markets_offline(self: Exchange, reload: bool = False) -> None:
        del reload
        self._api_async.set_markets(offline_catalog())
        return None

    Exchange._load_async_markets = _load_async_markets_offline


def main() -> int:
    os.environ.setdefault("NO_PROXY", "*")
    os.environ.setdefault("no_proxy", "*")
    install_offline_market_patch()
    print(
        "FQT_RND_OFFLINE_MARKET_CATALOG=BTC/USDC; "
        "execution/liquidity/live-order evidence=false",
        file=sys.stderr,
    )
    from freqtrade.main import main as freqtrade_main

    result = freqtrade_main()
    return int(result or 0)


if __name__ == "__main__":
    raise SystemExit(main())
