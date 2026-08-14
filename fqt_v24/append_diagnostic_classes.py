#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

path = Path("user_data/strategies/M4PioneerStableExposureV10.py")
text = path.read_text(encoding="utf-8")
marker = "# ===== FQT V2.4 ITERATION-3 DIAGNOSTIC CLASSES ====="
if marker in text:
    raise SystemExit("Diagnostic classes already appended; refusing duplicate append.")

appendix = r'''

# ===== FQT V2.4 ITERATION-3 DIAGNOSTIC CLASSES =====
import atexit as _fqt_atexit
import collections as _fqt_collections
import json as _fqt_json
import os as _fqt_os
import threading as _fqt_threading


class M4PioneerValidationV14(M4PioneerStableExposureV10):
    """Evidence boundary over V10; trading semantics intentionally unchanged."""
    validation_status = "RESEARCH_ONLY_NOT_PROMOTED"
    parent_anchor = "M4PioneerStableExposureV10"
    alpha_change = False
    timestamp_replay = False
    fresh_oos_opened = False

    @staticmethod
    def version() -> str:
        return "14.0-validation-parity"


_FQT_LEDGER_LOCK = _fqt_threading.Lock()
_FQT_LEDGER_COUNTS = _fqt_collections.Counter()
_FQT_LEDGER_BY_PAIR = _fqt_collections.defaultdict(_fqt_collections.Counter)
_FQT_LEDGER_BY_REASON = _fqt_collections.defaultdict(_fqt_collections.Counter)
_FQT_LEDGER_SAMPLES = _fqt_collections.defaultdict(list)
_FQT_LEDGER_LIMIT = int(_fqt_os.environ.get("FQT_CALLBACK_LEDGER_SAMPLE_LIMIT", "200"))


def _fqt_s(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _fqt_record(callback: str, pair: str, **fields):
    with _FQT_LEDGER_LOCK:
        _FQT_LEDGER_COUNTS[callback] += 1
        _FQT_LEDGER_BY_PAIR[pair][callback] += 1
        reason = str(fields.get("decision") or fields.get("exit_reason") or fields.get("result") or "none")
        _FQT_LEDGER_BY_REASON[callback][reason] += 1
        if len(_FQT_LEDGER_SAMPLES[callback]) < _FQT_LEDGER_LIMIT:
            _FQT_LEDGER_SAMPLES[callback].append({"pair": pair, **{k: _fqt_s(v) for k, v in fields.items()}})


def _fqt_dump_callback_ledger():
    target = _fqt_os.environ.get("FQT_CALLBACK_LEDGER_PATH")
    if not target:
        return
    payload = {
        "contract": "FQT_V24_CALLBACK_EVENT_LEDGER_V1",
        "counts": dict(_FQT_LEDGER_COUNTS),
        "by_pair": {k: dict(v) for k, v in sorted(_FQT_LEDGER_BY_PAIR.items())},
        "by_reason": {k: dict(v) for k, v in sorted(_FQT_LEDGER_BY_REASON.items())},
        "sample_limit_per_callback": _FQT_LEDGER_LIMIT,
        "samples": dict(_FQT_LEDGER_SAMPLES),
    }
    from pathlib import Path as _Path
    p = _Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_fqt_json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


_fqt_atexit.register(_fqt_dump_callback_ledger)


class M4PioneerValidationV14CallbackLedger(M4PioneerValidationV14):
    """Non-invasive callback instrumentation; decisions are delegated unchanged."""

    @staticmethod
    def version() -> str:
        return "14.0-callback-ledger-diagnostic"

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs):
        result = super().custom_stake_amount(
            pair, current_time, current_rate, proposed_stake, min_stake,
            max_stake, leverage, entry_tag, side, **kwargs
        )
        cfg = getattr(self, "config", {}) or {}
        _fqt_record(
            "custom_stake_amount", pair,
            current_time=current_time,
            proposed_stake=proposed_stake,
            min_stake=min_stake,
            max_stake=max_stake,
            result=result,
            entry_tag=entry_tag,
            config_max_open_trades=cfg.get("max_open_trades"),
            config_wallet=cfg.get("dry_run_wallet"),
            config_stake=cfg.get("stake_amount"),
        )
        return result

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        result = super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        _fqt_record(
            "custom_exit", pair,
            current_time=current_time,
            trade_open_date=getattr(trade, "open_date_utc", getattr(trade, "open_date", None)),
            current_profit=current_profit,
            result=result if result is not None else "none",
            enter_tag=getattr(trade, "enter_tag", None),
        )
        return result

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        result = super().custom_stoploss(pair, trade, current_time, current_rate, current_profit, **kwargs)
        _fqt_record(
            "custom_stoploss", pair,
            current_time=current_time,
            current_profit=current_profit,
            result=result,
            enter_tag=getattr(trade, "enter_tag", None),
        )
        return result

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        result = super().confirm_trade_exit(
            pair, trade, order_type, amount, rate, time_in_force, exit_reason, current_time, **kwargs
        )
        _fqt_record(
            "confirm_trade_exit", pair,
            current_time=current_time,
            exit_reason=exit_reason,
            result=result,
            enter_tag=getattr(trade, "enter_tag", None),
        )
        return result


class M4PioneerValidationV14SignalHarness(M4PioneerValidationV14):
    """Signal-only diagnostic. Not a trading candidate or production verdict."""
    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    @staticmethod
    def version() -> str:
        return "14.0-signal-harness-diagnostic"

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs):
        stake = float(proposed_stake)
        if min_stake is not None:
            stake = max(stake, float(min_stake))
        return float(min(stake, float(max_stake)))

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        return None

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        return True

# ===== END FQT V2.4 ITERATION-3 DIAGNOSTIC CLASSES =====
'''
path.write_text(text + appendix, encoding="utf-8")
print(f"Appended diagnostic classes to {path}")
