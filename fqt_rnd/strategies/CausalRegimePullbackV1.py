"""Pre-registered, causal and pair-agnostic first Challenger."""

from __future__ import annotations

from pandas import DataFrame, concat

from freqtrade.strategy import IStrategy


class CausalRegimePullbackV1(IStrategy):
    INTERFACE_VERSION = 3
    timeframe = "1m"
    can_short = False
    position_adjustment_enable = False
    startup_candle_count = 500
    process_only_new_candles = True
    minimal_roi = {"0": 0.008, "60": 0.005, "240": 0.002}
    stoploss = -0.018
    trailing_stop = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False

    @staticmethod
    def _rsi(close, period: int = 14):
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
        relative_strength = gain / loss.replace(0, float("nan"))
        return 100 - (100 / (1 + relative_strength))

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["ema_20"] = dataframe["close"].ewm(span=20, adjust=False).mean()
        dataframe["ema_50"] = dataframe["close"].ewm(span=50, adjust=False).mean()
        dataframe["ema_200"] = dataframe["close"].ewm(span=200, adjust=False).mean()
        dataframe["rsi_14"] = self._rsi(dataframe["close"], 14)
        previous_close = dataframe["close"].shift(1)
        true_range = concat(
            [
                dataframe["high"] - dataframe["low"],
                (dataframe["high"] - previous_close).abs(),
                (dataframe["low"] - previous_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        dataframe["atr_14"] = true_range.ewm(alpha=1 / 14, adjust=False).mean()
        dataframe["atr_ratio"] = dataframe["atr_14"] / dataframe["close"]
        dataframe["volume_median_60_prior"] = (
            dataframe["volume"].rolling(60, min_periods=60).median().shift(1)
        )
        return dataframe

    @staticmethod
    def _entry_condition(dataframe: DataFrame):
        return (
            (dataframe["ema_20"] > dataframe["ema_50"])
            & (dataframe["ema_50"] > dataframe["ema_200"])
            & (dataframe["close"] < dataframe["ema_20"])
            & (dataframe["close"] > dataframe["ema_50"])
            & dataframe["rsi_14"].between(35, 50, inclusive="both")
            & dataframe["atr_ratio"].between(0.0004, 0.008, inclusive="both")
            & (dataframe["volume"] >= dataframe["volume_median_60_prior"])
            & (dataframe["volume"] > 0)
        )

    @staticmethod
    def _exit_condition(dataframe: DataFrame):
        return (
            (dataframe["close"] > dataframe["ema_20"])
            | (dataframe["rsi_14"] > 65)
            | (dataframe["close"] < dataframe["ema_50"])
        )

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        dataframe.loc[
            self._entry_condition(dataframe), ["enter_long", "enter_tag"]
        ] = (1, "causal_trend_pullback_v1")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None
        dataframe.loc[self._exit_condition(dataframe), ["exit_long", "exit_tag"]] = (
            1,
            "causal_recovery_or_break",
        )
        return dataframe


class ReversedSignalControlV1(CausalRegimePullbackV1):
    """Negative control: exchange the Challenger's entry and exit predicates."""

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = None
        dataframe.loc[
            self._exit_condition(dataframe) & (dataframe["volume"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "reversed_control")
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        del metadata
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = None
        dataframe.loc[
            self._entry_condition(dataframe), ["exit_long", "exit_tag"]
        ] = (1, "reversed_control_exit")
        return dataframe


class Delay1CausalRegimePullbackV1(CausalRegimePullbackV1):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe["enter_long"] = dataframe["enter_long"].shift(1).fillna(0).astype(int)
        dataframe["enter_tag"] = dataframe["enter_tag"].shift(1)
        return dataframe


class Delay2CausalRegimePullbackV1(CausalRegimePullbackV1):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe["enter_long"] = dataframe["enter_long"].shift(2).fillna(0).astype(int)
        dataframe["enter_tag"] = dataframe["enter_tag"].shift(2)
        return dataframe


class NoVolumeAblationV1(CausalRegimePullbackV1):
    @staticmethod
    def _entry_condition(dataframe: DataFrame):
        return (
            (dataframe["ema_20"] > dataframe["ema_50"])
            & (dataframe["ema_50"] > dataframe["ema_200"])
            & (dataframe["close"] < dataframe["ema_20"])
            & (dataframe["close"] > dataframe["ema_50"])
            & dataframe["rsi_14"].between(35, 50, inclusive="both")
            & dataframe["atr_ratio"].between(0.0004, 0.008, inclusive="both")
            & (dataframe["volume"] > 0)
        )


class ROIOnlyExitAblationV1(CausalRegimePullbackV1):
    use_exit_signal = False


class CausalRegimePullbackV2(CausalRegimePullbackV1):
    """H002: require enough gross profit to cover the modeled roundtrip fee."""

    minimal_roi = {"0": 0.006, "60": 0.0045, "240": 0.003, "720": 0.0025}
    stoploss = -0.012
    exit_profit_only = True
    exit_profit_offset = 0.0025


class Delay1CausalRegimePullbackV2(CausalRegimePullbackV2):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe["enter_long"] = dataframe["enter_long"].shift(1).fillna(0).astype(int)
        dataframe["enter_tag"] = dataframe["enter_tag"].shift(1)
        return dataframe


class Delay2CausalRegimePullbackV2(CausalRegimePullbackV2):
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe["enter_long"] = dataframe["enter_long"].shift(2).fillna(0).astype(int)
        dataframe["enter_tag"] = dataframe["enter_tag"].shift(2)
        return dataframe
