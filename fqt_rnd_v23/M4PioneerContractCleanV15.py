"""FQT R&D V2.3 pair-agnostic portfolio/capital challenger.

Execution-only overlay for the frozen project runtime. The distributable standalone
strategy is assembled separately from the same base source plus this class body.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from pandas import DataFrame

from M4PioneerStableExposureV10 import (
    M4OOSFeeRiskActionV2,
    M4PioneerStableExposureV10,
)


class M4PioneerValidationV14(M4PioneerStableExposureV10):
    """Alpha-equivalent version boundary for the previous champion."""

    validation_status = "RESEARCH_ONLY_NOT_PROMOTED"
    parent_anchor = "M4PioneerStableExposureV10"
    alpha_change = False
    timestamp_replay = False
    fresh_oos_opened = False

    @staticmethod
    def version() -> str:
        return "14.0-validation-parity"


class M4PioneerContractCleanV15(M4PioneerValidationV14):
    """Remove outcome-selected pair/tag exposure from the effective stake path.

    Entry, exit, indicators, ROI, stoploss and risk-cap signal logic remain unchanged.
    The only active development surface is Portfolio/Capital. Stake sizing delegates
    directly to the causal tag-driven M4OOSFeeRiskActionV2 implementation, bypassing
    V4/V7/V10 pair/tag winner overlays. No pair identity, date, timestamp, future
    value or evaluation outcome participates in the effective stake decision.
    """

    INTERFACE_VERSION = 3
    VERSION_TAG = "M4_PIONEER_CONTRACT_CLEAN_V15"
    validation_status = "RESEARCH_CHALLENGER_NOT_PROMOTED"
    parent_anchor = "M4PioneerValidationV14"
    alpha_change = False
    development_surface = "Portfolio/Capital"
    result_pairguard_removed = True
    timestamp_replay = False
    fresh_oos_opened = False

    @classmethod
    def _portfolio_factor(cls, pair: str, entry_tag: str | None) -> float:
        return 1.0

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
        return M4OOSFeeRiskActionV2.custom_stake_amount(
            self,
            pair,
            current_time,
            current_rate,
            proposed_stake,
            min_stake,
            max_stake,
            leverage,
            entry_tag,
            side,
            **kwargs,
        )

    @staticmethod
    def version() -> str:
        return "15.0-contract-clean-pair-agnostic-capital"


class M4PioneerContractCleanV15_DELAY1(M4PioneerContractCleanV15):
    """Execution-persistence control; not a second challenger."""

    validation_status = "DELAY_DIAGNOSTIC_ONLY"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = (
            pd.to_numeric(df.get("enter_long", 0), errors="coerce")
            .fillna(0)
            .shift(1)
            .fillna(0)
            .astype(int)
        )
        df["enter_tag"] = (
            df.get("enter_tag", "").fillna("").astype(str).shift(1).fillna("")
        )
        return df

    @staticmethod
    def version() -> str:
        return "15.0-contract-clean-delay1-control"


class M4PioneerContractCleanV15_DELAY2(M4PioneerContractCleanV15):
    """Execution-persistence control; not a second challenger."""

    validation_status = "DELAY_DIAGNOSTIC_ONLY"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = (
            pd.to_numeric(df.get("enter_long", 0), errors="coerce")
            .fillna(0)
            .shift(2)
            .fillna(0)
            .astype(int)
        )
        df["enter_tag"] = (
            df.get("enter_tag", "").fillna("").astype(str).shift(2).fillna("")
        )
        return df

    @staticmethod
    def version() -> str:
        return "15.0-contract-clean-delay2-control"
