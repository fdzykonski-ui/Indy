from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd

from tools.extract_equity import portfolio_equity


ROOT = Path(__file__).resolve().parents[1]


def test_wallet_equity_sums_all_currencies_per_minute():
    frame = pd.DataFrame(
        [
            {"date": "2026-01-01T00:01:00Z", "currency": "USDC", "total_quote": 10.0},
            {"date": "2026-01-01T00:01:00Z", "currency": "BTC", "total_quote": 990.0},
            {"date": "2026-01-01T00:02:00Z", "currency": "USDC", "total_quote": 11.0},
            {"date": "2026-01-01T00:02:00Z", "currency": "BTC", "total_quote": 995.0},
        ]
    )
    aggregated = portfolio_equity(frame)
    assert aggregated["total_quote"].tolist() == [1000.0, 1006.0]
EXPECTED_CHAMPION_SHA256 = "a5ac726eab351b08605a4ac1cd1637ef4f82b91b559edcd849f37ac364a95388"
SENSITIVE_KEYS = {
    "key",
    "secret",
    "password",
    "username",
    "jwt_secret_key",
    "ws_token",
    "token",
}


def walk_keys(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key.lower()
            yield from walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_keys(child)


def test_frozen_champion_hash() -> None:
    strategy = ROOT / "champion/frozen/ED8_V741_E001FastCapture10m08bp.py"
    assert hashlib.sha256(strategy.read_bytes()).hexdigest() == EXPECTED_CHAMPION_SHA256


def test_configs_are_secret_free_and_dry_run_only() -> None:
    for config_path in (ROOT / "configs").glob("*.json"):
        config = json.loads(config_path.read_text())
        assert not (set(walk_keys(config)) & SENSITIVE_KEYS)
        assert config["dry_run"] is True
        assert config.get("api_server", {}).get("enabled", False) is False
        assert config.get("telegram", {}).get("enabled", False) is False
        assert config["exchange"]["name"] == "binance"
        assert config["trading_mode"] == "spot"
        assert config["stake_currency"] == "USDC"
        assert config["timeframe"] == "1m"
        assert config["max_open_trades"] == 1


def test_contract_hard_constraints() -> None:
    contract = json.loads((ROOT / "contracts/research_contract_v1.json").read_text())
    hard = contract["hard_constraints"]
    assert hard == {
        "exchange": "binance",
        "trading_mode": "spot",
        "quote_currency": "USDC",
        "timeframe": "1m",
        "long_only": True,
        "shorting": False,
        "futures": False,
        "grid": False,
        "position_adjustment_dca": False,
    }
