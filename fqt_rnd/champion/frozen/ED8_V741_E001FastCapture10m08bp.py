# pragma pylint: disable=missing-docstring, invalid-name, too-many-locals, too-many-branches, too-many-statements
"""
ED8_V712A_QualityPrune.py — BTC/USDC 1m Spot Long-Only Freqtrade Strategy
Version: V51.0-selected-from-50x-iteration-run-2026-05-31
Operator contract: Research prototype, not live-ready.

Source edge catalog:
- File: top_profit_strict_candidate_pool.csv
- SHA256: 7c5219044458df0c36778e908d0c533835cca428d476313958acca3e91dbc17d
- Selected edges: 180 exact condition-expression edges
- Selected catalog SHA256: d596fb78697f203a9fe8af092708b7106346748a8bfd9af5f53cb0e007857eb9

Hard constraints resolved from prompt:
- Strategy file/class: ED8.py / ED8
- Timeframe: 1m
- Market: BTC/USDC spot long-only
- No futures, no shorts, no leverage, no DCA/grid default.

Important truth anchor:
This file is a Freqtrade-compatible strategy implementation scaffold using the provided
edge condition expressions. It is not a live-profit claim. Required next gates are
backtesting, signal export, lookahead-analysis, recursive-analysis, OOS/walk-forward,
fee/slippage stress, tag-level analysis, and dry-run telemetry.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
import math
import re

import numpy as np
import pandas as pd
from pandas import DataFrame, Series

try:
    from numba import njit as _ed8_njit  # optional native/LLVM accelerator; strategy falls back if unavailable.
    ED8_NUMBA_AVAILABLE = True
except Exception:  # pragma: no cover - most Freqtrade installs may not ship numba.
    ED8_NUMBA_AVAILABLE = False

    def _ed8_njit(*_args: Any, **_kwargs: Any):  # type: ignore
        def _decorator(func: Any) -> Any:
            return func
        return _decorator


@_ed8_njit(cache=False)
def _ed8_native_isin_i32(values: np.ndarray, blocked_values: np.ndarray) -> np.ndarray:
    """Tiny native membership kernel for int32 context codes.

    This is intentionally small and optional. Numba compiles it through LLVM when
    available; without numba the class uses NumPy fallback instead.
    """
    out = np.zeros(values.shape[0], dtype=np.bool_)
    for i in range(values.shape[0]):
        v = values[i]
        for j in range(blocked_values.shape[0]):
            if v == blocked_values[j]:
                out[i] = True
                break
    return out

try:
    from freqtrade.strategy import IStrategy, IntParameter, DecimalParameter, BooleanParameter
except Exception:  # pragma: no cover - local syntax/import fallback when freqtrade is absent.
    class _ParameterFallback:
        def __init__(self, *args: Any, default: Any = None, **kwargs: Any) -> None:
            self.value = default if default is not None else (args[0] if args else None)

    class IStrategy:  # type: ignore
        pass

    class IntParameter(_ParameterFallback):  # type: ignore
        pass

    class DecimalParameter(_ParameterFallback):  # type: ignore
        pass

    class BooleanParameter(_ParameterFallback):  # type: ignore
        pass


class ED8(IStrategy):
    """V712A: Actual V711C quality prune. Removes net-negative volatility_shock/e095/capitulation_recovery and keeps the remaining core whitelist."""
    """
    ED8 — controlled-overbuild BTC/USDC 1m edge ensemble.

    V704 FAST PERFORMANCE REPAIR / 2026-06-03:
    - No intentional trade-logic change against matching V703 candidate.
    - Edge expressions are compiled once and token masks are reused.
    - Per-edge debug columns are disabled by default to reduce DataFrame width.
    - Indicator/regime columns are batch-concatenated to reduce pandas fragmentation.

    V710 DTYPE-SAFE DEBUG REPAIR / 2026-06-03:
    - Fixes Freqtrade crash in _fast_sanitize_numeric with timezone-aware datetime64[ms, UTC] columns.
    - Replaces np.issubdtype(dtype, np.floating) with pandas is_float_dtype guard.
    - Trading logic intentionally unchanged against V709; this is a runtime/debug fix.

    V706 FAST COMPUTE REPAIR / 2026-06-03:
    - Preserves V705 trading logic while reducing backtest CPU/RAM load.
    - Adds NumPy-first edge/token evaluation and faster numeric sanitization.
    - Optional edge prefiltering is available for ultra-fast triage, but defaults to full diagnostic equivalence.
    - Keeps deep forensic edge columns disabled by default.

    V705 LOSS ASYMMETRY REPAIR / 2026-06-03:
    - Built from the real V704A backtests in bk.zip, not from synthetic smoke scores.
    - Main defect: ~68% winrate but avg loss ~3x avg win, producing negative expectancy.
    - Repair focus: tighter hard loss cap, earlier context-loss exits, robust bad-context blocks.
    - Deliberate tradeoff: fewer toxic entries accepted if this improves expectancy and loss asymmetry.

    V703A_CONSERVATIVE_EVIDENCE_REPAIR_20260603 / 2026-06-03:
    - Built from ED8_V702 using Evidence-First Prompt v2.
    - Sample-rule repair: only N>=3 repeated negative contexts are hard-blocked.
    - Low-sample loss contexts are shadow-tracked, not hard-deleted.
    - Global low_vol_drift path block removed to resolve code/report contradiction.

    Hard-Evidence Context-Prune V702 / 2026-05-31:
    - Evidence source: ED8_V51 backtest bundle ED8+20260531_195932.
    - Primary repair: loss-heavy exit-signal stack is converted into profit-only signal exits plus PnL-aware custom_exit defense.
    - Secondary repair: weak in-sample edge/context evidence is penalized, not deleted, to reduce overfit risk.
    - This file is a validation candidate only; it does not claim live profitability.

    Architecture layers implemented:
    Data -> Indicator -> Regime -> Fingerprint -> Gate -> 180 Edge Entry Paths ->
    Exit -> Risk -> Exposure -> Meta Decision -> Debug/Forensics -> Validation Hooks.

    The 180 edge definitions are embedded below to avoid sidecar dependency.
    """

    INTERFACE_VERSION = 3
    timeframe = "1m"
    can_short = False
    process_only_new_candles = True
    startup_candle_count: int = 1600

    # --- Runtime / risk contract -------------------------------------------------
    position_adjustment_enable = False
    use_exit_signal = True
    exit_profit_only = True
    exit_profit_offset = 0.001
    ignore_roi_if_entry_signal = False

    # V705: keep profit capture realistic but remove the zero-profit long-tail ROI floor.
    # Backtests showed winners were too small relative to losses.
    minimal_roi = {
        "0": 0.030,
        "45": 0.021,
        "180": 0.010,
        "720": 0.005,
        "1440": 0.002,
    }

    # V705: hard loss asymmetry repair. V704A allowed losses around -3.0% to -6.7%
    # while average winners were around +1.0%. This cap must be verified by real backtest.
    stoploss = -0.022
    use_custom_stoploss = True
    trailing_stop = True
    trailing_stop_positive = 0.009
    trailing_stop_positive_offset = 0.020
    trailing_only_offset_is_reached = True

    order_types = {
        "entry": "limit",
        "exit": "limit",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    # --- Hyperopt-capable but not hyperopt-dependent defaults --------------------
    edge_hit_min = IntParameter(1, 3, default=1, space="buy", optimize=True)
    quarantine_edge_penalty = IntParameter(0, 25, default=0, space="buy", optimize=True)
    clean_pullback_penalty = IntParameter(0, 20, default=0, space="buy", optimize=True)
    entry_score_min = IntParameter(20, 72, default=55, space="buy", optimize=True)
    regime_score_min = IntParameter(10, 70, default=30, space="buy", optimize=True)
    soft_gate_min = IntParameter(1, 5, default=3, space="buy", optimize=True)
    max_risk_score = IntParameter(45, 90, default=78, space="buy", optimize=True)

    exit_pressure_min = IntParameter(58, 92, default=82, space="sell", optimize=True)
    time_decay_minutes = IntParameter(240, 2880, default=1440, space="sell", optimize=True)
    profit_decay_min = DecimalParameter(0.004, 0.045, default=0.018, decimals=3, space="sell", optimize=True)
    defensive_stop_profit = DecimalParameter(-0.09, -0.010, default=-0.018, decimals=3, space="sell", optimize=True)
    loss_exit_pressure_min = IntParameter(60, 98, default=78, space="sell", optimize=True)
    loss_exit_risk_min = IntParameter(45, 95, default=64, space="sell", optimize=True)
    loss_exit_min_minutes = IntParameter(5, 720, default=25, space="sell", optimize=True)


    # V714 evidence-first update / 2026-06-06:
    # - Based on internal Freqtrade monthly V713 validation.
    # - Re-blocks clean_uptrend/e041/continuation_momentum because V713 introduced a -2.29% tail loss.
    # - Keeps only volatility_shock/e005/trend_pullback as controlled flow addition over V712A.

    # V713 evidence-first update / 2026-06-06:
    # - Based on internal Freqtrade monthly validation runs 20260101-20260501.
    # - P1 loss first: keep V712A exit/risk stack, add only two small-sample flow contexts.
    # - Hard-block V712B contexts that increased trades but violated loss/tail discipline.

    # V712 evidence-first update / 2026-06-04:
    # - Built from actual V711C backtests.
    # - Removes/blocks V711C context volatility_shock/e095/capitulation_recovery after negative actual net result.
    # - Keeps code in Freqtrade v3 long-only spot mode; no performance claim without new backtest.
    # Evidence quarantine from ED8_V51 backtest 20250101-20260101.
    # These ranks are penalized, not removed. They must survive OOS before promotion/removal decisions.
    ED8_AUDIT_VERSION = 'ED8_V741_E001Fast10m_80bp'
    ED8_QUARANTINE_EDGE_RANKS = frozenset()
    ED8_SHADOW_EDGE_RANKS = frozenset()
    ED8_CONTEXT_PRUNE_PROFILE = 'ed8_v734_e001fastexit10roistretch21'

    # V705 hard blocks: contexts repeatedly loss-heavy in the real V704A backtests
    # from bk.zip. Format: (active_regime, best_edge_rank, active_path).
    ED8_BLOCKED_LOSS_CONTEXTS = frozenset({
        ('clean_uptrend', 2, 'continuation_momentum'),
        ('clean_uptrend', 6, 'continuation_momentum'),
        ('clean_uptrend', 120, 'low_vol_drift'),
        ('dirty_chop', 20, 'capitulation_recovery'),
        ('dirty_chop', 21, 'range_reversal'),
        ('dirty_chop', 36, 'capitulation_recovery'),
        ('range_rotation', 36, 'capitulation_recovery'),
        ('volatility_shock', 1, 'trend_pullback'),
        ('volatility_shock', 20, 'capitulation_recovery'),
        ('volatility_shock', 36, 'capitulation_recovery'),
        ('volatility_shock', 68, 'breakout_expansion'),
        ('volatility_shock', 83, 'capitulation_recovery'),
        ('volatility_shock', 95, 'capitulation_recovery'),
        # V713 loss-first blocks from internal monthly V712B evidence.
        # Block contexts that increased trade-flow but violated P1 loss discipline.
        ('clean_uptrend', 134, 'continuation_momentum'),
        ('dirty_chop', 24, 'capitulation_recovery'),
        ('volatility_shock', 6, 'continuation_momentum'),
        ('clean_uptrend', 41, 'continuation_momentum'),  # V714 re-block: V713 tail-loss breach.
    })

    # V705 shadow contexts: suspicious, but not hard-deleted due sample/instability concerns.
    ED8_SHADOW_LOSS_CONTEXTS = frozenset({
        ('breakout_expansion', 120, 'low_vol_drift'),
        ('breakout_expansion', 121, 'continuation_momentum'),
        ('clean_uptrend', 1, 'trend_pullback'),
        ('clean_uptrend', 56, 'continuation_momentum'),
        ('clean_uptrend', 68, 'breakout_expansion'),
        ('clean_uptrend', 121, 'continuation_momentum'),
        ('clean_uptrend', 133, 'range_reversal'),
        ('dirty_chop', 33, 'capitulation_recovery'),
        ('pullback_in_uptrend', 128, 'continuation_momentum'),
        ('range_rotation', 20, 'capitulation_recovery'),
        ('range_rotation', 21, 'range_reversal'),
        ('volatility_shock', 2, 'continuation_momentum'),
        ('volatility_shock', 19, 'capitulation_recovery'),
        ('volatility_shock', 21, 'range_reversal'),
        ('volatility_shock', 23, 'trend_pullback'),
        ('volatility_shock', 34, 'range_reversal'),
        ('volatility_shock', 41, 'continuation_momentum'),
        ('volatility_shock', 44, 'capitulation_recovery'),
        ('volatility_shock', 95, 'capitulation_recovery'),
        ('volatility_shock', 114, 'range_reversal'),
    })
    ED8_BLOCKED_EDGE_RANKS = frozenset()
    ED8_BLOCKED_REGIME_PATHS = frozenset()
    ED8_ALLOWED_ENTRY_CONTEXTS = frozenset({
        ('dirty_chop', 1, 'trend_pullback'),
        ('dirty_chop', 59, 'capitulation_recovery'),
        ('breakout_expansion', 59, 'capitulation_recovery'),
        ('volatility_shock', 121, 'continuation_momentum'),
        ('pullback_in_uptrend', 133, 'range_reversal'),
        ('volatility_shock', 5, 'trend_pullback'),
        ('clean_uptrend', 35, 'continuation_momentum'),
        ('clean_uptrend', 20, 'capitulation_recovery'),
        ('clean_uptrend', 36, 'capitulation_recovery'),
        ('clean_uptrend', 104, 'trend_pullback'),
        ('range_rotation', 83, 'capitulation_recovery'),
        ('volatility_shock', 7, 'continuation_momentum'),
    })
    # Deliberate path-level block retained: low_vol_drift was low-sample and poor in 2026 OOS;
    # it is disabled until it earns re-entry through a clean OOS test.
    ED8_BLOCKED_PATHS = frozenset({'low_vol_drift'})
    ED8_EXPORT_EDGE_COLUMNS: bool = False  # Set True only for deep edge-column forensics; False is faster for backtests.
    ED8_FAST_CACHE_VERSION = 'ED8_V741_E001Fast10m_80bp'
    # V706 performance switches. Keep prefilter True for normal fast backtests.
    # It preserves enter/exit decisions while setting edge diagnostics to neutral on rows that cannot enter.
    # Set False only for one targeted full forensic signal-export run.
    ED8_EDGE_PREFILTER_ENABLED: bool = True
    ED8_RETURN_COPY_AFTER_INDICATORS: bool = False
    ED8_EXPORT_DIAGNOSTIC_COLUMNS: bool = False  # Set True only for deep score/edge-family forensics.
    ED8_EXPORT_BLOCK_COLUMNS: bool = False  # Set True only when block-context debug columns are needed.
    ED8_EXPORT_EDGE_TAG_COLUMN: bool = False  # enter_tag still contains rank/path/score for actual entries.
    # V709: compact final analyzed dataframe after entry/exit decisions for normal trades-only backtests.
    # For deep signal exports, use SignalSlim/Forensic variants generated from this same source.
    ED8_COMPACT_AFTER_EXIT: bool = True
    ED8_COMPACT_PROFILE: str = "triage"  # triage | signal | forensic
    ED8_USE_NUMBA_NATIVE: bool = False  # Optional; Numba/native experiment is off by default to avoid JIT warmup cost.
    _EDGE_TOKENS_CACHE: Optional[List[str]] = None
    _EDGE_EXPR_TOKEN_CACHE: Optional[List[Tuple[int, float, str, str, List[List[str]]]]] = None
    _EDGE_PARSED_TOKEN_CACHE: Dict[str, Tuple[str, Optional[int], Optional[int], str, Optional[float]]] = {}

    # The catalog is intentionally compact: rank, edge_id, family, expression, score, metrics.
    EDGE_CATALOG: List[Dict[str, Any]] = [
            {
                    "rank": 1,
                    "edge_id": "T10R01_0101",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p25 AND rsi7_gt28 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 81.76,
                    "trades": 123.0,
                    "winrate": 60.162602,
                    "profit_pct": 93.658717,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 2,
                    "edge_id": "EDGE25KMORE_20413",
                    "family": "trend_momentum",
                    "expr": "roc60_gt2p5 AND roc960_gt0p8 AND lowdist100_gt0p15",
                    "score": 69.465701,
                    "trades": 882.0,
                    "winrate": 46.938776,
                    "profit_pct": 362.504416,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 3,
                    "edge_id": "T10R08_0140",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p25 AND rsi7_gt25 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 80.0,
                    "trades": 123.0,
                    "winrate": 60.162602,
                    "profit_pct": 89.908858,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 4,
                    "edge_id": "EDGE25KMORE_08728",
                    "family": "breakout_expansion",
                    "expr": "roc60_gt2p5 AND atrpct14_q20_gt AND roc960_gt1",
                    "score": 65.437262,
                    "trades": 872.0,
                    "winrate": 45.642202,
                    "profit_pct": 246.155213,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 5,
                    "edge_id": "T10SRR03_0296",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p35 AND rsi7_gt32 AND rsi7_lt55 AND roc5_gt0p12",
                    "score": 81.18,
                    "trades": 75.0,
                    "winrate": 61.333333,
                    "profit_pct": 81.300517,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 6,
                    "edge_id": "EDGE10X500_01043",
                    "family": "trend_momentum",
                    "expr": "roc180_gt2 AND roc30_gt1p2 AND lowdist480_gt4",
                    "score": 69.0,
                    "trades": 854.0,
                    "winrate": 49.297424,
                    "profit_pct": 187.43415,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 7,
                    "edge_id": "EDGE25KMORE_17370",
                    "family": "trend_momentum",
                    "expr": "eslope144_gtm0p1 AND roc90_gt0p25 AND lowdist100_gt4",
                    "score": 65.555152,
                    "trades": 809.0,
                    "winrate": 46.477132,
                    "profit_pct": 208.847515,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 8,
                    "edge_id": "EDGE25KMORE_03486",
                    "family": "trend_momentum",
                    "expr": "roc360_gt0p4 AND roc240_gt6 AND lowdist100_gt0p4 AND roc720_gt0p6",
                    "score": 69.0,
                    "trades": 542.0,
                    "winrate": 62.361624,
                    "profit_pct": 131.890447,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 9,
                    "edge_id": "T10R08_0177",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p35 AND rsi7_gt28 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 77.09,
                    "trades": 133.0,
                    "winrate": 59.398496,
                    "profit_pct": 89.557465,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 10,
                    "edge_id": "T10R10_0045",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p35 AND rsi7_gt32 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 77.09,
                    "trades": 133.0,
                    "winrate": 59.398496,
                    "profit_pct": 89.557465,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 11,
                    "edge_id": "T10R08_0433",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p35 AND rsi7_gt32 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 76.82,
                    "trades": 136.0,
                    "winrate": 58.088235,
                    "profit_pct": 89.320188,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 12,
                    "edge_id": "ADD25K3_11836",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p35 AND rsi7_gt28 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 76.82,
                    "trades": 136.0,
                    "winrate": 58.088235,
                    "profit_pct": 89.320188,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 13,
                    "edge_id": "T10R01_0144",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p25 AND rsi7_gt32 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 76.89,
                    "trades": 132.0,
                    "winrate": 58.333333,
                    "profit_pct": 88.685987,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 14,
                    "edge_id": "T10R08_0340",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p25 AND rsi7_gt28 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 76.89,
                    "trades": 132.0,
                    "winrate": 58.333333,
                    "profit_pct": 88.685987,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 15,
                    "edge_id": "T10SRR07_0041",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p35 AND rsi7_gt35 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 75.92,
                    "trades": 132.0,
                    "winrate": 59.090909,
                    "profit_pct": 87.900404,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 16,
                    "edge_id": "T10SRR05_0082",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p25 AND rsi7_gt25 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 74.43,
                    "trades": 132.0,
                    "winrate": 58.333333,
                    "profit_pct": 85.429715,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 17,
                    "edge_id": "T10R02_0074",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p35 AND rsi7_gt25 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 74.29,
                    "trades": 133.0,
                    "winrate": 59.398496,
                    "profit_pct": 85.807606,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 18,
                    "edge_id": "T10R02_0393",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p35 AND rsi7_gt25 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 74.03,
                    "trades": 136.0,
                    "winrate": 58.088235,
                    "profit_pct": 85.570329,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 19,
                    "edge_id": "ADD25K3_11296",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc120_ltm0p8 AND rsi28_lt28",
                    "score": 79.08,
                    "trades": 78.0,
                    "winrate": 57.692308,
                    "profit_pct": 75.109692,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 20,
                    "edge_id": "T10R03_0231",
                    "family": "capitulation_recovery",
                    "expr": "atrpct14_lt0p25 AND roc120_ltm0p6 AND rsi14_lt35",
                    "score": 74.82,
                    "trades": 52.0,
                    "winrate": 61.538462,
                    "profit_pct": 68.538827,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 21,
                    "edge_id": "ADD25K3_19872",
                    "family": "wick_reversal",
                    "expr": "roc30_ltm0p7 AND rsi7_lt28",
                    "score": 74.63,
                    "trades": 63.0,
                    "winrate": 60.31746,
                    "profit_pct": 63.854283,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 22,
                    "edge_id": "EDGE10X50090V2_05_217",
                    "family": "continuation_after_pullback",
                    "expr": "eslope8_ltm0p5 AND ddhigh200_ltm0p5",
                    "score": 79.0,
                    "trades": 50.0,
                    "winrate": 64.0,
                    "profit_pct": 20.468393,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 23,
                    "edge_id": "EDGE10X50090V2_01_455",
                    "family": "continuation_after_pullback",
                    "expr": "lowdist20_gt2 AND lowdist50_gt0p6",
                    "score": 79.0,
                    "trades": 51.0,
                    "winrate": 60.784314,
                    "profit_pct": 18.066539,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 24,
                    "edge_id": "T10SRR09_0103",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc360_ltm0p4 AND rsi28_lt28",
                    "score": 77.03,
                    "trades": 72.0,
                    "winrate": 56.944444,
                    "profit_pct": 70.473386,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 25,
                    "edge_id": "EDGE10X500_03965",
                    "family": "trend_momentum",
                    "expr": "roc720_gt1p5 AND roc15_gt0p1 AND lowdist100_gt4",
                    "score": 69.0,
                    "trades": 418.0,
                    "winrate": 43.301435,
                    "profit_pct": 112.731219,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 26,
                    "edge_id": "T10SRR02_0376",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt2 AND atrpct60_gt0p08 AND edist480_ltm0p2 AND rsi21_gt28 AND rsi21_lt52 AND roc10_gt0p03",
                    "score": 70.57,
                    "trades": 91.0,
                    "winrate": 64.835165,
                    "profit_pct": 73.407116,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 27,
                    "edge_id": "EDGE10X500_00686",
                    "family": "trend_momentum",
                    "expr": "roc720_gt2p5 AND roc20_gt1 AND lowdist480_gt2 AND eslope89_gt0p2",
                    "score": 69.0,
                    "trades": 338.0,
                    "winrate": 44.970414,
                    "profit_pct": 111.149665,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 28,
                    "edge_id": "EDGE10X500_04160",
                    "family": "trend_momentum",
                    "expr": "roc720_gt1p5 AND roc30_gt0p6 AND lowdist100_gt4",
                    "score": 69.0,
                    "trades": 433.0,
                    "winrate": 48.960739,
                    "profit_pct": 104.580207,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 29,
                    "edge_id": "T10R02_0244",
                    "family": "capitulation_recovery",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND roc240_ltm1p05 AND rsi28_lt28",
                    "score": 72.36,
                    "trades": 44.0,
                    "winrate": 61.363636,
                    "profit_pct": 64.150171,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 30,
                    "edge_id": "EDGE25KMORE_16537",
                    "family": "trend_momentum",
                    "expr": "roc60_gt0p8 AND edist100_gt2 AND volr480_gt0p6 AND lowdist20_gt0p1",
                    "score": 64.784743,
                    "trades": 491.0,
                    "winrate": 50.509165,
                    "profit_pct": 141.371611,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 31,
                    "edge_id": "EDGE25KMORE_00827",
                    "family": "breakout_expansion",
                    "expr": "edist100_gt2 AND atrpct14_q20_gt AND volz10_gtm1",
                    "score": 69.0,
                    "trades": 402.0,
                    "winrate": 55.223881,
                    "profit_pct": 99.569424,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 32,
                    "edge_id": "EDGE25KMORE_09760",
                    "family": "mean_reversion_pullback",
                    "expr": "edist200_ltm0p25 AND roc360_ltm4 AND lowdist120_gt1p5",
                    "score": 66.313993,
                    "trades": 583.0,
                    "winrate": 54.202401,
                    "profit_pct": 118.855298,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 33,
                    "edge_id": "ADD25K3_21738",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc30_ltm1p05 AND rsi28_lt28",
                    "score": 75.37,
                    "trades": 72.0,
                    "winrate": 58.333333,
                    "profit_pct": 69.391349,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 34,
                    "edge_id": "EDGE10X500_01959",
                    "family": "mean_reversion_pullback",
                    "expr": "edist200_ltm2 AND lowdist60_gt0p8 AND eslope8_gtm0p6",
                    "score": 69.0,
                    "trades": 344.0,
                    "winrate": 48.255814,
                    "profit_pct": 99.973731,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 35,
                    "edge_id": "EDGE10X500_01179",
                    "family": "trend_momentum",
                    "expr": "roc360_gt1p5 AND roc30_gt0p8 AND lowdist100_gt4",
                    "score": 69.0,
                    "trades": 417.0,
                    "winrate": 50.119904,
                    "profit_pct": 95.968992,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 36,
                    "edge_id": "T10R06_0222",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc120_ltm0p6 AND rsi7_lt32",
                    "score": 75.56,
                    "trades": 64.0,
                    "winrate": 59.375,
                    "profit_pct": 66.261442,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 37,
                    "edge_id": "T10SRR10_0305",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p25 AND rsi7_gt35 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 65.32,
                    "trades": 129.0,
                    "winrate": 57.364341,
                    "profit_pct": 73.216917,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 38,
                    "edge_id": "T10SRR04_0361",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p2 AND rsi7_gt32 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 65.22,
                    "trades": 126.0,
                    "winrate": 55.555556,
                    "profit_pct": 74.474821,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 39,
                    "edge_id": "T10SRR01_0484",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p35 AND rsi14_gt25 AND rsi14_lt52 AND roc10_gt0p12",
                    "score": 64.56,
                    "trades": 86.0,
                    "winrate": 60.465116,
                    "profit_pct": 66.535349,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 40,
                    "edge_id": "EDGE10X500_01384",
                    "family": "continuation_after_pullback",
                    "expr": "roc60_ltm1p5 AND eslope8_gt0p2 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 155.0,
                    "winrate": 40.0,
                    "profit_pct": 56.805169,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 41,
                    "edge_id": "EDGE10X500_04865",
                    "family": "trend_momentum",
                    "expr": "roc360_gt3 AND roc10_gt1p2 AND lowdist360_gt1",
                    "score": 69.0,
                    "trades": 192.0,
                    "winrate": 50.520833,
                    "profit_pct": 49.843409,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 42,
                    "edge_id": "EDGE10X500_03080",
                    "family": "trend_momentum",
                    "expr": "roc480_gt2 AND roc5_gt0p4 AND lowdist200_gt5",
                    "score": 68.756419,
                    "trades": 190.0,
                    "winrate": 46.842105,
                    "profit_pct": 51.645966,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 43,
                    "edge_id": "EDGE25KMORE_23714",
                    "family": "breakout_expansion",
                    "expr": "roc90_gt4 AND range_gt0p3 AND roc20_gt1p25",
                    "score": 68.589473,
                    "trades": 141.0,
                    "winrate": 49.64539,
                    "profit_pct": 58.247651,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 44,
                    "edge_id": "T10R05_0447",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p05 AND atrpct60_lt0p35 AND roc120_ltm0p6 AND rsi14_lt35",
                    "score": 68.79,
                    "trades": 85.0,
                    "winrate": 54.117647,
                    "profit_pct": 65.986274,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 45,
                    "edge_id": "EDGE10X500_01818",
                    "family": "capitulation_recovery",
                    "expr": "roc60_ltm2p5 AND lowdist30_gt0p8 AND closepos_gt65",
                    "score": 69.0,
                    "trades": 146.0,
                    "winrate": 51.369863,
                    "profit_pct": 53.026004,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 46,
                    "edge_id": "T10R01_0004",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p4 AND rsi7_gt28 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 64.06,
                    "trades": 137.0,
                    "winrate": 56.20438,
                    "profit_pct": 73.168855,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 47,
                    "edge_id": "T10SRR01_0006",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p4 AND rsi7_gt32 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 64.06,
                    "trades": 137.0,
                    "winrate": 56.20438,
                    "profit_pct": 73.168855,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 48,
                    "edge_id": "ADD25K3_01547",
                    "family": "wick_reversal",
                    "expr": "roc120_ltm1p5 AND rsi28_lt32",
                    "score": 67.38,
                    "trades": 98.0,
                    "winrate": 58.163265,
                    "profit_pct": 75.331113,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 49,
                    "edge_id": "T10SRR07_0092",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p35 AND rsi14_gt28 AND rsi14_lt52 AND roc3_gt0p12",
                    "score": 63.81,
                    "trades": 142.0,
                    "winrate": 58.450704,
                    "profit_pct": 73.005506,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 50,
                    "edge_id": "EDGE25KMORE_13537",
                    "family": "trend_momentum",
                    "expr": "eslope21_gt0p1 AND edist200_gt2 AND volr60_gt0p7 AND edist20_gt1",
                    "score": 69.0,
                    "trades": 159.0,
                    "winrate": 52.830189,
                    "profit_pct": 48.213706,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 51,
                    "edge_id": "EDGE25KMORE_19345",
                    "family": "trend_momentum",
                    "expr": "roc180_gt5 AND edist13_gt0 AND roc45_gt2",
                    "score": 67.594195,
                    "trades": 158.0,
                    "winrate": 48.101266,
                    "profit_pct": 58.656533,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 52,
                    "edge_id": "EDGE10X500_04600",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos100_lt25 AND highdist60_ltm0p75 AND lowdist200_gt4",
                    "score": 69.0,
                    "trades": 143.0,
                    "winrate": 42.657343,
                    "profit_pct": 46.122461,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 53,
                    "edge_id": "EDGE10X500_03681",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos50_lt12 AND highdist20_ltm1 AND lowdist720_gt3",
                    "score": 69.0,
                    "trades": 56.0,
                    "winrate": 60.714286,
                    "profit_pct": 14.168815,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 54,
                    "edge_id": "T10SRR05_0264",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p35 AND rsi14_gt25 AND rsi14_lt52 AND roc3_gt0p12",
                    "score": 63.3,
                    "trades": 142.0,
                    "winrate": 58.450704,
                    "profit_pct": 72.309359,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 55,
                    "edge_id": "EDGE10X500_04033",
                    "family": "trend_momentum",
                    "expr": "roc240_gt4 AND roc5_gt0p6 AND lowdist360_gt3",
                    "score": 69.0,
                    "trades": 146.0,
                    "winrate": 48.630137,
                    "profit_pct": 44.568709,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 56,
                    "edge_id": "EDGE10X500_04931",
                    "family": "trend_momentum",
                    "expr": "roc120_gt1p5 AND roc5_gt1 AND lowdist480_gt2",
                    "score": 69.0,
                    "trades": 153.0,
                    "winrate": 49.019608,
                    "profit_pct": 43.502288,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 57,
                    "edge_id": "EDGE10X500_01657",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos20_lt25 AND highdist60_ltm2p5 AND lowdist100_gt0p8",
                    "score": 69.0,
                    "trades": 117.0,
                    "winrate": 49.57265,
                    "profit_pct": 47.004863,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 58,
                    "edge_id": "EDGE10X500_02923",
                    "family": "trend_momentum",
                    "expr": "roc360_gt0p8 AND roc20_gt1p2 AND lowdist200_gt6 AND eslope89_gt0p2",
                    "score": 69.0,
                    "trades": 115.0,
                    "winrate": 46.086957,
                    "profit_pct": 47.292169,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 59,
                    "edge_id": "T10R10_0049",
                    "family": "volume_climax_absorption",
                    "expr": "atrpct14_lt0p25 AND roc120_ltm0p6 AND volz60_gt0p8",
                    "score": 67.01,
                    "trades": 96.0,
                    "winrate": 59.375,
                    "profit_pct": 68.844098,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 60,
                    "edge_id": "T10R10_0330",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc120_ltm0p75 AND rsi28_lt28",
                    "score": 66.84,
                    "trades": 93.0,
                    "winrate": 56.989247,
                    "profit_pct": 71.109162,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 61,
                    "edge_id": "EDGE25KMORE_12118",
                    "family": "mean_reversion_pullback",
                    "expr": "roc480_ltm0p25 AND roc45_ltm0p25 AND lowdist480_gt5",
                    "score": 66.667339,
                    "trades": 239.0,
                    "winrate": 53.556485,
                    "profit_pct": 53.116761,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 62,
                    "edge_id": "EDGE10X500_01070",
                    "family": "trend_momentum",
                    "expr": "roc120_gt2 AND roc10_gt1p2 AND lowdist360_gt4",
                    "score": 69.0,
                    "trades": 161.0,
                    "winrate": 50.931677,
                    "profit_pct": 37.390931,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 63,
                    "edge_id": "EDGE10X500_01663",
                    "family": "trend_momentum",
                    "expr": "roc120_gt0p8 AND roc15_gt1 AND lowdist200_gt6",
                    "score": 69.0,
                    "trades": 133.0,
                    "winrate": 48.120301,
                    "profit_pct": 40.549012,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 64,
                    "edge_id": "EDGE10X500_04286",
                    "family": "trend_momentum",
                    "expr": "roc240_gt2 AND roc10_gt0p8 AND lowdist200_gt5",
                    "score": 67.913514,
                    "trades": 166.0,
                    "winrate": 45.180723,
                    "profit_pct": 44.595188,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 65,
                    "edge_id": "EDGE10X500_00852",
                    "family": "trend_momentum",
                    "expr": "roc180_gt2p5 AND roc10_gt1p2 AND lowdist480_gt4",
                    "score": 69.0,
                    "trades": 143.0,
                    "winrate": 53.146853,
                    "profit_pct": 34.718118,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 66,
                    "edge_id": "EDGE10X500_03875",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos50_lt25 AND highdist20_ltm1 AND lowdist60_gt1p5",
                    "score": 68.800575,
                    "trades": 122.0,
                    "winrate": 44.262295,
                    "profit_pct": 38.105178,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 67,
                    "edge_id": "EDGE10X500_00652",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos50_lt25 AND highdist100_ltm1p5 AND lowdist200_gt4",
                    "score": 69.0,
                    "trades": 130.0,
                    "winrate": 52.307692,
                    "profit_pct": 34.462512,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 68,
                    "edge_id": "EDGE25KMORE_04271",
                    "family": "breakout_expansion",
                    "expr": "atrpct240_q80_lt AND roc20_gt1p5 AND volz240_gtm0p5",
                    "score": 67.645067,
                    "trades": 155.0,
                    "winrate": 45.806452,
                    "profit_pct": 43.614807,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 69,
                    "edge_id": "EDGE10X500_04436",
                    "family": "continuation_after_pullback",
                    "expr": "roc60_ltm0p8 AND eslope8_gt0p4 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 103.0,
                    "winrate": 44.660194,
                    "profit_pct": 36.047689,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 70,
                    "edge_id": "EDGE10X500_04326",
                    "family": "trend_momentum",
                    "expr": "roc720_gt4 AND roc30_gt1p2 AND lowdist200_gt6",
                    "score": 69.0,
                    "trades": 135.0,
                    "winrate": 54.074074,
                    "profit_pct": 30.410055,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 71,
                    "edge_id": "EDGE25KMORE_24065",
                    "family": "mean_reversion_pullback",
                    "expr": "roc180_ltm2p5 AND highdist720_ltm1 AND lowdist720_gt4",
                    "score": 69.0,
                    "trades": 130.0,
                    "winrate": 56.923077,
                    "profit_pct": 30.702363,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 72,
                    "edge_id": "ADD25K3_15608",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc240_ltm0p45 AND rsi28_lt28",
                    "score": 66.45,
                    "trades": 81.0,
                    "winrate": 55.555556,
                    "profit_pct": 65.462864,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 73,
                    "edge_id": "EDGE25KMORE_10837",
                    "family": "trend_momentum",
                    "expr": "eslope55_gt0p6 AND closepos_gt60 AND liquidityraw_q70_gt",
                    "score": 65.385701,
                    "trades": 236.0,
                    "winrate": 52.542373,
                    "profit_pct": 54.708437,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 74,
                    "edge_id": "EDGE25KMORE_14268",
                    "family": "mean_reversion_pullback",
                    "expr": "rsi21_lt40 AND lowdist30_gt1 AND volr60_gt0p9",
                    "score": 69.0,
                    "trades": 118.0,
                    "winrate": 37.288136,
                    "profit_pct": 31.678424,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 75,
                    "edge_id": "EDGE10X500_04933",
                    "family": "trend_momentum",
                    "expr": "roc240_gt3 AND roc10_gt1 AND lowdist100_gt4 AND eslope89_gt0",
                    "score": 69.0,
                    "trades": 119.0,
                    "winrate": 48.739496,
                    "profit_pct": 31.466987,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 76,
                    "edge_id": "EDGE25KMORE_06320",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos100_lt50 AND lowdist120_gt3 AND liquidityraw_q80_gt",
                    "score": 69.0,
                    "trades": 58.0,
                    "winrate": 41.37931,
                    "profit_pct": 44.777929,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 77,
                    "edge_id": "EDGE10X500_00597",
                    "family": "trend_momentum",
                    "expr": "roc180_gt3 AND roc10_gt1p2 AND lowdist480_gt1",
                    "score": 69.0,
                    "trades": 123.0,
                    "winrate": 52.845528,
                    "profit_pct": 29.31312,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 78,
                    "edge_id": "EDGE25KMORE_09774",
                    "family": "mean_reversion_pullback",
                    "expr": "roc960_ltm6 AND edist144_ltm0p75 AND lowdist100_gt3",
                    "score": 69.0,
                    "trades": 92.0,
                    "winrate": 38.043478,
                    "profit_pct": 33.784013,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 79,
                    "edge_id": "EDGE10X500_03052",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos100_lt15 AND highdist60_ltm0p5 AND lowdist60_gt2",
                    "score": 69.0,
                    "trades": 67.0,
                    "winrate": 29.850746,
                    "profit_pct": 39.929042,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 80,
                    "edge_id": "EDGE25KMORE_05589",
                    "family": "mean_reversion_pullback",
                    "expr": "ddhigh50_ltm2p5 AND lowdist200_gt0p25 AND volz240_gt1p5",
                    "score": 64.330321,
                    "trades": 251.0,
                    "winrate": 43.426295,
                    "profit_pct": 60.17785,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 81,
                    "edge_id": "EDGE25KMORE_02895",
                    "family": "mean_reversion_pullback",
                    "expr": "rsi21_lt35 AND lowdist50_gt0p8 AND volr240_gt0p5",
                    "score": 69.0,
                    "trades": 101.0,
                    "winrate": 38.613861,
                    "profit_pct": 31.23442,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 82,
                    "edge_id": "EDGE10X500_00894",
                    "family": "mean_reversion_pullback",
                    "expr": "ddhigh480_ltm4 AND lowdist100_gt0p05 AND rsi21_lt25",
                    "score": 69.0,
                    "trades": 85.0,
                    "winrate": 47.058824,
                    "profit_pct": 34.298747,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 83,
                    "edge_id": "EDGE25KMORE_21919",
                    "family": "capitulation_recovery",
                    "expr": "roc360_ltm3 AND lowdist120_gt0p25 AND volz120_gt3",
                    "score": 68.650955,
                    "trades": 132.0,
                    "winrate": 49.242424,
                    "profit_pct": 28.535279,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 84,
                    "edge_id": "EDGE10X500_03712",
                    "family": "continuation_after_pullback",
                    "expr": "roc45_ltm1p5 AND eslope13_gt0p1 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 87.0,
                    "winrate": 44.827586,
                    "profit_pct": 31.767868,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 85,
                    "edge_id": "T10SRR08_0334",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p4 AND rsi7_gt25 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 61.31,
                    "trades": 137.0,
                    "winrate": 56.20438,
                    "profit_pct": 69.418996,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 86,
                    "edge_id": "EDGE10X500_01803",
                    "family": "continuation_after_pullback",
                    "expr": "roc60_ltm2 AND eslope13_gt0p1 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 100.0,
                    "winrate": 52.0,
                    "profit_pct": 28.205358,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 87,
                    "edge_id": "EDGE25KMORE_11366",
                    "family": "trend_momentum",
                    "expr": "eslope100_gt0p6 AND edist144_gt1p5 AND volz240_gt1 AND eslope5_gt0p25",
                    "score": 67.463149,
                    "trades": 122.0,
                    "winrate": 44.262295,
                    "profit_pct": 39.186231,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 88,
                    "edge_id": "EDGE10X500_01652",
                    "family": "continuation_after_pullback",
                    "expr": "roc30_ltm0p8 AND eslope20_gt0 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 105.0,
                    "winrate": 46.666667,
                    "profit_pct": 26.78126,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 89,
                    "edge_id": "T10R06_0078",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc240_ltm0p25 AND rsi28_lt28",
                    "score": 65.06,
                    "trades": 91.0,
                    "winrate": 56.043956,
                    "profit_pct": 68.79796,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 90,
                    "edge_id": "EDGE10X500_04307",
                    "family": "trend_momentum",
                    "expr": "roc180_gt4 AND roc10_gt1 AND lowdist200_gt4 AND eslope200_gt0p1",
                    "score": 69.0,
                    "trades": 101.0,
                    "winrate": 49.50495,
                    "profit_pct": 26.715907,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 91,
                    "edge_id": "EDGE25KMORE_01082",
                    "family": "breakout_expansion",
                    "expr": "roc60_gt3 AND atrpct240_q50_gt AND volr480_gt1p5",
                    "score": 59.041233,
                    "trades": 414.0,
                    "winrate": 54.10628,
                    "profit_pct": 97.877728,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 92,
                    "edge_id": "EDGE10X500_02629",
                    "family": "trend_momentum",
                    "expr": "roc120_gt3 AND roc30_gt0p4 AND lowdist200_gt3 AND eslope50_gt0p4",
                    "score": 69.0,
                    "trades": 102.0,
                    "winrate": 49.019608,
                    "profit_pct": 26.122871,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 93,
                    "edge_id": "EDGE25KMORE_08966",
                    "family": "volatility_expansion_momentum",
                    "expr": "roc180_ltm0p8 AND bbw20_q20_gt AND lowdist120_gt4",
                    "score": 66.690479,
                    "trades": 173.0,
                    "winrate": 46.820809,
                    "profit_pct": 38.635289,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 94,
                    "edge_id": "EDGE10X500_01954",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos50_lt18 AND highdist50_ltm1p5 AND lowdist60_gt1p5",
                    "score": 69.0,
                    "trades": 84.0,
                    "winrate": 47.619048,
                    "profit_pct": 28.709269,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 95,
                    "edge_id": "EDGE10X500_00272",
                    "family": "capitulation_recovery",
                    "expr": "roc240_ltm3p5 AND lowdist50_gt0p6 AND closepos_gt60 AND volr720_gt4",
                    "score": 69.0,
                    "trades": 82.0,
                    "winrate": 47.560976,
                    "profit_pct": 29.141589,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 96,
                    "edge_id": "ADD25K3_03039",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc240_ltm0p35 AND rsi28_lt28",
                    "score": 64.79,
                    "trades": 91.0,
                    "winrate": 56.043956,
                    "profit_pct": 68.414653,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 97,
                    "edge_id": "EDGE10X500_00647",
                    "family": "trend_momentum",
                    "expr": "roc720_gt2 AND roc15_gt1 AND lowdist100_gt5",
                    "score": 69.0,
                    "trades": 105.0,
                    "winrate": 52.380952,
                    "profit_pct": 22.870153,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 98,
                    "edge_id": "EDGE10X500_03034",
                    "family": "capitulation_recovery",
                    "expr": "roc90_ltm3 AND lowdist30_gt0p25 AND lwick_gt50 AND volr720_gt1p5",
                    "score": 69.0,
                    "trades": 106.0,
                    "winrate": 54.716981,
                    "profit_pct": 22.386289,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 99,
                    "edge_id": "EDGE25KMORE_15497",
                    "family": "trend_momentum",
                    "expr": "roc480_gt6 AND roc45_gt1p25 AND volr480_gt0p9",
                    "score": 63.121631,
                    "trades": 266.0,
                    "winrate": 57.518797,
                    "profit_pct": 62.774388,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 100,
                    "edge_id": "EDGE10X500_04993",
                    "family": "continuation_after_pullback",
                    "expr": "roc90_ltm1p5 AND eslope8_gt0p4 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 91.0,
                    "winrate": 49.450549,
                    "profit_pct": 25.178211,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 101,
                    "edge_id": "T10R06_0298",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc60_ltm0p8 AND rsi28_lt28",
                    "score": 63.98,
                    "trades": 105.0,
                    "winrate": 56.190476,
                    "profit_pct": 72.149289,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 102,
                    "edge_id": "EDGE10X500_03306",
                    "family": "capitulation_recovery",
                    "expr": "roc120_ltm3p5 AND lowdist50_gt0p25 AND lwick_gt50",
                    "score": 69.0,
                    "trades": 103.0,
                    "winrate": 52.427184,
                    "profit_pct": 22.255391,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 103,
                    "edge_id": "EDGE25KMORE_00550",
                    "family": "breakout_expansion",
                    "expr": "roc240_gt2 AND atrpct240_q90_gt AND edist20_gt1",
                    "score": 69.0,
                    "trades": 104.0,
                    "winrate": 54.807692,
                    "profit_pct": 21.919908,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 104,
                    "edge_id": "EDGE25KMORE_06190",
                    "family": "continuation_after_pullback",
                    "expr": "highdist20_ltm0p25 AND roc720_gt4 AND lowdist50_gt2 AND volr30_gt0p9",
                    "score": 67.490923,
                    "trades": 142.0,
                    "winrate": 47.887324,
                    "profit_pct": 30.790775,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 105,
                    "edge_id": "EDGE10X500_01702",
                    "family": "continuation_after_pullback",
                    "expr": "roc60_ltm1 AND eslope8_gt0p4 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 92.0,
                    "winrate": 52.173913,
                    "profit_pct": 24.232629,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 106,
                    "edge_id": "EDGE25KMORE_21261",
                    "family": "trend_momentum",
                    "expr": "roc180_gt6 AND roc20_gt0p4 AND volz480_gt0 AND roc90_gt2p5",
                    "score": 66.903374,
                    "trades": 125.0,
                    "winrate": 52.8,
                    "profit_pct": 37.496651,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 107,
                    "edge_id": "EDGE25KMORE_12658",
                    "family": "trend_momentum",
                    "expr": "roc180_gt0p8 AND roc45_gt3 AND roc720_gt2p5",
                    "score": 63.532548,
                    "trades": 232.0,
                    "winrate": 48.275862,
                    "profit_pct": 58.901225,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 108,
                    "edge_id": "EDGE25KMORE_17221",
                    "family": "trend_momentum",
                    "expr": "eslope50_gt0p4 AND edist13_gt0p75 AND lowdist60_gt0p8 AND lowdist720_gt5",
                    "score": 68.904792,
                    "trades": 87.0,
                    "winrate": 52.873563,
                    "profit_pct": 22.751515,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 109,
                    "edge_id": "EDGE10X500_02146",
                    "family": "trend_momentum",
                    "expr": "roc120_gt1p5 AND roc5_gt1 AND lowdist360_gt4",
                    "score": 69.0,
                    "trades": 79.0,
                    "winrate": 54.43038,
                    "profit_pct": 22.965863,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 110,
                    "edge_id": "EDGE25KMORE_18340",
                    "family": "volatility_expansion_momentum",
                    "expr": "roc90_ltm1p75 AND bbw200_q70_gt AND eslope20_gt0p25",
                    "score": 67.694541,
                    "trades": 115.0,
                    "winrate": 50.434783,
                    "profit_pct": 25.483278,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 111,
                    "edge_id": "EDGE10X500_04749",
                    "family": "trend_momentum",
                    "expr": "roc480_gt5 AND roc30_gt0p4 AND lowdist480_gt1 AND eslope50_gt0p4",
                    "score": 69.0,
                    "trades": 53.0,
                    "winrate": 45.283019,
                    "profit_pct": 27.400659,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 112,
                    "edge_id": "EDGE10X500_02664",
                    "family": "continuation_after_pullback",
                    "expr": "roc45_ltm0p5 AND eslope8_gt0p4 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 85.0,
                    "winrate": 49.411765,
                    "profit_pct": 17.597539,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 113,
                    "edge_id": "EDGE10X500_04133",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos50_lt10 AND highdist100_ltm2p5 AND lowdist480_gt1p5",
                    "score": 68.109173,
                    "trades": 107.0,
                    "winrate": 46.728972,
                    "profit_pct": 21.821494,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 114,
                    "edge_id": "EDGE25KMORE_14619",
                    "family": "mean_reversion_pullback",
                    "expr": "roc360_ltm3 AND edist34_ltm0p75 AND reversalraw_q70_gt",
                    "score": 67.683739,
                    "trades": 108.0,
                    "winrate": 51.851852,
                    "profit_pct": 24.399454,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 115,
                    "edge_id": "EDGE10X500_02301",
                    "family": "continuation_after_pullback",
                    "expr": "roc30_ltm1 AND eslope8_gt0p2 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 77.0,
                    "winrate": 48.051948,
                    "profit_pct": 17.59733,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 116,
                    "edge_id": "EDGE25KMORE_19611",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos50_lt25 AND highdist360_ltm5p5 AND lwick_gt60",
                    "score": 69.0,
                    "trades": 59.0,
                    "winrate": 55.932203,
                    "profit_pct": 22.781967,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 117,
                    "edge_id": "EDGE10X50090V2_04_113",
                    "family": "mean_reversion_pullback",
                    "expr": "roc90_ltm2p5 AND lowdist200_gt0p6",
                    "score": 69.0,
                    "trades": 50.0,
                    "winrate": 56.0,
                    "profit_pct": 23.841204,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 118,
                    "edge_id": "EDGE10X500_02855",
                    "family": "capitulation_recovery",
                    "expr": "roc90_ltm3 AND lowdist50_gt0p8 AND lwick_gt50",
                    "score": 69.0,
                    "trades": 66.0,
                    "winrate": 53.030303,
                    "profit_pct": 14.871953,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 119,
                    "edge_id": "EDGE25KMORE_10895",
                    "family": "mean_reversion_pullback",
                    "expr": "ddhigh20_ltm0p1 AND lowdist100_gt3 AND volz720_gt1 AND roc720_gt4",
                    "score": 62.76138,
                    "trades": 233.0,
                    "winrate": 57.081545,
                    "profit_pct": 47.788546,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 120,
                    "edge_id": "EDGE10X50090V2_07_461",
                    "family": "low_vol_trend_drift",
                    "expr": "lwick_gt40 AND lowdist360_gt4",
                    "score": 69.0,
                    "trades": 51.0,
                    "winrate": 49.019608,
                    "profit_pct": 15.261934,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 121,
                    "edge_id": "EDGE10X50090V2_08_198",
                    "family": "trend_momentum",
                    "expr": "roc10_gt0p8 AND lowdist360_gt4",
                    "score": 68.813639,
                    "trades": 58.0,
                    "winrate": 50.0,
                    "profit_pct": 13.358898,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 122,
                    "edge_id": "EDGE25KMORE_23461",
                    "family": "mean_reversion_pullback",
                    "expr": "ddhigh200_ltm3 AND roc90_ltm1p25 AND lowdist60_gt3 AND volr480_gt0p6",
                    "score": 64.957495,
                    "trades": 131.0,
                    "winrate": 42.748092,
                    "profit_pct": 35.796739,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 123,
                    "edge_id": "EDGE25KMORE_08905",
                    "family": "volatility_expansion_momentum",
                    "expr": "atrpct120_q90_gt AND roc90_gt4 AND volr240_gt2",
                    "score": 63.685573,
                    "trades": 178.0,
                    "winrate": 56.179775,
                    "profit_pct": 42.075286,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 124,
                    "edge_id": "EDGE10X500_00959",
                    "family": "continuation_after_pullback",
                    "expr": "roc30_ltm0p5 AND eslope13_gt0p2 AND green_gt0p5",
                    "score": 69.0,
                    "trades": 56.0,
                    "winrate": 55.357143,
                    "profit_pct": 11.746524,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 125,
                    "edge_id": "EDGE25KMORE_05707",
                    "family": "trend_momentum",
                    "expr": "roc240_gt6 AND roc360_gt1 AND lowdist120_gt2",
                    "score": 57.414065,
                    "trades": 398.0,
                    "winrate": 58.291457,
                    "profit_pct": 88.149,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 126,
                    "edge_id": "EDGE10X500_02782",
                    "family": "capitulation_recovery",
                    "expr": "roc240_ltm2p5 AND lowdist100_gt1 AND closepos_gt55 AND volr200_gt2",
                    "score": 65.667956,
                    "trades": 131.0,
                    "winrate": 46.564885,
                    "profit_pct": 27.554175,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 127,
                    "edge_id": "T10SRR10_0204",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p35 AND rsi7_gt42 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 56.62,
                    "trades": 127.0,
                    "winrate": 60.629921,
                    "profit_pct": 68.468078,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 128,
                    "edge_id": "EDGE25KMORE_21236",
                    "family": "candle_impulse_followthrough",
                    "expr": "lowdist50_gt2 AND roc8_gt1p25 AND volz720_gt0p5 AND roc720_gt4",
                    "score": 68.695463,
                    "trades": 54.0,
                    "winrate": 59.259259,
                    "profit_pct": 13.444202,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 129,
                    "edge_id": "T10R01_0151",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist480_ltm0p35 AND rsi7_gt38 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 58.56,
                    "trades": 132.0,
                    "winrate": 57.575758,
                    "profit_pct": 65.166349,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 130,
                    "edge_id": "EDGE25KMORE_18548",
                    "family": "trend_momentum",
                    "expr": "roc60_gt0p6 AND edist233_gt2 AND volr10_gt0p9 AND ddhigh50_ltm0p25",
                    "score": 58.284293,
                    "trades": 356.0,
                    "winrate": 55.617978,
                    "profit_pct": 77.062536,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 131,
                    "edge_id": "ADD25K3_10571",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc240_ltm0p4 AND rsi28_lt28",
                    "score": 62.03,
                    "trades": 87.0,
                    "winrate": 55.172414,
                    "profit_pct": 64.125553,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 132,
                    "edge_id": "ADD25K3_02033",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc30_ltm0p6 AND rsi28_lt28",
                    "score": 61.0,
                    "trades": 107.0,
                    "winrate": 56.074766,
                    "profit_pct": 69.363982,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 133,
                    "edge_id": "T10SRR04_0274",
                    "family": "range_mean_reversion",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND rsi14_lt38",
                    "score": 61.33,
                    "trades": 107.0,
                    "winrate": 53.271028,
                    "profit_pct": 65.32862,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 134,
                    "edge_id": "EDGE25KMORE_23250",
                    "family": "trend_momentum",
                    "expr": "roc60_gt2p5 AND edist20_gt0p1 AND rsi5_gt60",
                    "score": 67.345685,
                    "trades": 53.0,
                    "winrate": 49.056604,
                    "profit_pct": 13.053454,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 135,
                    "edge_id": "T10SRR08_0218",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p2 AND rsi7_gt28 AND rsi7_lt60 AND roc3_gt0p12",
                    "score": 59.85,
                    "trades": 113.0,
                    "winrate": 55.752212,
                    "profit_pct": 70.074304,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 136,
                    "edge_id": "EDGE25KMORE_21928",
                    "family": "volatility_expansion_momentum",
                    "expr": "highdist200_ltm2p5 AND range_gt0p6 AND lowdist30_gt1p5",
                    "score": 63.377616,
                    "trades": 121.0,
                    "winrate": 46.280992,
                    "profit_pct": 29.805841,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 137,
                    "edge_id": "EDGE25KMORE_12708",
                    "family": "trend_momentum",
                    "expr": "eslope5_gt0p4 AND edist200_gt3 AND lowdist50_gt0p05",
                    "score": 63.831597,
                    "trades": 86.0,
                    "winrate": 47.674419,
                    "profit_pct": 29.773529,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 138,
                    "edge_id": "EDGE10X500_04435",
                    "family": "continuation_after_pullback",
                    "expr": "roc90_ltm1p5 AND eslope20_gt0p2 AND green_gt0p5",
                    "score": 64.400193,
                    "trades": 95.0,
                    "winrate": 45.263158,
                    "profit_pct": 21.11858,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 139,
                    "edge_id": "EDGE10X50090V2_02_276",
                    "family": "mean_reversion_pullback",
                    "expr": "lowdist480_gt0p3 AND lowdist720_gt4 AND lowdist20_gt0p1 AND roc60_ltm0p6",
                    "score": 65.780326,
                    "trades": 50.0,
                    "winrate": 48.0,
                    "profit_pct": 12.938955,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 140,
                    "edge_id": "EDGE10X500_03358",
                    "family": "trend_momentum",
                    "expr": "roc240_gt5 AND roc10_gt0p8 AND lowdist480_gt6",
                    "score": 61.976814,
                    "trades": 107.0,
                    "winrate": 41.121495,
                    "profit_pct": 29.286146,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 141,
                    "edge_id": "EDGE25KMORE_06775",
                    "family": "trend_momentum",
                    "expr": "roc180_gt4 AND roc30_gt2 AND volr720_gt0p4 AND volr20_gt0p6",
                    "score": 60.424144,
                    "trades": 130.0,
                    "winrate": 46.923077,
                    "profit_pct": 39.872143,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 142,
                    "edge_id": "EDGE25KMORE_18665",
                    "family": "continuation_after_pullback",
                    "expr": "highdist360_ltm0p5 AND roc60_gt3 AND roc15_gt1",
                    "score": 63.18271,
                    "trades": 86.0,
                    "winrate": 56.976744,
                    "profit_pct": 18.249158,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 143,
                    "edge_id": "EDGE25KMORE_02456",
                    "family": "capitulation_recovery",
                    "expr": "edist21_lt0 AND atrpct240_q95_gt AND lowdist100_gt4",
                    "score": 60.236024,
                    "trades": 151.0,
                    "winrate": 45.033113,
                    "profit_pct": 36.378222,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 144,
                    "edge_id": "T10SRR10_0028",
                    "family": "trend_pullback_reclaim",
                    "expr": "volz60_gt1 AND atrpct60_gt0p08 AND edist720_ltm0p35 AND rsi7_gt28 AND rsi7_lt55 AND roc3_gt0p12",
                    "score": 57.14,
                    "trades": 108.0,
                    "winrate": 59.259259,
                    "profit_pct": 65.918848,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 145,
                    "edge_id": "EDGE25KMORE_08768",
                    "family": "continuation_after_pullback",
                    "expr": "highdist360_ltm5 AND eslope8_gt0p1 AND lowdist360_gt2 AND volr720_gt2",
                    "score": 63.261998,
                    "trades": 56.0,
                    "winrate": 48.214286,
                    "profit_pct": 16.931963,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 146,
                    "edge_id": "ADD25K3_16952",
                    "family": "capitulation_recovery",
                    "expr": "atrpct60_gt0p08 AND roc15_ltm0p25 AND rsi28_lt28",
                    "score": 56.37,
                    "trades": 109.0,
                    "winrate": 55.045872,
                    "profit_pct": 64.25131,
                    "source": "edges2/top100_profitabelste_edges_machine_readable_complete_bundle_unzipped/top100_profitabelste_edges_detailed_machine_readable_complete.csv"
            },
            {
                    "rank": 147,
                    "edge_id": "EDGE25KMORE_16935",
                    "family": "trend_momentum",
                    "expr": "roc120_gt5 AND roc960_gt5 AND rsi5_gt55",
                    "score": 59.118537,
                    "trades": 131.0,
                    "winrate": 47.328244,
                    "profit_pct": 31.985017,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 148,
                    "edge_id": "EDGE25KMORE_04935",
                    "family": "continuation_after_pullback",
                    "expr": "highdist360_ltm1p5 AND eslope233_gt0p25 AND lowdist50_gt0p6 AND edist21_lt0",
                    "score": 59.554167,
                    "trades": 86.0,
                    "winrate": 47.674419,
                    "profit_pct": 23.797999,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 149,
                    "edge_id": "EDGE25KMORE_01689",
                    "family": "low_vol_trend_drift",
                    "expr": "atrpct60_q10_lt AND eslope50_gtm0p1 AND edist50_gt0p25",
                    "score": 59.325826,
                    "trades": 88.0,
                    "winrate": 50.0,
                    "profit_pct": 19.611883,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 150,
                    "edge_id": "EDGE25KMORE_07460",
                    "family": "trend_momentum",
                    "expr": "roc60_gt2p5 AND bbpos200_gt25 AND lowdist480_gt1p5",
                    "score": 60.402058,
                    "trades": 55.0,
                    "winrate": 49.090909,
                    "profit_pct": 12.007463,
                    "source": "edges/top100_edges_detailed.csv"
            },
            {
                    "rank": 151,
                    "edge_id": "EDGE25KMORE_03260",
                    "family": "trend_momentum",
                    "expr": "eslope55_gtm0p1 AND roc360_gt1p25 AND volr720_gt0p6 AND roc60_gt2p5",
                    "score": 34.728445,
                    "trades": 931.0,
                    "winrate": 47.583244,
                    "profit_pct": 207.969377,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top_profit_strict_candidate_pool.csv"
            },
            {
                    "rank": 152,
                    "edge_id": "EDGE10X500_04634",
                    "family": "trend_momentum",
                    "expr": "roc180_gt2 AND roc15_gt1 AND lowdist100_gt3",
                    "score": 39.800647,
                    "trades": 420.0,
                    "winrate": 50.714286,
                    "profit_pct": 160.370087,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 153,
                    "edge_id": "EDGE25KMORE_12944",
                    "family": "trend_momentum",
                    "expr": "roc180_gt0p15 AND roc90_gt3 AND closepos_gt35",
                    "score": 34.40466,
                    "trades": 745.0,
                    "winrate": 48.053691,
                    "profit_pct": 182.495989,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 154,
                    "edge_id": "EDGE25KMORE_00305",
                    "family": "continuation_after_pullback",
                    "expr": "roc720_ltm1p75 AND roc240_gt0p8 AND roc480_gt2p5",
                    "score": 54.763467,
                    "trades": 74.0,
                    "winrate": 39.189189,
                    "profit_pct": 15.249244,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 155,
                    "edge_id": "EDGE25KMORE_20290",
                    "family": "trend_momentum",
                    "expr": "roc960_gt0p4 AND rsi7_gt70 AND lowdist120_gt5",
                    "score": 52.435359,
                    "trades": 98.0,
                    "winrate": 57.142857,
                    "profit_pct": 23.118705,
                    "source": "edges/top250_edges_unconstrained_strict_pool.csv"
            },
            {
                    "rank": 156,
                    "edge_id": "EDGE10X500_00829",
                    "family": "trend_momentum",
                    "expr": "roc120_gt2p5 AND roc15_gt1p2 AND lowdist200_gt1",
                    "score": 37.154754,
                    "trades": 391.0,
                    "winrate": 50.127877,
                    "profit_pct": 145.839837,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top_profit_strict_candidate_pool.csv"
            },
            {
                    "rank": 157,
                    "edge_id": "EDGE25KMORE_12910",
                    "family": "trend_momentum",
                    "expr": "eslope55_gt0p6 AND edist200_gt0 AND lowdist360_gt0p6",
                    "score": 27.607653,
                    "trades": 732.0,
                    "winrate": 48.087432,
                    "profit_pct": 158.386008,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 158,
                    "edge_id": "EDGE10X500_02665",
                    "family": "trend_momentum",
                    "expr": "roc180_gt2p5 AND roc20_gt0p6 AND lowdist200_gt4",
                    "score": 27.438701,
                    "trades": 739.0,
                    "winrate": 47.361299,
                    "profit_pct": 151.990415,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 159,
                    "edge_id": "EDGE25KMORE_02198",
                    "family": "trend_momentum",
                    "expr": "eslope55_gt0p6 AND roc60_gt0p8 AND lowdist360_gt1",
                    "score": 26.026241,
                    "trades": 729.0,
                    "winrate": 47.8738,
                    "profit_pct": 151.080847,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 160,
                    "edge_id": "EDGE10X500_01862",
                    "family": "trend_momentum",
                    "expr": "roc120_gt4 AND roc5_gt0p2 AND lowdist200_gt2",
                    "score": 30.323692,
                    "trades": 325.0,
                    "winrate": 48.615385,
                    "profit_pct": 106.764595,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 161,
                    "edge_id": "EDGE25KMORE_14099",
                    "family": "trend_momentum",
                    "expr": "eslope55_gt0p6 AND edist34_gt0 AND volr480_gt0p4 AND volr720_gt0p5",
                    "score": 24.204424,
                    "trades": 699.0,
                    "winrate": 47.496423,
                    "profit_pct": 140.283152,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 162,
                    "edge_id": "EDGE10X500_04452",
                    "family": "mean_reversion_pullback",
                    "expr": "ddhigh480_ltm7 AND lowdist100_gt0p8 AND rsi14_gt25",
                    "score": 28.438252,
                    "trades": 368.0,
                    "winrate": 51.086957,
                    "profit_pct": 107.291177,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 163,
                    "edge_id": "EDGE25KMORE_06920",
                    "family": "trend_momentum",
                    "expr": "roc60_gt3 AND edist233_gt0 AND volr720_gt0p6",
                    "score": 26.025895,
                    "trades": 533.0,
                    "winrate": 50.093809,
                    "profit_pct": 122.914423,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 164,
                    "edge_id": "EDGE10X500_04381",
                    "family": "mean_reversion_pullback",
                    "expr": "bbpos100_lt15 AND highdist20_ltm2 AND lowdist480_gt0p25",
                    "score": 28.560293,
                    "trades": 277.0,
                    "winrate": 51.263538,
                    "profit_pct": 95.620352,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top_profit_strict_candidate_pool.csv"
            },
            {
                    "rank": 165,
                    "edge_id": "EDGE25KMORE_18720",
                    "family": "trend_momentum",
                    "expr": "roc240_gt1 AND roc30_gt2 AND lowdist120_gt0p8",
                    "score": 23.11835,
                    "trades": 624.0,
                    "winrate": 48.076923,
                    "profit_pct": 126.200742,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top_profit_strict_candidate_pool.csv"
            },
            {
                    "rank": 166,
                    "edge_id": "EDGE25KMORE_18966",
                    "family": "mean_reversion_pullback",
                    "expr": "ddhigh200_ltm4 AND highdist50_ltm1p5 AND lowdist240_gt0p6",
                    "score": 23.004295,
                    "trades": 608.0,
                    "winrate": 48.190789,
                    "profit_pct": 123.239478,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 167,
                    "edge_id": "EDGE25KMORE_22950",
                    "family": "trend_momentum",
                    "expr": "eslope21_gt0p25 AND roc120_gt2p5 AND rsi5_gt60",
                    "score": 22.915873,
                    "trades": 522.0,
                    "winrate": 53.256705,
                    "profit_pct": 116.946233,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top_profit_strict_candidate_pool.csv"
            },
            {
                    "rank": 168,
                    "edge_id": "EDGE25KMORE_08357",
                    "family": "breakout_expansion",
                    "expr": "edist144_gt2 AND bbw200_q90_gt AND liquidityraw_q80_gt",
                    "score": 21.187343,
                    "trades": 453.0,
                    "winrate": 54.083885,
                    "profit_pct": 99.62352,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 169,
                    "edge_id": "EDGE25KMORE_05633",
                    "family": "trend_momentum",
                    "expr": "roc180_gt3 AND body_gt0p2 AND lowdist720_gt2",
                    "score": 19.765837,
                    "trades": 469.0,
                    "winrate": 48.827292,
                    "profit_pct": 97.705608,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 170,
                    "edge_id": "EDGE10X500_04932",
                    "family": "trend_momentum",
                    "expr": "roc240_gt3 AND roc15_gt1p2 AND lowdist200_gt2",
                    "score": 20.977611,
                    "trades": 329.0,
                    "winrate": 55.015198,
                    "profit_pct": 86.238952,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 171,
                    "edge_id": "EDGE25KMORE_17640",
                    "family": "breakout_expansion",
                    "expr": "edist89_gt2 AND atrpct120_q20_gt AND volr240_gt1p2",
                    "score": 20.134122,
                    "trades": 352.0,
                    "winrate": 50.0,
                    "profit_pct": 83.942481,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 172,
                    "edge_id": "EDGE25KMORE_15248",
                    "family": "breakout_expansion",
                    "expr": "edist100_gt2 AND range_gt0p3 AND volr720_gt0p7",
                    "score": 20.254824,
                    "trades": 308.0,
                    "winrate": 50.974026,
                    "profit_pct": 80.089485,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 173,
                    "edge_id": "EDGE25KMORE_05826",
                    "family": "trend_momentum",
                    "expr": "roc180_gt0p25 AND edist100_gt2 AND eslope20_gt0 AND eslope8_gt0",
                    "score": 18.272454,
                    "trades": 429.0,
                    "winrate": 47.785548,
                    "profit_pct": 91.815789,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top_profit_strict_candidate_pool.csv"
            },
            {
                    "rank": 174,
                    "edge_id": "EDGE25KMORE_12543",
                    "family": "trend_momentum",
                    "expr": "eslope50_gt0p25 AND roc15_gt1p5 AND volz120_gt0",
                    "score": 17.733606,
                    "trades": 446.0,
                    "winrate": 50.896861,
                    "profit_pct": 94.120902,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 175,
                    "edge_id": "EDGE25KMORE_21390",
                    "family": "trend_momentum",
                    "expr": "roc360_gt0p15 AND edist20_gt0p1 AND eslope8_gt0p4 AND roc13_gt1",
                    "score": 18.786442,
                    "trades": 330.0,
                    "winrate": 49.69697,
                    "profit_pct": 82.596866,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 176,
                    "edge_id": "EDGE25KMORE_20275",
                    "family": "trend_momentum",
                    "expr": "roc960_gt5 AND rsi7_gt55 AND volz480_gt1p5",
                    "score": 17.479756,
                    "trades": 340.0,
                    "winrate": 47.647059,
                    "profit_pct": 76.750144,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top_profit_strict_candidate_pool.csv"
            },
            {
                    "rank": 177,
                    "edge_id": "EDGE10X500_01659",
                    "family": "trend_momentum",
                    "expr": "roc120_gt2p5 AND roc10_gt1p2 AND lowdist200_gt1 AND eslope100_gt0p2",
                    "score": 21.641512,
                    "trades": 108.0,
                    "winrate": 52.777778,
                    "profit_pct": 42.016274,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 178,
                    "edge_id": "EDGE10X500_00048",
                    "family": "mean_reversion_pullback",
                    "expr": "edist200_ltm2 AND lowdist60_gt0p8 AND eslope8_gtm0p4",
                    "score": 14.48818,
                    "trades": 306.0,
                    "winrate": 44.117647,
                    "profit_pct": 63.842481,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 179,
                    "edge_id": "EDGE25KMORE_09614",
                    "family": "trend_momentum",
                    "expr": "roc480_gt0p8 AND roc20_gt2 AND lowdist240_gt1p5",
                    "score": 13.731629,
                    "trades": 295.0,
                    "winrate": 53.898305,
                    "profit_pct": 64.666206,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            },
            {
                    "rank": 180,
                    "edge_id": "EDGE25KMORE_13364",
                    "family": "trend_momentum",
                    "expr": "eslope200_gt0p1 AND edist21_gt0p75 AND volz10_gt0 AND roc720_gt0p4",
                    "score": 13.77156,
                    "trades": 284.0,
                    "winrate": 48.943662,
                    "profit_pct": 62.921504,
                    "source": "edges/pioneer_edge_top100_profit_v6_20260529_bundle_unzipped/pioneer_edge_top100_profit_v6_20260529/top100_profitabelste_edges_detailed.csv"
            }
    ]

    FAMILY_TO_PATH: Dict[str, str] = {
        "trend_momentum": "continuation_momentum",
        "breakout_expansion": "breakout_expansion",
        "volatility_expansion_momentum": "breakout_expansion",
        "continuation_after_pullback": "trend_pullback",
        "trend_pullback_reclaim": "trend_pullback",
        "mean_reversion_pullback": "range_reversal",
        "range_mean_reversion": "range_reversal",
        "capitulation_recovery": "capitulation_recovery",
        "failed_breakdown_wick": "capitulation_recovery",
        "low_vol_trend_drift": "low_vol_drift",
        "candle_impulse_followthrough": "continuation_momentum",
        "wick_reversal": "range_reversal",
        "volume_climax_absorption": "capitulation_recovery",
        "candle_pattern": "range_reversal",
        "hybrid": "hybrid_recovery",
        "statistical_anomaly": "statistical_recovery",
    }

    ED8_REGIME_CODE: Dict[str, int] = {
        "none": 0,
        "dirty_chop": 1,
        "range_rotation": 2,
        "pullback_in_uptrend": 3,
        "clean_uptrend": 4,
        "breakout_expansion": 5,
        "volatility_shock": 6,
    }
    ED8_PATH_CODE: Dict[str, int] = {
        "no_path": 0,
        "range_reversal": 1,
        "trend_pullback": 2,
        "continuation_momentum": 3,
        "breakout_expansion": 4,
        "capitulation_recovery": 5,
        "low_vol_drift": 6,
        "hybrid_recovery": 7,
        "statistical_recovery": 8,
    }

    plot_config = {
        "main_plot": {
            "ema_60": {},
            "ema_240": {},
            "ema_720": {},
        },
        "subplots": {
            "ED8 Scores": {
                "entry_score": {},
                "meta_score": {},
                "regime_score": {},
                "risk_score": {},
            },
            "ED8 Edge Ensemble": {
                "edge_hits": {},
                "edge_score_avg": {},
                "exit_pressure": {},
            },
        },
    }

    @property
    def protections(self) -> List[Dict[str, Any]]:
        """Protections require --enable-protections in backtesting/hyperopt."""
        return [
            {"method": "CooldownPeriod", "stop_duration_candles": 12},
            {"method": "StoplossGuard", "lookback_period_candles": 720, "trade_limit": 3, "stop_duration_candles": 120, "only_per_pair": True},
            {"method": "MaxDrawdown", "lookback_period_candles": 1440, "trade_limit": 20, "stop_duration_candles": 360, "max_allowed_drawdown": 0.18},
            {"method": "LowProfitPairs", "lookback_period_candles": 1440, "trade_limit": 8, "stop_duration_candles": 240, "required_profit": -0.02, "only_per_pair": True},
        ]

    # -------------------------------------------------------------------------
    # Parameter helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _p(obj: Any, default: Any) -> Any:
        return getattr(obj, "value", default)

    @staticmethod
    def _safe_div(a: Any, b: Any, default: float = 0.0) -> Series:
        """Fast safe divide preserving the first Series index.

        Avoids repeated Series.replace/fillna chains in the indicator hotpath.
        """
        idx = getattr(a, "index", None)
        if idx is None:
            idx = getattr(b, "index", None)
        a_arr = a.to_numpy(dtype="float64", copy=False) if isinstance(a, Series) else np.asarray(a, dtype="float64")
        b_arr = b.to_numpy(dtype="float64", copy=False) if isinstance(b, Series) else np.asarray(b, dtype="float64")
        a_arr, b_arr = np.broadcast_arrays(a_arr, b_arr)
        out = np.full(a_arr.shape, float(default), dtype="float64")
        valid = np.isfinite(a_arr) & np.isfinite(b_arr) & (b_arr != 0.0)
        np.divide(a_arr, b_arr, out=out, where=valid)
        out[~np.isfinite(out)] = float(default)
        return Series(out, index=idx)

    @staticmethod
    def _num(raw: str) -> float:
        """Convert token number grammar: 0p25 -> 0.25, m0p6 -> -0.6."""
        cleaned = raw.strip().strip(".").replace("p", ".")
        if cleaned.startswith("m"):
            cleaned = "-" + cleaned[1:]
        return float(cleaned)

    @classmethod
    def _compiled_edge_expressions(cls) -> List[Tuple[int, float, str, str, List[List[str]]]]:
        """Compile edge expressions once per process.

        Return item format:
        (rank, score, family, edge_id, [[AND tokens], [OR group tokens], ...]).
        """
        cache = getattr(cls, "_EDGE_EXPR_TOKEN_CACHE", None)
        if cache is not None:
            return cache
        compiled: List[Tuple[int, float, str, str, List[List[str]]]] = []
        for edge in cls.EDGE_CATALOG:
            rank = int(edge["rank"])
            score = float(edge.get("score", 50.0))
            family = str(edge.get("family", "unknown"))
            edge_id = str(edge.get("edge_id", f"E{rank:03d}"))
            expr = str(edge.get("expr", ""))
            groups: List[List[str]] = []
            for group in re.split(r"\bOR\b", expr):
                tokens = [t.strip().strip(".") for t in re.split(r"\bAND\b|[()]", group) if t.strip().strip(".")]
                if tokens:
                    groups.append(tokens)
            compiled.append((rank, score, family, edge_id, groups))
        cls._EDGE_EXPR_TOKEN_CACHE = compiled
        return compiled

    @classmethod
    def _edge_tokens(cls) -> List[str]:
        cache = getattr(cls, "_EDGE_TOKENS_CACHE", None)
        if cache is not None:
            return cache
        tokens = sorted({token for *_head, groups in cls._compiled_edge_expressions() for group in groups for token in group})
        cls._EDGE_TOKENS_CACHE = tokens
        return tokens

    @classmethod
    def _parse_token(cls, token: str) -> Tuple[str, Optional[int], Optional[int], str, Optional[float]]:
        """Parse tokens like roc60_gt2p5, atrpct240_q95_gt, highdist100_ltm3 with a cache."""
        token = token.strip().strip(".")
        cache = getattr(cls, "_EDGE_PARSED_TOKEN_CACHE", None)
        if cache is None:
            cache = {}
            cls._EDGE_PARSED_TOKEN_CACHE = cache
        if token in cache:
            return cache[token]
        q_match = re.match(r"^([a-z]+)(\d+)?_q(\d+)_(gt|lt)$", token)
        if q_match:
            base, window, q, op = q_match.groups()
            parsed = (base, int(window) if window else None, int(q), op, None)
            cache[token] = parsed
            return parsed
        v_match = re.match(r"^([a-z]+)(\d+)?_(gt|lt)(.+)$", token)
        if not v_match:
            raise ValueError(f"Unsupported ED8 edge token: {token}")
        base, window, op, raw_value = v_match.groups()
        parsed = (base, int(window) if window else None, None, op, cls._num(raw_value))
        cache[token] = parsed
        return parsed

    @staticmethod
    def _rsi(close: Series, period: int) -> Series:
        # Keep the original pandas EWM semantics to preserve V705/V706 signals exactly.
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        return (100 - (100 / (1 + rs))).replace([np.inf, -np.inf], np.nan).fillna(50.0)

    @staticmethod
    def _atr(dataframe: DataFrame, period: int) -> Series:
        high = dataframe["high"].to_numpy(dtype="float64", copy=False)
        low = dataframe["low"].to_numpy(dtype="float64", copy=False)
        close = dataframe["close"].to_numpy(dtype="float64", copy=False)
        prev_close = np.empty_like(close)
        prev_close[0] = close[0] if close.size else np.nan
        prev_close[1:] = close[:-1]
        tr = np.maximum.reduce([np.abs(high - low), np.abs(high - prev_close), np.abs(low - prev_close)])
        return Series(tr, index=dataframe.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    @staticmethod
    def _quantile_window(window: Optional[int]) -> int:
        base = int(window or 120)
        return int(max(240, min(1440, base * 4)))

    @staticmethod
    def _fast_sanitize_numeric(dataframe: DataFrame) -> DataFrame:
        """Replace NaN/Inf only in float columns, never in datetime/string columns.

        Freqtrade 2026.x / pandas can pass timezone-aware candle timestamps as
        ``datetime64[ms, UTC]``. Those are pandas ExtensionDtype objects, not plain
        NumPy dtypes. Calling ``np.issubdtype(dtype, np.floating)`` on them raises
        ``TypeError: Cannot interpret 'datetime64[ms, UTC]' as a data type``.

        Use pandas' dtype guard instead, then mutate only real float columns that
        actually contain non-finite values. This keeps the fast path but makes the
        sanitizer robust against tz-aware date columns and other extension dtypes.
        """
        float_cols: List[str] = []
        for col, dtype in dataframe.dtypes.items():
            try:
                if pd.api.types.is_float_dtype(dtype):
                    float_cols.append(col)
            except (TypeError, ValueError):
                # Defensive: unknown extension dtypes are not numeric sanitizer targets.
                continue

        for col in float_cols:
            arr = dataframe[col].to_numpy(copy=False)
            if arr.size == 0:
                continue
            try:
                bad = ~np.isfinite(arr)
            except TypeError:
                # Nullable/extension floats may not expose a plain ndarray fast path.
                arr = dataframe[col].astype("float64").to_numpy(copy=True)
                bad = ~np.isfinite(arr)
            if bad.any():
                try:
                    arr[bad] = 0.0
                    dataframe[col] = arr
                except (ValueError, TypeError):
                    dataframe[col] = np.nan_to_num(arr.astype(float, copy=True), nan=0.0, posinf=0.0, neginf=0.0)
        return dataframe

    def _edge_candidate_positions(self, dataframe: DataFrame) -> np.ndarray:
        """Rows where the expensive edge ensemble can still influence an entry.

        If cheap non-edge gates already fail, edge_hits/edge_score cannot produce
        an entry. Setting edge columns to zero on those rows preserves trading
        decisions while reducing token/edge comparisons.
        """
        if not bool(getattr(self, "ED8_EDGE_PREFILTER_ENABLED", True)):
            return np.arange(len(dataframe), dtype=np.int64)
        if dataframe.empty or "hard_gate_pass" not in dataframe.columns:
            return np.arange(len(dataframe), dtype=np.int64)
        mask = (
            dataframe["hard_gate_pass"].to_numpy(dtype=bool, copy=False)
            & (dataframe["soft_gate_score"].to_numpy(copy=False) >= int(self._p(self.soft_gate_min, 1)))
            & (dataframe["regime_score"].to_numpy(copy=False) >= float(self._p(self.regime_score_min, 24)))
            & (dataframe["volume"].to_numpy(copy=False) > 0)
        )
        return np.flatnonzero(mask)

    def _eval_token_subset(self, dataframe: DataFrame, token: str, positions: np.ndarray) -> np.ndarray:
        """Evaluate one edge token only for selected row positions."""
        n = len(positions)
        if n == 0:
            return np.zeros(0, dtype=bool)
        base, window, q, op, value = self._parse_token(token)
        source_col = base if window is None else f"{base}_{window}"
        if source_col not in dataframe.columns:
            return np.zeros(n, dtype=bool)
        source = dataframe[source_col].to_numpy(copy=False)
        if q is not None:
            qcol = f"{source_col}_q{q}"
            if qcol not in dataframe.columns:
                return np.zeros(n, dtype=bool)
            threshold = dataframe[qcol].to_numpy(copy=False)
            if op == "gt":
                out = source[positions] > threshold[positions]
            else:
                out = source[positions] < threshold[positions]
        else:
            threshold_value = float(value)
            if op == "gt":
                out = source[positions] > threshold_value
            else:
                out = source[positions] < threshold_value
        return np.asarray(out, dtype=bool)

    # -------------------------------------------------------------------------
    # Indicator and feature layer
    # -------------------------------------------------------------------------
    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        """Build ED8 features with batched column insertion.

        V704 performance repair:
        - keeps indicator formulas unchanged;
        - caches edge-token parsing;
        - builds wide indicator columns in a dict and concatenates once;
        - prevents pandas DataFrame fragmentation before the edge/regime layers.
        """
        if dataframe.empty:
            return dataframe

        index = dataframe.index
        close = dataframe["close"].astype(float)
        high = dataframe["high"].astype(float)
        low = dataframe["low"].astype(float)
        open_ = dataframe["open"].astype(float)
        volume = dataframe["volume"].astype(float)

        feature_cols: Dict[str, Series] = {}

        def put(name: str, values: Any) -> Series:
            if isinstance(values, Series):
                series = values.reindex(index) if not values.index.equals(index) else values
            else:
                series = Series(values, index=index)
            feature_cols[name] = series
            return series

        def get_col(name: str, default: float = 0.0) -> Series:
            if name in feature_cols:
                return feature_cols[name]
            if name in dataframe.columns:
                return dataframe[name]
            return Series(default, index=index)

        put("bar_index", Series(np.arange(len(dataframe), dtype=np.int64), index=index))
        put("ed8_pair_ok", Series(np.int8(1 if metadata.get("pair", "BTC/USDC") == "BTC/USDC" else 0), index=index))

        candle_range = (high - low).replace(0, np.nan)
        put("range", self._safe_div(high - low, close).mul(100.0))
        put("closepos", self._safe_div(close - low, candle_range).mul(100.0).clip(0, 100))
        put("green", ((close - open_) / open_.replace(0, np.nan) * 100.0).replace([np.inf, -np.inf], np.nan).fillna(0.0))
        put("body", ((close - open_).abs() / open_.replace(0, np.nan) * 100.0).replace([np.inf, -np.inf], np.nan).fillna(0.0))
        put("lwick", self._safe_div(np.minimum(open_, close) - low, candle_range).mul(100.0).clip(0, 100))
        put("uwick", self._safe_div(high - np.maximum(open_, close), candle_range).mul(100.0).clip(0, 100))

        required: Dict[str, set] = {}
        quantile_features_set = set()
        for token in self._edge_tokens():
            base, window, q, _op, _value = self._parse_token(token)
            required.setdefault(base, set()).add(window)
            if q is not None:
                quantile_features_set.add((base, window, q))

        for base, windows in {
            "roc": [3, 5, 10, 30, 60, 120, 240, 480, 720, 960],
            "rsi": [7, 14, 21],
            "atrpct": [14, 60, 120, 240],
            "volr": [20, 60, 120, 240, 720],
            "volz": [20, 60, 120, 240, 720],
            "edist": [20, 60, 240, 720],
            "eslope": [20, 60, 240],
            "lowdist": [20, 60, 120, 240, 480, 720],
            "highdist": [20, 60, 120, 240, 480, 720],
            "bbw": [20, 50, 100, 200],
            "bbpos": [20, 50, 100, 200],
        }.items():
            required.setdefault(base, set()).update(windows)

        ema_windows = set(required.get("edist", set())) | set(required.get("eslope", set())) | {60, 240, 720}
        for window in sorted(w for w in ema_windows if w is not None):
            ema_col = f"ema_{window}"
            ema = get_col(ema_col, np.nan)
            if ema_col not in feature_cols and ema_col not in dataframe.columns:
                ema = close.ewm(span=int(window), adjust=False, min_periods=max(2, int(window * 0.35))).mean()
                put(ema_col, ema)
            if window in required.get("edist", set()) or window in {60, 240, 720}:
                put(f"edist_{window}", ((close / ema.replace(0, np.nan)) - 1.0).mul(100.0))
            if window in required.get("eslope", set()) or window in {60, 240}:
                slope_lag = max(1, min(5, int(window // 10) or 1))
                put(f"eslope_{window}", ema.pct_change(slope_lag).mul(100.0))

        for window in sorted(w for w in required.get("roc", set()) if w is not None):
            put(f"roc_{window}", close.pct_change(int(window)).mul(100.0))

        for window in sorted(w for w in required.get("rsi", set()) if w is not None):
            put(f"rsi_{window}", self._rsi(close, int(window)))

        lowdist_windows = set(required.get("lowdist", set()))
        highdist_windows = set(required.get("highdist", set())) | set(required.get("ddhigh", set()))
        for window in sorted(w for w in lowdist_windows if w is not None):
            rlow = low.rolling(int(window), min_periods=max(2, int(window * 0.35))).min()
            put(f"lowdist_{window}", ((close / rlow.replace(0, np.nan)) - 1.0).mul(100.0))
        for window in sorted(w for w in highdist_windows if w is not None):
            rhigh = high.rolling(int(window), min_periods=max(2, int(window * 0.35))).max()
            highdist = ((close / rhigh.replace(0, np.nan)) - 1.0).mul(100.0)
            put(f"highdist_{window}", highdist)
            put(f"ddhigh_{window}", highdist)

        for window in sorted(w for w in required.get("atrpct", set()) if w is not None):
            atr = self._atr(dataframe, int(window))
            put(f"atr_{window}", atr)
            put(f"atrpct_{window}", (atr / close.replace(0, np.nan)).mul(100.0))

        for window in sorted(w for w in required.get("volr", set()) | required.get("volz", set()) if w is not None):
            vmean = volume.rolling(int(window), min_periods=max(2, int(window * 0.35))).mean()
            vstd = volume.rolling(int(window), min_periods=max(2, int(window * 0.35))).std(ddof=0)
            put(f"volr_{window}", self._safe_div(volume, vmean, default=1.0))
            put(f"volz_{window}", self._safe_div(volume - vmean, vstd, default=0.0))

        for window in sorted(w for w in set(required.get("bbpos", set())) | set(required.get("bbw", set())) if w is not None):
            mid = close.rolling(int(window), min_periods=max(2, int(window * 0.35))).mean()
            std = close.rolling(int(window), min_periods=max(2, int(window * 0.35))).std(ddof=0)
            upper = mid + 2.0 * std
            lower = mid - 2.0 * std
            put(f"bbpos_{window}", self._safe_div(close - lower, upper - lower).mul(100.0).clip(-50, 150))
            put(f"bbw_{window}", self._safe_div(upper - lower, mid).mul(100.0))

        quote_volume = (close * volume).replace([np.inf, -np.inf], np.nan).fillna(0.0)
        qv_mean_120 = quote_volume.rolling(120, min_periods=30).mean()
        qv_std_120 = quote_volume.rolling(120, min_periods=30).std(ddof=0)
        put("liquidityraw", self._safe_div(quote_volume - qv_mean_120, qv_std_120, default=0.0))
        put("reversalraw", (
            get_col("lwick").div(100.0) * 0.45
            + get_col("closepos").div(100.0) * 0.30
            + (-get_col("roc_5", close.pct_change(5).mul(100.0))).clip(lower=0, upper=5).div(5.0) * 0.25
        ))

        for base, window, q in sorted(quantile_features_set, key=lambda x: (x[0], -1 if x[1] is None else int(x[1]), int(x[2]))):
            source_col = base if window is None else f"{base}_{window}"
            source = get_col(source_col, np.nan)
            if source_col not in feature_cols and source_col not in dataframe.columns:
                continue
            qwin = self._quantile_window(window)
            put(f"{source_col}_q{q}", source.rolling(qwin, min_periods=max(30, qwin // 4)).quantile(q / 100.0))

        if feature_cols:
            dataframe = pd.concat([dataframe, DataFrame(feature_cols, index=index)], axis=1, copy=False)

        dataframe = self._build_regime_fingerprint_gate_layer(dataframe)
        dataframe = self._build_edge_ensemble_layer(dataframe)
        dataframe = self._build_exit_pressure_layer(dataframe)

        dataframe = self._fast_sanitize_numeric(dataframe)
        if bool(getattr(self, "ED8_RETURN_COPY_AFTER_INDICATORS", False)):
            return dataframe.copy()
        return dataframe

    # -------------------------------------------------------------------------
    # Regime, fingerprint, gate, risk, meta layers
    # -------------------------------------------------------------------------
    def _build_regime_fingerprint_gate_layer(self, dataframe: DataFrame) -> DataFrame:
        close = dataframe["close"].astype(float)
        idx = dataframe.index
        ema60 = dataframe.get("ema_60", close.ewm(span=60, adjust=False).mean())
        ema240 = dataframe.get("ema_240", close.ewm(span=240, adjust=False).mean())
        ema720 = dataframe.get("ema_720", close.ewm(span=720, adjust=False).mean())
        roc60 = dataframe.get("roc_60", close.pct_change(60).mul(100.0)).fillna(0.0)
        roc240 = dataframe.get("roc_240", close.pct_change(240).mul(100.0)).fillna(0.0)
        rsi14 = dataframe.get("rsi_14", self._rsi(close, 14)).fillna(50.0)
        atr60 = dataframe.get("atrpct_60", Series(0.0, index=idx)).fillna(0.0)
        volr60 = dataframe.get("volr_60", Series(1.0, index=idx)).fillna(1.0)
        bbw100 = dataframe.get("bbw_100", Series(0.0, index=idx)).fillna(0.0)
        highdist120 = dataframe.get("highdist_120", Series(0.0, index=idx)).fillna(0.0)
        lowdist120 = dataframe.get("lowdist_120", Series(0.0, index=idx)).fillna(0.0)

        trend_score = (
            (close > ema240).astype(int) * 25
            + (ema60 > ema240).astype(int) * 20
            + (ema240 > ema720).astype(int) * 15
            + (dataframe.get("eslope_60", Series(0, index=idx)) > 0).astype(int) * 15
            + (roc240 > 0).astype(int) * 25
        )
        momentum_score = ((roc60.clip(-3, 3) + 3) / 6 * 45 + (rsi14.clip(25, 75) - 25) / 50 * 35 + (roc240 > 0).astype(int) * 20)
        volatility_score = (100 - (atr60.clip(0, 6) / 6 * 100)).clip(0, 100) * 0.55 + (bbw100.clip(0, 8) / 8 * 100).clip(0, 100) * 0.45
        liquidity_score = (volr60.clip(0, 2.5) / 2.5 * 100).clip(0, 100)
        quality_score = (trend_score * 0.35 + momentum_score * 0.25 + volatility_score * 0.20 + liquidity_score * 0.20).clip(0, 100)

        conditions = [
            (atr60 > atr60.rolling(720, min_periods=120).quantile(0.95).fillna(999)) | (roc60 < -4),
            (trend_score >= 70) & (roc60 > 0),
            (trend_score >= 55) & (highdist120 < -0.6) & (lowdist120 > 0.4),
            (bbw100 > bbw100.rolling(720, min_periods=120).quantile(0.80).fillna(999)) & (roc60 > 1.0),
            (trend_score < 45) & (atr60 < 3.5),
        ]
        choices = ["volatility_shock", "clean_uptrend", "pullback_in_uptrend", "breakout_expansion", "range_rotation"]
        active_regime = np.select(conditions, choices, default="dirty_chop")

        fingerprint_score = (
            (lowdist120.clip(0, 6) / 6 * 35)
            + ((-highdist120).clip(0, 6) / 6 * 25)
            + (dataframe["closepos"].clip(0, 100) / 100 * 20)
            + (dataframe["lwick"].clip(0, 100) / 100 * 20)
        ).clip(0, 100)
        active_fingerprint = np.select(
            [
                (dataframe["lwick"] > 55) & (dataframe["closepos"] > 50),
                (dataframe.get("bbw_50", Series(0, index=idx)) > dataframe.get("bbw_50_q80", Series(999, index=idx))),
                (trend_score >= 65) & (highdist120 < -0.5),
                (trend_score < 45) & (dataframe.get("bbpos_50", Series(50, index=idx)) < 25),
            ],
            ["liquidity_wick", "expansion_breakout", "trend_pullback", "range_mean_reversion_pocket"],
            default="mixed_context",
        )

        panic_component = (-dataframe.get("roc_5", Series(0, index=idx))).clip(0, 5) / 5 * 35
        vol_component = atr60.clip(0, 8) / 8 * 30
        liquidity_component = (1.0 - volr60.clip(0, 1)).clip(0, 1) * 20
        extension_component = dataframe.get("edist_240", Series(0, index=idx)).clip(0, 8) / 8 * 15
        risk_score = (panic_component + vol_component + liquidity_component + extension_component).clip(0, 100)
        risk_state = np.select(
            [risk_score >= 82, risk_score >= 65, risk_score >= 45],
            ["panic", "defensive", "elevated"],
            default="normal",
        )

        hard_gate_pass = (
            (dataframe["volume"] > 0)
            & (close > 0)
            & (dataframe["bar_index"] >= self.startup_candle_count)
            & (risk_score <= float(self._p(self.max_risk_score, 76)))
            & (volr60 > 0.12)
            & (dataframe["ed8_pair_ok"] == 1)
        )
        soft_gate_score = (
            (volr60 > 0.30).astype(int)
            + (atr60 < 5.0).astype(int)
            + (quality_score >= float(self._p(self.regime_score_min, 24))).astype(int)
            + (dataframe["closepos"] >= 20).astype(int)
            + (risk_score < 70).astype(int)
        )
        gate_pass_count = hard_gate_pass.astype(int) + soft_gate_score
        gate_fail_reason = np.select(
            [
                dataframe["volume"] <= 0,
                dataframe["bar_index"] < self.startup_candle_count,
                risk_score > float(self._p(self.max_risk_score, 76)),
                volr60 <= 0.12,
                dataframe["ed8_pair_ok"] != 1,
            ],
            ["zero_volume", "startup", "risk_veto", "liquidity_veto", "pair_veto"],
            default="none",
        )

        additions = {
            "regime_trend": trend_score.clip(0, 100),
            "regime_momentum": momentum_score.clip(0, 100),
            "regime_volatility": volatility_score.clip(0, 100),
            "regime_liquidity": liquidity_score.clip(0, 100),
            "regime_quality": quality_score,
            "regime_score": quality_score,
            "active_regime": Series(active_regime, index=idx),
            "active_regime_code": Series(active_regime, index=idx).map(self.ED8_REGIME_CODE).fillna(0).astype("int16"),
            "fingerprint_score": fingerprint_score,
            "active_fingerprint": Series(active_fingerprint, index=idx),
            "risk_score": risk_score,
            "risk_state": Series(risk_state, index=idx),
            "hard_gate_pass": hard_gate_pass,
            "soft_gate_score": soft_gate_score,
            "gate_pass_count": gate_pass_count,
            "gate_fail_count": 6 - gate_pass_count,
            "gate_fail_reason": Series(gate_fail_reason, index=idx),
        }
        dataframe = pd.concat([dataframe, DataFrame(additions, index=idx)], axis=1, copy=False)
        return dataframe

    # -------------------------------------------------------------------------
    # Edge token evaluation and ensemble layer
    # -------------------------------------------------------------------------
    def _series_for_token(self, dataframe: DataFrame, base: str, window: Optional[int], q: Optional[int]) -> Series:
        source_col = base if window is None else f"{base}_{window}"
        if q is not None:
            qcol = f"{source_col}_q{q}"
            if qcol not in dataframe.columns:
                return Series(False, index=dataframe.index)
            return dataframe[source_col] > dataframe[qcol]
        if source_col not in dataframe.columns:
            return Series(0.0, index=dataframe.index)
        return dataframe[source_col]

    def _eval_token(self, dataframe: DataFrame, token: str) -> Series:
        base, window, q, op, value = self._parse_token(token)
        if q is not None:
            source_col = base if window is None else f"{base}_{window}"
            qcol = f"{source_col}_q{q}"
            if source_col not in dataframe.columns or qcol not in dataframe.columns:
                return Series(False, index=dataframe.index)
            if op == "gt":
                return (dataframe[source_col] > dataframe[qcol]).fillna(False)
            return (dataframe[source_col] < dataframe[qcol]).fillna(False)
        series = self._series_for_token(dataframe, base, window, None)
        if op == "gt":
            return (series > float(value)).fillna(False)
        return (series < float(value)).fillna(False)

    def _condition_to_mask(self, dataframe: DataFrame, expr: str) -> Series:
        # The supplied pool uses simple AND expressions. OR support is kept for future source drift.
        or_groups = re.split(r"\bOR\b", str(expr))
        final_mask = Series(False, index=dataframe.index)
        for group in or_groups:
            tokens = [t.strip().strip(".") for t in re.split(r"\bAND\b|[()]", group) if t.strip().strip(".")]
            if not tokens:
                continue
            group_mask = Series(True, index=dataframe.index)
            for token in tokens:
                group_mask &= self._eval_token(dataframe, token)
            final_mask |= group_mask
        return final_mask.fillna(False)

    def _build_edge_ensemble_layer(self, dataframe: DataFrame) -> DataFrame:
        """Evaluate ED8 edges with V706 candidate-row prefiltering.

        Trading-equivalence principle:
        rows that fail hard/soft/regime/volume gates cannot enter later, so the
        expensive 180-edge ensemble is only evaluated on rows where it can still
        affect `enter_long`. Non-candidate rows receive neutral edge values.
        """
        index = dataframe.index
        n_rows = len(dataframe)
        positions = self._edge_candidate_positions(dataframe)
        n_pos = len(positions)

        edge_hits_arr = np.zeros(n_rows, dtype=np.int16)
        edge_score_sum_arr = np.zeros(n_rows, dtype=np.float64)
        best_rank_arr = np.zeros(n_rows, dtype=np.int16)
        best_score_arr = np.zeros(n_rows, dtype=np.float64)
        best_family_arr = np.full(n_rows, "none", dtype=object)
        best_edge_id_arr = np.full(n_rows, "none", dtype=object)

        export_edge_columns = bool(getattr(self, "ED8_EXPORT_EDGE_COLUMNS", False))
        edge_columns: Dict[str, Series] = {}

        if n_pos > 0:
            token_masks: Dict[str, np.ndarray] = {
                token: self._eval_token_subset(dataframe, token, positions)
                for token in self._edge_tokens()
            }

            edge_hits_sub = np.zeros(n_pos, dtype=np.int16)
            edge_score_sum_sub = np.zeros(n_pos, dtype=np.float64)
            best_rank_sub = np.zeros(n_pos, dtype=np.int16)
            best_score_sub = np.zeros(n_pos, dtype=np.float64)
            best_family_sub = np.full(n_pos, "none", dtype=object)
            best_edge_id_sub = np.full(n_pos, "none", dtype=object)

            false_sub = np.zeros(n_pos, dtype=bool)
            for rank, score, family, edge_id, groups in self._compiled_edge_expressions():
                if not groups:
                    mask_sub = false_sub.copy()
                else:
                    mask_sub = np.zeros(n_pos, dtype=bool)
                    for group in groups:
                        group_sub = np.ones(n_pos, dtype=bool)
                        for token in group:
                            group_sub &= token_masks.get(token, false_sub)
                        mask_sub |= group_sub

                if export_edge_columns:
                    full_mask = np.zeros(n_rows, dtype=np.int8)
                    full_mask[positions] = mask_sub.astype(np.int8)
                    edge_columns[f"ed8_e{rank:03d}"] = Series(full_mask, index=index)

                edge_hits_sub += mask_sub.astype(np.int16)
                edge_score_sum_sub += mask_sub.astype(np.float64) * score
                is_better = mask_sub & ((best_rank_sub == 0) | (score > best_score_sub))
                if is_better.any():
                    best_rank_sub[is_better] = rank
                    best_score_sub[is_better] = score
                    best_family_sub[is_better] = family
                    best_edge_id_sub[is_better] = edge_id

            edge_hits_arr[positions] = edge_hits_sub
            edge_score_sum_arr[positions] = edge_score_sum_sub
            best_rank_arr[positions] = best_rank_sub
            best_score_arr[positions] = best_score_sub
            best_family_arr[positions] = best_family_sub
            best_edge_id_arr[positions] = best_edge_id_sub

        if edge_columns:
            dataframe = pd.concat([dataframe, DataFrame(edge_columns, index=index)], axis=1, copy=False)

        edge_hits = Series(edge_hits_arr, index=index, dtype="int16")
        edge_score_sum = Series(edge_score_sum_arr, index=index)
        best_rank = Series(best_rank_arr, index=index, dtype="int16")
        best_score = Series(best_score_arr, index=index)
        best_family = Series(best_family_arr, index=index, dtype="object")
        best_edge_id = Series(best_edge_id_arr, index=index, dtype="object")

        edge_score_avg = self._safe_div(edge_score_sum, edge_hits.replace(0, np.nan), default=0.0).clip(0, 100)
        active_path = best_family.map(self.FAMILY_TO_PATH).fillna("no_path")
        active_path_code = active_path.map(self.ED8_PATH_CODE).fillna(0).astype("int16")
        active_regime_code = dataframe.get("active_regime_code", Series(0, index=index)).astype("int16")
        ed8_context_code = (active_regime_code.astype("int32") * 10000 + best_rank.astype("int32") * 10 + active_path_code.astype("int32")).astype("int32")
        trigger_score = (edge_hits.clip(0, 5) / 5 * 100).clip(0, 100)
        confirmation_score = (
            dataframe["soft_gate_score"].clip(0, 5) / 5 * 55
            + dataframe["fingerprint_score"].clip(0, 100) * 0.45
        ).clip(0, 100)
        risk_penalty = dataframe["risk_score"].clip(0, 100) * 0.55
        conflict_penalty = (edge_hits > 8).astype(int) * 8
        entry_path_score = (best_score.clip(0, 100) * 0.65 + trigger_score * 0.35).clip(0, 100)

        quarantine_ranks = list(self.ED8_QUARANTINE_EDGE_RANKS)
        shadow_ranks = list(self.ED8_SHADOW_EDGE_RANKS)
        quarantine_edge_flag = best_rank.isin(quarantine_ranks).astype("int8")
        shadow_edge_flag = best_rank.isin(shadow_ranks).astype("int8")
        clean_pullback_flag = (
            (dataframe["active_regime"] == "clean_uptrend")
            & (active_path.isin(["trend_pullback", "low_vol_drift"]))
        ).astype("int8")
        evidence_penalty = (
            quarantine_edge_flag * float(self._p(self.quarantine_edge_penalty, 14))
            + shadow_edge_flag * 5.0
            + clean_pullback_flag * float(self._p(self.clean_pullback_penalty, 8))
            + (active_path == "low_vol_drift").astype(int) * 10.0
        ).clip(0, 45)
        audit_repair_flag = Series(np.select(
            [quarantine_edge_flag == 1, shadow_edge_flag == 1, clean_pullback_flag == 1],
            ["quarantine_edge_penalty", "shadow_edge_penalty", "clean_pullback_penalty"],
            default="none",
        ), index=index)
        entry_score = (
            entry_path_score * 0.45
            + dataframe["regime_score"] * 0.20
            + dataframe["fingerprint_score"] * 0.15
            + confirmation_score * 0.20
            - risk_penalty
            - conflict_penalty
            - evidence_penalty
        ).clip(0, 100)
        meta_score = (
            entry_score * 0.72
            + edge_score_avg * 0.18
            + dataframe["regime_quality"] * 0.10
        ).clip(0, 100)
        meta_action = Series(np.select(
            [
                dataframe["hard_gate_pass"] & (edge_hits >= int(self._p(self.edge_hit_min, 1))) & (meta_score >= float(self._p(self.entry_score_min, 38))),
                dataframe["risk_score"] >= float(self._p(self.max_risk_score, 76)),
            ],
            ["ALLOW_ENTRY", "BLOCK_RISK"],
            default="WAIT",
        ), index=index)
        signal_conflict = ((edge_hits > 5) & (dataframe["risk_score"] > 65)).astype("int8")
        entry_collision = (edge_hits > 1).astype("int8")

        additions = {
            "edge_hits": edge_hits.clip(0, 32767),
            "best_edge_rank": best_rank,
            "best_edge_score": best_score.clip(0, 100),
            "active_path": active_path,
            "active_path_code": active_path_code,
            "ed8_context_code": ed8_context_code,
            "entry_score": entry_score,
            "meta_score": meta_score,
            "meta_action": meta_action,
            "signal_conflict": signal_conflict,
        }
        if bool(getattr(self, "ED8_EXPORT_DIAGNOSTIC_COLUMNS", False)):
            additions.update({
                "edge_score_sum": edge_score_sum,
                "edge_score_avg": edge_score_avg,
                "best_edge_family": best_family,
                "best_edge_id": best_edge_id,
                "trigger_score": trigger_score,
                "confirmation_score": confirmation_score,
                "risk_penalty": risk_penalty,
                "conflict_penalty": conflict_penalty,
                "entry_path_score": entry_path_score,
                "quarantine_edge_flag": quarantine_edge_flag,
                "shadow_edge_flag": shadow_edge_flag,
                "clean_pullback_flag": clean_pullback_flag,
                "evidence_penalty": evidence_penalty,
                "audit_repair_flag": audit_repair_flag,
                "entry_collision": entry_collision,
            })
        if bool(getattr(self, "ED8_EXPORT_EDGE_TAG_COLUMN", False)):
            additions["edge_tag"] = (
                "e" + best_rank.astype(int).astype(str).str.zfill(3)
                + "|" + active_path.astype(str).str.slice(0, 18)
                + "|s" + best_score.round(0).astype(int).astype(str)
            )
        dataframe = pd.concat([dataframe, DataFrame(additions, index=index)], axis=1, copy=False)
        return dataframe

    def _build_exit_pressure_layer(self, dataframe: DataFrame) -> DataFrame:
        roc5 = dataframe.get("roc_5", Series(0, index=dataframe.index)).fillna(0.0)
        roc30 = dataframe.get("roc_30", Series(0, index=dataframe.index)).fillna(0.0)
        rsi14 = dataframe.get("rsi_14", Series(50, index=dataframe.index)).fillna(50.0)
        atr60 = dataframe.get("atrpct_60", Series(0, index=dataframe.index)).fillna(0.0)
        close = dataframe["close"].astype(float)
        ema60 = dataframe.get("ema_60", close.ewm(span=60, adjust=False).mean())
        ema240 = dataframe.get("ema_240", close.ewm(span=240, adjust=False).mean())

        momentum_decay = ((roc5 < -0.25).astype(int) * 18 + (roc30 < -0.75).astype(int) * 18 + (rsi14 < 42).astype(int) * 10)
        regime_break = ((close < ema60).astype(int) * 15 + (ema60 < ema240).astype(int) * 12 + (dataframe["regime_score"] < 30).astype(int) * 10)
        vol_shock = ((roc5 < -2.5).astype(int) * 22 + (atr60 > atr60.rolling(720, min_periods=120).quantile(0.90).fillna(999)).astype(int) * 12)
        late_extension = ((dataframe.get("edist_240", Series(0, index=dataframe.index)) > 5).astype(int) * 8 + (rsi14 > 78).astype(int) * 8)
        dataframe["exit_pressure"] = (momentum_decay + regime_break + vol_shock + late_extension + dataframe["risk_score"] * 0.25).clip(0, 100)
        dataframe["exit_collision"] = ((dataframe["exit_pressure"] > 60) & (dataframe["meta_action"] == "ALLOW_ENTRY")).astype("int8")
        return dataframe

    # -------------------------------------------------------------------------
    # Entry and exit signal layers
    # -------------------------------------------------------------------------
    @classmethod
    def _encode_context(cls, regime: str, rank: int, path: str) -> int:
        return int(cls.ED8_REGIME_CODE.get(str(regime), 0)) * 10000 + int(rank) * 10 + int(cls.ED8_PATH_CODE.get(str(path), 0))

    @classmethod
    def _compact_after_exit_columns(cls, dataframe: DataFrame) -> DataFrame:
        """Final column compaction for fast trades-only backtests.

        This runs after populate_entry_trend/populate_exit_trend. It therefore
        cannot alter the generated signals; it only reduces DataFrame width held
        by Freqtrade/export paths. custom_exit() keeps the columns it needs.
        """
        # V711: keep all columns required by populate_entry_trend/populate_exit_trend.
        # Earlier UltraFast compaction dropped hard_gate_pass and crashed lookahead-analysis.
        base_keep = [
            "date", "open", "high", "low", "close", "volume",
            "enter_long", "enter_tag", "exit_long", "exit_tag",
            "active_regime", "active_path", "best_edge_rank", "best_edge_score",
            "edge_hits", "entry_score", "meta_score", "meta_action",
            "regime_score", "regime_quality", "risk_score", "risk_state",
            "exit_pressure", "hard_gate_pass", "soft_gate_score",
            "gate_fail_reason", "signal_conflict", "active_regime_code",
            "active_path_code", "ed8_context_code", "roc_5", "roc_30", "edist_60",
        ]
        signal_keep = base_keep + [
            "active_path", "best_edge_rank", "best_edge_score", "edge_hits",
            "entry_score", "meta_score", "regime_score", "regime_quality",
            "risk_state", "hard_gate_pass", "soft_gate_score", "gate_fail_reason",
            "active_regime_code", "active_path_code", "ed8_context_code",
        ]
        profile = str(getattr(cls, "ED8_COMPACT_PROFILE", "triage")).lower()
        if profile == "forensic":
            return dataframe
        keep_order = signal_keep if profile == "signal" else base_keep
        keep = [c for c in keep_order if c in dataframe.columns]
        return dataframe.loc[:, keep] if keep else dataframe

    def _context_match_array(self, dataframe: DataFrame, contexts: Iterable[Tuple[str, int, str]]) -> np.ndarray:
        """Fast matcher for (active_regime, best_edge_rank, active_path) contexts.

        V709 prefers int32 context codes and optionally a tiny Numba/LLVM kernel.
        String fallback is kept for forensic/source drift safety.
        """
        n_rows = len(dataframe)
        context_list = list(contexts)
        if not context_list:
            return np.zeros(n_rows, dtype=bool)
        if "ed8_context_code" in dataframe.columns:
            values = dataframe["ed8_context_code"].to_numpy(dtype=np.int32, copy=False)
            blocked = np.asarray([self._encode_context(r, rk, p) for r, rk, p in context_list], dtype=np.int32)
            if bool(getattr(self, "ED8_USE_NUMBA_NATIVE", True)) and ED8_NUMBA_AVAILABLE and blocked.size > 0:
                return _ed8_native_isin_i32(values, blocked)
            return np.isin(values, blocked)
        out = np.zeros(n_rows, dtype=bool)
        regime_arr = dataframe["active_regime"].astype(str).to_numpy(copy=False)
        rank_arr = dataframe["best_edge_rank"].fillna(-1).astype(np.int16).to_numpy(copy=False)
        path_arr = dataframe["active_path"].astype(str).to_numpy(copy=False)
        for regime, rank, path in context_list:
            out |= (regime_arr == str(regime)) & (rank_arr == int(rank)) & (path_arr == str(path))
        return out

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["enter_long"] = 0
        dataframe["enter_tag"] = ""

        required_entry_columns = {
            "hard_gate_pass": False, "soft_gate_score": 0, "edge_hits": 0,
            "regime_score": 0.0, "entry_score": 0.0, "meta_action": "BLOCK",
            "signal_conflict": 1, "volume": 0.0, "best_edge_rank": -1,
            "active_path": "no_path", "active_regime": "none", "risk_state": "unknown",
            "best_edge_score": 0.0, "ed8_context_code": -1,
        }
        for _col, _default in required_entry_columns.items():
            if _col not in dataframe.columns:
                dataframe[_col] = _default

        entry_mask = (
            dataframe["hard_gate_pass"].astype(bool)
            & (dataframe["soft_gate_score"] >= int(self._p(self.soft_gate_min, 1)))
            & (dataframe["edge_hits"] >= int(self._p(self.edge_hit_min, 1)))
            & (dataframe["regime_score"] >= float(self._p(self.regime_score_min, 24)))
            & (dataframe["entry_score"] >= float(self._p(self.entry_score_min, 38)))
            & (dataframe["meta_action"] == "ALLOW_ENTRY")
            & (dataframe["signal_conflict"] == 0)
            & (dataframe["volume"] > 0)
        )

        n_rows = len(dataframe)
        blocked_loss_context_arr = self._context_match_array(dataframe, self.ED8_BLOCKED_LOSS_CONTEXTS)
        shadow_loss_context_arr = self._context_match_array(dataframe, self.ED8_SHADOW_LOSS_CONTEXTS)
        rank_arr = dataframe["best_edge_rank"].fillna(-1).astype(np.int16).to_numpy(copy=False)
        path_arr = dataframe["active_path"].astype(str).to_numpy(copy=False)
        blocked_edge_rank_arr = np.isin(rank_arr, list(self.ED8_BLOCKED_EDGE_RANKS)) if self.ED8_BLOCKED_EDGE_RANKS else np.zeros(n_rows, dtype=bool)
        blocked_path_arr = np.isin(path_arr, list(self.ED8_BLOCKED_PATHS)) if self.ED8_BLOCKED_PATHS else np.zeros(n_rows, dtype=bool)
        blocked_regime_path_arr = np.zeros(n_rows, dtype=bool)
        if self.ED8_BLOCKED_REGIME_PATHS:
            regime_arr = dataframe["active_regime"].astype(str).to_numpy(copy=False)
            for blocked_regime, blocked_path in self.ED8_BLOCKED_REGIME_PATHS:
                blocked_regime_path_arr |= (regime_arr == str(blocked_regime)) & (path_arr == str(blocked_path))

        if bool(getattr(self, "ED8_EXPORT_BLOCK_COLUMNS", False)):
            block_additions = {
                "ed8_blocked_loss_context": Series(blocked_loss_context_arr.astype(np.int8), index=dataframe.index),
                "ed8_shadow_loss_context": Series(shadow_loss_context_arr.astype(np.int8), index=dataframe.index),
                "ed8_blocked_edge_rank": Series(blocked_edge_rank_arr.astype(np.int8), index=dataframe.index),
                "ed8_blocked_regime_path": Series(blocked_regime_path_arr.astype(np.int8), index=dataframe.index),
                "ed8_blocked_path": Series(blocked_path_arr.astype(np.int8), index=dataframe.index),
            }
            dataframe = pd.concat([dataframe, DataFrame(block_additions, index=dataframe.index)], axis=1, copy=False)

        allowed_entry_contexts = getattr(self, "ED8_ALLOWED_ENTRY_CONTEXTS", frozenset())
        if allowed_entry_contexts:
            allowed_context_arr = self._context_match_array(dataframe, allowed_entry_contexts)
            entry_mask = entry_mask & allowed_context_arr

        entry_mask = entry_mask & (~blocked_loss_context_arr) & (~blocked_edge_rank_arr) & (~blocked_regime_path_arr) & (~blocked_path_arr)

        dataframe.loc[entry_mask, "enter_long"] = 1
        if bool(entry_mask.any()):
            edge_tag_subset = (
                "e" + dataframe.loc[entry_mask, "best_edge_rank"].astype(int).astype(str).str.zfill(3)
                + "|" + dataframe.loc[entry_mask, "active_path"].astype(str).str.slice(0, 18)
                + "|s" + dataframe.loc[entry_mask, "best_edge_score"].round(0).astype(int).astype(str)
            )
            dataframe.loc[entry_mask, "enter_tag"] = (
                "ED8|"
                + dataframe.loc[entry_mask, "active_regime"].astype(str).str.slice(0, 14)
                + "|"
                + edge_tag_subset.str.slice(0, 32)
                + "|r"
                + dataframe.loc[entry_mask, "risk_state"].astype(str).str.slice(0, 8)
            ).str.slice(0, 64)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["exit_long"] = 0
        dataframe["exit_tag"] = ""
        exit_pressure_min = float(self._p(self.exit_pressure_min, 72))
        required_exit_columns = {
            "risk_score": 0.0, "exit_pressure": 0.0, "active_regime": "none",
            "regime_score": 0.0, "volume": 0.0, "edist_60": 0.0,
        }
        for _col, _default in required_exit_columns.items():
            if _col not in dataframe.columns:
                dataframe[_col] = _default

        roc5 = dataframe.get("roc_5", Series(0, index=dataframe.index))
        roc30 = dataframe.get("roc_30", Series(0, index=dataframe.index))
        vol_shock_exit = (roc5 < -3.2) & (dataframe["risk_score"] > 76)
        regime_break_exit = (
            (dataframe["exit_pressure"] >= exit_pressure_min + 8)
            & (dataframe["active_regime"].isin(["dirty_chop", "volatility_shock"]))
            & ((dataframe["risk_score"] >= 72) | (roc5 < -1.8) | (roc30 < -1.6))
        )
        momentum_decay_exit = (dataframe["exit_pressure"] >= exit_pressure_min + 10) & (roc30 < -1.2) & (dataframe["risk_score"] >= 62)
        structural_exit = (dataframe.get("edist_60", Series(0, index=dataframe.index)) < -1.8) & (dataframe["regime_score"] < 28) & (dataframe["risk_score"] >= 65)

        exit_mask = (vol_shock_exit | regime_break_exit | momentum_decay_exit | structural_exit) & (dataframe["volume"] > 0)
        dataframe.loc[exit_mask, "exit_long"] = 1
        dataframe.loc[vol_shock_exit & exit_mask, "exit_tag"] = "volatility_shock|risk_exit|risk_defensive"
        dataframe.loc[regime_break_exit & exit_mask & (dataframe["exit_tag"] == ""), "exit_tag"] = "regime_break|context_lost|risk_elevated"
        dataframe.loc[momentum_decay_exit & exit_mask & (dataframe["exit_tag"] == ""), "exit_tag"] = "momentum_decay|weakness|risk_elevated"
        dataframe.loc[structural_exit & exit_mask & (dataframe["exit_tag"] == ""), "exit_tag"] = "structural_stop|ema_break|risk_elevated"
        if bool(getattr(self, "ED8_COMPACT_AFTER_EXIT", False)):
            dataframe = self._compact_after_exit_columns(dataframe)
        return dataframe

    # -------------------------------------------------------------------------
    # Callback risk layer. iloc[-1] is intentionally only used in callbacks.
    # -------------------------------------------------------------------------
    def custom_stoploss(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> float:
        # V705: protect winners earlier and enforce a much smaller default loss envelope.
        # Returned values are trailing distances relative to current_rate.
        if current_profit > 0.050:
            return -0.006
        if current_profit > 0.030:
            return -0.008
        if current_profit > 0.018:
            return -0.011
        if current_profit > 0.009:
            return -0.015
        return float(self.stoploss)

    def custom_exit(
        self,
        pair: str,
        trade: Any,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs: Any,
    ) -> Optional[str]:
        tag = getattr(trade, "enter_tag", "") or ""
        try:
            trade_minutes_pre = (current_time - trade.open_date_utc).total_seconds() / 60.0
        except Exception:
            trade_minutes_pre = 0.0
        if "dirty_chop|e001|trend_pullback" in tag and trade_minutes_pre >= 10 and current_profit >= 0.008:
            return "profit_capture|e001_fast_save"
        if not hasattr(self, "dp") or self.dp is None:
            return None
        try:
            dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
            if dataframe is None or dataframe.empty:
                return None
            last = dataframe.iloc[-1]
        except Exception:
            return None

        open_time = getattr(trade, "open_date_utc", None) or getattr(trade, "open_date", None)
        trade_minutes = 0.0
        if open_time is not None:
            trade_minutes = max(0.0, (current_time - open_time).total_seconds() / 60.0)

        exit_pressure = float(last.get("exit_pressure", 0.0))
        risk_score = float(last.get("risk_score", 0.0))
        regime = str(last.get("active_regime", "unknown"))
        profit_decay_min = float(self._p(self.profit_decay_min, 0.018))
        defensive_stop_profit = float(self._p(self.defensive_stop_profit, -0.035))
        loss_exit_pressure_min = float(self._p(self.loss_exit_pressure_min, 88))
        loss_exit_risk_min = float(self._p(self.loss_exit_risk_min, 72))
        loss_exit_min_minutes = float(self._p(self.loss_exit_min_minutes, 90))

        if current_profit >= profit_decay_min and exit_pressure >= float(self._p(self.exit_pressure_min, 72)):
            return "profit_capture|exit_pressure|risk_normal"
        if current_profit >= 0.035 and regime in ("dirty_chop", "volatility_shock"):
            return "profit_capture|regime_degrade|risk_elevated"
        if trade_minutes >= float(self._p(self.time_decay_minutes, 1440)) and current_profit >= 0.003:
            return "time_decay|stale_profit|risk_normal"

        # V705: loss exits are intentionally earlier. The V704A backtests showed
        # average loss around -2.75% to -3.52% against average win around +0.96% to +0.99%.
        severe_context_loss = (exit_pressure >= loss_exit_pressure_min) or (risk_score >= loss_exit_risk_min) or (regime in ("volatility_shock", "dirty_chop"))
        if trade_minutes >= loss_exit_min_minutes and current_profit <= defensive_stop_profit and severe_context_loss:
            return "risk_stop|v705_context_loss_cut"
        if trade_minutes >= 10 and current_profit <= -0.022:
            return "risk_stop|v705_hard_loss_cap"
        if trade_minutes >= 180 and current_profit <= -0.012 and severe_context_loss:
            return "risk_stop|v705_stale_loss_cut"
        return None
