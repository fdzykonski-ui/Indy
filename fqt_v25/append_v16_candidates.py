#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

TARGET = Path("user_data/strategies/M4PioneerStableExposureV10.py")
MARKER = "# ===== FQT V2.5 OOS50 CANDIDATES ====="
text = TARGET.read_text(encoding="utf-8")
if MARKER in text:
    raise SystemExit("V2.5 candidate classes already appended; refusing duplicate append.")

appendix = r'''

# ===== FQT V2.5 OOS50 CANDIDATES =====
import numpy as _fqt_v16_np
import pandas as _fqt_v16_pd


class _M4PioneerOOS50V16Features:
    """Pair-agnostic, causal features used only by the preregistered V16 experiments."""

    def populate_indicators(self, dataframe, metadata):
        dataframe = super().populate_indicators(dataframe, metadata)
        close = dataframe["close"].astype(float)
        high = dataframe["high"].astype(float)
        low = dataframe["low"].astype(float)
        volume = dataframe["volume"].astype(float)
        previous_close = close.shift(1)
        true_range = _fqt_v16_pd.concat(
            [
                high - low,
                (high - previous_close).abs(),
                (low - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        dataframe["fqt_v16_ema20"] = close.ewm(span=20, adjust=False, min_periods=20).mean()
        dataframe["fqt_v16_ema50"] = close.ewm(span=50, adjust=False, min_periods=50).mean()
        dataframe["fqt_v16_ema20_slope"] = dataframe["fqt_v16_ema20"].diff(5) / close.replace(0, _fqt_v16_np.nan)
        dataframe["fqt_v16_ret15"] = close.pct_change(15, fill_method=None)
        dataframe["fqt_v16_atr_pct"] = true_range.rolling(14, min_periods=14).mean() / close.replace(0, _fqt_v16_np.nan)
        volume_median = volume.rolling(30, min_periods=30).median().replace(0, _fqt_v16_np.nan)
        dataframe["fqt_v16_volume_ratio"] = volume / volume_median
        dataframe["fqt_v16_range12"] = (
            high.rolling(12, min_periods=12).max()
            / low.rolling(12, min_periods=12).min().replace(0, _fqt_v16_np.nan)
            - 1.0
        )
        return dataframe

    @staticmethod
    def _fqt_v16_tag_mask(dataframe, token: str):
        tags = dataframe.get("enter_tag", _fqt_v16_pd.Series("", index=dataframe.index))
        return tags.fillna("").astype(str).str.contains(token, case=False, regex=False)


class M4PioneerOOS50V16VwapPrune(_M4PioneerOOS50V16Features, M4PioneerValidationV14):
    """Single hypothesis: remove the historically negative VWAP-reclaim path."""

    @staticmethod
    def version() -> str:
        return "16.0-vwap-prune-research"

    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        weak_path = self._fqt_v16_tag_mask(dataframe, "vwap_reclaim")
        dataframe.loc[weak_path, "enter_long"] = 0
        return dataframe


class M4PioneerOOS50V16VwapQuality(_M4PioneerOOS50V16Features, M4PioneerValidationV14):
    """Single hypothesis: retain VWAP reclaims only under causal trend/liquidity quality."""

    @staticmethod
    def version() -> str:
        return "16.0-vwap-quality-research"

    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        vwap_path = self._fqt_v16_tag_mask(dataframe, "vwap_reclaim")
        quality = (
            (dataframe["close"] >= dataframe["fqt_v16_ema20"])
            & (dataframe["fqt_v16_ema20"] > dataframe["fqt_v16_ema50"])
            & (dataframe["fqt_v16_ema20_slope"] > 0.0)
            & (dataframe["fqt_v16_ret15"] > -0.0025)
            & (dataframe["fqt_v16_volume_ratio"] >= 0.50)
            & dataframe["fqt_v16_atr_pct"].between(0.00045, 0.025, inclusive="both")
        ).fillna(False)
        dataframe.loc[vwap_path & ~quality, "enter_long"] = 0
        return dataframe


class M4PioneerOOS50V16TrendQuality(_M4PioneerOOS50V16Features, M4PioneerValidationV14):
    """Single hypothesis: gate only pullback/reclaim paths during deteriorating local trend quality."""

    @staticmethod
    def version() -> str:
        return "16.0-trend-quality-research"

    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        trend_path = self._fqt_v16_tag_mask(dataframe, "trend_pullback") | self._fqt_v16_tag_mask(dataframe, "vwap_reclaim")
        quality = (
            (dataframe["fqt_v16_ema20_slope"] > -0.00035)
            & (dataframe["fqt_v16_ret15"] > -0.0060)
            & (dataframe["fqt_v16_volume_ratio"] >= 0.25)
            & dataframe["fqt_v16_atr_pct"].between(0.00035, 0.030, inclusive="both")
            & (dataframe["fqt_v16_range12"] <= 0.055)
        ).fillna(False)
        dataframe.loc[trend_path & ~quality, "enter_long"] = 0
        return dataframe


class _M4PioneerOOS50Delay1:
    """Adverse one-completed-candle entry-delay control; not a candidate."""

    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe["enter_long"] = dataframe["enter_long"].shift(1).fillna(0).astype(int)
        if "enter_tag" in dataframe.columns:
            dataframe["enter_tag"] = dataframe["enter_tag"].shift(1).fillna("")
        return dataframe


class M4PioneerValidationV14Delay1(_M4PioneerOOS50Delay1, M4PioneerValidationV14):
    @staticmethod
    def version() -> str:
        return "14.0-delay1-control"


class M4PioneerOOS50V16VwapPruneDelay1(_M4PioneerOOS50Delay1, M4PioneerOOS50V16VwapPrune):
    @staticmethod
    def version() -> str:
        return "16.0-vwap-prune-delay1"


class M4PioneerOOS50V16VwapQualityDelay1(_M4PioneerOOS50Delay1, M4PioneerOOS50V16VwapQuality):
    @staticmethod
    def version() -> str:
        return "16.0-vwap-quality-delay1"


class M4PioneerOOS50V16TrendQualityDelay1(_M4PioneerOOS50Delay1, M4PioneerOOS50V16TrendQuality):
    @staticmethod
    def version() -> str:
        return "16.0-trend-quality-delay1"

# ===== END FQT V2.5 OOS50 CANDIDATES =====
'''

TARGET.write_text(text + appendix, encoding="utf-8")
print(f"Appended preregistered V2.5 research candidates to {TARGET}")
