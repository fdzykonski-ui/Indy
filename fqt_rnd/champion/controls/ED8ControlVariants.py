"""Controlled test subclasses; the frozen ED8 Champion remains untouched."""

from __future__ import annotations

from champion.frozen.ED8_V741_E001FastCapture10m08bp import ED8


class ED8Delay1(ED8):
    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe["enter_long"] = dataframe["enter_long"].shift(1).fillna(0).astype(int)
        dataframe["enter_tag"] = dataframe["enter_tag"].shift(1)
        return dataframe


class ED8Delay2(ED8):
    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        dataframe["enter_long"] = dataframe["enter_long"].shift(2).fillna(0).astype(int)
        dataframe["enter_tag"] = dataframe["enter_tag"].shift(2)
        return dataframe


class ED8NoCustomExitAblation(ED8):
    def custom_exit(self, *args, **kwargs):
        del args, kwargs
        return None


class ED8ROIOnlyExitAblation(ED8NoCustomExitAblation):
    use_exit_signal = False


class ED8OnlyE001EntryAblation(ED8):
    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        keep = dataframe["enter_tag"].fillna("").str.contains("|e001|", regex=False)
        dataframe.loc[~keep, "enter_long"] = 0
        dataframe.loc[~keep, "enter_tag"] = None
        return dataframe


class ED8WithoutE001EntryAblation(ED8):
    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        remove = dataframe["enter_tag"].fillna("").str.contains("|e001|", regex=False)
        dataframe.loc[remove, "enter_long"] = 0
        dataframe.loc[remove, "enter_tag"] = None
        return dataframe
