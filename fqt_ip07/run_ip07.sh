#!/usr/bin/env bash
set -euo pipefail

export PYTHONHASHSEED=0
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export NUMEXPR_NUM_THREADS=1

# Reuse the exact project source/data/runtime setup and deterministic champion
# reproduction.  This deliberately preserves the established provenance chain.
chmod +x fqt_ip04a/run_ip04a_v2.sh
fqt_ip04a/run_ip04a_v2.sh

mkdir -p evidence user_data/strategies
cp fqt_ip07/M4PioneerV10LookaheadDiagnostic.py user_data/strategies/

python - <<'PY'
import json
import pathlib

source = pathlib.Path("config_ip04.json")
config = json.loads(source.read_text())
# The diagnostic strategy uses market orders only so Freqtrade's generic helper
# does not need limit-order exceptions.  Alpha/dataframe callbacks are unchanged.
config["entry_pricing"]["price_side"] = "other"
config["exit_pricing"]["price_side"] = "other"
config["lookahead_allow_limit_orders"] = False
config["evidence_status"] = "IP07_EXECUTION_NEUTRAL_SIGNAL_DIAGNOSTIC_ONLY"
config["governance"] = {
    "alpha_change": False,
    "diagnostic_execution_only": True,
    "promotion_allowed": False,
    "oos_allowed": False,
    "dry_run_allowed": False,
    "live_trading_allowed": False,
}
pathlib.Path("config_ip07.json").write_text(json.dumps(config, indent=2) + "\n")
PY

python -m py_compile \
  user_data/strategies/M4PioneerStableExposureV10.py \
  user_data/strategies/M4PioneerV10LookaheadDiagnostic.py

python fqt_ip04a/seed/freqtrade_offline.py list-strategies \
  --userdir user_data \
  --strategy-path user_data/strategies \
  --no-color | tee evidence/ip07_list_strategies.log

python fqt_ip04a/seed/freqtrade_offline.py show-config \
  -c config_ip07.json \
  --no-color | tee evidence/ip07_show_config.log

# Hard alpha/dataframe parity gate across all 31 pairs and the complete frozen
# development interval.
python fqt_ip07/verify_signal_parity.py \
  --strategy-dir user_data/strategies \
  --config config_ip07.json \
  --out evidence/IP07_SIGNAL_PARITY.json \
  | tee evidence/ip07_signal_parity.log

# Full-universe recursive signal convergence workaround.  Indicator drift is
# retained in the evidence and does not silently close the official indicator
# recursive-analysis gate.
python fqt_ip07/full_recursive_matrix.py \
  --strategy user_data/strategies/M4PioneerStableExposureV10.py \
  --config config_ip07.json \
  --out evidence/IP07_RECURSIVE_MATRIX.json \
  --startup 800 1100 1600 2400 \
  --anchors 5 \
  | tee evidence/ip07_recursive_matrix.log

# Attempt the official tool as supplementary evidence.  A version/CLI/tool
# limitation is recorded but does not overwrite the custom full-universe result.
set +e
python fqt_ip04a/seed/freqtrade_offline.py recursive-analysis \
  -c config_ip07.json \
  --strategy-path user_data/strategies \
  -s M4PioneerStableExposureV10 \
  -i 1m \
  --timerange 20260101-20260501 \
  --startup-candle 800 1100 1600 2400 \
  --no-color 2>&1 | tee evidence/ip07_official_recursive.log
OFFICIAL_RECURSIVE_RC=${PIPESTATUS[0]}
echo "$OFFICIAL_RECURSIVE_RC" > evidence/ip07_official_recursive.rc
set -e

# Establish that the execution-neutral class yields sufficient completed trades.
python fqt_ip04a/seed/freqtrade_offline.py backtesting \
  -c config_ip07.json \
  --strategy-path user_data/strategies \
  -s M4PioneerV10LookaheadDiagnostic \
  -i 1m \
  --timerange 20260101-20260501 \
  --fee 0.001 \
  --export trades \
  --breakdown month \
  --cache none \
  --no-color 2>&1 | tee evidence/ip07_diagnostic_backtest.log

# Native Freqtrade signal-generation lookahead analysis on the parity-proven
# diagnostic execution class.
python fqt_ip04a/seed/freqtrade_offline.py lookahead-analysis \
  -c config_ip07.json \
  --strategy-path user_data/strategies \
  -s M4PioneerV10LookaheadDiagnostic \
  -i 1m \
  --timerange 20260101-20260501 \
  --fee 0.001 \
  --minimum-trade-amount 10 \
  --targeted-trade-amount 50 \
  --lookahead-analysis-exportfilename evidence/ip07_lookahead.csv \
  --no-color 2>&1 | tee evidence/ip07_lookahead.log

# The summarizer fails closed unless parity, recursive signal stability and a
# non-biased native lookahead verdict are all present.
python fqt_ip07/summarize_ip07.py \
  --root . \
  --out evidence/IP07_SUMMARY.json
