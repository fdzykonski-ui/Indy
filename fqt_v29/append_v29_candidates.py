#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import pathlib

TARGET = pathlib.Path("user_data/strategies/M4PioneerV26Factory.py")
RECEIPT = pathlib.Path("evidence/CANDIDATE_REGISTRY_V29.json")
MARKER = "# ===== FQT V29 CAUSAL PERFORMANCE CANDIDATES ====="

APPENDIX = r'''

# ===== FQT V29 CAUSAL PERFORMANCE CANDIDATES =====
class _FQTV29RiskMixin:
    """Pair/date agnostic risk controls evaluated only from completed candles and trade state."""
    alpha_change = True
    timestamp_replay = False
    pair_specific_signal_rules = False
    date_specific_rules = False

    def _v29_parent_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        parent = super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        return parent

    @staticmethod
    def _v29_minutes_open(trade, current_time):
        opened = getattr(trade, 'open_date_utc', getattr(trade, 'open_date', None))
        if opened is None:
            return 0.0
        return max((current_time - opened).total_seconds() / 60.0, 0.0)

    @staticmethod
    def _v29_full_stake(proposed_stake, min_stake, max_stake):
        stake = float(proposed_stake)
        if min_stake is not None:
            stake = max(stake, float(min_stake))
        return float(min(stake, float(max_stake)))


class M4PioneerV29ProfitVelocity(_FQTV29RiskMixin, _FQTV26Features):
    """Higher capital turnover with a shallower hard tail; signals remain unchanged."""
    minimal_roi = {'0': 0.0065, '75': 0.0035, '240': 0.0015, '600': 0.0}
    stoploss = -0.055

    @staticmethod
    def version() -> str:
        return '29.1-profit-velocity'

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs):
        return self._v29_full_stake(proposed_stake, min_stake, max_stake)


class M4PioneerV29TailShield(_FQTV29RiskMixin, M4PioneerV26FullStake):
    """Full MOT=1 exposure plus staged time-under-water loss containment."""
    stoploss = -0.06

    @staticmethod
    def version() -> str:
        return '29.2-tail-shield'

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        parent = self._v29_parent_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        if parent is not None:
            return parent
        minutes = self._v29_minutes_open(trade, current_time)
        if minutes >= 180 and current_profit <= -0.016:
            return 'v29_tail_180m'
        if minutes >= 360 and current_profit <= -0.010:
            return 'v29_tail_360m'
        if minutes >= 720 and current_profit <= -0.005:
            return 'v29_tail_720m'
        return None


class M4PioneerV29RegimeScore(_FQTV29RiskMixin, M4PioneerV26FullStake):
    """Moderate causal quality score: keep throughput, veto only low-margin regimes."""
    stoploss = -0.065

    @staticmethod
    def version() -> str:
        return '29.3-regime-score'

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        signal = df.get('enter_long', 0).fillna(0).astype(int).eq(1)
        tags = self._tag_text(df)
        score = (
            df['v26_ema_gap'].fillna(-1.0).ge(-0.004).astype(int)
            + df['v26_atr14_ratio'].fillna(0.0).between(0.00030, 0.028).astype(int)
            + df['v26_vol_ratio'].fillna(0.0).ge(0.32).astype(int)
            + df['v26_ret5'].fillna(-1.0).ge(-0.012).astype(int)
            + df['v26_ret15'].fillna(-1.0).ge(-0.020).astype(int)
            + df['v26_range12'].fillna(1.0).le(0.085).astype(int)
        )
        vwap = tags.str.contains('vwap_reclaim', case=False, regex=False, na=False)
        momentum = tags.str.contains('momentum_continuation', case=False, regex=False, na=False)
        required = _fqt_v26_pd.Series(3, index=df.index, dtype='int64')
        required.loc[vwap] = 5
        required.loc[momentum] = 4
        df.loc[signal & score.lt(required), 'enter_long'] = 0
        return df


class M4PioneerV29AdaptiveBalanced(_FQTV29RiskMixin, M4PioneerV26FullStake):
    """Medium-to-large causal patch: score veto, faster ROI and convex tail containment."""
    minimal_roi = {'0': 0.0070, '90': 0.0038, '270': 0.0014, '660': 0.0}
    stoploss = -0.052

    @staticmethod
    def version() -> str:
        return '29.4-adaptive-balanced'

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        signal = df.get('enter_long', 0).fillna(0).astype(int).eq(1)
        tags = self._tag_text(df)
        targeted = tags.str.contains('trend_pullback|vwap_reclaim', case=False, regex=True, na=False)
        hazardous = (
            (df['v26_ema_gap'].fillna(-1.0).lt(-0.008) & df['v26_ret15'].fillna(-1.0).lt(-0.018))
            | (df['v26_vol_ratio'].fillna(0.0).lt(0.22))
            | (df['v26_atr14_ratio'].fillna(1.0).gt(0.032))
            | (df['v26_range12'].fillna(1.0).gt(0.11))
        )
        vwap_weak = tags.str.contains('vwap_reclaim', case=False, regex=False, na=False) & (
            df['v26_ema_gap'].fillna(-1.0).lt(-0.002)
            | df['v26_vol_ratio'].fillna(0.0).lt(0.42)
        )
        df.loc[signal & ((targeted & hazardous) | vwap_weak), 'enter_long'] = 0
        return df

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        parent = self._v29_parent_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        if parent is not None:
            return parent
        minutes = self._v29_minutes_open(trade, current_time)
        if minutes >= 150 and current_profit <= -0.018:
            return 'v29_adaptive_tail_150m'
        if minutes >= 330 and current_profit <= -0.009:
            return 'v29_adaptive_tail_330m'
        if minutes >= 690 and current_profit <= -0.004:
            return 'v29_adaptive_tail_690m'
        return None


class M4PioneerV29HighMargin(_FQTV29RiskMixin, M4PioneerV26FullStake):
    """High-selectivity challenger for PF/fee margin; deliberately sacrifices throughput."""
    minimal_roi = {'0': 0.0085, '120': 0.0045, '360': 0.0018, '840': 0.0}
    stoploss = -0.045

    @staticmethod
    def version() -> str:
        return '29.5-high-margin'

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        signal = df.get('enter_long', 0).fillna(0).astype(int).eq(1)
        quality = (
            df['v26_ema_gap'].fillna(-1.0).ge(-0.0015)
            & df['v26_atr14_ratio'].fillna(0.0).between(0.00045, 0.022)
            & df['v26_vol_ratio'].fillna(0.0).ge(0.48)
            & df['v26_ret5'].fillna(-1.0).ge(-0.007)
            & df['v26_ret15'].fillna(-1.0).ge(-0.012)
            & df['v26_range12'].fillna(1.0).le(0.065)
        )
        df.loc[signal & ~quality, 'enter_long'] = 0
        return df


def _fqt_v29_delay_class(name, parent, candles):
    def populate_entry_trend(self, dataframe, metadata):
        df = super(cls, self).populate_entry_trend(dataframe, metadata)
        original = df.get('enter_long', 0).fillna(0).astype(int)
        original_tag = df.get('enter_tag', _fqt_v26_pd.Series(None, index=df.index))
        df['enter_long'] = original.shift(candles, fill_value=0).astype(int)
        df['enter_tag'] = original_tag.shift(candles)
        return df
    cls = type(name, (parent,), {
        'version': staticmethod(lambda: f'29.delay-plus-{candles}'),
        'populate_entry_trend': populate_entry_trend,
    })
    return cls


_FQT_V29_PARENTS = {
    'M4PioneerV29ProfitVelocity': M4PioneerV29ProfitVelocity,
    'M4PioneerV29TailShield': M4PioneerV29TailShield,
    'M4PioneerV29RegimeScore': M4PioneerV29RegimeScore,
    'M4PioneerV29AdaptiveBalanced': M4PioneerV29AdaptiveBalanced,
    'M4PioneerV29HighMargin': M4PioneerV29HighMargin,
}
for _name, _parent in _FQT_V29_PARENTS.items():
    globals()[f'{_name}Delay1'] = _fqt_v29_delay_class(f'{_name}Delay1', _parent, 1)
    globals()[f'{_name}Delay2'] = _fqt_v29_delay_class(f'{_name}Delay2', _parent, 2)
# ===== END FQT V29 CAUSAL PERFORMANCE CANDIDATES =====
'''


def digest(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not TARGET.exists():
        raise FileNotFoundError(TARGET)
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        raise SystemExit(0)
    candidate = text + APPENDIX
    ast.parse(candidate)
    TARGET.write_text(candidate, encoding="utf-8")
    candidates = [
        "M4PioneerV29ProfitVelocity",
        "M4PioneerV29TailShield",
        "M4PioneerV29RegimeScore",
        "M4PioneerV29AdaptiveBalanced",
        "M4PioneerV29HighMargin",
    ]
    receipt = {
        "contract": "FQT_V29_CAUSAL_CANDIDATE_REGISTRY_V1",
        "status": "PASS",
        "strategy_path": str(TARGET),
        "strategy_sha256": digest(TARGET),
        "candidates": candidates,
        "delay1_controls": [f"{name}Delay1" for name in candidates],
        "delay2_controls": [f"{name}Delay2" for name in candidates],
        "timestamp_replay": False,
        "pair_specific_signal_rules": False,
        "date_specific_rules": False,
        "oos_used_for_construction": False,
        "risk_mode": "aggressive spot exposure with shallower tail, no leverage, fail-closed promotion",
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
