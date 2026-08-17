#!/usr/bin/env python3
"""Freeze the supplied Champion and emit only secret-free reproduction inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from zipfile import ZipFile


SENSITIVE_KEYS = {
    "key",
    "secret",
    "password",
    "username",
    "jwt_secret_key",
    "ws_token",
    "token",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, mode)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def assert_no_sensitive_values(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key.lower() in SENSITIVE_KEYS:
                raise ValueError(f"sensitive key survived sanitization: {path}.{key}")
            assert_no_sensitive_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            assert_no_sensitive_values(child, f"{path}[{index}]")


def sanitize_config(source: dict, wallet: float) -> dict:
    """Use an explicit allowlist so unknown historical fields cannot leak."""
    exchange = source.get("exchange", {})
    sanitized = {
        "$schema": source.get("$schema", "https://schema.freqtrade.io/schema.json"),
        "version": 3,
        "bot_name": "FQT_RND_OFFLINE",
        "trading_mode": "spot",
        "margin_mode": "",
        "timeframe": "1m",
        "max_open_trades": 1,
        "stake_currency": "USDC",
        "stake_amount": "unlimited",
        "tradable_balance_ratio": float(source.get("tradable_balance_ratio", 0.99)),
        "fiat_display_currency": source.get("fiat_display_currency", "USD"),
        "dry_run": True,
        "dry_run_wallet": float(wallet),
        "cancel_open_orders_on_exit": False,
        "force_entry_enable": False,
        "dataformat_ohlcv": "parquet",
        "db_url": "sqlite://",
        "exchange": {
            "name": "binance",
            "enable_ws": False,
            "ccxt_config": exchange.get("ccxt_config", {}),
            "ccxt_async_config": exchange.get("ccxt_async_config", {}),
            "pair_whitelist": ["BTC/USDC"],
            "pair_blacklist": [],
        },
        "pairlists": [{"method": "StaticPairList"}],
        "entry_pricing": source.get(
            "entry_pricing", {"price_side": "other", "use_order_book": False}
        ),
        "exit_pricing": source.get(
            "exit_pricing", {"price_side": "other", "use_order_book": False}
        ),
        "order_types": source.get(
            "order_types",
            {
                "entry": "limit",
                "exit": "limit",
                "stoploss": "market",
                "stoploss_on_exchange": False,
            },
        ),
        "order_time_in_force": source.get(
            "order_time_in_force", {"entry": "GTC", "exit": "GTC"}
        ),
        "unfilledtimeout": source.get(
            "unfilledtimeout", {"entry": 90, "exit": 120, "unit": "seconds"}
        ),
        "internals": source.get(
            "internals", {"process_only_new_candles": True, "process_throttle_secs": 15}
        ),
    }
    assert_no_sensitive_values(sanitized)
    return sanitized


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", type=Path, required=True)
    parser.add_argument("--backtest-zip", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    external = args.strategy.read_bytes()
    with ZipFile(args.backtest_zip) as archive:
        strategy_names = [n for n in archive.namelist() if n.endswith("_ED8.py")]
        config_names = [n for n in archive.namelist() if n.endswith("_config.json")]
        if len(strategy_names) != 1 or len(config_names) != 1:
            raise ValueError("expected exactly one embedded ED8 strategy and config")
        embedded = archive.read(strategy_names[0])
        raw_config = archive.read(config_names[0])

    if external != embedded:
        raise ValueError("external and embedded Champion strategy differ")

    strategy_target = args.output_dir / "frozen" / "ED8_V741_E001FastCapture10m08bp.py"
    atomic_write(strategy_target, external, mode=0o444)

    historical = sanitize_config(json.loads(raw_config), wallet=50.0)
    comparison = sanitize_config(json.loads(raw_config), wallet=1000.0)
    historical["strategy"] = "ED8"
    comparison["strategy"] = "ED8"

    config_dir = args.output_dir.parent / "configs"
    atomic_write(
        config_dir / "champion_v741_historical_repro.json",
        (json.dumps(historical, indent=2, sort_keys=True) + "\n").encode(),
    )
    atomic_write(
        config_dir / "common_research_1000usdc.json",
        (json.dumps(comparison, indent=2, sort_keys=True) + "\n").encode(),
    )

    manifest = {
        "status": "VERIFIZIERT",
        "claim": "external and embedded V741 strategy bytes are identical",
        "strategy_sha256": sha256(external),
        "embedded_strategy_sha256": sha256(embedded),
        "raw_config_sha256": sha256(raw_config),
        "raw_config_contains_sensitive_keys": True,
        "raw_config_publishable": False,
        "sanitized_historical_config_sha256": sha256(
            (json.dumps(historical, indent=2, sort_keys=True) + "\n").encode()
        ),
        "sanitized_comparison_config_sha256": sha256(
            (json.dumps(comparison, indent=2, sort_keys=True) + "\n").encode()
        ),
        "immutability": "Frozen file is read-only; tests enforce the strategy hash.",
    }
    atomic_write(
        args.output_dir / "CHAMPION_MANIFEST.json",
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
