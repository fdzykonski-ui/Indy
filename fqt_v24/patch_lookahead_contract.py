#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path

path = Path("freqtrade_src/freqtrade/optimize/analysis/lookahead_helpers.py")
text = path.read_text(encoding="utf-8")
original = text

old = '''        config["max_open_trades"] = -1
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
new = '''        preserve_contract = bool(config.get("lookahead_preserve_portfolio_contract", False))
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
if old not in text:
    raise SystemExit("Expected lookahead override block was not found; refusing to patch.")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")

receipt = {
    "contract": "FQT_V24_LOOKAHEAD_PORTFOLIO_CONTRACT_PATCH_V1",
    "path": str(path),
    "before_sha256": hashlib.sha256(original.encode()).hexdigest(),
    "after_sha256": hashlib.sha256(text.encode()).hexdigest(),
    "semantic_change": {
        "generic_lane": "replace -1 max_open_trades sentinel with positive pair count; retain 1B wallet and 10k stake overrides",
        "production_lane": "optional config flag preserves max_open_trades=2, wallet=1000 and stake_amount=unlimited",
        "strategy_alpha": "unchanged",
    },
}
Path("evidence").mkdir(exist_ok=True)
Path("evidence/LOOKAHEAD_CONTRACT_PATCH_RECEIPT.json").write_text(
    json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
)
print(json.dumps(receipt, indent=2))
