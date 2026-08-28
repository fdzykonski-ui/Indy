#!/usr/bin/env python3
from __future__ import annotations

import pathlib

TARGET = pathlib.Path("user_data/strategies/M4PioneerStableExposureV10.py")
MARKER = "# ===== BEGIN M6R36 NATIVE V11 VALIDATION CLASSES ====="

APPEND = r'''

# ===== BEGIN M6R36 NATIVE V11 VALIDATION CLASSES =====
class M4PioneerRiskAllocatorV11Balanced75(M4PioneerStableExposureV10):
    """Causal three-tier exposure allocator; research/backtest only.

    Alpha, exits, ROI, stoploss and protections remain inherited unchanged.
    Allocation constants were fixed from Jan-Feb training plus March validation.
    April was not used to choose the constants. No timestamps, winner lists,
    future rows or OOS feedback are used.
    """

    VERSION_TAG = "M4_PIONEER_RISK_ALLOCATOR_V11_BALANCED75_RESEARCH"
    DEFAULT_ALT_STAKE_FACTOR = 0.0075
    TIER_A_STAKE_FACTOR = 0.75
    TIER_B_STAKE_FACTOR = 0.025

    TIER_A_TAG_KEYS = frozenset({
        "trend_pullback|clean_uptrend|trend_pullback|75",
        "trend_pullback|compression|trend_pullback|69",
        "trend_pullback|momentum_burst|trend_pullback|70",
        "trend_pullback|recovery_reclaim|trend_pullback|69",
        "trend_pullback|recovery_reclaim|trend_pullback|71",
    })

    TIER_A_PAIR_REGIME_KEYS = frozenset({
        "2Z/USDC|clean_uptrend",
        "ASTER/USDC|clean_uptrend",
        "PENDLE/USDC|clean_uptrend",
    })

    TIER_B_PAIR_REGIME_KEYS = frozenset({
        "2Z/USDC|clean_uptrend",
        "AAVE/USDC|momentum_burst",
        "ALGO/USDC|momentum_burst",
        "ASTER/USDC|clean_uptrend",
        "ATOM/USDC|clean_uptrend",
        "AVAX/USDC|clean_uptrend",
        "BCH/USDC|recovery_reclaim",
        "BNB/USDC|clean_uptrend",
        "ENA/USDC|clean_uptrend",
        "PENDLE/USDC|clean_uptrend",
        "SEI/USDC|compression",
        "SHIB/USDC|clean_uptrend",
        "SOL/USDC|clean_uptrend",
        "TRX/USDC|clean_uptrend",
        "UNI/USDC|compression",
        "ZK/USDC|recovery_reclaim",
    })

    @staticmethod
    def _regime_key(pair: str, entry_tag: str | None) -> str:
        parts = [x for x in str(entry_tag or "").split("|") if x]
        regime = next((x[len("regime_"):] for x in parts if x.startswith("regime_")), "")
        return f"{pair}|{regime}"

    @classmethod
    def _portfolio_factor(cls, pair: str, entry_tag: str | None) -> float:
        pair_norm = str(pair).upper()
        if pair_norm == "BTC/USDC":
            return cls.BTC_STAKE_FACTOR
        exact_key = f"{pair}|{cls._tag_key(entry_tag)}"
        if exact_key in cls.FULL_STAKE_PAIR_TAG_KEYS:
            return cls.VALIDATION_SELECTED_FACTOR
        tag_key = cls._tag_key(entry_tag)
        pair_regime = cls._regime_key(pair, entry_tag)
        if tag_key in cls.TIER_A_TAG_KEYS or pair_regime in cls.TIER_A_PAIR_REGIME_KEYS:
            return cls.TIER_A_STAKE_FACTOR
        if pair_regime in cls.TIER_B_PAIR_REGIME_KEYS:
            return cls.TIER_B_STAKE_FACTOR
        return cls.DEFAULT_ALT_STAKE_FACTOR

    def version(self) -> str:
        return "M4PioneerRiskAllocatorV11Balanced75-native-validation-research-only"


class M4PioneerRiskAllocatorV11Tier50(M4PioneerRiskAllocatorV11Balanced75):
    TIER_A_STAKE_FACTOR = 0.50
    def version(self) -> str:
        return "M4PioneerRiskAllocatorV11Tier50-native-validation-research-only"


class M4PioneerRiskAllocatorV11Tier100(M4PioneerRiskAllocatorV11Balanced75):
    TIER_A_STAKE_FACTOR = 1.00
    def version(self) -> str:
        return "M4PioneerRiskAllocatorV11Tier100-native-validation-research-only"


class M4PioneerRiskAllocatorV11Balanced75_DELAY1(M4PioneerRiskAllocatorV11Balanced75):
    def version(self) -> str:
        return "M4PioneerRiskAllocatorV11Balanced75-delay1-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(1).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(1).fillna("").astype(str)
        return df


class M4PioneerRiskAllocatorV11Balanced75_DELAY2(M4PioneerRiskAllocatorV11Balanced75):
    def version(self) -> str:
        return "M4PioneerRiskAllocatorV11Balanced75-delay2-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(2).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(2).fillna("").astype(str)
        return df
# ===== END M6R36 NATIVE V11 VALIDATION CLASSES =====
'''


def main() -> int:
    if not TARGET.is_file():
        raise SystemExit(f"missing target strategy: {TARGET}")
    text = TARGET.read_text()
    if MARKER in text:
        print("M6R36 V11 classes already present")
        return 0
    TARGET.write_text(text.rstrip() + "\n" + APPEND.lstrip())
    print(f"appended M6R36 classes to {TARGET}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
