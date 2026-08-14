#!/usr/bin/env python3
"""Apply evidence-only instrumentation and two boundary fixes to Freqtrade analysis code."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one marker, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    source = Path(args.source)
    helpers = source / "freqtrade/optimize/analysis/lookahead_helpers.py"
    lookahead = source / "freqtrade/optimize/analysis/lookahead.py"
    before = {str(path.relative_to(source)): sha(path) for path in [helpers, lookahead]}

    ht = helpers.read_text()
    if "FQT_IP07_HELPER_CONFIG_BEFORE" not in ht:
        ht = replace_once(ht, "import logging\n", "import json\nimport logging\n", "helpers import")
        marker = "    def calculate_config_overrides(config: Config):\n"
        insertion = '''    def calculate_config_overrides(config: Config):
        # FQT_IP07_HELPER_CONFIG_BEFORE: evidence-only snapshot.
        _safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(config.get("strategy", "unknown")))
        _evidence = Path("evidence/ip07/lookahead")
        _evidence.mkdir(parents=True, exist_ok=True)
        _keys = [
            "strategy", "max_open_trades", "dry_run_wallet", "stake_amount",
            "order_types", "entry_pricing", "exit_pricing", "enable_protections",
            "lookahead_allow_limit_orders", "timerange", "minimum_trade_amount",
            "targeted_trade_amount", "backtest_cache",
        ]
        (_evidence / f"HELPER_CONFIG_BEFORE_{_safe}.json").write_text(
            json.dumps({key: config.get(key) for key in _keys}, indent=2, default=str) + "\\n"
        )
'''
        ht = replace_once(ht, marker, insertion, "helpers before snapshot")
        end_marker = "        return config\n\n    @staticmethod\n    def initialize_single_lookahead_analysis"
        end_replacement = '''        # FQT_IP07_HELPER_CONFIG_AFTER: evidence-only snapshot.
        (_evidence / f"HELPER_CONFIG_AFTER_{_safe}.json").write_text(
            json.dumps({key: config.get(key) for key in _keys}, indent=2, default=str) + "\\n"
        )
        return config

    @staticmethod
    def initialize_single_lookahead_analysis'''
        ht = replace_once(ht, end_marker, end_replacement, "helpers after snapshot")
        # Boundary repair: a result exactly at minimum is accepted by the table/start logic.
        ht = replace_once(
            ht,
            'inst.current_analysis.total_signals > config["minimum_trade_amount"]',
            'inst.current_analysis.total_signals >= config["minimum_trade_amount"]',
            "CSV minimum boundary",
        )
        helpers.write_text(ht)

    lt = lookahead.read_text()
    if "FQT_IP07_FULL_RESULT_SNAPSHOT" not in lt:
        lt = replace_once(lt, "import logging\n", "import json\nimport logging\n", "lookahead import")
        start_marker = "    def start(self) -> None:\n        super().start()\n\n        reduce_verbosity_for_bias_tester()\n"
        start_replacement = '''    def start(self) -> None:
        super().start()

        # FQT_IP07_FULL_RESULT_SNAPSHOT: evidence-only full-backtest diagnostics.
        _results = self.full_varHolder.result["results"]
        _safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(self.local_config.get("strategy", "unknown")))
        _evidence = Path("evidence/ip07/lookahead")
        _evidence.mkdir(parents=True, exist_ok=True)
        _exit_counts = (
            _results["exit_reason"].astype(str).value_counts().to_dict()
            if "exit_reason" in _results.columns else {}
        )
        _pair_counts = (
            _results["pair"].astype(str).value_counts().to_dict()
            if "pair" in _results.columns else {}
        )
        (_evidence / f"FULL_RESULT_{_safe}.json").write_text(
            json.dumps(
                {
                    "strategy": self.local_config.get("strategy"),
                    "rows": int(_results.shape[0]),
                    "columns": list(_results.columns),
                    "exit_reason_counts": _exit_counts,
                    "pair_counts": _pair_counts,
                    "from_dt": str(self.full_varHolder.from_dt),
                    "to_dt": str(self.full_varHolder.to_dt),
                    "max_open_trades": self.local_config.get("max_open_trades"),
                    "dry_run_wallet": self.local_config.get("dry_run_wallet"),
                    "stake_amount": self.local_config.get("stake_amount"),
                    "order_types": self.local_config.get("order_types"),
                },
                indent=2,
                default=str,
            ) + "\\n"
        )

        reduce_verbosity_for_bias_tester()
'''
        lt = replace_once(lt, start_marker, start_replacement, "lookahead result snapshot")
        # Boundary repair: previous +1 reported one trade when the result frame was empty.
        lt = replace_once(
            lt,
            'found_signals: int = self.full_varHolder.result["results"].shape[0] + 1',
            'found_signals: int = self.full_varHolder.result["results"].shape[0]',
            "found signals off-by-one",
        )
        lookahead.write_text(lt)

    after = {str(path.relative_to(source)): sha(path) for path in [helpers, lookahead]}
    out = {
        "contract": "FQT_V23_IP07_FREQTRADE_ANALYSIS_INSTRUMENTATION_V1",
        "source": str(source),
        "before_sha256": before,
        "after_sha256": after,
        "changes": [
            "lookahead helper config before/after snapshots",
            "full backtest result shape/pair/exit snapshots",
            "found_signals off-by-one +1 removed",
            "CSV export minimum boundary changed from > to >=",
        ],
        "strategy_semantics_changed": False,
        "backtesting_semantics_changed": False,
        "analysis_harness_changed": True,
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
