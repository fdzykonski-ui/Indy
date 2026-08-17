#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UPSTREAM_DIR="$ROOT_DIR/reconstruction/freqtrade"
VENV_PYTHON="$UPSTREAM_DIR/.venv/bin/python"
RUN_LABEL="${RUN_LABEL:-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="$ROOT_DIR/runtime/runs/$RUN_LABEL"
RESULT_DIR="$RUN_DIR/results"
LOG_DIR="$RUN_DIR/logs"
mkdir -p "$RESULT_DIR" "$LOG_DIR"
export PYTHONPATH="$UPSTREAM_DIR:$ROOT_DIR"

run_ft() {
  local log_name="$1"
  shift
  (
    cd "$UPSTREAM_DIR"
    "$VENV_PYTHON" "$ROOT_DIR/tools/run_freqtrade_offline.py" "$@"
  ) 2>&1 | tee "$LOG_DIR/$log_name.log"
}

COMMON=(
  --config "$ROOT_DIR/configs/common_research_1000usdc.json"
  --timeframe 1m
  --fee 0.001
  --cache none
  --no-color
)

mkdir -p \
  "$RESULT_DIR/champion_train" \
  "$RESULT_DIR/champion_development" \
  "$RESULT_DIR/baselines_train" \
  "$RESULT_DIR/challengers_train" \
  "$RESULT_DIR/champion_ablation" \
  "$RESULT_DIR/champion_fee_002" \
  "$RESULT_DIR/champion_fee_003"

run_ft version --version
run_ft champion_train backtesting "${COMMON[@]}" \
  --strategy-path "$ROOT_DIR/champion/frozen" --strategy ED8 \
  --timerange 20260101-20260301 --export trades \
  --backtest-directory "$RESULT_DIR/champion_train"
run_ft champion_development backtesting "${COMMON[@]}" \
  --strategy-path "$ROOT_DIR/champion/frozen" --strategy ED8 \
  --timerange 20260101-20260501 --export trades \
  --backtest-directory "$RESULT_DIR/champion_development"
run_ft baselines_train backtesting "${COMMON[@]}" \
  --strategy-path "$ROOT_DIR/strategies" \
  --strategy-list CashBaseline BuyHoldBaseline EMACrossoverBaseline SMACrossoverBaseline \
    BreakoutBaseline ROIOnlyBaseline StoplossOnlyBaseline RandomSignalControl \
  --timerange 20260101-20260301 --export trades \
  --backtest-directory "$RESULT_DIR/baselines_train"
run_ft challengers_train backtesting "${COMMON[@]}" \
  --strategy-path "$ROOT_DIR/strategies" \
  --strategy-list CausalRegimePullbackV1 Delay1CausalRegimePullbackV1 \
    Delay2CausalRegimePullbackV1 NoVolumeAblationV1 ROIOnlyExitAblationV1 \
    ReversedSignalControlV1 CausalRegimePullbackV2 Delay1CausalRegimePullbackV2 \
    Delay2CausalRegimePullbackV2 RandomSignalControl \
  --timerange 20260101-20260301 --export trades \
  --backtest-directory "$RESULT_DIR/challengers_train"
run_ft champion_fee_002 backtesting "${COMMON[@]}" --fee 0.002 \
  --strategy-path "$ROOT_DIR/champion/frozen" --strategy ED8 \
  --timerange 20260101-20260501 --export trades \
  --backtest-directory "$RESULT_DIR/champion_fee_002"
run_ft champion_fee_003 backtesting "${COMMON[@]}" --fee 0.003 \
  --strategy-path "$ROOT_DIR/champion/frozen" --strategy ED8 \
  --timerange 20260101-20260501 --export trades \
  --backtest-directory "$RESULT_DIR/champion_fee_003"
run_ft champion_ablation backtesting "${COMMON[@]}" \
  --strategy-path "$ROOT_DIR/champion/controls" \
  --strategy-list ED8Delay1 ED8Delay2 ED8NoCustomExitAblation \
    ED8ROIOnlyExitAblation ED8OnlyE001EntryAblation ED8WithoutE001EntryAblation \
  --timerange 20260101-20260501 --export trades \
  --backtest-directory "$RESULT_DIR/champion_ablation"
run_ft champion_lookahead lookahead-analysis "${COMMON[@]}" \
  --strategy-path "$ROOT_DIR/champion/frozen" --strategy ED8 \
  --timerange 20260101-20260501 --minimum-trade-amount 10 \
  --targeted-trade-amount 20 --lookahead-analysis-exportfilename "$RESULT_DIR/champion_lookahead.csv"
run_ft champion_recursive recursive-analysis "${COMMON[@]}" \
  --strategy-path "$ROOT_DIR/champion/frozen" --strategy ED8 \
  --timerange 20260101-20260501 --startup-candle 499 999 1599 1600 1800 2999 4999

echo "Engine suite complete: $RUN_DIR"
echo "Frozen OOS 20260502-20260509 and dry-run trading were intentionally not run."
