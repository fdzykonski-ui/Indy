#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib

MARKER = '# ===== FQT V26 PIONEER FACTORY CANDIDATES ====='

APPENDIX = r'''

# ===== FQT V26 PIONEER FACTORY CANDIDATES =====
import numpy as _fqt_v26_np
import pandas as _fqt_v26_pd


class M4PioneerValidationV14(M4PioneerStableExposureV10):
    """Frozen evidence boundary over V10; alpha unchanged."""
    can_short = False
    alpha_change = False
    timestamp_replay = False
    @staticmethod
    def version() -> str:
        return "14.0-validation-parity"


class _FQTV26Features(M4PioneerValidationV14):
    """Pair-agnostic causal features available at the completed entry candle."""
    def populate_indicators(self, dataframe, metadata):
        df = super().populate_indicators(dataframe, metadata)
        close = _fqt_v26_pd.to_numeric(df['close'], errors='coerce')
        high = _fqt_v26_pd.to_numeric(df['high'], errors='coerce')
        low = _fqt_v26_pd.to_numeric(df['low'], errors='coerce')
        volume = _fqt_v26_pd.to_numeric(df['volume'], errors='coerce')
        prev_close = close.shift(1)
        tr = _fqt_v26_pd.concat([
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        df['v26_ema20'] = close.ewm(span=20, adjust=False, min_periods=20).mean()
        df['v26_ema80'] = close.ewm(span=80, adjust=False, min_periods=80).mean()
        df['v26_ema_gap'] = (df['v26_ema20'] / df['v26_ema80'].replace(0, _fqt_v26_np.nan)) - 1.0
        df['v26_atr14_ratio'] = tr.rolling(14, min_periods=14).mean() / close.replace(0, _fqt_v26_np.nan)
        df['v26_vol_ratio'] = volume / volume.rolling(30, min_periods=30).median().replace(0, _fqt_v26_np.nan)
        df['v26_ret5'] = close.pct_change(5, fill_method=None)
        df['v26_ret15'] = close.pct_change(15, fill_method=None)
        df['v26_range12'] = (high.rolling(12, min_periods=12).max() / low.rolling(12, min_periods=12).min()) - 1.0
        return df

    @staticmethod
    def _tag_text(dataframe):
        return dataframe.get('enter_tag', _fqt_v26_pd.Series('', index=dataframe.index)).astype('string').fillna('')


class M4PioneerV26FullStake(_FQTV26Features):
    """No signal change; remove historical tag/pair stake attenuation under MOT=1."""
    @staticmethod
    def version() -> str:
        return "26.1-full-stake"

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs):
        stake = float(proposed_stake)
        if min_stake is not None:
            stake = max(stake, float(min_stake))
        return float(min(stake, float(max_stake)))


class M4PioneerV26VWAPPrune(_FQTV26Features):
    """Preregistered ablation of the historically negative VWAP-reclaim path."""
    @staticmethod
    def version() -> str:
        return "26.2-vwap-prune"

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        tags = self._tag_text(df)
        reject = tags.str.contains('vwap_reclaim', case=False, regex=False, na=False)
        df.loc[reject, 'enter_long'] = 0
        return df


class M4PioneerV26CausalQuality(_FQTV26Features):
    """Causal quality filter; no pair/date/outcome lookup."""
    @staticmethod
    def version() -> str:
        return "26.3-causal-quality"

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        signal = df.get('enter_long', 0).fillna(0).astype(int) == 1
        quality = (
            df['v26_ema_gap'].fillna(-1.0).ge(-0.004)
            & df['v26_atr14_ratio'].fillna(0.0).between(0.00035, 0.030)
            & df['v26_vol_ratio'].fillna(0.0).ge(0.35)
            & df['v26_ret15'].fillna(-1.0).ge(-0.018)
        )
        df.loc[signal & ~quality, 'enter_long'] = 0
        return df


class M4PioneerV26PathQuality(_FQTV26Features):
    """Filter only weak trend-pullback/VWAP contexts; other paths unchanged."""
    @staticmethod
    def version() -> str:
        return "26.4-path-quality"

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        tags = self._tag_text(df)
        targeted = tags.str.contains('trend_pullback|vwap_reclaim', case=False, regex=True, na=False)
        weak = (
            df['v26_ema_gap'].fillna(-1.0).lt(-0.006)
            | df['v26_vol_ratio'].fillna(0.0).lt(0.30)
            | df['v26_ret5'].fillna(-1.0).lt(-0.012)
        )
        df.loc[targeted & weak, 'enter_long'] = 0
        return df


class M4PioneerV26TailBrake(_FQTV26Features):
    """Causal time-under-water brake for the emergency-loss tail."""
    @staticmethod
    def version() -> str:
        return "26.5-tail-brake"

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        parent = super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        if parent is not None:
            return parent
        opened = getattr(trade, 'open_date_utc', getattr(trade, 'open_date', None))
        if opened is None:
            return None
        minutes = max((current_time - opened).total_seconds() / 60.0, 0.0)
        if minutes >= 240 and current_profit <= -0.006:
            return 'v26_tail_brake_240m'
        if minutes >= 720 and current_profit <= -0.002:
            return 'v26_tail_brake_720m'
        return None


class M4PioneerV26Balanced(M4PioneerV26FullStake):
    """Full MOT=1 stake plus narrow causal rejection of weak target paths."""
    @staticmethod
    def version() -> str:
        return "26.6-balanced"

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        tags = self._tag_text(df)
        targeted = tags.str.contains('trend_pullback|vwap_reclaim', case=False, regex=True, na=False)
        reject = targeted & (
            df['v26_ema_gap'].fillna(-1.0).lt(-0.007)
            | df['v26_vol_ratio'].fillna(0.0).lt(0.25)
            | df['v26_ret15'].fillna(-1.0).lt(-0.020)
        )
        df.loc[reject, 'enter_long'] = 0
        return df


def _fqt_v26_delay_class(name, parent):
    def populate_entry_trend(self, dataframe, metadata):
        df = super(cls, self).populate_entry_trend(dataframe, metadata)
        original = df.get('enter_long', 0).fillna(0).astype(int)
        original_tag = df.get('enter_tag', _fqt_v26_pd.Series(None, index=df.index))
        df['enter_long'] = original.shift(1, fill_value=0).astype(int)
        df['enter_tag'] = original_tag.shift(1)
        return df
    cls = type(name, (parent,), {
        'version': staticmethod(lambda: '26.delay-plus-1'),
        'populate_entry_trend': populate_entry_trend,
    })
    return cls


M4PioneerV26FullStakeDelay1 = _fqt_v26_delay_class('M4PioneerV26FullStakeDelay1', M4PioneerV26FullStake)
M4PioneerV26VWAPPruneDelay1 = _fqt_v26_delay_class('M4PioneerV26VWAPPruneDelay1', M4PioneerV26VWAPPrune)
M4PioneerV26CausalQualityDelay1 = _fqt_v26_delay_class('M4PioneerV26CausalQualityDelay1', M4PioneerV26CausalQuality)
M4PioneerV26PathQualityDelay1 = _fqt_v26_delay_class('M4PioneerV26PathQualityDelay1', M4PioneerV26PathQuality)
M4PioneerV26TailBrakeDelay1 = _fqt_v26_delay_class('M4PioneerV26TailBrakeDelay1', M4PioneerV26TailBrake)
M4PioneerV26BalancedDelay1 = _fqt_v26_delay_class('M4PioneerV26BalancedDelay1', M4PioneerV26Balanced)
# ===== END FQT V26 PIONEER FACTORY CANDIDATES =====
'''


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=pathlib.Path, required=True)
    parser.add_argument('--out', type=pathlib.Path, required=True)
    parser.add_argument('--receipt', type=pathlib.Path, required=True)
    args = parser.parse_args()
    text = args.source.read_text(encoding='utf-8')
    if MARKER in text:
        raise RuntimeError('V26 candidate appendix already present')
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text + APPENDIX, encoding='utf-8')
    receipt = {
        'contract': 'FQT_V26_CANDIDATE_REGISTRY_V1',
        'source_sha256': sha256(args.source),
        'output_sha256': sha256(args.out),
        'alpha_change': True,
        'timestamp_replay': False,
        'pair_specific_signal_rules': False,
        'date_specific_rules': False,
        'candidates': [
            'M4PioneerValidationV14',
            'M4PioneerV26FullStake',
            'M4PioneerV26VWAPPrune',
            'M4PioneerV26CausalQuality',
            'M4PioneerV26PathQuality',
            'M4PioneerV26TailBrake',
            'M4PioneerV26Balanced',
        ],
        'delay_controls': [
            'M4PioneerV26FullStakeDelay1','M4PioneerV26VWAPPruneDelay1',
            'M4PioneerV26CausalQualityDelay1','M4PioneerV26PathQualityDelay1',
            'M4PioneerV26TailBrakeDelay1','M4PioneerV26BalancedDelay1',
        ],
        'selection_policy': 'training/known data only; OOS sealed; one final candidate may be authorized',
    }
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    args.receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
