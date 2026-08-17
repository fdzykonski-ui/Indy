"""Causal, pair-agnostic baselines for the FQT research contract."""

from __future__ import annotations

import numpy as np
from pandas import DataFrame

from freqtrade.strategy import IStrategy


class _SpotLongBaseline(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1m"
    can_short = False
    position_adjustment_enable = False
    startup_candle_count = 201
    process_only_new_candles = True
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    minimal_roi = {"0": 0.02}
    stoploss = -0.03

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["ema_20"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        dataframe["ema_50"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        dataframe["sma_20"] = dataframe["close"].rolling(20, min_periods=20).mean()
        dataframe["sma_100"] = dataframe["close"].rolling(100, min_periods=100).mean()
        dataframe["high_60_prior"] = dataframe["high"].rolling(60, min_periods=60).max().shift(1)
        dataframe["low_30_prior"] = dataframe["low"].rolling(30, min_periods=30).min().shift(1)
        dataframe["volume_20_prior"] = (
            dataframe["volume"].rolling(20, min_periods=20).median().shift(1)
        )
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None
        return dataframe


class CashBaseline(_SpotLongBaseline):
    """No-market-exposure control."""


class BuyHoldBaseline(_SpotLongBaseline):
    """Enter at the first tradable candle and retain exposure until force-exit."""

    startup_candle_count = 1
    minimal_roi = {"0": 100.0}
    stoploss = -0.99
    use_exit_signal = False

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        dataframe.loc[dataframe["volume"] >= 0, ["enter_long", "enter_tag"]] = (
            1,
            "buy_hold",
        )
        return dataframe


class EMACrossoverBaseline(_SpotLongBaseline):
    minimal_roi = {"0": 100.0}
    stoploss = -0.05

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        cross_up = (dataframe["ema_20"] > dataframe["ema_50"]) & (
            dataframe["ema_20"].shift(1) <= dataframe["ema_50"].shift(1)
        )
        dataframe.loc[cross_up & (dataframe["volume"] > 0), ["enter_long", "enter_tag"]] = (
            1,
            "ema_cross",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None
        cross_down = (dataframe["ema_20"] < dataframe["ema_50"]) & (
            dataframe["ema_20"].shift(1) >= dataframe["ema_50"].shift(1)
        )
        dataframe.loc[cross_down, ["exit_long", "exit_tag"]] = (1, "ema_uncross")
        return dataframe


class SMACrossoverBaseline(_SpotLongBaseline):
    minimal_roi = {"0": 100.0}
    stoploss = -0.05

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        cross_up = (dataframe["sma_20"] > dataframe["sma_100"]) & (
            dataframe["sma_20"].shift(1) <= dataframe["sma_100"].shift(1)
        )
        dataframe.loc[cross_up & (dataframe["volume"] > 0), ["enter_long", "enter_tag"]] = (
            1,
            "sma_cross",
        )
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None
        cross_down = (dataframe["sma_20"] < dataframe["sma_100"]) & (
            dataframe["sma_20"].shift(1) >= dataframe["sma_100"].shift(1)
        )
        dataframe.loc[cross_down, ["exit_long", "exit_tag"]] = (1, "sma_uncross")
        return dataframe


class BreakoutBaseline(_SpotLongBaseline):
    minimal_roi = {"0": 100.0}
    stoploss = -0.03

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        condition = (
            (dataframe["close"] > dataframe["high_60_prior"])
            & (dataframe["volume"] > dataframe["volume_20_prior"])
            & (dataframe["volume"] > 0)
        )
        dataframe.loc[condition, ["enter_long", "enter_tag"]] = (1, "breakout_60")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None
        dataframe.loc[
            dataframe["close"] < dataframe["low_30_prior"], ["exit_long", "exit_tag"]
        ] = (1, "breakdown_30")
        return dataframe


class ROIOnlyBaseline(EMACrossoverBaseline):
    minimal_roi = {"0": 0.01, "60": 0.005, "240": 0.002}
    stoploss = -0.99
    use_exit_signal = False


class StoplossOnlyBaseline(EMACrossoverBaseline):
    minimal_roi = {"0": 100.0}
    stoploss = -0.02
    use_exit_signal = False


class RandomSignalControl(_SpotLongBaseline):
    """Deterministic, price-independent negative control; never deploy."""

    startup_candle_count = 1
    minimal_roi = {"0": 100.0}
    stoploss = -0.03

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        random_values = np.random.default_rng(17).random(len(dataframe))
        dataframe.loc[
            (random_values < 0.004) & (dataframe["volume"] >= 0),
            ["enter_long", "enter_tag"],
        ] = (1, "random_seed_17")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None
        random_values = np.random.default_rng(43).random(len(dataframe))
        dataframe.loc[random_values < 0.008, ["exit_long", "exit_tag"]] = (
            1,
            "random_seed_43",
        )
        return dataframe
