#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
export TERM=xterm
mkdir -p evidence/ip07/{setup,parity,matrix,lookahead,recursive,final}

# Reconstruct the exact source/data/runtime and re-establish deterministic V10 baseline evidence.
chmod +x fqt_ip04a/run_ip04a_v2.sh
set +e
fqt_ip04a/run_ip04a_v2.sh 2>&1 | tee evidence/ip07/setup/ip04a_setup_and_baseline.log
setup_rc=${PIPESTATUS[0]}
set -e
echo "$setup_rc" > evidence/ip07/setup/EXIT_CODE.txt
if [[ "$setup_rc" != "0" ]]; then
  cat > evidence/ip07/final/IP07_FINAL_STATUS.json <<EOF
{"contract":"FQT_V23_IP07_CORRECTNESS_GATE_CLOSURE_V1","status":"BLOCKED_SETUP","setup_exit_code":$setup_rc,"decision":"KEEP_CHAMPION","oos":"DO_NOT_OPEN","dry_run":"DO_NOT_START","live":"FORBIDDEN"}
EOF
  exit 0
fi

# Install the frozen V14 evidence boundary plus non-tradable diagnostics.
cp -f fqt_ip07/M4PioneerValidationV14Diagnostic.py user_data/strategies/
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py user_data/strategies/M4PioneerValidationV14Diagnostic.py
python fqt_ip04a/seed/freqtrade_offline.py list-strategies \
  -c config_ip04.json --strategy-path user_data/strategies --no-color \
  2>&1 | tee evidence/ip07/setup/list_strategies.log

# Evidence-only Freqtrade analysis instrumentation and boundary repairs.
python fqt_ip07/instrument_freqtrade.py \
  --source freqtrade_src \
  --out evidence/ip07/setup/INSTRUMENTATION_RECEIPT.json \
  2>&1 | tee evidence/ip07/setup/instrumentation.log

# Exact full-universe signal parity, future-append causality, collision and funnel audit.
set +e
python fqt_ip07/signal_parity.py \
  --config config_ip04.json \
  --datadir user_data/data/binance \
  --strategy-path user_data/strategies \
  --out-json evidence/ip07/parity/SIGNAL_PARITY.json \
  --out-csv evidence/ip07/parity/SIGNAL_PARITY.csv \
  2>&1 | tee evidence/ip07/parity/signal_parity.log
parity_rc=${PIPESTATUS[0]}
set -e
echo "$parity_rc" > evidence/ip07/parity/EXIT_CODE.txt
if [[ ! -s evidence/ip07/parity/SIGNAL_PARITY.json ]]; then
  echo '{"contract":"FQT_V23_IP07_FULL_UNIVERSE_SIGNAL_PARITY_V1","status":"FAIL","hard_failures":["no_output"]}' > evidence/ip07/parity/SIGNAL_PARITY.json
fi

# One-factor-at-a-time helper override matrix on January 2026.
set +e
python fqt_ip07/variant_matrix.py \
  --base-config config_ip04.json \
  --offline-wrapper fqt_ip04a/seed/freqtrade_offline.py \
  --timerange 20260101-20260201 \
  --outdir evidence/ip07/matrix \
  2>&1 | tee evidence/ip07/matrix/variant_matrix.log
matrix_rc=${PIPESTATUS[0]}
set -e
echo "$matrix_rc" > evidence/ip07/matrix/EXIT_CODE.txt
if [[ ! -s evidence/ip07/matrix/VARIANT_MATRIX.json ]]; then
  echo '{"contract":"FQT_V23_IP07_LOOKAHEAD_OVERRIDE_MATRIX_V1","status":"FAIL","diagnostic_sufficient_trades":false,"rows":[]}' > evidence/ip07/matrix/VARIANT_MATRIX.json
fi

# Full 31-pair native Freqtrade lookahead on the smallest sufficient diagnostic harness.
set +e
python fqt_ip07/run_lookahead_diagnostics.py \
  --base-config config_ip04.json \
  --offline-wrapper fqt_ip04a/seed/freqtrade_offline.py \
  --matrix evidence/ip07/matrix/VARIANT_MATRIX.json \
  --parity evidence/ip07/parity/SIGNAL_PARITY.json \
  --outdir evidence/ip07/lookahead \
  --timerange 20260101-20260501 \
  --minimum 10 \
  --target 50 \
  2>&1 | tee evidence/ip07/lookahead/lookahead_diagnostic.log
lookahead_rc=${PIPESTATUS[0]}
set -e
echo "$lookahead_rc" > evidence/ip07/lookahead/EXIT_CODE.txt
if [[ ! -s evidence/ip07/lookahead/LOOKAHEAD_DIAGNOSTIC_SUMMARY.json ]]; then
  echo '{"contract":"FQT_V23_IP07_DIAGNOSTIC_EQUIVALENT_NATIVE_LOOKAHEAD_V1","decision":"BLOCKED","diagnostic_equivalence_pass":false,"bias_detected_in_any_valid_run":false,"runs":[]}' > evidence/ip07/lookahead/LOOKAHEAD_DIAGNOSTIC_SUMMARY.json
fi

# Official command is first-pair-only; invoke once per pair for a true 31-pair matrix.
set +e
python fqt_ip07/recursive_matrix.py \
  --config config_ip04.json \
  --offline-wrapper fqt_ip04a/seed/freqtrade_offline.py \
  --lookahead-summary evidence/ip07/lookahead/LOOKAHEAD_DIAGNOSTIC_SUMMARY.json \
  --outdir evidence/ip07/recursive \
  --timerange 20260420-20260501 \
  --threshold-pct 0.1 \
  2>&1 | tee evidence/ip07/recursive/recursive_matrix.log
recursive_rc=${PIPESTATUS[0]}
set -e
echo "$recursive_rc" > evidence/ip07/recursive/EXIT_CODE.txt
if [[ ! -s evidence/ip07/recursive/RECURSIVE_MATRIX.json ]]; then
  echo '{"contract":"FQT_V23_IP07_FULL_31PAIR_RECURSIVE_MATRIX_V1","status":"FAIL","rows":[]}' > evidence/ip07/recursive/RECURSIVE_MATRIX.json
fi

# Consolidated fail-closed CAPA, funnel and next-work-package receipts.
python fqt_ip07/finalize_ip07.py \
  --parity evidence/ip07/parity/SIGNAL_PARITY.json \
  --matrix evidence/ip07/matrix/VARIANT_MATRIX.json \
  --lookahead evidence/ip07/lookahead/LOOKAHEAD_DIAGNOSTIC_SUMMARY.json \
  --recursive evidence/ip07/recursive/RECURSIVE_MATRIX.json \
  --instrumentation evidence/ip07/setup/INSTRUMENTATION_RECEIPT.json \
  --outdir evidence/ip07/final \
  2>&1 | tee evidence/ip07/final/finalize.log

python - <<'PY'
import hashlib,json,pathlib
root=pathlib.Path('evidence/ip07')
files=[]
for p in sorted(root.rglob('*')):
    if p.is_file():
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        files.append({'path':str(p),'bytes':p.stat().st_size,'sha256':h})
out={'contract':'FQT_V23_IP07_ARTIFACT_MANIFEST_V1','files':files}
(root/'IP07_ARTIFACT_MANIFEST.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'files':len(files)},indent=2))
PY

# Script returns success so workflow can always package evidence; enforcement is a separate step.
exit 0
