#!/usr/bin/env bash
set -euo pipefail

# FQT V26 official market-order correctness/data-contract wrapper.
#
# Extends the V25 market-order wrapper with a fail-closed timestamp-unit fix
# for pandas/Binance archive interoperability and an official-data horizon
# through 2026-08-14. Candidate definitions and selection rules are unchanged.
python fqt_v25/patch_v26_timestamp_contract.py

# Freqtrade's documented lookahead contract uses market orders, large wallet,
# static stake and enough slots to minimize portfolio-capacity false positives.
# The prior V25 script explicitly enabled limit orders and preserved the
# production portfolio contract. This wrapper removes both overrides and
# injects a native four-pair recursive predecessor without changing candidates,
# known-data windows, stress tests or the one-shot OOS interlock.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
python - <<'PY' > "$tmp"
from pathlib import Path
text = Path('fqt_v25/run_v25.sh').read_text()
parse_line = "python fqt_v25/parse_iteration3b.py --artifact iteration3b_input --work iteration3b_work --out evidence/ITERATION3B_NORMALIZED_SUMMARY.json | tee logs/iteration3b_parse.log"
frozen_line = "cp fqt_v25/frozen_iteration3b_normalized_summary.json evidence/ITERATION3B_NORMALIZED_SUMMARY.json && printf '%s\\n' 'FQT_V26_FROZEN_ITERATION3B_RECEIPT: receipt_sha256=2106b23f7dcdf3a3976548bda806c526043024dfa15b4949bd046e846a16cc29 source_summary_sha256=5dca84a194a394e402fc1867d60d538face0eb4309a4bafb2692e9ecf2371f00 source_run=31812959072 source_artifact=9612713371' | tee logs/iteration3b_parse.log"
if parse_line not in text:
    raise SystemExit('iteration3b parse anchor not found')
text = text.replace(parse_line, frozen_line)
text = text.replace(' --allow-limit-orders ', ' ')
text = text.replace("c['lookahead_preserve_portfolio_contract']=True", "c['lookahead_preserve_portfolio_contract']=False")
text = text.replace("c['lookahead_allow_limit_orders']=True", "c['lookahead_allow_limit_orders']=False")
anchor = '# Combine current native lookahead with the completed Iteration-3B recursive receipt.'
replacement = '''# Run the native recursive predecessor under the same ranked config.\npython fqt_v25/run_recursive_gate.py --config config_mot1_ranked.json --strategy M4PioneerValidationV14 --timerange 20260101-20260116 --out evidence/V25_RECURSIVE_SUMMARY.json | tee logs/V25_RECURSIVE.log\n\n# Combine current native lookahead with the newly executed recursive receipt.'''
if anchor not in text:
    raise SystemExit('recursive injection anchor not found')
text = text.replace(anchor, replacement)
old = "rec=it.get('recursive') or {'pass':False,'status':'NOT_FOUND'}"
new = "rec=json.loads(pathlib.Path('evidence/V25_RECURSIVE_SUMMARY.json').read_text())"
if old not in text:
    raise SystemExit('recursive assignment anchor not found')
text = text.replace(old, new)
print(text, end='')
PY
chmod +x "$tmp"
bash "$tmp"
