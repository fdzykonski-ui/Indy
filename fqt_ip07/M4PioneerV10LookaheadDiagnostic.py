from __future__ import annotations

import M4PioneerStableExposureV10 as frozen


class M4PioneerV10LookaheadDiagnostic(frozen.M4PioneerStableExposureV10):
    """Execution-neutral correctness harness for the frozen V10/V14 alpha.

    Indicator, entry-signal and dataframe exit-signal callbacks are inherited
    unchanged.  Only execution callbacks and execution parameters are neutralized
    so Freqtrade's generic lookahead helper can complete enough trades for a
    signal-generation verdict.  This class is diagnostic-only and must never be
    promoted, dry-run or traded live.
    """

    minimal_roi = {"0": 0.001}
    stoploss = -0.02
    trailing_stop = False
    use_custom_stoploss = False
    position_adjustment_enable = False
    max_entry_position_adjustment = -1
    order_types = {
        "entry": "market",
        "exit": "market",
        "emergency_exit": "market",
        "force_entry": "market",
        "force_exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }
    order_time_in_force = {"entry": "GTC", "exit": "GTC"}

    def custom_stake_amount(self, *args, **kwargs):
        proposed = kwargs.get("proposed_stake")
        if proposed is None and len(args) >= 4:
            proposed = args[3]
        proposed = float(proposed or 10000.0)
        min_stake = kwargs.get("min_stake")
        max_stake = kwargs.get("max_stake")
        if min_stake is not None:
            proposed = max(proposed, float(min_stake))
        if max_stake is not None:
            proposed = min(proposed, float(max_stake))
        return proposed

    def custom_exit(self, *args, **kwargs):
        return None

    def custom_entry_price(self, *args, **kwargs):
        proposed = kwargs.get("proposed_rate")
        if proposed is None and len(args) >= 4:
            proposed = args[3]
        return float(proposed)

    def custom_exit_price(self, *args, **kwargs):
        proposed = kwargs.get("proposed_rate")
        if proposed is None and len(args) >= 4:
            proposed = args[3]
        return float(proposed)

    def confirm_trade_entry(self, *args, **kwargs):
        return True

    def confirm_trade_exit(self, *args, **kwargs):
        return True

    def adjust_trade_position(self, *args, **kwargs):
        return None

    def custom_roi(self, *args, **kwargs):
        return None
