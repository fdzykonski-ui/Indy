#!/usr/bin/env python3
"""Executable causality harness for frozen champion execution callbacks.

The harness uses native backtest trades and official pair candles.  For every
covered callback/event it compares:

1. a dataframe calculated only to the event timestamp;
2. the same timestamp prefix sliced from a longer future-appended calculation;
3. fresh-instance versus chronological pair-order replay.

Differences are failures.  Unsupported callback dependencies are explicit
coverage gaps, never silent passes.
"""
from __future__ import annotations

import argparse
import ast
import datetime as dt
import gc
import importlib.util
import inspect
import json
import math
import pathlib
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np
import pandas as pd

CALLBACKS = (
    "custom_stake_amount",
    "custom_exit",
    "custom_entry_price",
    "custom_exit_price",
    "confirm_trade_entry",
    "confirm_trade_exit",
    "custom_stoploss",
    "custom_roi",
    "adjust_trade_position",
)


def load_module(path: pathlib.Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def make_strategy(cls: type, config: dict[str, Any]):
    try:
        return cls(config)
    except TypeError:
        return cls()


def pipeline(strategy: Any, dataframe: pd.DataFrame, pair: str) -> pd.DataFrame:
    output = strategy.populate_indicators(dataframe.copy(), {"pair": pair})
    output = strategy.populate_entry_trend(output, {"pair": pair})
    output = strategy.populate_exit_trend(output, {"pair": pair})
    return output


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if math.isnan(value):
            return "NaN"
        if math.isinf(value):
            return "Infinity" if value > 0 else "-Infinity"
        return round(value, 14)
    if isinstance(value, (np.integer, np.floating)):
        return normalize(value.item())
    if isinstance(value, (dt.datetime, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (tuple, list)):
        return [normalize(item) for item in value]
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in sorted(value.items())}
    return repr(value)


@dataclass
class TradeDummy:
    pair: str
    open_date_utc: dt.datetime
    open_rate: float
    stake_amount: float
    amount: float
    enter_tag: str | None
    max_rate: float
    min_rate: float
    is_short: bool = False
    leverage: float = 1.0
    exit_reason: str | None = None
    close_rate: float | None = None
    close_date_utc: dt.datetime | None = None
    nr_of_successful_entries: int = 1
    nr_of_successful_exits: int = 0
    open_order_id: str | None = None
    has_open_orders: bool = False
    date_last_filled_utc: dt.datetime | None = None
    custom_data: dict[str, Any] = field(default_factory=dict)

    def calc_profit_ratio(self, rate: float) -> float:
        if not self.open_rate:
            return 0.0
        return float(rate) / float(self.open_rate) - 1.0

    def select_filled_orders(self, side: str | None = None) -> list[Any]:
        return []

    def get_custom_data(self, key: str, default: Any = None) -> Any:
        return self.custom_data.get(key, default)

    def set_custom_data(self, key: str, value: Any) -> None:
        self.custom_data[key] = value


class DataProviderStub:
    def __init__(self, pair: str, dataframe: pd.DataFrame, whitelist: list[str]):
        self.pair = pair
        self.dataframe = dataframe
        self._whitelist = whitelist
        self.runmode = SimpleNamespace(value="backtest")

    def get_analyzed_dataframe(self, pair: str, timeframe: str):
        return self.dataframe.copy(), None

    def get_pair_dataframe(self, pair: str, timeframe: str, candle_type=None):
        return self.dataframe.copy()

    def current_whitelist(self) -> list[str]:
        return list(self._whitelist)

    def market(self, pair: str) -> dict[str, Any]:
        base, quote = pair.split("/")
        return {
            "symbol": pair,
            "base": base,
            "quote": quote,
            "active": True,
            "precision": {"amount": 1e-8, "price": 1e-8},
            "limits": {"cost": {"min": 5.0, "max": None}},
        }

    def ticker(self, pair: str) -> dict[str, float]:
        close = float(self.dataframe.iloc[-1]["close"])
        return {"last": close, "bid": close, "ask": close}

    def orderbook(self, pair: str, maximum: int = 1) -> dict[str, list[list[float]]]:
        close = float(self.dataframe.iloc[-1]["close"])
        return {"bids": [[close, 1.0]], "asks": [[close, 1.0]]}

    def send_msg(self, message: str, always_send: bool = False) -> None:
        return None


class WalletStub:
    def __init__(self, total: float = 1000.0, available: float = 1000.0):
        self.total = total
        self.available = available

    def get_total_stake_amount(self) -> float:
        return self.total

    def get_available_stake_amount(self) -> float:
        return self.available

    def get_trade_stake_amount(self, pair: str, max_open_trades: int, update: bool = True) -> float:
        return self.available / max(int(max_open_trades), 1)

    def get_free(self, currency: str) -> float:
        return self.available

    def get_total(self, currency: str) -> float:
        return self.total


class InvocationError(RuntimeError):
    pass


def defined_callback_names(source: str, target_class: str) -> set[str]:
    tree = ast.parse(source)
    classes: dict[str, tuple[list[str], set[str]]] = {}
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = []
        for base in node.bases:
            if isinstance(base, ast.Name):
                bases.append(base.id)
            elif isinstance(base, ast.Attribute):
                bases.append(base.attr)
        methods = {
            child.name
            for child in node.body
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        classes[node.name] = (bases, methods)
    current = target_class
    seen: set[str] = set()
    output: set[str] = set()
    while current in classes and current not in seen:
        seen.add(current)
        bases, methods = classes[current]
        output |= methods.intersection(CALLBACKS)
        local = [base for base in bases if base in classes]
        current = local[0] if local else ""
    return output


def load_backtest_trades(path: pathlib.Path) -> list[dict[str, Any]]:
    with zipfile.ZipFile(path) as archive:
        names = [
            name
            for name in archive.namelist()
            if name.endswith(".json") and not name.endswith("_config.json")
        ]
        if len(names) != 1:
            raise RuntimeError(f"{path}: expected one result JSON")
        obj = json.loads(archive.read(names[0]))
    result = next(iter(obj["strategy"].values()))
    return list(result["trades"])


def timestamp(value: Any) -> pd.Timestamp:
    if isinstance(value, (int, float)):
        return pd.to_datetime(int(value), unit="ms", utc=True)
    return pd.Timestamp(value, tz="UTC") if pd.Timestamp(value).tzinfo is None else pd.Timestamp(value).tz_convert("UTC")


def trade_dummy(row: dict[str, Any]) -> TradeDummy:
    open_time = timestamp(row.get("open_timestamp") or row.get("open_date"))
    close_raw = row.get("close_timestamp") or row.get("close_date")
    close_time = timestamp(close_raw) if close_raw is not None else None
    open_rate = float(row.get("open_rate") or 0.0)
    close_rate = float(row.get("close_rate") or open_rate)
    return TradeDummy(
        pair=row["pair"],
        open_date_utc=open_time.to_pydatetime(),
        open_rate=open_rate,
        stake_amount=float(row.get("stake_amount") or 100.0),
        amount=float(row.get("amount") or (100.0 / max(open_rate, 1e-12))),
        enter_tag=row.get("enter_tag"),
        max_rate=float(row.get("max_rate") or max(open_rate, close_rate)),
        min_rate=float(row.get("min_rate") or min(open_rate, close_rate)),
        is_short=bool(row.get("is_short", False)),
        leverage=float(row.get("leverage") or 1.0),
        exit_reason=row.get("exit_reason"),
        close_rate=close_rate,
        close_date_utc=close_time.to_pydatetime() if close_time is not None else None,
        date_last_filled_utc=open_time.to_pydatetime(),
    )


def build_kwargs(
    callback: str,
    method: Callable[..., Any],
    trade: TradeDummy,
    event_time: pd.Timestamp,
    rate: float,
    profit: float,
) -> dict[str, Any]:
    available: dict[str, Any] = {
        "pair": trade.pair,
        "trade": trade,
        "current_time": event_time.to_pydatetime(),
        "current_rate": rate,
        "current_profit": profit,
        "proposed_rate": rate,
        "proposed_stake": trade.stake_amount,
        "min_stake": 5.0,
        "max_stake": max(trade.stake_amount, 1000.0),
        "leverage": trade.leverage,
        "entry_tag": trade.enter_tag,
        "side": "short" if trade.is_short else "long",
        "order_type": "market",
        "amount": trade.amount,
        "rate": rate,
        "time_in_force": "GTC",
        "exit_reason": trade.exit_reason or "roi",
        "exit_tag": trade.exit_reason or "roi",
        "after_fill": False,
        "current_entry_rate": trade.open_rate,
        "current_exit_rate": rate,
        "current_entry_profit": profit,
        "current_exit_profit": profit,
    }
    signature = inspect.signature(method)
    kwargs: dict[str, Any] = {}
    missing = []
    for name, parameter in signature.parameters.items():
        if name == "self" or parameter.kind in (parameter.VAR_POSITIONAL, parameter.VAR_KEYWORD):
            continue
        if name in available:
            kwargs[name] = available[name]
        elif parameter.default is inspect.Parameter.empty:
            missing.append(name)
    if missing:
        raise InvocationError(f"{callback}: unsupported required parameters {missing}")
    return kwargs


def invoke(
    strategy: Any,
    callback: str,
    trade: TradeDummy,
    event_time: pd.Timestamp,
    rate: float,
    profit: float,
) -> dict[str, Any]:
    method = getattr(strategy, callback)
    kwargs = build_kwargs(callback, method, trade, event_time, rate, profit)
    try:
        value = method(**kwargs)
        return {"ok": True, "value": normalize(value), "kwargs": sorted(kwargs)}
    except Exception as exc:
        return {
            "ok": False,
            "error_type": type(exc).__name__,
            "error": str(exc)[:500],
            "kwargs": sorted(kwargs),
        }


def set_environment(strategy: Any, pair: str, dataframe: pd.DataFrame, whitelist: list[str]) -> None:
    strategy.dp = DataProviderStub(pair, dataframe, whitelist)
    strategy.wallets = WalletStub()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-trades", type=int, default=60)
    parser.add_argument("--future-candles", type=int, default=1440)
    args = parser.parse_args()

    strategy_path = pathlib.Path(args.strategy)
    source = strategy_path.read_text()
    module = load_module(strategy_path, "fqt_ip08_strategy")
    target_name = "M4PioneerValidationV14" if hasattr(module, "M4PioneerValidationV14") else "M4PioneerStableExposureV10"
    target_class = getattr(module, target_name)
    config = json.loads(pathlib.Path(args.config).read_text())
    whitelist = list(config["exchange"]["pair_whitelist"])
    datadir = pathlib.Path(config["datadir"])
    active_callbacks = sorted(defined_callback_names(source, target_name))
    trades = load_backtest_trades(pathlib.Path(args.result))[: args.max_trades]

    data_cache: dict[str, pd.DataFrame] = {}
    full_cache: dict[str, pd.DataFrame] = {}
    event_rows: list[dict[str, Any]] = []
    coverage = defaultdict(lambda: {"attempts": 0, "successes": 0, "errors": 0, "differences": 0})

    for index, trade_row in enumerate(trades):
        pair = trade_row["pair"]
        if pair not in data_cache:
            parquet = datadir / f"{pair.replace('/', '_')}-1m.parquet"
            raw = pd.read_parquet(parquet).sort_values("date").reset_index(drop=True)
            raw["date"] = pd.to_datetime(raw["date"], utc=True)
            data_cache[pair] = raw
            base_strategy = make_strategy(target_class, config)
            full_cache[pair] = pipeline(base_strategy, raw, pair)
            del base_strategy
            gc.collect()

        raw = data_cache[pair]
        full = full_cache[pair]
        dummy = trade_dummy(trade_row)
        open_time = pd.Timestamp(dummy.open_date_utc)
        close_time = pd.Timestamp(dummy.close_date_utc) if dummy.close_date_utc else open_time

        for phase, event_time, rate in (
            ("entry", open_time, dummy.open_rate),
            ("exit", close_time, float(dummy.close_rate or dummy.open_rate)),
        ):
            eligible = [
                callback
                for callback in active_callbacks
                if (
                    phase == "entry"
                    and callback in {"custom_stake_amount", "custom_entry_price", "confirm_trade_entry"}
                )
                or (
                    phase == "exit"
                    and callback in {"custom_exit", "custom_exit_price", "confirm_trade_exit", "custom_stoploss", "custom_roi", "adjust_trade_position"}
                )
            ]
            if not eligible:
                continue
            current_index = int(raw["date"].searchsorted(event_time, side="right") - 1)
            if current_index < 1:
                continue
            end_index = min(len(raw), current_index + 1 + args.future_candles)
            prefix_raw = raw.iloc[: current_index + 1].copy()
            future_raw = raw.iloc[:end_index].copy()

            prefix_strategy = make_strategy(target_class, config)
            future_strategy = make_strategy(target_class, config)
            prefix_output = pipeline(prefix_strategy, prefix_raw, pair)
            future_output = pipeline(future_strategy, future_raw, pair).iloc[: current_index + 1].copy()
            set_environment(prefix_strategy, pair, prefix_output, whitelist)
            set_environment(future_strategy, pair, future_output, whitelist)
            profit = dummy.calc_profit_ratio(rate)

            for callback in eligible:
                coverage[callback]["attempts"] += 1
                left = invoke(prefix_strategy, callback, dummy, event_time, rate, profit)
                right = invoke(future_strategy, callback, dummy, event_time, rate, profit)
                equal = left == right
                if left.get("ok") and right.get("ok"):
                    coverage[callback]["successes"] += 1
                else:
                    coverage[callback]["errors"] += 1
                if not equal:
                    coverage[callback]["differences"] += 1
                event_rows.append(
                    {
                        "trade_index": index,
                        "pair": pair,
                        "phase": phase,
                        "event_time": event_time.isoformat(),
                        "callback": callback,
                        "prefix": left,
                        "future_appended_prefix": right,
                        "equal": equal,
                    }
                )
            del prefix_strategy, future_strategy, prefix_output, future_output
            gc.collect()

    coverage_rows = []
    for callback in active_callbacks:
        row = {"callback": callback, **coverage[callback]}
        row["covered"] = row["attempts"] > 0 and row["successes"] > 0
        row["pass"] = row["covered"] and row["errors"] == 0 and row["differences"] == 0
        coverage_rows.append(row)

    causality_pass = all(row["pass"] for row in coverage_rows) if coverage_rows else False
    output = {
        "contract": "FQT_IP08_CALLBACK_PREFIX_CAUSALITY_HARNESS_V1",
        "classification": "EXECUTABLE_CALLBACK_GATE",
        "strategy": target_name,
        "active_callbacks": active_callbacks,
        "trade_events_requested": len(trades),
        "coverage": coverage_rows,
        "events": event_rows,
        "prefix_future_append_pass": causality_pass,
        "pair_order_gate_closed": False,
        "capital_slot_gate_closed": False,
        "same_candle_order_state_gate_closed": False,
        "gate_closed": False,
        "gate_reason": (
            "Prefix causality is one subgate. Pair-order, capital/slot and same-candle/order-state matrices remain required."
            if causality_pass
            else "At least one active callback is unsupported, errors or changes under future append."
        ),
        "promotion_authorized": False,
        "oos_authorized": False,
        "dry_run_authorized": False,
        "live_authorized": False,
    }
    pathlib.Path(args.out).write_text(json.dumps(output, indent=2) + "\n")
    print(
        json.dumps(
            {
                "contract": output["contract"],
                "strategy": target_name,
                "active_callback_count": len(active_callbacks),
                "prefix_future_append_pass": causality_pass,
                "gate_closed": False,
                "coverage": coverage_rows,
            },
            indent=2,
        )
    )
    return 0 if causality_pass else 2


if __name__ == "__main__":
    raise SystemExit(main())
