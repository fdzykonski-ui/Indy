#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="$ROOT_DIR/reconstruction/freqtrade"
VENV_PYTHON="$UPSTREAM_DIR/.venv/bin/python"
export PYTHONPATH="$UPSTREAM_DIR"
BTC_USDC_1M="$UPSTREAM_DIR/user_data/data/binance/BTC_USDC-1m.parquet"
BTC_USDC_1M_SHA256="0b311b5a815a35c616d786c5eee0b67750213c8d5fb8d36e4403b425e4a762a9"

cd "$ROOT_DIR"
"$VENV_PYTHON" tools/audit_ohlcv.py \
  --input "$BTC_USDC_1M" \
  --output-dir audit/data_quality \
  --expected-sha256 "$BTC_USDC_1M_SHA256"
python tools/collect_results.py
python tools/audit_strategies.py
python tools/source_inventory.py
python tools/scan_secrets.py
python tools/statistical_stress.py
"$VENV_PYTHON" tools/extract_equity.py
python tools/summarize_causality.py
python tools/version_audit.py
"$VENV_PYTHON" tools/runtime_signal_audit.py
python tools/build_gate_matrix.py
python tools/build_notebook.py
python tools/validate_notebook.py
python tools/build_report_artifact.py

REPORT_BUILDER="${REPORT_BUILDER:-/root/.codex/plugins/cache/openai-curated-remote/data-analytics/0.2.8-13ceeea1f599/skills/build-report/scripts/deliver_portable_artifact.mjs}"
if [[ ! -f "$REPORT_BUILDER" ]]; then
  echo "BLOCKIERT: portable report builder not found at $REPORT_BUILDER" >&2
  exit 2
fi
node "$REPORT_BUILDER" \
  --input report/artifact.json \
  --output report/report.html | tee report/delivery_receipt.json
python tools/verify_project.py

echo "Development pipeline complete. Frozen OOS and canary were intentionally not run."
