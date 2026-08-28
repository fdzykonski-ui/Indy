#!/usr/bin/env python3
"""Append the frozen M6R36/V11 causal exposure allocator to the rebuilt V10 strategy.

The patch changes only custom stake allocation. Entry signals, exit signals,
ROI, stoploss, protections, pair order and timestamps are inherited unchanged.
Selection used Jan-Feb training plus March validation; April and the one-shot
post-2026-06-22 OOS are not used to alter constants.
"""
from pathlib import Path

PATH = Path("user_data/strategies/M4PioneerStableExposureV10.py")
MARKER = "# ===== BEGIN M6R36 V11 NATIVE OOS ALLOCATOR ====="
text = PATH.read_text()
if MARKER in text:
    raise SystemExit("M6R36 allocator already appended")

APPEND = r'''

# ===== BEGIN M6R36 V11 NATIVE OOS ALLOCATOR =====
class M4PioneerRiskAllocatorV11Balanced75(M4PioneerStableExposureV10):
    """Causal three-tier exposure allocator; research/backtest only.

    Entries, exits, ROI, stoploss and protections are inherited unchanged.
    Existing V10 BTC and full-stake pair/tag contexts remain full stake.
    Tier-A contexts were positive in Jan-Feb training and March validation and
    receive 75% of the proposed stake. The residual alt pool was negative in
    both windows and is reduced to a minimum-like 0.75% factor. April and the
    independent OOS are excluded from parameter selection. No timestamp replay,
    winner whitelist, future row or OOS feedback is used.
    """

    VERSION_TAG = "M4_PIONEER_RISK_ALLOCATOR_V11_BALANCED75_NATIVE_OOS"
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
        return "M4PioneerRiskAllocatorV11Balanced75-native-one-shot-oos-research"


class M4PioneerRiskAllocatorV11Balanced75Delay1(M4PioneerRiskAllocatorV11Balanced75):
    def version(self) -> str:
        return "M4PioneerRiskAllocatorV11Balanced75-delay1"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(1).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(1).fillna("").astype(str)
        return df


class M4PioneerRiskAllocatorV11Balanced75Delay2(M4PioneerRiskAllocatorV11Balanced75):
    def version(self) -> str:
        return "M4PioneerRiskAllocatorV11Balanced75-delay2"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(2).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(2).fillna("").astype(str)
        return df
# ===== END M6R36 V11 NATIVE OOS ALLOCATOR =====
'''
PATH.write_text(text + APPEND)
print(f"appended M6R36 allocator to {PATH}")
