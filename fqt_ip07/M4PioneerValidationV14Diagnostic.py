"""Execution-neutral diagnostic classes for FQT V14 correctness gates.

These classes are NEVER deployment candidates.  They inherit every vectorized
indicator, entry and exit-signal method from the frozen V10/V14 champion.  Only
execution callbacks are neutralized so Freqtrade's generic lookahead harness can
produce enough completed trades to test causal signal generation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from M4PioneerStableExposureV10 import M4PioneerStableExposureV10, Trade


class M4PioneerValidationV14(M4PioneerStableExposureV10):
    """Frozen V14 evidence boundary; trading semantics equal to V10."""

    validation_status = "RESEARCH_ONLY_NOT_PROMOTED"
    parent_anchor = "M4PioneerStableExposureV10"
    alpha_change = False
    timestamp_replay = False
    fresh_oos_opened = False

    @staticmethod
    def version() -> str:
        return "14.0-validation-parity"


class M4PioneerValidationV14LookaheadStakeNeutral(M4PioneerValidationV14):
    """Diagnostic only: preserve signals, neutralize pair/tag stake allocation."""

    validation_status = "LOOKAHEAD_DIAGNOSTIC_ONLY_NOT_TRADABLE"
    alpha_change = False

    @staticmethod
    def version() -> str:
        return "14.0-lookahead-stake-neutral-diagnostic"

    def custom_stake_amount(
        self,
        pair: str,
        current_time: datetime,
        current_rate: float,
        proposed_stake: float,
        min_stake: float | None,
        max_stake: float,
        leverage: float,
        entry_tag: str | None,
        side: str,
        **kwargs: Any,
    ) -> float:
        stake = float(proposed_stake)
        if min_stake is not None:
            stake = max(stake, float(min_stake))
        return float(min(stake, float(max_stake)))


class M4PioneerValidationV14LookaheadExecutionNeutral(
    M4PioneerValidationV14LookaheadStakeNeutral
):
    """Diagnostic only: additionally disable profit-sensitive custom exits.

    ROI, stoploss and vectorized exit signals stay active.  The inherited
    populate_* methods are unchanged and are hash-checked against V14.
    """

    @staticmethod
    def version() -> str:
        return "14.0-lookahead-execution-neutral-diagnostic"

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> str | bool | None:
        return None
