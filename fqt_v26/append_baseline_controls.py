#!/usr/bin/env python3
from pathlib import Path

path = Path('user_data/strategies/M4PioneerV26Factory.py')
text = path.read_text(encoding='utf-8')
marker = '# ===== FQT V26 BASELINE CONTROLS ====='
if marker in text:
    raise SystemExit(0)
text += r'''

# ===== FQT V26 BASELINE CONTROLS =====
from freqtrade.strategy import IStrategy as _FQTV26IStrategy


class FQTV26EMABaseline(_FQTV26IStrategy):
    timeframe = '1m'
    can_short = False
    startup_candle_count = 60
    minimal_roi = {'120': 0.0}
    stoploss = -0.05
    process_only_new_candles = True

    def populate_indicators(self, dataframe, metadata):
        dataframe['ctrl_ema12'] = dataframe['close'].ewm(span=12, adjust=False, min_periods=12).mean()
        dataframe['ctrl_ema48'] = dataframe['close'].ewm(span=48, adjust=False, min_periods=48).mean()
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        cross = (dataframe['ctrl_ema12'] > dataframe['ctrl_ema48']) & (dataframe['ctrl_ema12'].shift(1) <= dataframe['ctrl_ema48'].shift(1))
        dataframe.loc[cross & (dataframe['volume'] > 0), ['enter_long', 'enter_tag']] = (1, 'ema_cross_control')
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        cross = (dataframe['ctrl_ema12'] < dataframe['ctrl_ema48']) & (dataframe['ctrl_ema12'].shift(1) >= dataframe['ctrl_ema48'].shift(1))
        dataframe.loc[cross, ['exit_long', 'exit_tag']] = (1, 'ema_reverse_control')
        return dataframe


class FQTV26ReverseEMANegativeControl(FQTV26EMABaseline):
    def populate_entry_trend(self, dataframe, metadata):
        cross = (dataframe['ctrl_ema12'] < dataframe['ctrl_ema48']) & (dataframe['ctrl_ema12'].shift(1) >= dataframe['ctrl_ema48'].shift(1))
        dataframe.loc[cross & (dataframe['volume'] > 0), ['enter_long', 'enter_tag']] = (1, 'reverse_ema_negative_control')
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        cross = (dataframe['ctrl_ema12'] > dataframe['ctrl_ema48']) & (dataframe['ctrl_ema12'].shift(1) <= dataframe['ctrl_ema48'].shift(1))
        dataframe.loc[cross, ['exit_long', 'exit_tag']] = (1, 'reverse_ema_exit_control')
        return dataframe


class FQTV26PeriodicNegativeControl(_FQTV26IStrategy):
    timeframe = '1m'
    can_short = False
    startup_candle_count = 60
    minimal_roi = {'60': 0.0}
    stoploss = -0.05
    process_only_new_candles = True

    def populate_indicators(self, dataframe, metadata):
        dataframe['ctrl_index'] = _fqt_v26_np.arange(len(dataframe), dtype='int64')
        return dataframe

    def populate_entry_trend(self, dataframe, metadata):
        condition = (dataframe['ctrl_index'] % 180 == 0) & (dataframe['volume'] > 0)
        dataframe.loc[condition, ['enter_long', 'enter_tag']] = (1, 'periodic_negative_control')
        return dataframe

    def populate_exit_trend(self, dataframe, metadata):
        return dataframe
# ===== END FQT V26 BASELINE CONTROLS =====
'''
path.write_text(text, encoding='utf-8')
