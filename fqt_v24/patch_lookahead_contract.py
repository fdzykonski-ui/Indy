#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

helper_path = Path("freqtrade_src/freqtrade/optimize/analysis/lookahead_helpers.py")
helper_text = helper_path.read_text(encoding="utf-8")
helper_original = helper_text

helper_old = '''        config["max_open_trades"] = -1
        logger.info("Forced max_open_trades to -1 (same amount as there are pairs)")

        min_dry_run_wallet = 1000000000
        if get_dry_run_wallet(config) < min_dry_run_wallet:
            logger.info(
                "Dry run wallet was not set to 1 billion, pushing it up there "
                "just to avoid false positives"
            )
            config["dry_run_wallet"] = min_dry_run_wallet

        if "timerange" not in config:
            # setting a timerange is enforced here
            raise OperationalException(
                "Please set a timerange. "
                "Usually a few months are enough depending on your needs and strategy."
            )
        # fix stake_amount to 10k.
        # in a combination with a wallet size of 1 billion it should always be able to trade
        # no matter if they use custom_stake_amount as a small percentage of wallet size
        # or fixate custom_stake_amount to a certain value.
        logger.info("fixing stake_amount to 10k")
        config["stake_amount"] = 10000
'''
helper_new = '''        preserve_contract = bool(config.get("lookahead_preserve_portfolio_contract", False))
        if preserve_contract:
            logger.info(
                "FQT diagnostic: preserving production portfolio contract "
                "(max_open_trades, wallet and stake_amount)."
            )
        else:
            pair_count = max(len(config.get("exchange", {}).get("pair_whitelist", [])), 1)
            config["max_open_trades"] = pair_count
            logger.info(
                "FQT repair: forced max_open_trades to positive pair count "
                f"({pair_count}) instead of the generic -1 sentinel."
            )

            min_dry_run_wallet = 1000000000
            if get_dry_run_wallet(config) < min_dry_run_wallet:
                logger.info(
                    "Dry run wallet was not set to 1 billion, pushing it up there "
                    "just to avoid false positives"
                )
                config["dry_run_wallet"] = min_dry_run_wallet

            # Fix stake_amount to 10k in the generic helper lane.
            logger.info("fixing stake_amount to 10k")
            config["stake_amount"] = 10000

        if "timerange" not in config:
            # setting a timerange is enforced here
            raise OperationalException(
                "Please set a timerange. "
                "Usually a few months are enough depending on your needs and strategy."
            )
'''
if helper_old not in helper_text:
    raise SystemExit("Expected lookahead override block was not found; refusing to patch.")
helper_text = helper_text.replace(helper_old, helper_new, 1)
helper_path.write_text(helper_text, encoding="utf-8")

# Freqtrade's lookahead prepare_data() pre-populates entry/exit signals for
# indicator comparison and then passed the already-signalled frames into
# Backtesting.backtest(). Backtesting calls ft_advise_signals() again. This is
# harmless for idempotent strategies, but V14 deliberately compacts its frame in
# populate_exit_trend(). The second signal pass therefore receives a compacted
# frame without the indicator columns and produces zero entries. Normal
# backtesting applies signals once and yields 663 trades. Keep the signalled copy
# for comparison, but run the baseline backtest from indicator-only frames so the
# normal single signal pass is preserved.
lookahead_path = Path("freqtrade_src/freqtrade/optimize/analysis/lookahead.py")
lookahead_text = lookahead_path.read_text(encoding="utf-8")
lookahead_original = lookahead_text
lookahead_old = '''        temp_indicators = backtesting.strategy.advise_all_indicators(varholder.data)
        filled_indicators = dict()
        for pair, dataframe in temp_indicators.items():
            filled_indicators[pair] = backtesting.strategy.ft_advise_signals(
                dataframe, {"pair": pair}
            )
        varholder.indicators = filled_indicators
        varholder.result = self.get_result(backtesting, varholder.indicators)
'''
lookahead_new = '''        temp_indicators = backtesting.strategy.advise_all_indicators(varholder.data)
        filled_indicators = dict()
        for pair, dataframe in temp_indicators.items():
            filled_indicators[pair] = backtesting.strategy.ft_advise_signals(
                dataframe.copy(), {"pair": pair}
            )
        varholder.indicators = filled_indicators
        logger.info(
            "FQT repair: indicator comparison retains signalled frames, while "
            "the baseline backtest receives indicator-only frames to avoid a "
            "second ft_advise_signals pass on compacted data."
        )
        varholder.result = self.get_result(backtesting, temp_indicators)
'''
if lookahead_old not in lookahead_text:
    raise SystemExit("Expected lookahead prepare_data block was not found; refusing to patch.")
lookahead_text = lookahead_text.replace(lookahead_old, lookahead_new, 1)
lookahead_path.write_text(lookahead_text, encoding="utf-8")

receipt = {
    "contract": "FQT_V24_LOOKAHEAD_EXECUTION_AND_DOUBLE_SIGNAL_PATCH_V2",
    "helper_path": str(helper_path),
    "lookahead_path": str(lookahead_path),
    "helper_before_sha256": hashlib.sha256(helper_original.encode()).hexdigest(),
    "helper_after_sha256": hashlib.sha256(helper_text.encode()).hexdigest(),
    "lookahead_before_sha256": hashlib.sha256(lookahead_original.encode()).hexdigest(),
    "lookahead_after_sha256": hashlib.sha256(lookahead_text.encode()).hexdigest(),
    "root_cause": {
        "normal_backtest": "advise indicators, then ft_advise_signals once inside backtest",
        "old_lookahead": "ft_advise_signals in prepare_data, then ft_advise_signals again inside backtest",
        "strategy_interaction": "populate_exit_trend compacts the frame, so the second pass lacks required indicator columns and emits zero entries",
        "observed_symptom": "native lookahead baseline found zero result trades while the identical normal portfolio run had 663 trades",
    },
    "semantic_change": {
        "generic_lane": "replace -1 max_open_trades sentinel with positive pair count; retain 1B wallet and 10k stake overrides",
        "production_lane": "optional config flag preserves max_open_trades=2, wallet=1000 and stake_amount=unlimited",
        "lookahead_baseline": "apply strategy signals exactly once, matching normal Backtesting.backtest semantics",
        "indicator_comparison": "retain independently signalled frames for full-vs-cut indicator/signal comparison",
        "strategy_alpha": "unchanged",
    },
}
Path("evidence").mkdir(exist_ok=True)
Path("evidence/LOOKAHEAD_CONTRACT_PATCH_RECEIPT.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, indent=2))
