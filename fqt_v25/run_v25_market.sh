#!/usr/bin/env bash
set -euo pipefail

# FQT V25 official market-order correctness wrapper.
#
# Freqtrade's documented lookahead contract uses market orders, large wallet,
# static stake and enough slots to minimize portfolio-capacity false positives.
# The prior V25 script explicitly enabled limit orders and preserved the
# production portfolio contract.  This wrapper removes both overrides without
# changing candidates, known-data windows, stress tests or the OOS interlock.

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
python - <<'PY' > "$tmp"
from pathlib import Path
text = Path('fqt_v25/run_v25.sh').read_text()
text = text.replace(' --allow-limit-orders ', ' ')
text = text.replace("c['lookahead_preserve_portfolio_contract']=True", "c['lookahead_preserve_portfolio_contract']=False")
text = text.replace("c['lookahead_allow_limit_orders']=True", "c['lookahead_allow_limit_orders']=False")
print(text, end='')
PY
chmod +x "$tmp"
bash "$tmp"
