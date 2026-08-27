#!/usr/bin/env bash
set -euo pipefail

# FQT V25 market-order correctness wrapper.
# Freqtrade's official lookahead-analysis contract forces market orders to
# reduce false positives.  The prior V25 script explicitly enabled limit
# orders, so this wrapper removes that opt-in without changing any other
# preregistered stage, candidate or OOS interlock.

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
sed 's/[[:space:]]--allow-limit-orders[[:space:]]/ /g' fqt_v25/run_v25.sh > "$tmp"
chmod +x "$tmp"
bash "$tmp"
