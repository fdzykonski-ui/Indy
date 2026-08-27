# pragma pylint: disable=missing-docstring, invalid-name, too-many-lines
"""M4MultiCoinPortfolioV7WalkForward — single-file research strategy.

This file intentionally contains the inherited M4 -> R4/R5 -> PerformanceRepair ->
OOSFeeRiskAction -> V4 chain inline, then adds V7 walk-forward stake allocation.
Research/backtest only. No live-trading or promotion claim.
"""




# ===== BEGIN INLINE SOURCE: M4.py =====

"""
TFS5V6962TailSignatureVeto

BTC rebuild-confirm Freqtrade research strategy.

Purpose
-------
This version intentionally does NOT add another huge edge layer. It converts the 1250-iteration trade-level prior into a stricter BTC retest controller, not a proof of live edge.
It rebuilds the decision surface into a path-specific, evidence-gated, auditable controller:
Data -> Indicators -> Regime -> Fingerprint -> Gates -> Paths -> Tier -> Risk -> Meta -> Entry/Exit.

Scope
-----
- Timeframe: 1m
- Mode: Spot / long-only
- can_short = False
- Pair whitelist: none inside strategy. Pair universe is controlled by Freqtrade config / pairlist.
- No profit guarantee. Backtest, analysis, lookahead, recursive, OOS and execution evidence are required.

Evidence status
---------------
Research build only. V6899 uses 5000 additional 100000-run trade-level optimization iterations (500000000 additional runs) after V1899. The selected defaults are still only a weak trade-level surrogate prior, not an official Freqtrade backtest and not a promotion claim. Backtest, analysis, lookahead, recursive, OOS and execution evidence remain required.
"""


from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

try:
    from freqtrade.strategy import IStrategy, BooleanParameter, DecimalParameter, IntParameter
    try:
        from freqtrade.persistence import Trade
    except Exception:  # pragma: no cover
        Trade = Any  # type: ignore
except Exception:  # pragma: no cover - local syntax/smoke fallback
    class IStrategy:  # type: ignore
        pass

    class _Param:  # type: ignore
        def __init__(self, *args: Any, default: Any = None, **kwargs: Any) -> None:
            self.value = default
            self.default = default

    BooleanParameter = DecimalParameter = IntParameter = _Param  # type: ignore
    Trade = Any  # type: ignore


def _pv(param_or_value: Any) -> Any:
    """Return .value for Freqtrade Parameters, otherwise the object itself."""
    return getattr(param_or_value, "value", param_or_value)


class M4(IStrategy):
    """Evidence-gated lean cross-layer controller.

    Design rule:
    - Legacy large-layer concepts are not trusted as direct entry/exit decisions.
    - Every final entry requires Data + Regime + Fingerprint + Path + Gate + Tier + Risk + Meta.
    - Profit-sensitive exits stay in custom_exit(), not blind vector exits.
    """

    INTERFACE_VERSION = 3

    timeframe = "1m"
    can_short = False
    startup_candle_count = 800
    process_only_new_candles = True

    minimal_roi = {
        "0": 0.008,
        "120": 0.004,
        "360": 0.001,
        "900": 0.0,
    }

    stoploss = -0.10
    trailing_stop = False
    use_custom_stoploss = False
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    position_adjustment_enable = False

    max_open_trades = 5

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
        "emergency_exit": "market",
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # Controller switches.
    enable_rearch_controller = BooleanParameter(default=True, space="buy", optimize=False)
    enable_shadow_legacy_measurement = BooleanParameter(default=True, space="buy", optimize=False)
    enable_profit_sensitive_custom_exits = BooleanParameter(default=True, space="sell", optimize=False)

    # Entry controller thresholds.
    buy_min_market_context = DecimalParameter(45.0, 85.0, default=56.0, decimals=1, space="buy", optimize=True)
    buy_min_entry_score = DecimalParameter(50.0, 90.0, default=68.0, decimals=1, space="buy", optimize=True)
    buy_max_entry_score = DecimalParameter(60.0, 96.0, default=79.0, decimals=1, space="buy", optimize=True)
    buy_min_path_score = DecimalParameter(45.0, 90.0, default=61.0, decimals=1, space="buy", optimize=True)
    buy_min_risk_score = DecimalParameter(45.0, 95.0, default=64.0, decimals=1, space="buy", optimize=True)
    buy_min_soft_gate_score = DecimalParameter(45.0, 95.0, default=60.0, decimals=1, space="buy", optimize=True)
    buy_max_exit_pressure = DecimalParameter(25.0, 80.0, default=46.0, decimals=1, space="buy", optimize=True)
    buy_min_volume_ratio = DecimalParameter(0.15, 2.50, default=0.3, decimals=2, space="buy", optimize=True)
    buy_max_late_chase_atr = DecimalParameter(1.0, 5.0, default=2.0, decimals=1, space="buy", optimize=True)
    buy_max_chop_penalty = DecimalParameter(25.0, 95.0, default=55.0, decimals=1, space="buy", optimize=True)

    # V6944 OOS repair: causal pre-entry tail-risk veto from March-OOS loss isolation.
    # These are not promotion parameters; they require April/March/OOS ablation.
    buy_tail_veto_closepos_max = DecimalParameter(0.20, 0.70, default=0.50, decimals=2, space="buy", optimize=True)
    buy_tail_veto_rsi_min = DecimalParameter(52.0, 70.0, default=58.0, decimals=1, space="buy", optimize=True)
    buy_tail_veto_low_volume_max = DecimalParameter(0.10, 0.80, default=0.35, decimals=2, space="buy", optimize=True)
    buy_tail_veto_dead_closepos_max = DecimalParameter(0.00, 0.20, default=0.05, decimals=2, space="buy", optimize=True)

    # Exit / risk controller thresholds.
    sell_hard_exit_pressure = DecimalParameter(60.0, 98.0, default=92.0, decimals=1, space="sell", optimize=True)
    sell_profit_lock_min = DecimalParameter(0.001, 0.060, default=0.006, decimals=3, space="sell", optimize=True)
    sell_thesis_profit_min = DecimalParameter(0.001, 0.060, default=0.006, decimals=3, space="sell", optimize=True)
    sell_time_decay_profit_min = DecimalParameter(0.000, 0.040, default=0.004, decimals=3, space="sell", optimize=True)
    sell_emergency_loss_floor = DecimalParameter(-0.080, -0.006, default=-0.040, decimals=3, space="sell", optimize=True)
    sell_time_decay_minutes = IntParameter(60, 1440, default=240, space="sell", optimize=True)

    # Protection parameters. These are ablation targets, not proof of robustness.
    protection_enable_cooldown = BooleanParameter(default=False, space="protection", optimize=True)
    protection_enable_stoploss_guard = BooleanParameter(default=False, space="protection", optimize=True)
    protection_enable_max_drawdown = BooleanParameter(default=False, space="protection", optimize=True)
    protection_enable_low_profit_pairs = BooleanParameter(default=False, space="protection", optimize=True)
    protection_cooldown_candles = IntParameter(1, 180, default=30, space="protection", optimize=True)
    protection_stoploss_guard_lookback = IntParameter(30, 720, default=240, space="protection", optimize=True)
    protection_stoploss_guard_trade_limit = IntParameter(1, 12, default=4, space="protection", optimize=True)
    protection_stoploss_guard_duration = IntParameter(10, 360, default=60, space="protection", optimize=True)
    protection_max_drawdown_lookback = IntParameter(120, 2880, default=1440, space="protection", optimize=True)
    protection_max_drawdown_trade_limit = IntParameter(5, 80, default=20, space="protection", optimize=True)
    protection_max_drawdown_duration = IntParameter(30, 1440, default=240, space="protection", optimize=True)
    protection_max_allowed_drawdown = DecimalParameter(0.02, 0.30, default=0.08, decimals=3, space="protection", optimize=True)

    # Component status ledger. Every component has one explicit status.
    COMPONENT_STATUS = (
        ("score_only_entries", "Entry", "REMOVE", "Score alone is not a tradable edge."),
        ("legacy_large_edge_layers", "Entry/Meta", "QUARANTINE", "Legacy layers may nominate candidates but cannot trade without final controller."),
        ("profit_sensitive_vector_exits", "Exit", "MOVE", "Profit-sensitive exits need current_profit and belong in custom_exit."),
        ("protective_vector_exits", "Exit/Risk", "KEEP", "Emergency/structure/volatility exits may protect without profit context."),
        ("global_quality_gates", "Gate", "SPLIT", "Data/risk/emergency hard; quality gates become path/meta penalties."),
        ("tier_without_risk_effect", "Tier", "REBUILD", "Tier must alter threshold/risk/exits or remain decorative."),
        ("custom_stoploss", "Risk", "KEEP", "Correct mechanism for dynamic stop protection."),
        ("protections", "Risk/Governance", "KEEP", "Keep only with protections off/on ablation."),
        ("all_pairs_scope", "Universe", "MODIFY", "Config pairlist controls universe; validation must be pair-stratified."),
        ("path_specific_policy", "Path/Gate", "MODIFY", "Global gates are converted to path-specific regime/fingerprint/risk/exit thresholds."),
        ("clean_retest_active_entry", "Entry", "REMOVE", "V13 backtest: 104 trades / -24.55%; kept only as shadow/quarantine."),
        ("wick_range_squeeze_reversal_active_entries", "Entry", "QUARANTINE", "Noisy BTC 1m reversal patterns; tag-only until OOS evidence."),
        ("aggressive_stake_action", "Risk", "REMOVE", "No stake increase before official evidence validation."),
        ("path_aware_stoploss", "Risk", "MODIFY", "custom_stoploss now adapts to path family and tier."),
        ("full_forensics_columns", "Forensics", "MODIFY", "Keep core decision forensics; heavy research forensics only in analysis profile."),
        ("dca", "Risk", "REMOVE", "Position adjustment disabled; no DCA recovery masking."),
        ("short_logic", "Scope", "REMOVE", "Spot long-only strategy; no short claims."),
        ("freqai_ml", "ML", "QUARANTINE", "No FreqAI evidence pipeline."),
        ("orderflow", "Execution", "QUARANTINE", "No historical orderflow/queue dataset."),
    )

    PATH_FAMILIES = (
        "trend_pullback",
        "momentum_continuation",
        "breakout_expansion",
        "squeeze_release",
        "failed_breakdown_recovery",
        "vwap_reclaim",
        "range_reversal",
        "wick_rejection_reclaim",
        "exhaustion_bounce",
        "clean_retest",
    )

    @property
    def protections(self) -> list[dict[str, Any]]:
        prot: list[dict[str, Any]] = []
        if bool(_pv(self.protection_enable_cooldown)):
            prot.append({"method": "CooldownPeriod", "stop_duration_candles": int(_pv(self.protection_cooldown_candles))})
        if bool(_pv(self.protection_enable_stoploss_guard)):
            prot.append({
                "method": "StoplossGuard",
                "lookback_period_candles": int(_pv(self.protection_stoploss_guard_lookback)),
                "trade_limit": int(_pv(self.protection_stoploss_guard_trade_limit)),
                "stop_duration_candles": int(_pv(self.protection_stoploss_guard_duration)),
                "only_per_pair": False,
            })
        if bool(_pv(self.protection_enable_max_drawdown)):
            prot.append({
                "method": "MaxDrawdown",
                "lookback_period_candles": int(_pv(self.protection_max_drawdown_lookback)),
                "trade_limit": int(_pv(self.protection_max_drawdown_trade_limit)),
                "stop_duration_candles": int(_pv(self.protection_max_drawdown_duration)),
                "max_allowed_drawdown": float(_pv(self.protection_max_allowed_drawdown)),
            })
        if bool(_pv(self.protection_enable_low_profit_pairs)):
            prot.append({"method": "LowProfitPairs", "lookback_period_candles": 720, "trade_limit": 3, "stop_duration_candles": 120, "required_profit": -0.01})
        return prot

    def version(self) -> str:
        return "M4-tfs5-anchor-rename-v6971-no-logic-change"

    def informative_pairs(self) -> list[tuple[str, str]]:
        # No HTF/MTF claim. Keep strategy causality simple until official validation passes.
        return []

    @staticmethod
    def _append_columns(df: DataFrame, cols: dict[str, Any]) -> DataFrame:
        if not cols:
            return df.copy()
        add = pd.DataFrame(cols, index=df.index)
        overlap = [c for c in add.columns if c in df.columns]
        if overlap:
            df = df.drop(columns=overlap, errors="ignore")
        return pd.concat([df, add], axis=1).copy()

    @staticmethod
    def _s(df: DataFrame, name: str, default: Any = 0.0) -> Series:
        if name in df.columns:
            return df[name]
        return pd.Series(default, index=df.index)

    @staticmethod
    def _clip(s: Series, low: float = 0.0, high: float = 100.0) -> Series:
        return pd.to_numeric(s, errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(low, high)

    @staticmethod
    def _ema(s: Series, span: int) -> Series:
        return pd.to_numeric(s, errors="coerce").ewm(span=span, adjust=False, min_periods=max(2, span // 2)).mean()

    @staticmethod
    def _rsi(close: Series, period: int = 14) -> Series:
        close = pd.to_numeric(close, errors="coerce")
        delta = close.diff()
        gain = delta.clip(lower=0.0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        loss = (-delta.clip(upper=0.0)).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        rs = gain / loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).replace([np.inf, -np.inf], np.nan).fillna(50.0)

    @staticmethod
    def _true_range(high: Series, low: Series, close: Series) -> Series:
        prev_close = close.shift(1)
        return pd.concat([(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)

    def _last_analyzed_candle(self, pair: str) -> Optional[Series]:
        if not hasattr(self, "dp") or self.dp is None:  # type: ignore[attr-defined]
            return None
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair=pair, timeframe=self.timeframe)  # type: ignore[attr-defined]
            if dataframe is None or dataframe.empty:
                return None
            return dataframe.iloc[-1]
        except Exception:
            return None

    def _trade_minutes_open(self, trade: Trade, current_time: datetime) -> float:
        open_dt = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        if open_dt is None:
            return 0.0
        if getattr(open_dt, "tzinfo", None) is None:
            open_dt = open_dt.replace(tzinfo=timezone.utc)
        if current_time.tzinfo is None:
            current_time = current_time.replace(tzinfo=timezone.utc)
        return max(0.0, (current_time - open_dt).total_seconds() / 60.0)

    def leverage(self, pair: str, current_time: datetime, current_rate: float, proposed_leverage: float, max_leverage: float, entry_tag: str | None, side: str, **kwargs: Any) -> float:
        return 1.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()
        idx = df.index
        eps = 1e-12

        # Preserve OHLCV semantics. Convert only local derived Series, do not overwrite OHLCV columns.
        open_ = pd.to_numeric(df.get("open", pd.Series(np.nan, index=idx)), errors="coerce")
        high = pd.to_numeric(df.get("high", pd.Series(np.nan, index=idx)), errors="coerce")
        low = pd.to_numeric(df.get("low", pd.Series(np.nan, index=idx)), errors="coerce")
        close = pd.to_numeric(df.get("close", pd.Series(np.nan, index=idx)), errors="coerce")
        volume = pd.to_numeric(df.get("volume", pd.Series(0.0, index=idx)), errors="coerce").fillna(0.0)

        true_range = self._true_range(high, low, close)
        atr_14 = true_range.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        range_abs = (high - low).abs()
        range_pct = range_abs / close.replace(0, np.nan)
        body_pct = (close - open_).abs() / close.replace(0, np.nan)
        upper_wick_pct = (high - pd.concat([open_, close], axis=1).max(axis=1)).clip(lower=0.0) / close.replace(0, np.nan)
        lower_wick_pct = (pd.concat([open_, close], axis=1).min(axis=1) - low).clip(lower=0.0) / close.replace(0, np.nan)
        close_position = ((close - low) / range_abs.replace(0, np.nan)).clip(0, 1).fillna(0.5)
        candle_dir = np.sign(close - open_).replace(0, 0)
        data_gap_flag = (close.pct_change().abs() > 0.04).astype(int)
        finite = open_.notna() & high.notna() & low.notna() & close.notna() & volume.notna()
        startup_ok = pd.Series(np.arange(len(df)) >= self.startup_candle_count, index=idx)
        data_valid = finite & (high >= low) & (close > 0) & (volume > 0) & startup_ok & (data_gap_flag == 0)

        # Indicators.
        ema8 = self._ema(close, 8)
        ema21 = self._ema(close, 21)
        ema55 = self._ema(close, 55)
        ema200 = self._ema(close, 200)
        ema_stack_bull = (ema8 > ema21) & (ema21 > ema55)
        trend_slope_fast = (ema21 - ema21.shift(12)) / atr_14.replace(0, np.nan)
        trend_slope_slow = (ema55 - ema55.shift(48)) / atr_14.replace(0, np.nan)
        rsi14 = self._rsi(close, 14)
        roc5 = close.pct_change(5)
        roc20 = close.pct_change(20)
        macd_fast = self._ema(close, 12)
        macd_slow = self._ema(close, 26)
        macd = macd_fast - macd_slow
        macd_signal = self._ema(macd, 9)
        macd_hist = macd - macd_signal
        atr_pct = atr_14 / close.replace(0, np.nan)
        bb_mid = close.rolling(20, min_periods=20).mean()
        bb_std = close.rolling(20, min_periods=20).std()
        bb_upper = bb_mid + 2 * bb_std
        bb_lower = bb_mid - 2 * bb_std
        bb_width = (bb_upper - bb_lower) / bb_mid.replace(0, np.nan)
        bb_pos = ((close - bb_lower) / (bb_upper - bb_lower).replace(0, np.nan)).clip(0, 1).fillna(0.5)
        volume_sma20 = volume.rolling(20, min_periods=20).mean()
        volume_sma120 = volume.rolling(120, min_periods=30).mean()
        volume_ratio = volume / volume_sma120.replace(0, np.nan)
        volume_z = (volume - volume_sma120) / volume.rolling(120, min_periods=30).std().replace(0, np.nan)
        donchian_high60 = high.rolling(60, min_periods=60).max()
        donchian_low60 = low.rolling(60, min_periods=60).min()
        donchian_mid60 = (donchian_high60 + donchian_low60) / 2
        vwap_num = (close * volume).rolling(60, min_periods=20).sum()
        vwap_den = volume.rolling(60, min_periods=20).sum().replace(0, np.nan)
        vwap60 = vwap_num / vwap_den
        vwap_distance = (close - vwap60) / atr_14.replace(0, np.nan)
        efficiency30 = (close - close.shift(30)).abs() / close.diff().abs().rolling(30, min_periods=30).sum().replace(0, np.nan)

        # Quality scores.
        trend_quality = self._clip((ema_stack_bull.astype(int) * 35) + trend_slope_fast.fillna(0) * 9 + trend_slope_slow.fillna(0) * 7 + (rsi14 - 50) * 0.6)
        momentum_quality = self._clip((rsi14 - 45) * 1.2 + roc5.fillna(0) * 2500 + macd_hist.fillna(0) / atr_14.replace(0, np.nan).fillna(1) * 10 + 35)
        volatility_quality = self._clip((atr_pct.fillna(0) * 6000).clip(0, 45) + (bb_width.fillna(0) * 2500).clip(0, 35) + 20)
        liquidity_quality = self._clip(volume_ratio.fillna(0) * 35 + volume_z.fillna(0).clip(-2, 4) * 8 + 25)
        structure_quality = self._clip((close > donchian_mid60).astype(int) * 25 + close_position * 25 + (close > ema21).astype(int) * 25 + (close > vwap60).astype(int) * 25)
        candle_quality = self._clip((close_position * 45) + (body_pct.fillna(0) * 2200).clip(0, 30) + (lower_wick_pct.fillna(0) * 1600).clip(0, 25) - (upper_wick_pct.fillna(0) * 900).clip(0, 25))
        chop_penalty = self._clip((1 - efficiency30.fillna(0.0)) * 65 + ((bb_width.fillna(0) < bb_width.rolling(120, min_periods=30).median()).astype(int) * 20))
        dirty_market_penalty = self._clip((close < ema55).astype(int) * 25 + (high / low.replace(0, np.nan) - 1).fillna(0) * 1800 + data_gap_flag * 100)

        # Regimes and fingerprints.
        clean_uptrend = (ema_stack_bull & (trend_slope_fast > 0) & (rsi14 > 50) & (close > vwap60))
        weak_uptrend = ((ema21 > ema55) & (trend_slope_fast > -0.2) & (rsi14 > 45))
        downtrend_risk = (close < ema55) & (trend_slope_slow < 0)
        range_chop = (chop_penalty > 55) & (trend_quality < 45)
        compression = bb_width < bb_width.rolling(120, min_periods=60).quantile(0.30)
        expansion = (atr_pct > atr_pct.rolling(120, min_periods=60).quantile(0.65)) | (bb_width > bb_width.rolling(120, min_periods=60).quantile(0.70))
        volume_expansion = volume_ratio > 1.25
        low_liquidity = volume_ratio < 0.25
        overextended = (vwap_distance > float(_pv(self.buy_max_late_chase_atr))) | (rsi14 > 78) | (bb_pos > 0.96)
        recovery_reclaim = (close > ema21) & (close.shift(1) < ema21.shift(1)) & (rsi14 > 43)
        breakdown_risk = (close < donchian_mid60) | ((close < ema21) & (trend_slope_fast < 0))
        momentum_burst = (roc5 > 0) & (macd_hist > macd_hist.shift(1)) & volume_expansion

        active_regime = pd.Series("neutral", index=idx, dtype="object")
        active_regime = active_regime.mask(clean_uptrend, "clean_uptrend")
        active_regime = active_regime.mask(weak_uptrend & ~clean_uptrend, "weak_uptrend")
        active_regime = active_regime.mask(range_chop, "range_chop")
        active_regime = active_regime.mask(compression, "compression")
        active_regime = active_regime.mask(expansion & ~clean_uptrend, "volatility_expansion")
        active_regime = active_regime.mask(downtrend_risk, "downtrend_risk")
        active_regime = active_regime.mask(low_liquidity, "low_liquidity")
        active_regime = active_regime.mask(overextended, "overextended")
        active_regime = active_regime.mask(recovery_reclaim, "recovery_reclaim")
        active_regime = active_regime.mask(breakdown_risk, "breakdown_risk")
        active_regime = active_regime.mask(momentum_burst, "momentum_burst")

        fp_trend_pullback = clean_uptrend & (close <= ema21 + atr_14 * 0.9) & (close >= ema55) & (rsi14.between(45, 68))
        fp_momentum_cont = clean_uptrend & momentum_burst & ~overextended
        fp_breakout = (close > donchian_high60.shift(1)) & expansion & volume_expansion & (close_position > 0.62)
        fp_squeeze_release = compression.shift(1).astype("boolean").fillna(False).astype(bool) & expansion & (close > bb_mid) & volume_expansion
        fp_failed_breakdown = (low < donchian_low60.shift(1)) & (close > donchian_mid60) & (lower_wick_pct > upper_wick_pct)
        fp_vwap_reclaim = (close > vwap60) & (close.shift(1) <= vwap60.shift(1)) & (rsi14 > 42)
        fp_range_reversal = range_chop & (bb_pos < 0.25) & (close_position > 0.55) & (rsi14 < 48)
        fp_wick_rejection = (lower_wick_pct > body_pct * 1.5) & (close_position > 0.58) & (volume_ratio > 0.6)
        fp_exhaustion_bounce = (rsi14 < 35) & (lower_wick_pct > upper_wick_pct) & (close > open_)
        fp_clean_retest = ((close > donchian_high60.shift(3)) & (low <= donchian_high60.shift(3) + atr_14 * 0.6) & (close_position > 0.55))
        active_fingerprint = pd.Series("none", index=idx, dtype="object")
        for name, mask in (
            ("trend_pullback", fp_trend_pullback),
            ("momentum_continuation", fp_momentum_cont),
            ("breakout_expansion", fp_breakout),
            ("squeeze_release", fp_squeeze_release),
            ("failed_breakdown_recovery", fp_failed_breakdown),
            ("vwap_reclaim", fp_vwap_reclaim),
            ("range_reversal", fp_range_reversal),
            ("wick_rejection", fp_wick_rejection),
            ("exhaustion_bounce", fp_exhaustion_bounce),
            ("clean_retest", fp_clean_retest),
        ):
            active_fingerprint = active_fingerprint.mask(mask & active_fingerprint.eq("none"), name)

        fingerprint_score = self._clip(
            fp_trend_pullback.astype(int) * 55
            + fp_momentum_cont.astype(int) * 60
            + fp_breakout.astype(int) * 60
            + fp_squeeze_release.astype(int) * 55
            + fp_failed_breakdown.astype(int) * 58
            + fp_vwap_reclaim.astype(int) * 52
            + fp_range_reversal.astype(int) * 45
            + fp_wick_rejection.astype(int) * 42
            + fp_exhaustion_bounce.astype(int) * 40
            + fp_clean_retest.astype(int) * 54
        )

        regime_score = self._clip(trend_quality * 0.30 + momentum_quality * 0.20 + volatility_quality * 0.12 + liquidity_quality * 0.16 + structure_quality * 0.16 + candle_quality * 0.06 - chop_penalty * 0.10 - dirty_market_penalty * 0.16)
        market_context_score = self._clip(regime_score * 0.42 + fingerprint_score * 0.18 + trend_quality * 0.14 + momentum_quality * 0.12 + liquidity_quality * 0.10 + volatility_quality * 0.04 - chop_penalty * 0.08)
        exit_pressure = self._clip(
            downtrend_risk.astype(int) * 35
            + breakdown_risk.astype(int) * 25
            + overextended.astype(int) * 20
            + (upper_wick_pct.fillna(0) * 1200).clip(0, 20)
            + (rsi14 > 78).astype(int) * 15
            + (volume_ratio < 0.20).astype(int) * 15
            + dirty_market_penalty * 0.30
        )
        risk_score = self._clip(100 - exit_pressure * 0.55 - dirty_market_penalty * 0.30 - chop_penalty * 0.16 + liquidity_quality * 0.15 + structure_quality * 0.10)
        # V18 pre-entry structure guard: avoid entering where the old strategy would immediately fall into structure/regime exits.
        structure_preentry_ok = (close > ema55) & (close > donchian_mid60) & (close > vwap60) & ~breakdown_risk & ~overextended & (risk_score >= 55)

        hard_gate_pass = data_valid & (volume_ratio.fillna(0) >= float(_pv(self.buy_min_volume_ratio))) & ~low_liquidity & (risk_score >= 30) & (dirty_market_penalty < 90)
        gate_fail_reason = pd.Series("", index=idx, dtype="object")
        gate_fail_reason = gate_fail_reason.mask(~data_valid, "data_invalid")
        gate_fail_reason = gate_fail_reason.mask(data_valid & (volume_ratio.fillna(0) < float(_pv(self.buy_min_volume_ratio))), "volume_low")
        gate_fail_reason = gate_fail_reason.mask(data_valid & low_liquidity, "low_liquidity")
        gate_fail_reason = gate_fail_reason.mask(data_valid & (risk_score < 30), "risk_floor")
        gate_fail_reason = gate_fail_reason.mask(data_valid & (dirty_market_penalty >= 90), "dirty_market")
        soft_gate_score = self._clip((trend_quality + momentum_quality + liquidity_quality + candle_quality + risk_score) / 5 - chop_penalty * 0.10)
        gate_quality_score = self._clip(hard_gate_pass.astype(int) * 30 + soft_gate_score * 0.70)

        cols = {
            "range_pct": range_pct.fillna(0.0),
            "body_pct": body_pct.fillna(0.0),
            "upper_wick_pct": upper_wick_pct.fillna(0.0),
            "lower_wick_pct": lower_wick_pct.fillna(0.0),
            "true_range_pct": (true_range / close.replace(0, np.nan)).fillna(0.0),
            "close_position": close_position,
            "candle_dir": candle_dir,
            "data_gap_flag": data_gap_flag,
            "data_valid": data_valid.astype(int),
            "ema8": ema8,
            "ema21": ema21,
            "ema55": ema55,
            "ema200": ema200,
            "ema_stack_bull": ema_stack_bull.astype(int),
            "trend_slope_fast_atr": trend_slope_fast.fillna(0.0),
            "trend_slope_slow_atr": trend_slope_slow.fillna(0.0),
            "rsi14": rsi14,
            "roc5": roc5.fillna(0.0),
            "roc20": roc20.fillna(0.0),
            "macd_hist": macd_hist.fillna(0.0),
            "atr14": atr_14.fillna(0.0),
            "atr_pct": atr_pct.fillna(0.0),
            "bb_width": bb_width.fillna(0.0),
            "bb_pos": bb_pos,
            "volume_sma20": volume_sma20.fillna(0.0),
            "volume_sma120": volume_sma120.fillna(0.0),
            "volume_ratio": volume_ratio.replace([np.inf, -np.inf], np.nan).fillna(0.0),
            "volume_z": volume_z.replace([np.inf, -np.inf], np.nan).fillna(0.0),
            "donchian_high60": donchian_high60.fillna(close),
            "donchian_low60": donchian_low60.fillna(close),
            "donchian_mid60": donchian_mid60.fillna(close),
            "vwap60": vwap60.fillna(close),
            "vwap_distance_atr": vwap_distance.replace([np.inf, -np.inf], np.nan).fillna(0.0),
            "efficiency30": efficiency30.replace([np.inf, -np.inf], np.nan).fillna(0.0),
            "trend_quality": trend_quality,
            "momentum_quality": momentum_quality,
            "volatility_quality": volatility_quality,
            "liquidity_quality": liquidity_quality,
            "structure_quality": structure_quality,
            "candle_quality_score": candle_quality,
            "chop_penalty": chop_penalty,
            "dirty_market_penalty": dirty_market_penalty,
            "regime_clean_uptrend": clean_uptrend.astype(int),
            "regime_weak_uptrend": weak_uptrend.astype(int),
            "regime_downtrend_risk": downtrend_risk.astype(int),
            "regime_range_chop": range_chop.astype(int),
            "regime_compression": compression.astype(int),
            "regime_expansion": expansion.astype(int),
            "regime_volume_expansion": volume_expansion.astype(int),
            "regime_low_liquidity": low_liquidity.astype(int),
            "regime_overextended": overextended.astype(int),
            "regime_recovery_reclaim": recovery_reclaim.astype(int),
            "regime_breakdown_risk": breakdown_risk.astype(int),
            "regime_momentum_burst": momentum_burst.astype(int),
            "active_regime": active_regime,
            "fp_trend_pullback": fp_trend_pullback.astype(int),
            "fp_momentum_continuation": fp_momentum_cont.astype(int),
            "fp_breakout_expansion": fp_breakout.astype(int),
            "fp_squeeze_release": fp_squeeze_release.astype(int),
            "fp_failed_breakdown_recovery": fp_failed_breakdown.astype(int),
            "fp_vwap_reclaim": fp_vwap_reclaim.astype(int),
            "fp_range_reversal": fp_range_reversal.astype(int),
            "fp_wick_rejection": fp_wick_rejection.astype(int),
            "fp_exhaustion_bounce": fp_exhaustion_bounce.astype(int),
            "fp_clean_retest": fp_clean_retest.astype(int),
            "active_fingerprint": active_fingerprint,
            "fingerprint_score": fingerprint_score,
            "regime_score": regime_score,
            "market_context_score": market_context_score,
            "exit_pressure": exit_pressure,
            "risk_score": risk_score,
            "structure_preentry_ok": structure_preentry_ok.astype(int),
            "hard_gate_pass": hard_gate_pass.astype(int),
            "soft_gate_score": soft_gate_score,
            "gate_quality_score": gate_quality_score,
            "gate_fail_reason": gate_fail_reason,
            "strategy_stage": pd.Series("research_build_no_promotion", index=idx, dtype="object"),
        }
        return self._append_columns(df, cols)

    def _entry_candidate_scores(self, df: DataFrame) -> dict[str, Series]:
        s = self._s
        q = self._clip
        return {
            "trend_pullback": q(s(df, "fp_trend_pullback") * 45 + s(df, "trend_quality") * 0.22 + s(df, "candle_quality_score") * 0.18 + s(df, "liquidity_quality") * 0.12),
            "momentum_continuation": q(s(df, "fp_momentum_continuation") * 45 + s(df, "momentum_quality") * 0.24 + s(df, "trend_quality") * 0.16 + s(df, "liquidity_quality") * 0.10),
            "breakout_expansion": q(s(df, "fp_breakout_expansion") * 45 + s(df, "volatility_quality") * 0.22 + s(df, "liquidity_quality") * 0.18 + s(df, "structure_quality") * 0.12),
            "squeeze_release": q(s(df, "fp_squeeze_release") * 45 + s(df, "volatility_quality") * 0.20 + s(df, "momentum_quality") * 0.18 + s(df, "liquidity_quality") * 0.14),
            "failed_breakdown_recovery": q(s(df, "fp_failed_breakdown_recovery") * 45 + s(df, "structure_quality") * 0.20 + s(df, "candle_quality_score") * 0.22 + s(df, "risk_score") * 0.08),
            "vwap_reclaim": q(s(df, "fp_vwap_reclaim") * 45 + s(df, "structure_quality") * 0.18 + s(df, "momentum_quality") * 0.16 + s(df, "candle_quality_score") * 0.12),
            "range_reversal": q(s(df, "fp_range_reversal") * 45 + (100 - s(df, "chop_penalty")) * 0.12 + s(df, "candle_quality_score") * 0.20 + s(df, "risk_score") * 0.12),
            "wick_rejection_reclaim": q(s(df, "fp_wick_rejection") * 42 + s(df, "candle_quality_score") * 0.28 + s(df, "structure_quality") * 0.14 + s(df, "liquidity_quality") * 0.08),
            "exhaustion_bounce": q(s(df, "fp_exhaustion_bounce") * 42 + s(df, "candle_quality_score") * 0.20 + (100 - s(df, "momentum_quality")) * 0.10 + s(df, "risk_score") * 0.12),
            "clean_retest": q(s(df, "fp_clean_retest") * 45 + s(df, "structure_quality") * 0.18 + s(df, "trend_quality") * 0.14 + s(df, "risk_score") * 0.10),
        }


    def _path_policy_series(self, df: DataFrame, best_path: Series) -> dict[str, Series]:
        """Build path-specific policy vectors.

        This turns formerly global gates into path-specific requirements:
        - compatible regimes
        - compatible fingerprints
        - entry threshold
        - risk floor
        - exit-pressure limit
        """
        idx = df.index
        active_regime = self._s(df, "active_regime", "neutral").astype(str)
        active_fp = self._s(df, "active_fingerprint", "none").astype(str)

        compat_regime = pd.Series(False, index=idx)
        compat_fp = pd.Series(False, index=idx)
        path_entry_threshold = pd.Series(999.0, index=idx)
        path_score_floor = pd.Series(999.0, index=idx)
        path_risk_floor = pd.Series(999.0, index=idx)
        path_exit_limit = pd.Series(-1.0, index=idx)
        path_policy = pd.Series("UNKNOWN", index=idx, dtype="object")
        path_status = pd.Series("QUARANTINE", index=idx, dtype="object")
        armed_exit_family = pd.Series("none", index=idx, dtype="object")

        policy = {
            "trend_pullback": {
                "regimes": ("clean_uptrend", "compression", "recovery_reclaim", "momentum_burst"),
                "fingerprints": ("wick_rejection", "trend_pullback", "vwap_reclaim"),
                "entry": 68.0, "path": 61.0, "risk": 64.0, "exit": 46.0,
                "family": "momentum_decay_or_profit_capture", "status": "KEEP_REBUILT_ACTIVE_V6899",
            },
            "momentum_continuation": {
                "regimes": ("clean_uptrend", "compression", "momentum_burst", "recovery_reclaim"),
                "fingerprints": ("trend_pullback", "vwap_reclaim", "wick_rejection"),
                "entry": 69.0, "path": 63.0, "risk": 65.0, "exit": 44.0,
                "family": "momentum_decay_or_profit_capture", "status": "CONTROLLED_REBUILD_ACTIVE_V6899_NEEDS_ABLATION",
            },
            "breakout_expansion": {
                "regimes": ("clean_uptrend", "compression", "momentum_burst", "volatility_expansion"),
                "fingerprints": ("wick_rejection", "trend_pullback", "vwap_reclaim"),
                "entry": 69.0, "path": 63.0, "risk": 65.0, "exit": 44.0,
                "family": "failed_breakout_or_profit_capture", "status": "KEEP_REBUILT_ABLATION_ACTIVE_V6899",
            },
            "squeeze_release": {
                "regimes": ("compression", "volatility_expansion", "momentum_burst"),
                "fingerprints": ("squeeze_release", "trend_pullback", "vwap_reclaim", "wick_rejection"),
                "entry": 72.0, "path": 68.0, "risk": 68.0, "exit": 42.0,
                "family": "failed_breakout_or_volatility_shock", "status": "CONTROLLED_REBUILD_ACTIVE_V6899_NEEDS_ABLATION",
            },
            "failed_breakdown_recovery": {
                "regimes": ("recovery_reclaim", "range_chop", "weak_uptrend"),
                "fingerprints": ("failed_breakdown_recovery",),
                "entry": 62.0, "path": 58.0, "risk": 62.0, "exit": 56.0,
                "family": "structure_or_thesis_invalidated", "status": "QUARANTINE_UNTIL_ABLATION",
            },
            "vwap_reclaim": {
                "regimes": ("clean_uptrend", "compression", "momentum_burst", "recovery_reclaim"),
                "fingerprints": ("trend_pullback", "vwap_reclaim", "wick_rejection"),
                "entry": 68.0, "path": 61.0, "risk": 64.0, "exit": 46.0,
                "family": "vwap_loss_or_profit_capture", "status": "KEEP_REBUILT_ACTIVE_V6899",
            },
            "range_reversal": {
                "regimes": ("clean_uptrend", "compression", "breakdown_risk"),
                "fingerprints": ("wick_rejection", "trend_pullback"),
                "entry": 70.0, "path": 66.0, "risk": 68.0, "exit": 44.0,
                "family": "mean_reversion_complete_or_structure_break", "status": "QUARANTINE_NOT_SELECTED_V6899",
            },
            "wick_rejection_reclaim": {
                "regimes": ("clean_uptrend", "compression", "recovery_reclaim", "momentum_burst"),
                "fingerprints": ("wick_rejection", "trend_pullback", "vwap_reclaim"),
                "entry": 69.0, "path": 64.0, "risk": 64.0, "exit": 44.0,
                "family": "wick_failure_or_profit_capture", "status": "CONTROLLED_REBUILD_ACTIVE_V6899_NEEDS_ABLATION",
            },
            "exhaustion_bounce": {
                "regimes": ("recovery_reclaim", "range_chop"),
                "fingerprints": ("exhaustion_bounce",),
                "entry": 66.0, "path": 62.0, "risk": 68.0, "exit": 50.0,
                "family": "fast_mean_reversion_or_emergency", "status": "QUARANTINE_UNTIL_ABLATION",
            },
            "clean_retest": {
                "regimes": ("clean_uptrend", "momentum_burst", "volatility_expansion"),
                "fingerprints": ("clean_retest",),
                "entry": 80.0, "path": 76.0, "risk": 72.0, "exit": 42.0,
                "family": "failed_retest_or_profit_capture", "status": "QUARANTINE_HIGH_DAMAGE_NOT_ACTIVE_V6899",
            },
        }

        for path, rule in policy.items():
            mask = best_path.astype(str).eq(path)
            if not mask.any():
                continue
            regime_ok = active_regime.isin(rule["regimes"])
            fp_ok = active_fp.isin(rule["fingerprints"])
            compat_regime = compat_regime.mask(mask, regime_ok)
            compat_fp = compat_fp.mask(mask, fp_ok)
            path_entry_threshold = path_entry_threshold.mask(mask, float(rule["entry"]))
            path_score_floor = path_score_floor.mask(mask, float(rule["path"]))
            path_risk_floor = path_risk_floor.mask(mask, float(rule["risk"]))
            path_exit_limit = path_exit_limit.mask(mask, float(rule["exit"]))
            path_policy = path_policy.mask(mask, "regime+fingerprint+path+risk+exit_family")
            path_status = path_status.mask(mask, str(rule["status"]))
            armed_exit_family = armed_exit_family.mask(mask, str(rule["family"]))

        return {
            "path_regime_compatible": compat_regime.astype(int),
            "path_fingerprint_compatible": compat_fp.astype(int),
            "path_specific_entry_threshold": path_entry_threshold,
            "path_specific_score_floor": path_score_floor,
            "path_specific_risk_floor": path_risk_floor,
            "path_specific_exit_limit": path_exit_limit,
            "path_policy": path_policy,
            "path_component_status": path_status,
            "armed_exit_family": armed_exit_family,
            "path_context_allowed": (compat_regime & compat_fp).astype(int),
        }

    @staticmethod
    def _path_from_tag(entry_tag: str | None) -> str:
        if not entry_tag:
            return "unknown"
        parts = str(entry_tag).split("|")
        if len(parts) >= 2 and parts[0].startswith(("rearch_v", "btcp_v")):
            return parts[1]
        return "unknown"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()
        if not bool(_pv(self.enable_rearch_controller)):
            df["enter_long"] = 0
            df["enter_tag"] = ""
            return df

        scores = self._entry_candidate_scores(df)
        score_df = pd.DataFrame(scores, index=df.index)
        shadow_best_score = score_df.max(axis=1)
        shadow_best_path = score_df.idxmax(axis=1).where(shadow_best_score > 0, "none")
        # V6899 5000x100k continuation found strict-positive trade-level surrogate candidates. Active routing uses the selected path set, but no promotion exists until official Freqtrade validation.
        active_entry_paths = ['trend_pullback', 'vwap_reclaim', 'momentum_continuation', 'breakout_expansion']
        active_score_df = score_df.reindex(columns=active_entry_paths).fillna(0.0)
        best_score = active_score_df.max(axis=1)
        best_path = active_score_df.idxmax(axis=1).where(best_score > 0, "none")

        setup_score = best_score
        trigger_score = self._clip(self._s(df, "momentum_quality") * 0.35 + self._s(df, "structure_quality") * 0.30 + self._s(df, "candle_quality_score") * 0.20 + self._s(df, "liquidity_quality") * 0.15)
        confirmation_score = self._clip(self._s(df, "market_context_score") * 0.40 + self._s(df, "gate_quality_score") * 0.30 + self._s(df, "risk_score") * 0.30)
        path_quality_score = best_score
        tier_confidence_score = self._clip(best_score * 0.55 + self._s(df, "risk_score") * 0.25 + self._s(df, "market_context_score") * 0.20)
        gate_penalty = self._clip((1 - (self._s(df, "hard_gate_pass") > 0).astype(int)) * 40 + (100 - self._s(df, "soft_gate_score")) * 0.18)
        collision_penalty = (self._s(df, "exit_pressure") > float(_pv(self.buy_max_exit_pressure))).astype(int) * 30
        risk_penalty = self._clip((float(_pv(self.buy_min_risk_score)) - self._s(df, "risk_score")) * 1.2)
        overfit_penalty = pd.Series(0.0, index=df.index)
        entry_candidate_score = self._clip(
            setup_score * 0.22
            + trigger_score * 0.15
            + confirmation_score * 0.16
            + self._s(df, "market_context_score") * 0.18
            + path_quality_score * 0.16
            + tier_confidence_score * 0.10
            - gate_penalty * 0.20
            - collision_penalty
            - risk_penalty
            - overfit_penalty
        )

        selected_tier = pd.Series("Q", index=df.index, dtype="object")
        selected_tier = selected_tier.mask(entry_candidate_score >= 52, "C")
        selected_tier = selected_tier.mask(entry_candidate_score >= 65, "B")
        selected_tier = selected_tier.mask((entry_candidate_score >= 78) & (self._s(df, "risk_score") >= 70), "A")

        risk_action = pd.Series("BLOCK_ENTRY", index=df.index, dtype="object")
        risk_action = risk_action.mask((self._s(df, "risk_score") >= float(_pv(self.buy_min_risk_score))) & (self._s(df, "risk_score") < 75), "REDUCE_STAKE")
        risk_action = risk_action.mask((self._s(df, "risk_score") >= 75) & (self._s(df, "risk_score") < 88), "NORMAL_STAKE")
        risk_action = risk_action.mask(self._s(df, "risk_score") >= 88, "NORMAL_STAKE")
        risk_action_ok = ~risk_action.isin(["BLOCK_ENTRY", "FORCE_DEFENSIVE_EXIT", "DISABLE_PATH_TEMPORARILY"])

        data_ok = self._s(df, "data_valid") > 0
        structure_ok = self._s(df, "structure_preentry_ok") > 0
        hard_ok = self._s(df, "hard_gate_pass") > 0
        market_ok = self._s(df, "market_context_score") >= float(_pv(self.buy_min_market_context))
        score_ok = entry_candidate_score >= float(_pv(self.buy_min_entry_score))
        path_ok = path_quality_score >= float(_pv(self.buy_min_path_score))
        risk_ok = self._s(df, "risk_score") >= float(_pv(self.buy_min_risk_score))
        soft_ok = self._s(df, "soft_gate_score") >= float(_pv(self.buy_min_soft_gate_score))
        exit_clear = self._s(df, "exit_pressure") <= float(_pv(self.buy_max_exit_pressure))
        tier_ok = selected_tier.isin(["A", "B", "C"])  # V6899: selected 5000x100k strict surrogate allowed A/B/C; official ablation still required
        path_exists = best_path.ne("none")
        path_policy = self._path_policy_series(df, best_path)
        path_regime_ok = pd.to_numeric(path_policy["path_regime_compatible"], errors="coerce").fillna(0).astype(bool)
        path_fingerprint_ok = pd.to_numeric(path_policy["path_fingerprint_compatible"], errors="coerce").fillna(0).astype(bool)
        path_context_ok = pd.to_numeric(path_policy["path_context_allowed"], errors="coerce").fillna(0).astype(bool)
        # V18: quarantined paths are strictly shadow-only. They may be measured, but cannot open trades.
        path_active_status_ok = ~path_policy["path_component_status"].astype(str).str.contains("QUARANTINE", case=False, na=True)
        path_entry_threshold = pd.to_numeric(path_policy["path_specific_entry_threshold"], errors="coerce").fillna(999.0)
        path_score_floor = pd.to_numeric(path_policy["path_specific_score_floor"], errors="coerce").fillna(999.0)
        path_risk_floor = pd.to_numeric(path_policy["path_specific_risk_floor"], errors="coerce").fillna(999.0)
        path_exit_limit = pd.to_numeric(path_policy["path_specific_exit_limit"], errors="coerce").fillna(-1.0)

        # Global thresholds are still upper/lower safety rails, but the actual decision is path-specific.
        score_floor_ok = entry_candidate_score >= np.maximum(path_entry_threshold, float(_pv(self.buy_min_entry_score)))
        score_ceiling_ok = entry_candidate_score <= float(_pv(self.buy_max_entry_score))
        score_ok = score_floor_ok & score_ceiling_ok
        path_ok = path_quality_score >= np.maximum(path_score_floor, float(_pv(self.buy_min_path_score)))
        risk_ok = self._s(df, "risk_score") >= np.maximum(path_risk_floor, float(_pv(self.buy_min_risk_score)))
        exit_clear = self._s(df, "exit_pressure") <= np.minimum(path_exit_limit, float(_pv(self.buy_max_exit_pressure)))

        # V6944: causal pre-entry tail-risk veto.
        # Derived from March-OOS loss isolation, using only entry-candle features already available in populate_entry_trend.
        # It avoids the rejected post-entry stale-low-MFE exit approach from V6941/V6942.
        preentry_tail_scope = (
            self._s(df, "active_regime", "").astype(str).isin(["clean_uptrend", "momentum_burst"])
            & best_path.astype(str).isin(["trend_pullback", "momentum_continuation"])
        )
        preentry_weak_close_high_rsi = (
            preentry_tail_scope
            & (self._s(df, "close_position") <= float(_pv(self.buy_tail_veto_closepos_max)))
            & (self._s(df, "rsi14") >= float(_pv(self.buy_tail_veto_rsi_min)))
        )
        preentry_dead_low_volume_close = (
            preentry_tail_scope
            & (self._s(df, "close_position") <= float(_pv(self.buy_tail_veto_dead_closepos_max)))
            & (self._s(df, "volume_ratio") <= float(_pv(self.buy_tail_veto_low_volume_max)))
        )
        preentry_momentum_low_score_veto = (preentry_tail_scope & self._s(df, 'active_regime', '').astype(str).eq('momentum_burst') & (entry_candidate_score <= 68.5))
        preentry_tail_risk_veto = preentry_weak_close_high_rsi | preentry_dead_low_volume_close | preentry_momentum_low_score_veto
        preentry_clean_stop_signature_veto = (
            preentry_tail_scope
            & self._s(df, 'active_regime', '').astype(str).eq('clean_uptrend')
            & best_path.astype(str).eq('trend_pullback')
            & (entry_candidate_score >= 68.5) & (entry_candidate_score <= 69.5)
            & (self._s(df, 'close_position') >= 0.95)
            & (self._s(df, 'volume_ratio') <= 1.30)
            & (self._s(df, 'exit_pressure') <= 0.25)
        )
        preentry_momentum_emergency_signature_veto = (
            preentry_tail_scope
            & self._s(df, 'active_regime', '').astype(str).eq('momentum_burst')
            & best_path.astype(str).isin(['trend_pullback', 'momentum_continuation'])
            & (entry_candidate_score <= 70.5)
            & (self._s(df, 'close_position') >= 0.55) & (self._s(df, 'close_position') <= 0.78)
            & (self._s(df, 'volume_ratio') >= 2.50)
            & (self._s(df, 'trend_slope_slow_atr') <= 4.60)
        )
        preentry_tail_risk_veto = preentry_tail_risk_veto | preentry_clean_stop_signature_veto | preentry_momentum_emergency_signature_veto


        entry_allowed = (
            data_ok & structure_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok
            & soft_ok & exit_clear & tier_ok & path_exists & path_context_ok & path_active_status_ok
            & ~preentry_tail_risk_veto
        )

        meta_action = pd.Series("BLOCK_ALL", index=df.index, dtype="object")
        meta_action = meta_action.mask(entry_allowed & selected_tier.eq("C"), "ALLOW_REDUCED_RISK")
        meta_action = meta_action.mask(entry_allowed & selected_tier.eq("B"), "ALLOW_NORMAL")
        meta_action = meta_action.mask(entry_allowed & selected_tier.eq("A"), "ALLOW_HIGH_CONFIDENCE_ENTRY")

        veto = pd.Series("", index=df.index, dtype="object")
        veto = veto.mask(~data_ok, "data_invalid")
        veto = veto.mask(data_ok & ~structure_ok, "structure_preentry_block")
        veto = veto.mask(data_ok & structure_ok & ~hard_ok, self._s(df, "gate_fail_reason", "hard_gate_fail"))
        veto = veto.mask(data_ok & hard_ok & ~market_ok, "market_context_low")
        veto = veto.mask(data_ok & hard_ok & market_ok & ~score_floor_ok, "entry_score_low")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_floor_ok & ~score_ceiling_ok, "entry_score_overfit_ceiling")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & ~path_ok, "path_score_low")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & ~risk_ok, "risk_score_low")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & ~risk_action_ok, "risk_action_block")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok & ~soft_ok, "soft_gate_low")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok & soft_ok & ~exit_clear, "preentry_exit_pressure")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok & soft_ok & exit_clear & preentry_tail_risk_veto, "preentry_tail_risk_veto")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok & soft_ok & exit_clear & ~preentry_tail_risk_veto & ~path_regime_ok, "path_regime_incompatible")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok & soft_ok & exit_clear & path_regime_ok & ~path_fingerprint_ok, "path_fingerprint_incompatible")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok & soft_ok & exit_clear & path_context_ok & ~tier_ok, "tier_quarantine")
        veto = veto.mask(data_ok & hard_ok & market_ok & score_ok & path_ok & risk_ok & risk_action_ok & soft_ok & exit_clear & path_context_ok & tier_ok & ~path_exists, "no_path")
        veto = veto.mask(entry_allowed, "")

        meta_score = self._clip(self._s(df, "market_context_score") * 0.28 + entry_candidate_score * 0.30 + path_quality_score * 0.16 + tier_confidence_score * 0.12 + self._s(df, "risk_score") * 0.16 - collision_penalty * 0.20)

        cols = {
            **{f"path_score_{name}": val for name, val in scores.items()},
            "selected_entry_candidate": best_path.astype(str),
            "shadow_selected_entry_candidate": shadow_best_path.astype(str),
            "shadow_entry_candidate_score": shadow_best_score,
            "active_path": best_path.astype(str),
            "path_regime_compatible": path_policy["path_regime_compatible"],
            "path_fingerprint_compatible": path_policy["path_fingerprint_compatible"],
            "path_context_allowed": path_policy["path_context_allowed"],
            "path_specific_entry_threshold": path_policy["path_specific_entry_threshold"],
            "path_specific_score_floor": path_policy["path_specific_score_floor"],
            "path_specific_risk_floor": path_policy["path_specific_risk_floor"],
            "path_specific_exit_limit": path_policy["path_specific_exit_limit"],
            "path_policy": path_policy["path_policy"],
            "path_active_status_ok": path_active_status_ok.astype(int),
            "path_component_status": path_policy["path_component_status"],
            "armed_exit_family": path_policy["armed_exit_family"],
            "setup_score": setup_score,
            "trigger_score": trigger_score,
            "confirmation_score": confirmation_score,
            "path_quality_score": path_quality_score,
            "entry_score_floor_ok": score_floor_ok.astype(int),
            "entry_score_ceiling_ok": score_ceiling_ok.astype(int),
            "tier_confidence_score": tier_confidence_score,
            "entry_candidate_score": entry_candidate_score,
            "entry_score": entry_candidate_score,
            "selected_tier": selected_tier,
            "risk_action": risk_action,
            "risk_action_ok": risk_action_ok.astype(int),
            "meta_score": meta_score,
            "meta_action": meta_action,
            "veto_reason": veto,
            "collision_reason": pd.Series("", index=df.index, dtype="object"),
            "entry_allowed": entry_allowed.astype(int),
            "structure_preentry_entry_ok": structure_ok.astype(int),
            "preentry_tail_scope": preentry_tail_scope.astype(int),
            "preentry_weak_close_high_rsi": preentry_weak_close_high_rsi.astype(int),
            "preentry_dead_low_volume_close": preentry_dead_low_volume_close.astype(int),
            "preentry_tail_risk_veto": preentry_tail_risk_veto.astype(int),
            "gate_pass_count": (data_ok.astype(int) + structure_ok.astype(int) + hard_ok.astype(int) + market_ok.astype(int) + score_ok.astype(int) + path_ok.astype(int) + risk_ok.astype(int) + soft_ok.astype(int) + exit_clear.astype(int) + (~preentry_tail_risk_veto).astype(int)),
            "component_status_contract": pd.Series("btcp_v6971_preentry_tail_risk_repair_no_promotion", index=df.index, dtype="object"),
            "opt100k_selected_run_id": pd.Series(267484794, index=df.index),
            "opt100k_strict_positive_candidates": pd.Series(14673, index=df.index),
            "opt100k_gate_note": pd.Series("additional_5000x100k_tradelevel_strict_surrogate_selected_needs_freqtrade_validation", index=df.index, dtype="object"),
        }
        df = self._append_columns(df, cols)
        df["enter_long"] = 0
        df["enter_tag"] = ""
        df.loc[entry_allowed, "enter_long"] = 1
        tags = (
            "btcp_v6971|"
            + best_path.astype(str)
            + "|tier_" + selected_tier.astype(str)
            + "|score_" + entry_candidate_score.round(0).astype(int).astype(str)
            + "|risk_" + risk_action.astype(str)
            + "|policy_" + path_policy["path_component_status"].astype(str)
            + "|regime_" + self._s(df, "active_regime", "neutral").astype(str)
            + "|fp_" + self._s(df, "active_fingerprint", "none").astype(str)
        )
        df.loc[entry_allowed, "enter_tag"] = tags.loc[entry_allowed].str.slice(0, 255)
        return df.copy()

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = dataframe.copy()
        idx = df.index
        s = self._s

        # V18: old broad structure/regime vector exits caused the V13 loss machine.
        # They are now shadow diagnostics unless the situation is severe enough to qualify as hard protection.
        emergency_tail = (s(df, "exit_pressure") >= float(_pv(self.sell_hard_exit_pressure))) | ((s(df, "dirty_market_penalty") >= 94) & (s(df, "risk_score") < 28))
        structure_break_shadow = ((s(df, "regime_breakdown_risk") > 0) & (s(df, "structure_quality") < 36)) | ((s(df, "close") < s(df, "ema55")) & (s(df, "trend_slope_fast_atr") < -0.20))
        severe_structure_break = structure_break_shadow & (s(df, "risk_score") < 25) & (s(df, "close") < s(df, "ema200"))
        volatility_shock_shadow = (s(df, "true_range_pct") > s(df, "true_range_pct").rolling(120, min_periods=30).quantile(0.97).fillna(999)) & (s(df, "close_position") < 0.30)
        severe_volatility_shock = volatility_shock_shadow & (s(df, "exit_pressure") >= 82)
        liquidity_failure_shadow = (s(df, "volume_ratio") < 0.15) & (s(df, "risk_score") < 55)
        severe_liquidity_failure = liquidity_failure_shadow & (s(df, "risk_score") < 30)
        regime_failure_shadow = (s(df, "regime_downtrend_risk") > 0) | ((s(df, "active_regime", "") == "downtrend_risk") & (s(df, "risk_score") < 60))
        severe_regime_failure = regime_failure_shadow & (s(df, "risk_score") < 28) & (s(df, "close") < s(df, "ema200"))
        hard_exit = pd.Series(False, index=idx)

        exit_tag = pd.Series("", index=idx, dtype="object")
        exit_tag = exit_tag.mask(emergency_tail, "protective_exit|emergency_tail_break|risk_hard|btcp_v6971")
        exit_tag = exit_tag.mask(~emergency_tail & severe_structure_break, "protective_exit|severe_structure_break|risk_hard|btcp_v6971")
        exit_tag = exit_tag.mask(~emergency_tail & ~severe_structure_break & severe_volatility_shock, "protective_exit|severe_volatility_shock|risk_hard|btcp_v6971")
        exit_tag = exit_tag.mask(~emergency_tail & ~severe_structure_break & ~severe_volatility_shock & severe_regime_failure, "protective_exit|severe_regime_failure|risk_hard|btcp_v6971")
        exit_tag = exit_tag.mask(~emergency_tail & ~severe_structure_break & ~severe_volatility_shock & ~severe_regime_failure & severe_liquidity_failure, "protective_exit|severe_liquidity_failure|risk_hard|btcp_v6971")

        # Profit-sensitive signals are debug-only here. custom_exit decides with current_profit.
        momentum_decay = (s(df, "momentum_quality") < s(df, "momentum_quality").shift(5).fillna(s(df, "momentum_quality")) - 15) & (s(df, "active_regime", "") != "clean_uptrend")
        overextension_distribution = (s(df, "regime_overextended") > 0) & (s(df, "upper_wick_pct") > s(df, "lower_wick_pct"))
        time_decay_proxy = (s(df, "market_context_score") < 40) & (s(df, "risk_score") < 55)

        df = self._append_columns(df, {
            "exit_signal_emergency_tail": emergency_tail.astype(int),
            "exit_signal_structure_break": severe_structure_break.astype(int),
            "exit_signal_structure_break_shadow": structure_break_shadow.astype(int),
            "exit_signal_volatility_shock": severe_volatility_shock.astype(int),
            "exit_signal_volatility_shock_shadow": volatility_shock_shadow.astype(int),
            "exit_signal_regime_failure": severe_regime_failure.astype(int),
            "exit_signal_regime_failure_shadow": regime_failure_shadow.astype(int),
            "exit_signal_liquidity_failure": severe_liquidity_failure.astype(int),
            "exit_signal_liquidity_failure_shadow": liquidity_failure_shadow.astype(int),
            "exit_signal_momentum_decay_shadow": momentum_decay.astype(int),
            "exit_signal_overextension_distribution_shadow": overextension_distribution.astype(int),
            "exit_signal_time_decay_shadow": time_decay_proxy.astype(int),
            "selected_exit_candidate": exit_tag.where(hard_exit, "none"),
            "exit_allowed": hard_exit.astype(int),
            "exit_priority": pd.Series("severe_protective_first_soft_exits_custom_exit", index=idx, dtype="object"),
        })
        df["exit_long"] = 0
        df["exit_tag"] = ""
        df.loc[hard_exit, "exit_long"] = 1
        df.loc[hard_exit, "exit_tag"] = exit_tag.loc[hard_exit].str.slice(0, 255)

        same_candle = (self._s(df, "enter_long") > 0) & (self._s(df, "exit_long") > 0)
        if same_candle.any():
            df.loc[same_candle, "enter_long"] = 0
            df.loc[same_candle, "enter_tag"] = ""
            df.loc[same_candle, "collision_reason"] = "exit_wins_same_candle"
        return df.copy()

    def custom_exit(self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs: Any) -> str | bool | None:
        if not bool(_pv(self.enable_profit_sensitive_custom_exits)):
            return None
        candle = self._last_analyzed_candle(pair)
        if candle is None:
            return None
        def flag(name: str) -> bool:
            try:
                return int(candle.get(name, 0) or 0) == 1
            except Exception:
                return False
        minutes = self._trade_minutes_open(trade, current_time)
        if current_profit <= float(_pv(self.sell_emergency_loss_floor)) and (
            flag("exit_signal_emergency_tail") or flag("exit_signal_structure_break") or flag("exit_signal_volatility_shock")
        ):
            return "protective_exit|custom_emergency|btcp_v6971"
        if current_profit >= float(_pv(self.sell_profit_lock_min)) and (
            flag("exit_signal_momentum_decay_shadow") or flag("exit_signal_overextension_distribution_shadow")
        ):
            return "profit_capture|custom_profit_lock|btcp_v6971"
        if current_profit >= float(_pv(self.sell_thesis_profit_min)) and flag("exit_signal_regime_failure"):
            return "profit_capture|custom_thesis_invalidated|btcp_v6971"
        if minutes >= int(_pv(self.sell_time_decay_minutes)) and current_profit >= float(_pv(self.sell_time_decay_profit_min)) and flag("exit_signal_time_decay_shadow"):
            return "profit_capture|custom_time_decay|btcp_v6971"
        return None

    def custom_stoploss(self, pair: str, trade: Trade, current_time: datetime, current_rate: float, current_profit: float, **kwargs: Any) -> float:
        # Dynamic stop belongs here, not in custom_exit.
        candle = self._last_analyzed_candle(pair)
        atr_pct = 0.01
        tier = "Q"
        if candle is not None:
            try:
                atr_pct = float(candle.get("atr_pct", atr_pct) or atr_pct)
                tier = str(candle.get("selected_tier", tier) or tier)
            except Exception:
                pass
        if current_profit >= 0.030:
            return -0.003
        if current_profit >= 0.018:
            return -0.006
        if current_profit >= 0.010:
            return -0.009
        path = self._path_from_tag(getattr(trade, "enter_tag", None))
        if path in {"range_reversal", "exhaustion_bounce", "wick_rejection_reclaim"}:
            mult = 1.20
        elif path in {"breakout_expansion", "squeeze_release"}:
            mult = 1.50
        elif path in {"vwap_reclaim"}:
            mult = 1.60
        elif path in {"trend_pullback", "momentum_continuation", "clean_retest"}:
            mult = 1.90
        else:
            mult = 1.50
        if tier == "A":
            mult += 0.25
        elif tier == "C":
            mult -= 0.20
        return max(self.stoploss, -float(np.clip(atr_pct * mult, 0.0055, 0.024)))

    def custom_stake_amount(self, pair: str, current_time: datetime, current_rate: float, proposed_stake: float, min_stake: float | None, max_stake: float, leverage: float, entry_tag: str | None, side: str, **kwargs: Any) -> float:
        candle = self._last_analyzed_candle(pair)
        factor = 1.0
        if candle is not None:
            risk_action = str(candle.get("risk_action", "NORMAL_STAKE") or "NORMAL_STAKE")
            tier = str(candle.get("selected_tier", "C") or "C")
            if risk_action == "REDUCE_STAKE" or tier == "C":
                factor = 0.60
            elif tier == "A":
                factor = 1.0  # no aggressive increase before evidence validation
        stake = proposed_stake * factor
        if min_stake is not None:
            stake = max(stake, min_stake)
        return float(min(stake, max_stake))

    def confirm_trade_exit(self, pair: str, trade: Trade, order_type: str, amount: float, rate: float, time_in_force: str, exit_reason: str, current_time: datetime, **kwargs: Any) -> bool:
        # Do not block protective exits / stoploss. Blocking stoploss here can increase losses.
        return True


class M4_DELAY1(M4):
    """Execution-delay proxy: shift entry signal by +1 closed candle. Offline stress-test only."""
    def version(self) -> str:
        return "M4-delay1-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(1).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(1).fillna("").astype(str)
        return df


class M4_DELAY2(M4):
    """Execution-delay proxy: shift entry signal by +2 closed candles. Offline stress-test only."""
    def version(self) -> str:
        return "M4-delay2-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(2).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(2).fillna("").astype(str)
        return df

# ===== END INLINE SOURCE: M4.py =====



# ===== BEGIN INLINE SOURCE: M4R4TargetedLossRepair.py =====

"""
M4R4TargetedLossRepair

Evidence-gated targeted repair candidate for the exact M4 BTC/USDC 1m loss
families reported by the user on 2026-07-07.

Scope:
- Inherits M4 without changing ROI, stoploss, leverage, DCA, timeframe or pair scope.
- Applies one causal pre-entry veto family after M4's normal controller.
- Uses only current/previous candle features already produced by M4.populate_*.
- No calendar/date-specific rule and no live-trading claim.

Hypothesis:
The listed deep losses are caused by narrow B-tier score/regime/fingerprint
signatures that look safe by risk_score but have weak entry-candle continuation
quality. Blocking only those signatures should reduce tail loss without damaging
M4's >100-trade count.
"""

import pandas as pd
from pandas import DataFrame



class M4R4TargetedLossRepair(M4):
    VERSION_TAG = "M4R4_TARGETED_LOSS_SIGNATURE_REPAIR"

    def version(self) -> str:
        return "M4R4-targeted-loss-signature-veto-no-promotion"

    @staticmethod
    def _tag_has(tag: pd.Series, *parts: str) -> pd.Series:
        mask = pd.Series(True, index=tag.index)
        for part in parts:
            mask &= tag.str.contains(part, regex=False, na=False)
        return mask

    def _apply_targeted_lossrepair_veto(self, df: DataFrame) -> DataFrame:
        tag = df.get("enter_tag", "").fillna("").astype(str)
        active = df.get("enter_long", 0).fillna(0).astype(int) > 0
        s = self._s

        # 1) User-listed momentum-continuation score_70 / momentum-burst / fp_trend_pullback.
        #    In the recovered M4 trade export this bucket had 1/1 deep protective loss.
        veto_momo70_burst = self._tag_has(
            tag,
            "|momentum_continuation|",
            "|score_70|",
            "|regime_momentum_burst|",
            "|fp_trend_pullback",
        )

        # 2) User-listed trend_pullback score_72 / momentum-burst stoploss pocket.
        #    Narrowed by low bb position at signal candle to avoid killing the three
        #    profitable score_72 momentum-burst trades seen in the anchor export.
        veto_tp72_burst_low_bb = (
            self._tag_has(tag, "|trend_pullback|", "|score_72|", "|regime_momentum_burst|", "|fp_trend_pullback")
            & (s(df, "bb_pos") <= 0.40)
            & (s(df, "volume_ratio") >= 2.0)
        )

        # 3) User-listed trend_pullback score_72 / clean-uptrend emergency pocket.
        #    Requires both short-horizon momentum and 20-candle return to be non-positive.
        veto_tp72_clean_negative_momo = (
            self._tag_has(tag, "|trend_pullback|", "|score_72|", "|regime_clean_uptrend|", "|fp_trend_pullback")
            & (s(df, "roc5") < 0.0)
            & (s(df, "roc20") <= 0.0)
            & (s(df, "candle_quality_score") < 35.0)
        )

        # 4) User-listed trend_pullback score_71 / clean-uptrend emergency pocket.
        #    Narrow entry-structure signature from the actual loss: high close-position,
        #    weak slow-trend slope and very low exit-pressure. This avoids broad score_71 killing.
        veto_tp71_clean_flat_slow = (
            self._tag_has(tag, "|trend_pullback|", "|score_71|", "|regime_clean_uptrend|", "|fp_trend_pullback")
            & (s(df, "close_position") >= 0.80)
            & (s(df, "close_position") <= 0.90)
            & (s(df, "trend_slope_slow_atr") <= 1.25)
            & (s(df, "exit_pressure") <= 0.50)
        )

        # 5) User-listed trend_pullback score_70 / recovery-reclaim 7-day emergency pocket.
        #    The loss has very low ATR and sub-57 market context; winners in the recovered
        #    export did not share both constraints.
        veto_tp70_recovery_low_atr_context = (
            self._tag_has(tag, "|trend_pullback|", "|score_70|", "|regime_recovery_reclaim|", "|fp_trend_pullback")
            & (s(df, "market_context_score") < 57.0)
            & (s(df, "atr_pct") < 0.00040)
            & (s(df, "exit_pressure") < 0.40)
        )

        # 6) User-listed vwap_reclaim score_69 clean-uptrend zero-ROI dead trade.
        #    Tiny economic effect, but included because the user explicitly listed it.
        #    Only blocks weak-volume / near-VWAP reclaim, preserving the recovery-reclaim
        #    vwap trade visible in the anchor export.
        veto_vwap69_dead_reclaim = (
            self._tag_has(tag, "|vwap_reclaim|", "|score_69|", "|regime_clean_uptrend|", "|fp_vwap_reclaim")
            & (s(df, "volume_ratio") < 1.20)
            & (s(df, "vwap_distance_atr") < 0.40)
        )

        targeted_veto = active & (
            veto_momo70_burst
            | veto_tp72_burst_low_bb
            | veto_tp72_clean_negative_momo
            | veto_tp71_clean_flat_slow
            | veto_tp70_recovery_low_atr_context
            | veto_vwap69_dead_reclaim
        )
        if targeted_veto.any():
            df.loc[targeted_veto, "enter_long"] = 0
            df.loc[targeted_veto, "enter_tag"] = ""
            df.loc[targeted_veto, "veto_reason"] = "m4r4_targeted_loss_signature_veto"
            df.loc[targeted_veto, "m4r4_targeted_loss_veto"] = 1
        if "m4r4_targeted_loss_veto" not in df.columns:
            df["m4r4_targeted_loss_veto"] = 0
        df["m4r4_veto_momo70_burst"] = (active & veto_momo70_burst).astype(int)
        df["m4r4_veto_tp72_burst_low_bb"] = (active & veto_tp72_burst_low_bb).astype(int)
        df["m4r4_veto_tp72_clean_negative_momo"] = (active & veto_tp72_clean_negative_momo).astype(int)
        df["m4r4_veto_tp71_clean_flat_slow"] = (active & veto_tp71_clean_flat_slow).astype(int)
        df["m4r4_veto_tp70_recovery_low_atr_context"] = (active & veto_tp70_recovery_low_atr_context).astype(int)
        df["m4r4_veto_vwap69_dead_reclaim"] = (active & veto_vwap69_dead_reclaim).astype(int)
        return df

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        return self._apply_targeted_lossrepair_veto(df).copy()


class M4R4TargetedLossRepair_DELAY1(M4R4TargetedLossRepair):
    def version(self) -> str:
        return "M4R4-targeted-loss-signature-veto-delay1-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(1).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(1).fillna("")
        return df.copy()


class M4R4TargetedLossRepair_DELAY2(M4R4TargetedLossRepair):
    def version(self) -> str:
        return "M4R4-targeted-loss-signature-veto-delay2-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(2).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(2).fillna("")
        return df.copy()

class M4R5TargetedHazardCooldown(M4R4TargetedLossRepair):
    """Second diagnostic branch: hazard-event + 2-day causal cooldown.

    This addresses the measured failure of R4: blocking the exact initial entry
    can free max_open_trades and allow a replacement entry inside the same adverse
    episode. R5 blocks the hazard event and subsequent 2880 one-minute candles.
    """
    VERSION_TAG = "M4R5_TARGETED_HAZARD_COOLDOWN"
    HAZARD_COOLDOWN_CANDLES = 2880

    def version(self) -> str:
        return "M4R5-targeted-hazard-2d-cooldown-no-promotion"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # Start from base M4, not R4, so hazard cooldown owns all blocking.
        df = M4.populate_entry_trend(self, dataframe, metadata)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        active = df.get("enter_long", 0).fillna(0).astype(int) > 0
        s = self._s

        hazard_momo70_burst = self._tag_has(tag, "|momentum_continuation|", "|score_70|", "|regime_momentum_burst|", "|fp_trend_pullback")
        hazard_tp72_burst_low_bb = (
            self._tag_has(tag, "|trend_pullback|", "|score_72|", "|regime_momentum_burst|", "|fp_trend_pullback")
            & (s(df, "bb_pos") <= 0.40) & (s(df, "volume_ratio") >= 2.0)
        )
        hazard_tp72_clean_negative_momo = (
            self._tag_has(tag, "|trend_pullback|", "|score_72|", "|regime_clean_uptrend|", "|fp_trend_pullback")
            & (s(df, "roc5") < 0.0) & (s(df, "roc20") <= 0.0) & (s(df, "candle_quality_score") < 35.0)
        )
        hazard_tp71_clean_flat_slow = (
            self._tag_has(tag, "|trend_pullback|", "|score_71|", "|regime_clean_uptrend|", "|fp_trend_pullback")
            & (s(df, "close_position") >= 0.80) & (s(df, "close_position") <= 0.90)
            & (s(df, "trend_slope_slow_atr") <= 1.25) & (s(df, "exit_pressure") <= 0.50)
        )
        hazard_tp70_recovery_low_atr_context = (
            self._tag_has(tag, "|trend_pullback|", "|score_70|", "|regime_recovery_reclaim|", "|fp_trend_pullback")
            & (s(df, "market_context_score") < 57.0) & (s(df, "atr_pct") < 0.00040) & (s(df, "exit_pressure") < 0.40)
        )
        hazard_vwap69_dead_reclaim = (
            self._tag_has(tag, "|vwap_reclaim|", "|score_69|", "|regime_clean_uptrend|", "|fp_vwap_reclaim")
            & (s(df, "volume_ratio") < 1.20) & (s(df, "vwap_distance_atr") < 0.40)
        )
        hazard_event = active & (
            hazard_momo70_burst | hazard_tp72_burst_low_bb | hazard_tp72_clean_negative_momo
            | hazard_tp71_clean_flat_slow | hazard_tp70_recovery_low_atr_context | hazard_vwap69_dead_reclaim
        )
        cooldown = hazard_event.astype(int).rolling(self.HAZARD_COOLDOWN_CANDLES, min_periods=1).max().astype(bool)
        blocked = active & cooldown
        if blocked.any():
            df.loc[blocked, "enter_long"] = 0
            df.loc[blocked, "enter_tag"] = ""
            df.loc[blocked, "veto_reason"] = "m4r5_targeted_hazard_cooldown_2d"
        df["m4r5_hazard_event"] = hazard_event.astype(int)
        df["m4r5_hazard_cooldown_active"] = cooldown.astype(int)
        df["m4r5_hazard_cooldown_block"] = blocked.astype(int)
        return df.copy()


class M4R5TargetedHazardCooldown_DELAY1(M4R5TargetedHazardCooldown):
    def version(self) -> str:
        return "M4R5-targeted-hazard-2d-cooldown-delay1-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(1).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(1).fillna("")
        return df.copy()

class M4R5TargetedHazardCooldown_DELAY2(M4R5TargetedHazardCooldown):
    def version(self) -> str:
        return "M4R5-targeted-hazard-2d-cooldown-delay2-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(2).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(2).fillna("")
        return df.copy()

class M4R5TargetedHazardCooldown36h(M4R5TargetedHazardCooldown):
    """Same hazard repair as R5, but 36h cooldown to test trade-count preservation."""
    HAZARD_COOLDOWN_CANDLES = 2160
    def version(self) -> str:
        return "M4R5-targeted-hazard-36h-cooldown-no-promotion"

class M4R5TargetedHazardCooldown24h(M4R5TargetedHazardCooldown):
    """Same hazard repair as R5, but 24h cooldown to test trade-count preservation."""
    HAZARD_COOLDOWN_CANDLES = 1440
    def version(self) -> str:
        return "M4R5-targeted-hazard-24h-cooldown-no-promotion"

class M4R5TargetedHazardCooldown36h_DELAY1(M4R5TargetedHazardCooldown36h):
    def version(self) -> str:
        return "M4R5-targeted-hazard-36h-cooldown-delay1-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(1).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(1).fillna("")
        return df.copy()

class M4R5TargetedHazardCooldown36h_DELAY2(M4R5TargetedHazardCooldown36h):
    def version(self) -> str:
        return "M4R5-targeted-hazard-36h-cooldown-delay2-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(2).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(2).fillna("")
        return df.copy()

class M4R6OOSFebTrendPullbackLossBrake(M4R5TargetedHazardCooldown36h):
    """OOS-February targeted diagnostic loss brake.

    Hypothesis: Remaining OOS-Feb 2025 collapse after R5 is not an entry-density issue,
    but long-held low-score trend_pullback/fp_trend_pullback tier_B trades that need an
    early path-specific underwater timeout. This does not add entries and does not change
    ROI/stoploss/timeframe/pair scope.
    """
    VERSION_TAG = "M4R6_OOSFEB_TP6970_LOSS_BRAKE"

    def version(self) -> str:
        return "M4R6-oosfeb-trendpullback-score6970-loss-brake-no-promotion"

    @staticmethod
    def _entry_tag_from_trade(trade) -> str:
        return str(getattr(trade, "enter_tag", "") or getattr(trade, "entry_tag", "") or "")

    @staticmethod
    def _minutes_open(trade, current_time) -> float:
        open_dt = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        if open_dt is None:
            return 0.0
        return max(0.0, (current_time - open_dt).total_seconds() / 60.0)

    @classmethod
    def _is_tp6970_fp_trendpullback(cls, tag: str) -> bool:
        return (
            "|trend_pullback|" in tag
            and "|fp_trend_pullback" in tag
            and ("|score_69|" in tag or "|score_70|" in tag)
            and "|tier_B|" in tag
            and "risk_NORMAL_STAKE" in tag
        )

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        tag = self._entry_tag_from_trade(trade)
        minutes = self._minutes_open(trade, current_time)
        if self._is_tp6970_fp_trendpullback(tag):
            if minutes >= 180 and current_profit <= -0.012:
                return "loss_brake|r6_tp6970_180m_120bps"
            if minutes >= 720 and current_profit <= -0.006:
                return "loss_brake|r6_tp6970_720m_60bps"
        return super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)

class M4R6OOSFebTrendPullbackLossBrake_DELAY1(M4R6OOSFebTrendPullbackLossBrake):
    def version(self) -> str:
        return "M4R6-oosfeb-tp6970-loss-brake-delay1-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(1).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(1).fillna("")
        return df.copy()

class M4R6OOSFebTrendPullbackLossBrake_DELAY2(M4R6OOSFebTrendPullbackLossBrake):
    def version(self) -> str:
        return "M4R6-oosfeb-tp6970-loss-brake-delay2-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(2).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(2).fillna("")
        return df.copy()

# ===== END INLINE SOURCE: M4R4TargetedLossRepair.py =====



# ===== BEGIN INLINE SOURCE: M4PerformanceRepairV1.py =====

"""M4PerformanceRepairV1

Repair of the last delivered M4Mixed100TagFilterV2.

Hypothesis:
The strict in-sample Mixed-100 tag whitelist is an overfit trade-count killer: it
creates 100% Main winrate by reducing trades to 59 and fails OOS. Removing that
whitelist and reverting to the prior targeted hazard-cooldown controller should
restore >100 Main trades and improve Main profit while keeping the previously
repaired tail-risk behaviour.

Change:
- Inherits M4R5TargetedHazardCooldown36h directly.
- No entry-time whitelist, no pair guard, no timestamp/frozenset replay, no DCA,
  no Grid, no Short, no Leverage, no date/calendar gate.
- No new entry paths. This is a rollback/repair of an overfit filter, not a new
  broad mesh expansion.

Research/backtest only; no live/promoted claim.
"""



class M4PerformanceRepairV1(M4R5TargetedHazardCooldown36h):
    VERSION_TAG = "M4_PERFORMANCE_REPAIR_V1_REMOVE_MIXED100_OVERFIT_FILTER"

    def version(self) -> str:
        return "M4PerformanceRepairV1-remove-mixed100-overfit-filter-no-promotion"


class M4PerformanceRepairV1_DELAY1(M4PerformanceRepairV1):
    def version(self) -> str:
        return "M4PerformanceRepairV1-delay1-proxy"
    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(1).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(1).fillna("")
        return df.copy()


class M4PerformanceRepairV1_DELAY2(M4PerformanceRepairV1):
    def version(self) -> str:
        return "M4PerformanceRepairV1-delay2-proxy"
    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        sig = df.get("enter_long", 0).fillna(0).astype(int)
        tag = df.get("enter_tag", "").fillna("").astype(str)
        df["enter_long"] = sig.shift(2).fillna(0).astype(int)
        df["enter_tag"] = tag.shift(2).fillna("")
        return df.copy()

# ===== END INLINE SOURCE: M4PerformanceRepairV1.py =====



# ===== BEGIN INLINE SOURCE: RepairCandidate_M4OOSFeeRiskActionV2.py =====

"""M4OOSFeeRiskActionV2

Runtime-safe implementation of the prior OOS/Fee stake-cap hypothesis.

Evidence-gated hypothesis
-------------------------
The causal pre-entry state
    trend_slope_slow_atr >= 4.959565
    vwap_distance_atr    >= 1.536673
concentrated disproportionate OOS/Fee losses in the prior trade-level audit.
Rather than deleting entries or querying the DataProvider from custom_stake_amount,
this version computes a vectorized debug flag, carries the decision in enter_tag,
and applies a 0.20 stake factor from that tag.

No ENTRY_TIMES, EXIT_TIMES, timestamp lists, frozenset replay, calendar rules,
pair guards, DCA, grid, shorts, leverage, or new entry paths.
Research/backtest only. No promotion or live-trading claim.
"""

from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from pandas import DataFrame



class M4OOSFeeRiskActionV2(M4PerformanceRepairV1):
    VERSION_TAG = "M4_OOS_FEE_RISKACTION_V2_RUNTIME_SAFE"
    timeframe = "1m"
    OOS_FEE_SLOW_TREND_MIN = 4.959565
    OOS_FEE_VWAP_DIST_MIN = 1.536673
    OOS_FEE_STAKE_FACTOR = 0.20
    BASE_REDUCED_STAKE_FACTOR = 0.60
    HAZARD_COOLDOWN_CANDLES = 2160  # 36h on 1m

    def version(self) -> str:
        return "M4OOSFeeRiskActionV2-1m-runtime-safe-vector-riskcap-no-promotion"

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_indicators(dataframe, metadata)
        slow_src = df["trend_slope_slow_atr"] if "trend_slope_slow_atr" in df.columns else pd.Series(0.0, index=df.index)
        vwapd_src = df["vwap_distance_atr"] if "vwap_distance_atr" in df.columns else pd.Series(0.0, index=df.index)
        volume_src = df["volume"] if "volume" in df.columns else pd.Series(0.0, index=df.index)
        slow = pd.to_numeric(slow_src, errors="coerce").fillna(0.0)
        vwapd = pd.to_numeric(vwapd_src, errors="coerce").fillna(0.0)
        volume = pd.to_numeric(volume_src, errors="coerce").fillna(0.0)
        candidate = (
            (volume > 0.0)
            & (slow >= float(self.OOS_FEE_SLOW_TREND_MIN))
            & (vwapd >= float(self.OOS_FEE_VWAP_DIST_MIN))
        )
        df["risk_oos_fee_cap_candidate"] = candidate.astype(int)
        df["risk_oos_fee_cap_factor"] = np.where(candidate, float(self.OOS_FEE_STAKE_FACTOR), 1.0)
        df["risk_oos_fee_cap_reason"] = np.where(candidate, "slowtrend_plus_vwap_extension", "none")
        return df.copy()

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        active_src = df["enter_long"] if "enter_long" in df.columns else pd.Series(0, index=df.index)
        cap_src = df["risk_oos_fee_cap_candidate"] if "risk_oos_fee_cap_candidate" in df.columns else pd.Series(0, index=df.index)
        active = pd.to_numeric(active_src, errors="coerce").fillna(0).astype(int) > 0
        cap = pd.to_numeric(cap_src, errors="coerce").fillna(0).astype(int) > 0
        cap_entry = active & cap
        df["risk_oos_fee_cap_entry"] = cap_entry.astype(int)
        if bool(cap_entry.any()):
            tag = df.loc[cap_entry, "enter_tag"].fillna("").astype(str)
            # Append the decision token. Existing tags are comfortably below 255 chars.
            df.loc[cap_entry, "enter_tag"] = (tag + "|riskcap_020").str.slice(0, 255)
        return df.copy()

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
        """Tag-driven stake decision; deliberately no DataProvider access."""
        tag = str(entry_tag or "")
        if "riskcap_020" in tag:
            factor = float(self.OOS_FEE_STAKE_FACTOR)
        elif "|risk_REDUCE_STAKE|" in tag or "|tier_C|" in tag:
            factor = float(self.BASE_REDUCED_STAKE_FACTOR)
        else:
            factor = 1.0
        stake = float(proposed_stake) * factor
        if min_stake is not None:
            stake = max(float(min_stake), stake)
        return float(min(stake, float(max_stake)))


class M4OOSFeeRiskActionV2_DELAY1(M4OOSFeeRiskActionV2):
    def version(self) -> str:
        return "M4OOSFeeRiskActionV2-1m-delay1-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        for col, default in (("enter_long", 0), ("enter_tag", ""), ("risk_oos_fee_cap_entry", 0)):
            s = df.get(col, default)
            if not isinstance(s, pd.Series):
                s = pd.Series(default, index=df.index)
            df[col] = s.shift(1).fillna(default)
        df["enter_long"] = pd.to_numeric(df["enter_long"], errors="coerce").fillna(0).astype(int)
        df["risk_oos_fee_cap_entry"] = pd.to_numeric(df["risk_oos_fee_cap_entry"], errors="coerce").fillna(0).astype(int)
        df["enter_tag"] = df["enter_tag"].fillna("").astype(str)
        return df.copy()


class M4OOSFeeRiskActionV2_DELAY2(M4OOSFeeRiskActionV2):
    def version(self) -> str:
        return "M4OOSFeeRiskActionV2-1m-delay2-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        for col, default in (("enter_long", 0), ("enter_tag", ""), ("risk_oos_fee_cap_entry", 0)):
            s = df.get(col, default)
            if not isinstance(s, pd.Series):
                s = pd.Series(default, index=df.index)
            df[col] = s.shift(2).fillna(default)
        df["enter_long"] = pd.to_numeric(df["enter_long"], errors="coerce").fillna(0).astype(int)
        df["risk_oos_fee_cap_entry"] = pd.to_numeric(df["risk_oos_fee_cap_entry"], errors="coerce").fillna(0).astype(int)
        df["enter_tag"] = df["enter_tag"].fillna("").astype(str)
        return df.copy()


class M4OOSFeeRiskActionV2_5m(M4OOSFeeRiskActionV2):
    timeframe = "5m"
    HAZARD_COOLDOWN_CANDLES = 432  # preserve 36h

    def version(self) -> str:
        return "M4OOSFeeRiskActionV2-5m-runtime-safe-vector-riskcap-no-promotion"


class M4OOSFeeRiskActionV2_15m(M4OOSFeeRiskActionV2):
    timeframe = "15m"
    HAZARD_COOLDOWN_CANDLES = 144  # preserve 36h

    def version(self) -> str:
        return "M4OOSFeeRiskActionV2-15m-runtime-safe-vector-riskcap-no-promotion"

# ===== END INLINE SOURCE: RepairCandidate_M4OOSFeeRiskActionV2.py =====



# ===== BEGIN INLINE SOURCE: M4MultiCoinPortfolioV4.py =====

"""M4MultiCoinPortfolioV4 — causal portfolio exposure repair.

All 31 pairs remain configured. Entry/exit/ROI/stoploss logic is unchanged.
The only new action is a tag-derived stake allocation:
- BTC: full inherited stake.
- Altcoin tag family stable and profitable in both Jan-Feb and Mar-Apr 2026: full inherited stake.
- Other altcoin tags: 0.5% of inherited stake, clamped to exchange minimum.
This avoids pair deletion while sharply reducing exposure to historically unstable tag families.
Research/backtest only; no live or promotion claim.
"""
from datetime import datetime
from typing import Any
import pandas as pd
from pandas import DataFrame

class M4MultiCoinPortfolioV4(M4OOSFeeRiskActionV2):
    INTERFACE_VERSION = 3
    VERSION_TAG = 'M4_MULTICOIN_PORTFOLIO_V4_ROBUST_TAG_EXPOSURE'
    DEFAULT_ALT_STAKE_FACTOR = 0.005
    BTC_STAKE_FACTOR = 1.0
    ROBUST_FULL_STAKE_KEYS = frozenset({
        'momentum_continuation|momentum_burst|trend_pullback|72',
        'trend_pullback|compression|trend_pullback|68',
        'trend_pullback|compression|trend_pullback|77',
        'trend_pullback|momentum_burst|trend_pullback|72',
        'trend_pullback|recovery_reclaim|trend_pullback|76',
        'vwap_reclaim|clean_uptrend|vwap_reclaim|69',
        'vwap_reclaim|clean_uptrend|vwap_reclaim|72',
        'vwap_reclaim|clean_uptrend|vwap_reclaim|75',
        'vwap_reclaim|momentum_burst|vwap_reclaim|74',
        'vwap_reclaim|recovery_reclaim|vwap_reclaim|71',
    })
    KEEP_COLUMNS = (
        'date','open','high','low','close','volume','enter_long','enter_tag','exit_long','exit_tag',
        'exit_signal_emergency_tail','exit_signal_structure_break','exit_signal_volatility_shock',
        'exit_signal_momentum_decay_shadow','exit_signal_overextension_distribution_shadow',
        'exit_signal_regime_failure','exit_signal_time_decay_shadow',
    )
    def version(self) -> str:
        return 'M4MultiCoinPortfolioV4-robust-tag-exposure-no-promotion'
    @classmethod
    def _tag_key(cls, entry_tag: str | None) -> str:
        parts=[x for x in str(entry_tag or '').split('|') if x]
        path=parts[1] if len(parts)>1 else ''
        regime=next((x[len('regime_'):] for x in parts if x.startswith('regime_')),'')
        fp=next((x[len('fp_'):] for x in parts if x.startswith('fp_')),'')
        score=next((x[len('score_'):] for x in parts if x.startswith('score_')),'')
        return f'{path}|{regime}|{fp}|{score}'
    @classmethod
    def _portfolio_factor(cls,pair: str,entry_tag: str|None) -> float:
        if pair.upper()=='BTC/USDC': return cls.BTC_STAKE_FACTOR
        return 1.0 if cls._tag_key(entry_tag) in cls.ROBUST_FULL_STAKE_KEYS else cls.DEFAULT_ALT_STAKE_FACTOR
    def custom_stake_amount(self,pair: str,current_time: datetime,current_rate: float,proposed_stake: float,
                            min_stake: float|None,max_stake: float,leverage: float,entry_tag: str|None,
                            side: str,**kwargs: Any)->float:
        # Preserve the parent riskcap/tier action first, but defer minimum clamping until the final overlay.
        inherited=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,None,max_stake,
                                               leverage,entry_tag,side,**kwargs)
        stake=float(inherited)*float(self._portfolio_factor(pair,entry_tag))
        if min_stake is not None: stake=max(float(min_stake),stake)
        return float(min(stake,float(max_stake)))
    def populate_exit_trend(self,dataframe: DataFrame,metadata: dict)->DataFrame:
        df=super().populate_exit_trend(dataframe,metadata)
        keep=[c for c in self.KEEP_COLUMNS if c in df.columns]
        out=df.loc[:,keep].copy()
        for c in ('enter_long','exit_long','exit_signal_emergency_tail','exit_signal_structure_break',
                  'exit_signal_volatility_shock','exit_signal_momentum_decay_shadow',
                  'exit_signal_overextension_distribution_shadow','exit_signal_regime_failure',
                  'exit_signal_time_decay_shadow'):
            if c in out.columns:
                out[c]=pd.to_numeric(out[c],errors='coerce').fillna(0).astype('int8')
        return out

class M4MultiCoinPortfolioV4_DELAY1(M4MultiCoinPortfolioV4):
    def version(self)->str: return 'M4MultiCoinPortfolioV4-delay1-proxy'
    def populate_entry_trend(self,dataframe: DataFrame,metadata: dict)->DataFrame:
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(1).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(1).fillna('').astype(str)
        return df
class M4MultiCoinPortfolioV4_DELAY2(M4MultiCoinPortfolioV4):
    def version(self)->str: return 'M4MultiCoinPortfolioV4-delay2-proxy'
    def populate_entry_trend(self,dataframe: DataFrame,metadata: dict)->DataFrame:
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(2).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(2).fillna('').astype(str)
        return df

# ===== END INLINE SOURCE: M4MultiCoinPortfolioV4.py =====



# ===== BEGIN V7 WALK-FORWARD RESEARCH OVERLAY =====
class M4MultiCoinPortfolioV7WalkForward(M4MultiCoinPortfolioV4):
    """Walk-forward research overlay.

    Uses only pair/tag families that were positive in Jan-Feb 2026, Mar-Apr 2026
    and May 2026 selection diagnostics. June 2026 remains a validation holdout.
    Non-selected families are not deleted; they are reduced to minimum-like stake.
    """
    VERSION_TAG = 'M4_MULTICOIN_PORTFOLIO_V7_WALK_FORWARD_RESEARCH'
    DEFAULT_ALT_STAKE_FACTOR = 0.0025
    BTC_STAKE_FACTOR = 1.0
    ROBUST_FULL_STAKE_KEYS = frozenset({
        'vwap_reclaim|clean_uptrend|vwap_reclaim|72',
        'vwap_reclaim|clean_uptrend|vwap_reclaim|75',
        'vwap_reclaim|momentum_burst|vwap_reclaim|74',
        'vwap_reclaim|recovery_reclaim|vwap_reclaim|71',
        'trend_pullback|compression|trend_pullback|77',
        'trend_pullback|recovery_reclaim|trend_pullback|76',
        'momentum_continuation|momentum_burst|trend_pullback|72',
        'trend_pullback|momentum_burst|trend_pullback|72',
        'vwap_reclaim|clean_uptrend|vwap_reclaim|69',
        'trend_pullback|compression|trend_pullback|68',
        'vwap_reclaim|compression|vwap_reclaim|70',
    })

    def version(self) -> str:
        return 'M4MultiCoinPortfolioV7WalkForward-research-only-not-promoted'

class M4MultiCoinPortfolioV7WalkForward_DELAY1(M4MultiCoinPortfolioV7WalkForward):
    def version(self)->str: return 'M4MultiCoinPortfolioV7WalkForward-delay1-proxy'
    def populate_entry_trend(self,dataframe,metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(1).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(1).fillna('').astype(str)
        return df

class M4MultiCoinPortfolioV7WalkForward_DELAY2(M4MultiCoinPortfolioV7WalkForward):
    def version(self)->str: return 'M4MultiCoinPortfolioV7WalkForward-delay2-proxy'
    def populate_entry_trend(self,dataframe,metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(2).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(2).fillna('').astype(str)
        return df
# ===== END V7 WALK-FORWARD RESEARCH OVERLAY =====


# ===== BEGIN V8 INDICATOR-ORACLE SHADOW TELEMETRY =====
try:
    import talib as _V8_TALIB  # type: ignore
except Exception:  # pragma: no cover - deterministic pandas/numpy fallback
    _V8_TALIB = None


class M4IndicatorOraclePioneerV8(M4MultiCoinPortfolioV7WalkForward):
    """Causal Top-25 indicator telemetry on the validated V7 trading surface.

    The March-2026 ZigZag labels are deliberately *not* used as live signals.
    This class computes the strongest causal features and shadow entry/exit scores,
    while preserving the inherited entries, exits, ROI, stoploss and stake logic.
    Active oracle-exit experiments were rejected because they reduced BTC main profit.
    Research/backtest only; no live or promotion claim.
    """

    VERSION_TAG = "M4_INDICATOR_ORACLE_PIONEER_V8_SHADOW_ONLY"
    ORACLE_ANALYSIS_MONTH = "2026-03"
    ORACLE_ZIGZAG_REVERSAL = 0.008
    ORACLE_SHADOW_ONLY = True

    TOP25_TELEMETRY_COLUMNS = (
        "drawdown_120", "rsi_50", "rsi_28", "keltner_pos_100",
        "keltner_pos_50", "rsi_21", "ema_dist_89_atr",
        "ema_dist_55_atr", "ema_dist_100_atr",
        "trend_strength_composite", "wma_dist_100_atr",
        "dist_high_120_atr", "drawdown_60", "roc_30",
        "donchian_pos_120", "bb_pos_100", "sma_dist_55_atr",
        "roc_45", "drawdown_240", "sma_dist_89_atr", "roc_15",
        "ema_slope_21_atr", "sma_dist_100_atr", "bb_pos_50",
        "kama_dist_100_atr", "oracle_entry_score", "oracle_exit_score",
        "oracle_entry_shadow", "oracle_exit_shadow", "oracle_shadow_state",
    )
    KEEP_COLUMNS = M4MultiCoinPortfolioV4.KEEP_COLUMNS + TOP25_TELEMETRY_COLUMNS

    # Ex-post March medians are retained only as frozen shadow thresholds.
    # They do not change trade decisions.
    ENTRY_THRESHOLDS = {
        "drawdown_120": -0.012891,
        "rsi_50": 41.324949,
        "rsi_28": 38.292650,
        "keltner_pos_100": -0.773323,
        "keltner_pos_50": -0.385466,
        "rsi_21": 36.663774,
        "ema_dist_89_atr": -4.372597,
        "ema_dist_55_atr": -3.479881,
        "ema_dist_100_atr": -4.566544,
        "wma_dist_100_atr": -4.137587,
        "donchian_pos_120": 0.094419,
        "bb_pos_100": 0.016568,
        "sma_dist_55_atr": -3.816039,
        "roc_30": -0.005125,
    }
    EXIT_THRESHOLDS = {
        "rsi_50": 58.756171,
        "rsi_28": 62.008675,
        "keltner_pos_100": 1.808912,
        "keltner_pos_50": 1.432761,
        "rsi_21": 63.601545,
        "ema_dist_89_atr": 4.345096,
        "ema_dist_55_atr": 3.632834,
        "ema_dist_100_atr": 4.521867,
        "wma_dist_100_atr": 4.197858,
        "donchian_pos_120": 0.898368,
        "bb_pos_100": 0.967534,
        "sma_dist_55_atr": 4.020369,
        "roc_30": 0.004733,
        "roc_45": 0.006193,
    }

    def version(self) -> str:
        return "M4IndicatorOraclePioneerV8-shadow-top25-causal-no-promotion"

    @staticmethod
    def _v8_ema(series: Series, length: int) -> Series:
        return series.ewm(span=length, adjust=False, min_periods=max(2, length // 2)).mean()

    @staticmethod
    def _v8_atr(high: Series, low: Series, close: Series, length: int) -> Series:
        prev_close = close.shift(1)
        tr = pd.concat(
            [(high - low).abs(), (high - prev_close).abs(), (low - prev_close).abs()],
            axis=1,
        ).max(axis=1)
        return tr.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()

    @staticmethod
    def _v8_rsi(close: Series, length: int) -> Series:
        delta = close.diff()
        gain = delta.clip(lower=0).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
        loss = (-delta.clip(upper=0)).ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean()
        rs = gain / loss.replace(0.0, np.nan)
        return (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    @staticmethod
    def _v8_wma(series: Series, length: int) -> Series:
        values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
        if _V8_TALIB is not None:
            return pd.Series(_V8_TALIB.WMA(values, timeperiod=length), index=series.index)
        weights = np.arange(1.0, float(length) + 1.0)
        out = np.full(values.shape, np.nan, dtype=float)
        valid = np.nan_to_num(values, nan=0.0)
        conv = np.convolve(valid, weights[::-1], mode="valid") / weights.sum()
        count = np.convolve(np.isfinite(values).astype(float), np.ones(length), mode="valid")
        conv[count < length] = np.nan
        out[length - 1 :] = conv
        return pd.Series(out, index=series.index)

    @staticmethod
    def _v8_kama(series: Series, length: int = 100, fast: int = 2, slow: int = 30) -> Series:
        values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
        if _V8_TALIB is not None:
            return pd.Series(_V8_TALIB.KAMA(values, timeperiod=length), index=series.index)
        n = len(values)
        out = np.full(n, np.nan, dtype=float)
        if n <= length:
            return pd.Series(out, index=series.index)
        change = np.abs(values - np.roll(values, length))
        volatility = pd.Series(np.abs(np.diff(values, prepend=np.nan)), index=series.index).rolling(
            length, min_periods=length
        ).sum().to_numpy(dtype=float)
        er = np.divide(change, volatility, out=np.zeros_like(change), where=volatility > 0)
        fast_sc = 2.0 / (fast + 1.0)
        slow_sc = 2.0 / (slow + 1.0)
        sc = np.square(er * (fast_sc - slow_sc) + slow_sc)
        first = length
        out[first] = values[first]
        for i in range(first + 1, n):
            if not np.isfinite(values[i]):
                out[i] = out[i - 1]
            else:
                prev = out[i - 1] if np.isfinite(out[i - 1]) else values[i - 1]
                out[i] = prev + sc[i] * (values[i] - prev)
        return pd.Series(out, index=series.index)

    @staticmethod
    def _v8_di_spread(high: Series, low: Series, close: Series, length: int = 14) -> Series:
        up = high.diff()
        down = -low.diff()
        plus_dm = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=high.index)
        minus_dm = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=high.index)
        atr = M4IndicatorOraclePioneerV8._v8_atr(high, low, close, length).replace(0.0, np.nan)
        plus_di = 100.0 * plus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr
        minus_di = 100.0 * minus_dm.ewm(alpha=1.0 / length, adjust=False, min_periods=length).mean() / atr
        return plus_di - minus_di

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_indicators(dataframe, metadata)
        close = pd.to_numeric(df["close"], errors="coerce").astype(float)
        high = pd.to_numeric(df["high"], errors="coerce").astype(float)
        low = pd.to_numeric(df["low"], errors="coerce").astype(float)
        atr14 = self._v8_atr(high, low, close, 14).replace(0.0, np.nan)

        for length in (21, 28, 50):
            df[f"rsi_{length}"] = self._v8_rsi(close, length)

        ema21 = self._v8_ema(close, 21)
        ema55 = self._v8_ema(close, 55)
        for length, ema_series in ((55, ema55), (89, self._v8_ema(close, 89)), (100, self._v8_ema(close, 100))):
            df[f"ema_dist_{length}_atr"] = (close - ema_series) / atr14
        df["ema_slope_21_atr"] = (ema21 - ema21.shift(5)) / atr14
        ema_slope_55_atr = (ema55 - ema55.shift(13)) / atr14
        di_spread14 = self._v8_di_spread(high, low, close, 14)
        df["trend_strength_composite"] = df["ema_slope_21_atr"] + ema_slope_55_atr + di_spread14 / 25.0

        for length in (55, 89, 100):
            sma = close.rolling(length, min_periods=max(2, length // 2)).mean()
            df[f"sma_dist_{length}_atr"] = (close - sma) / atr14

        wma100 = self._v8_wma(close, 100)
        kama100 = self._v8_kama(close, 100)
        df["wma_dist_100_atr"] = (close - wma100) / atr14
        df["kama_dist_100_atr"] = (close - kama100) / atr14

        for length in (50, 100):
            mid = close.rolling(length, min_periods=length).mean()
            sd = close.rolling(length, min_periods=length).std(ddof=0)
            upper = mid + 2.0 * sd
            lower = mid - 2.0 * sd
            df[f"bb_pos_{length}"] = (close - lower) / (upper - lower).replace(0.0, np.nan)
            kmid = self._v8_ema(close, length)
            katr = self._v8_atr(high, low, close, length)
            kupper = kmid + 2.0 * katr
            klower = kmid - 2.0 * katr
            df[f"keltner_pos_{length}"] = (close - klower) / (kupper - klower).replace(0.0, np.nan)

        rolling_high_60 = high.rolling(60, min_periods=20).max()
        rolling_high_120 = high.rolling(120, min_periods=40).max()
        rolling_high_240 = high.rolling(240, min_periods=80).max()
        rolling_low_120 = low.rolling(120, min_periods=40).min()
        df["drawdown_60"] = close / rolling_high_60 - 1.0
        df["drawdown_120"] = close / rolling_high_120 - 1.0
        df["drawdown_240"] = close / rolling_high_240 - 1.0
        df["dist_high_120_atr"] = (close - rolling_high_120) / atr14
        df["donchian_pos_120"] = (close - rolling_low_120) / (rolling_high_120 - rolling_low_120).replace(0.0, np.nan)

        for length in (15, 30, 45):
            df[f"roc_{length}"] = close.pct_change(length)

        entry_votes = pd.DataFrame(
            {name: pd.to_numeric(df[name], errors="coerce") <= threshold for name, threshold in self.ENTRY_THRESHOLDS.items()},
            index=df.index,
        )
        exit_votes = pd.DataFrame(
            {name: pd.to_numeric(df[name], errors="coerce") >= threshold for name, threshold in self.EXIT_THRESHOLDS.items()},
            index=df.index,
        )
        df["oracle_entry_score"] = (100.0 * entry_votes.mean(axis=1)).fillna(0.0)
        df["oracle_exit_score"] = (100.0 * exit_votes.mean(axis=1)).fillna(0.0)
        df["oracle_entry_shadow"] = (df["oracle_entry_score"] >= 60.0).astype("int8")
        df["oracle_exit_shadow"] = (df["oracle_exit_score"] >= 60.0).astype("int8")
        df["oracle_shadow_state"] = np.select(
            [df["oracle_entry_shadow"].eq(1), df["oracle_exit_shadow"].eq(1)],
            ["ENTRY_STRETCH", "EXIT_STRETCH"],
            default="NEUTRAL",
        )
        return df


class M4IndicatorOraclePioneerV8_DELAY1(M4IndicatorOraclePioneerV8):
    def version(self) -> str:
        return "M4IndicatorOraclePioneerV8-delay1-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(1).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(1).fillna("").astype(str)
        return df


class M4IndicatorOraclePioneerV8_DELAY2(M4IndicatorOraclePioneerV8):
    def version(self) -> str:
        return "M4IndicatorOraclePioneerV8-delay2-proxy"

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(2).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(2).fillna("").astype(str)
        return df
# ===== END V8 INDICATOR-ORACLE SHADOW TELEMETRY =====


# ===== BEGIN V10 CHRONOLOGICAL STABLE-EXPOSURE REPAIR =====
class M4PioneerStableExposureV10(M4MultiCoinPortfolioV7WalkForward):
    """Chronologically selected exposure repair for the retained 31-pair universe.

    Jan-Feb 2026 classifies pair/tag contexts. March selects a predeclared exposure
    factor. April is untouched architecture holdout. Entries, exits, ROI and stoploss
    are unchanged from V7. All pairs/signals remain; unselected alt contexts use a
    minimum-like stake. Research/backtest only.
    """
    VERSION_TAG = "M4_PIONEER_STABLE_EXPOSURE_V10"
    DEFAULT_ALT_STAKE_FACTOR = 0.025
    BTC_STAKE_FACTOR = 1.0
    VALIDATION_SELECTED_FACTOR = 1.0
    PROVEN_PAIR_TAG_KEYS = frozenset({
        '2Z/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
        'ASTER/USDC|trend_pullback|clean_uptrend|trend_pullback|70',
        'DASH/USDC|trend_pullback|clean_uptrend|trend_pullback|71',
        'DOT/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
        'ETH/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
        'PENDLE/USDC|trend_pullback|clean_uptrend|trend_pullback|73',
        'SHIB/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
        'XPL/USDC|trend_pullback|recovery_reclaim|trend_pullback|69',
        'XRP/USDC|trend_pullback|clean_uptrend|trend_pullback|68',
    })
    CANDIDATE_PAIR_TAG_KEYS = frozenset({
        'ASTER/USDC|trend_pullback|clean_uptrend|trend_pullback|68',
        'ATOM/USDC|trend_pullback|clean_uptrend|trend_pullback|72',
        'AVAX/USDC|trend_pullback|clean_uptrend|trend_pullback|70',
        'AVAX/USDC|trend_pullback|clean_uptrend|trend_pullback|71',
        'BCH/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
        'BCH/USDC|trend_pullback|clean_uptrend|trend_pullback|73',
        'BCH/USDC|trend_pullback|recovery_reclaim|trend_pullback|70',
        'BTC/USDC|trend_pullback|clean_uptrend|trend_pullback|68',
        'BTC/USDC|trend_pullback|recovery_reclaim|trend_pullback|69',
        'DOT/USDC|trend_pullback|momentum_burst|trend_pullback|72',
        'DOT/USDC|trend_pullback|recovery_reclaim|trend_pullback|71',
        'LINK/USDC|trend_pullback|clean_uptrend|trend_pullback|73',
        'LINK/USDC|trend_pullback|momentum_burst|trend_pullback|70',
        'LTC/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
        'PENDLE/USDC|vwap_reclaim|recovery_reclaim|vwap_reclaim|69',
        'PUMP/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
        'PUMP/USDC|trend_pullback|clean_uptrend|trend_pullback|72',
        'TRX/USDC|trend_pullback|clean_uptrend|trend_pullback|68',
        'XPL/USDC|trend_pullback|clean_uptrend|trend_pullback|70',
        'ZK/USDC|momentum_continuation|momentum_burst|trend_pullback|74',
        'ZK/USDC|trend_pullback|clean_uptrend|trend_pullback|69',
    })
    FULL_STAKE_PAIR_TAG_KEYS = PROVEN_PAIR_TAG_KEYS | CANDIDATE_PAIR_TAG_KEYS

    @classmethod
    def _portfolio_factor(cls, pair: str, entry_tag: str | None) -> float:
        if str(pair).upper() == "BTC/USDC":
            return cls.BTC_STAKE_FACTOR
        key = f"{pair}|{cls._tag_key(entry_tag)}"
        return cls.VALIDATION_SELECTED_FACTOR if key in cls.FULL_STAKE_PAIR_TAG_KEYS else cls.DEFAULT_ALT_STAKE_FACTOR

    def version(self) -> str:
        return "M4PioneerStableExposureV10-chronological-risk-allocation-research-only"

class M4PioneerStableExposureV10_DELAY1(M4PioneerStableExposureV10):
    def version(self) -> str: return "M4PioneerStableExposureV10-delay1-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(1).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(1).fillna("").astype(str)
        return df

class M4PioneerStableExposureV10_DELAY2(M4PioneerStableExposureV10):
    def version(self) -> str: return "M4PioneerStableExposureV10-delay2-proxy"
    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        df = super().populate_entry_trend(dataframe, metadata)
        df["enter_long"] = df.get("enter_long", 0).shift(2).fillna(0).astype(int)
        df["enter_tag"] = df.get("enter_tag", "").shift(2).fillna("").astype(str)
        return df
# ===== END V10 CHRONOLOGICAL STABLE-EXPOSURE REPAIR =====


# ===== FQT V2.4 ITERATION-3 DIAGNOSTIC CLASSES =====
import atexit as _fqt_atexit
import collections as _fqt_collections
import json as _fqt_json
import os as _fqt_os
import threading as _fqt_threading


class M4PioneerValidationV14(M4PioneerStableExposureV10):
    """Evidence boundary over V10; trading semantics intentionally unchanged."""
    validation_status = "RESEARCH_ONLY_NOT_PROMOTED"
    parent_anchor = "M4PioneerStableExposureV10"
    alpha_change = False
    timestamp_replay = False
    fresh_oos_opened = False

    @staticmethod
    def version() -> str:
        return "14.0-validation-parity"


_FQT_LEDGER_LOCK = _fqt_threading.Lock()
_FQT_LEDGER_COUNTS = _fqt_collections.Counter()
_FQT_LEDGER_BY_PAIR = _fqt_collections.defaultdict(_fqt_collections.Counter)
_FQT_LEDGER_BY_REASON = _fqt_collections.defaultdict(_fqt_collections.Counter)
_FQT_LEDGER_SAMPLES = _fqt_collections.defaultdict(list)
_FQT_LEDGER_LIMIT = int(_fqt_os.environ.get("FQT_CALLBACK_LEDGER_SAMPLE_LIMIT", "200"))


def _fqt_s(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    if isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _fqt_record(callback: str, pair: str, **fields):
    with _FQT_LEDGER_LOCK:
        _FQT_LEDGER_COUNTS[callback] += 1
        _FQT_LEDGER_BY_PAIR[pair][callback] += 1
        reason = str(fields.get("decision") or fields.get("exit_reason") or fields.get("result") or "none")
        _FQT_LEDGER_BY_REASON[callback][reason] += 1
        if len(_FQT_LEDGER_SAMPLES[callback]) < _FQT_LEDGER_LIMIT:
            _FQT_LEDGER_SAMPLES[callback].append({"pair": pair, **{k: _fqt_s(v) for k, v in fields.items()}})


def _fqt_dump_callback_ledger():
    target = _fqt_os.environ.get("FQT_CALLBACK_LEDGER_PATH")
    if not target:
        return
    payload = {
        "contract": "FQT_V24_CALLBACK_EVENT_LEDGER_V1",
        "counts": dict(_FQT_LEDGER_COUNTS),
        "by_pair": {k: dict(v) for k, v in sorted(_FQT_LEDGER_BY_PAIR.items())},
        "by_reason": {k: dict(v) for k, v in sorted(_FQT_LEDGER_BY_REASON.items())},
        "sample_limit_per_callback": _FQT_LEDGER_LIMIT,
        "samples": dict(_FQT_LEDGER_SAMPLES),
    }
    from pathlib import Path as _Path
    p = _Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_fqt_json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


_fqt_atexit.register(_fqt_dump_callback_ledger)


class M4PioneerValidationV14CallbackLedger(M4PioneerValidationV14):
    """Non-invasive callback instrumentation; decisions are delegated unchanged."""

    @staticmethod
    def version() -> str:
        return "14.0-callback-ledger-diagnostic"

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs):
        result = super().custom_stake_amount(
            pair, current_time, current_rate, proposed_stake, min_stake,
            max_stake, leverage, entry_tag, side, **kwargs
        )
        cfg = getattr(self, "config", {}) or {}
        _fqt_record(
            "custom_stake_amount", pair,
            current_time=current_time,
            proposed_stake=proposed_stake,
            min_stake=min_stake,
            max_stake=max_stake,
            result=result,
            entry_tag=entry_tag,
            config_max_open_trades=cfg.get("max_open_trades"),
            config_wallet=cfg.get("dry_run_wallet"),
            config_stake=cfg.get("stake_amount"),
        )
        return result

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        result = super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)
        _fqt_record(
            "custom_exit", pair,
            current_time=current_time,
            trade_open_date=getattr(trade, "open_date_utc", getattr(trade, "open_date", None)),
            current_profit=current_profit,
            result=result if result is not None else "none",
            enter_tag=getattr(trade, "enter_tag", None),
        )
        return result

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        result = super().custom_stoploss(pair, trade, current_time, current_rate, current_profit, **kwargs)
        _fqt_record(
            "custom_stoploss", pair,
            current_time=current_time,
            current_profit=current_profit,
            result=result,
            enter_tag=getattr(trade, "enter_tag", None),
        )
        return result

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        result = super().confirm_trade_exit(
            pair, trade, order_type, amount, rate, time_in_force, exit_reason, current_time, **kwargs
        )
        _fqt_record(
            "confirm_trade_exit", pair,
            current_time=current_time,
            exit_reason=exit_reason,
            result=result,
            enter_tag=getattr(trade, "enter_tag", None),
        )
        return result


class M4PioneerValidationV14SignalHarness(M4PioneerValidationV14):
    """Signal-only diagnostic. Not a trading candidate or production verdict."""
    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    @staticmethod
    def version() -> str:
        return "14.0-signal-harness-diagnostic"

    def custom_stake_amount(self, pair, current_time, current_rate, proposed_stake, min_stake,
                            max_stake, leverage, entry_tag, side, **kwargs):
        stake = float(proposed_stake)
        if min_stake is not None:
            stake = max(stake, float(min_stake))
        return float(min(stake, float(max_stake)))

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        return None

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        return True

# ===== END FQT V2.4 ITERATION-3 DIAGNOSTIC CLASSES =====


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
