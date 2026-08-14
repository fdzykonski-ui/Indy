#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

mkdir -p evidence receipts reports tables logs configs user_data/strategies user_data/backtest_results

# Highest-value RQ and confirmation contract are sealed before outcome-producing runs.
python - <<'PY'
import hashlib,json,pathlib,datetime
p=pathlib.Path('fqt_v24/run_iteration3.sh')
plan={
 'contract':'FQT_V24_REGISTERED_ANALYSIS_PLAN_ITERATION3_V1',
 'utc_frozen':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'rq_id':'RQ-I3-LOOKAHEAD-CALLBACK-001',
 'claim':'The frozen V14 signal and callback system is future-causal under both a positive-pair-count native lookahead lane and the production portfolio contract.',
 'estimand':{
   'primary':'number and proportion of verified native entry/exit signals with any indicator/signal timestamp mismatch',
   'unit':'checked completed trade signal',
   'target':'0 biased signals among at least 10 checked signals in each native lane'
 },
 'population':'31 frozen Binance Spot USDC pairs, 1m, development [2026-01-01,2026-05-01)',
 'intervention_comparator':'generic helper with positive pair-count slots versus production contract max_open_trades=2, wallet=1000, stake=unlimited',
 'primary_endpoint':'explicit native has_bias=false with >=10 checked signals in both lanes',
 'secondary_endpoints':['V10↔V14 semantic ledger parity','callback-ledger instrumentation parity','portfolio-state sensitivity'],
 'falsification':['any biased entry/exit/indicator','<10 checked signals','signal/ledger mismatch','instrumentation changes trades'],
 'alternatives':['generic -1 sentinel incompatibility','capital/slot callback dependence','limit-order helper false positives','true future-data leakage'],
 'decision_rule':'PASS only if both native lanes have explicit has_bias=false and >=10 checked signals; otherwise INVALID/TEILWEISE and stop before recursive/alpha work',
 'fresh_oos':'forbidden/not opened',
 'dry_run':'forbidden/not started',
 'live':'forbidden',
 'script_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
}
pathlib.Path('receipts/REGISTERED_ANALYSIS_PLAN.json').write_text(json.dumps(plan,indent=2)+'\n')
pathlib.Path('reports/CAUSAL_DAG.md').write_text('''# Causal DAG — RQ-I3-LOOKAHEAD-CALLBACK-001\n\n`past candles → indicators → signals/tags → stake/slot/capital state → order/fill simulation → exits → trade outcome`\n\nPotential confounders/selection nodes: pair order, max-open-trades, wallet, stake proposal, limit fill model, force exits and truncated helper horizon. Future candles must have no arrow into historical indicators/signals/tags. The production and pair-count lanes separate the helper-sentinel mechanism from genuine signal leakage.\n''')
PY

# Reconstruct exact runtime/data and two deterministic V10 baseline runs.
chmod +x fqt_ip04a/run_ip04a_v2.sh
fqt_ip04a/run_ip04a_v2.sh 2>&1 | tee logs/ip04a_setup_and_baseline.log
cp evidence/IP04A_CONTINUOUS_RUN1.zip evidence/IP04A_CONTINUOUS_RUN1.zip

# Add V14 boundary and diagnostic-only classes, then patch only the analysis helper.
python fqt_v24/append_diagnostic_classes.py | tee logs/append_diagnostic_classes.log
python fqt_v24/patch_lookahead_contract.py | tee logs/patch_lookahead_contract.log
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py
python fqt_ip04a/seed/freqtrade_offline.py list-strategies --userdir user_data --strategy-path user_data/strategies --no-color | tee evidence/list_strategies_v24.log

# Config lanes.
python - <<'PY'
import json,pathlib
base=json.loads(pathlib.Path('config_ip04.json').read_text())
base['datadir']='user_data/data/binance'; base['user_data_dir']='user_data'
base['lookahead_allow_limit_orders']=True
base['evidence_status']='FQT_V24_ITERATION3'
for name,preserve in [('paircount',False),('production',True)]:
 c=json.loads(json.dumps(base)); c['lookahead_preserve_portfolio_contract']=preserve
 pathlib.Path(f'configs/config_{name}.json').write_text(json.dumps(c,indent=2)+'\n')
h=json.loads(json.dumps(base)); h['lookahead_allow_limit_orders']=False; h['lookahead_preserve_portfolio_contract']=True
pathlib.Path('configs/config_signal_harness.json').write_text(json.dumps(h,indent=2)+'\n')
PY

run_bt() {
  local label="$1"; local strategy="$2"; local config="$3"; local timerange="$4"; local fee="${5:-0.001}"
  local before newest
  before=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' | wc -l)
  set +e
  /usr/bin/time -v -o "evidence/time_${label}.txt" \
    python fqt_ip04a/seed/freqtrade_offline.py backtesting \
      -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m \
      --timerange "$timerange" --fee "$fee" --export trades --breakdown month --cache none --no-color \
      2>&1 | tee "evidence/${label}.log"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "$rc" > "evidence/${label}.exit_code"
  if [ "$rc" -ne 0 ]; then return "$rc"; fi
  newest=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  test -n "$newest"
  cp "$newest" "evidence/${label}.zip"
}

# Exact V14 main class parity against V10.
run_bt V14_CONTINUOUS_MAIN M4PioneerValidationV14 configs/config_production.json 20260101-20260501

# Callback/event-ledger scenarios on January. The plain and instrumented baseline must be ledger-identical.
make_scenario_config() {
  local label="$1"; local mot="$2"; local wallet="$3"; local reverse="$4"
  python - "$label" "$mot" "$wallet" "$reverse" <<'PY'
import json,pathlib,sys
label,mot,wallet,rev=sys.argv[1],int(sys.argv[2]),float(sys.argv[3]),sys.argv[4]=='true'
c=json.loads(pathlib.Path('configs/config_production.json').read_text())
c['max_open_trades']=mot; c['dry_run_wallet']=wallet; c['stake_amount']='unlimited'
if rev: c['exchange']['pair_whitelist']=list(reversed(c['exchange']['pair_whitelist']))
pathlib.Path(f'configs/scenario_{label}.json').write_text(json.dumps(c,indent=2)+'\n')
PY
}

make_scenario_config plain_mot2_wallet1000 2 1000 false
run_bt CALLBACK_plain_mot2_wallet1000 M4PioneerValidationV14 configs/scenario_plain_mot2_wallet1000.json 20260101-20260201

for spec in \
  'ledger_mot2_wallet1000 2 1000 false' \
  'ledger_mot1_wallet1000 1 1000 false' \
  'ledger_mot3_wallet1000 3 1000 false' \
  'ledger_mot31_wallet1000 31 1000 false' \
  'ledger_mot2_wallet500 2 500 false' \
  'ledger_mot2_wallet2000 2 2000 false' \
  'ledger_mot2_wallet1000_reverse 2 1000 true'; do
  set -- $spec; label="$1"; mot="$2"; wallet="$3"; reverse="$4"
  make_scenario_config "$label" "$mot" "$wallet" "$reverse"
  export FQT_CALLBACK_LEDGER_PATH="$PWD/evidence/callback_${label}.json"
  export FQT_CALLBACK_LEDGER_SAMPLE_LIMIT=100
  run_bt "CALLBACK_${label}" M4PioneerValidationV14CallbackLedger "configs/scenario_${label}.json" 20260101-20260201
  unset FQT_CALLBACK_LEDGER_PATH FQT_CALLBACK_LEDGER_SAMPLE_LIMIT
done

run_lookahead() {
  local label="$1"; local strategy="$2"; local config="$3"
  rm -f "evidence/lookahead_${label}.csv"
  set +e
  /usr/bin/time -v -o "evidence/time_lookahead_${label}.txt" \
    python fqt_ip04a/seed/freqtrade_offline.py lookahead-analysis \
      -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m \
      --timerange 20260101-20260501 --fee 0.001 \
      --minimum-trade-amount 5 --targeted-trade-amount 12 \
      --lookahead-analysis-exportfilename "evidence/lookahead_${label}.csv" --no-color \
      2>&1 | tee "evidence/lookahead_${label}.log"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "$rc" > "evidence/lookahead_${label}.exit_code"
}

run_lookahead paircount M4PioneerValidationV14 configs/config_paircount.json
run_lookahead production M4PioneerValidationV14 configs/config_production.json
run_lookahead signal_harness M4PioneerValidationV14SignalHarness configs/config_signal_harness.json

python fqt_v24/summarize_iteration3.py | tee logs/iteration3_summary_first_pass.log

# Only after both native lookahead lanes PASS, execute the full recursive universe.
if python - <<'PY'
import json,sys
s=json.load(open('evidence/FINAL_ITERATION3_SUMMARY.json'))
sys.exit(0 if s['lookahead_gate']=='PASS' else 1)
PY
then
  mkdir -p evidence/recursive31
  python - <<'PY'
import json,pathlib
pairs=json.load(open('configs/config_production.json'))['exchange']['pair_whitelist']
pathlib.Path('evidence/recursive31/pairs.json').write_text(json.dumps(pairs,indent=2)+'\n')
PY
  while IFS= read -r pair; do
    safe=${pair//\//_}
    set +e
    python fqt_ip04a/seed/freqtrade_offline.py recursive-analysis \
      -c configs/config_production.json --strategy-path user_data/strategies \
      -s M4PioneerValidationV14 -i 1m --timerange 20260401-20260501 \
      -p "$pair" --startup-candle 200 400 800 1100 1600 --no-color \
      2>&1 | tee "evidence/recursive31/${safe}.log"
    rc=${PIPESTATUS[0]}
    set -e
    echo "$rc" > "evidence/recursive31/${safe}.exit_code"
  done < <(python - <<'PY'
import json
print('\n'.join(json.load(open('configs/config_production.json'))['exchange']['pair_whitelist']))
PY
)
  python - <<'PY'
import json,pathlib,re
root=pathlib.Path('evidence/recursive31'); rows=[]
for lp in sorted(root.glob('*.log')):
    pair=lp.stem.replace('_','/',1)
    log=lp.read_text(errors='replace'); rc=int(lp.with_suffix('.exit_code').read_text())
    table=log.split('Recursive Analysis')[-1]
    vals=[abs(float(x)) for x in re.findall(r'(-?\d+\.\d+)%',table)]
    no_bias='No lookahead bias on indicators found.' in log
    maxdev=max(vals) if vals else None
    passed=rc==0 and no_bias and maxdev is not None and maxdev<=0.001
    rows.append({'pair':pair,'exit_code':rc,'indicator_lookahead_no_bias':no_bias,'max_abs_deviation_pct':maxdev,'pass':passed})
out={'contract':'FQT_V24_RECURSIVE_31PAIR_V1','status':'PASS' if all(r['pass'] for r in rows) and len(rows)==31 else 'FAIL','pair_count':len(rows),'passed_pairs':sum(r['pass'] for r in rows),'tolerance_pct':0.001,'rows':rows}
pathlib.Path('evidence/RECURSIVE_31PAIR_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({'status':out['status'],'pair_count':len(rows),'passed_pairs':out['passed_pairs']},indent=2))
PY
  python fqt_v24/summarize_iteration3.py | tee logs/iteration3_summary_final.log
else
  echo 'Recursive full universe NOT_RUN: native lookahead predecessor did not PASS in both lanes.' | tee evidence/recursive31_NOT_RUN.txt
fi

# Explicit deviation/negative-result and command ledgers.
python - <<'PY'
import json,pathlib,datetime,glob,hashlib
now=datetime.datetime.now(datetime.timezone.utc).isoformat()
summary=json.load(open('evidence/FINAL_ITERATION3_SUMMARY.json'))
pathlib.Path('evidence/ANALYSIS_DEVIATIONS.jsonl').write_text(json.dumps({
 'id':'DEV-I3-001','utc':now,'classification':'NONMATERIAL_METHOD_DIAGNOSTIC',
 'deviation':'Two lookahead helper contracts were executed in addition to the default lane.',
 'reason':'The default -1 sentinel produced no analyzable trades in prior evidence.',
 'effect':'Claims remain lane-specific; signal harness cannot promote the production class.'})+'\n')
neg=[]
for lane in summary['lookahead_lanes']:
 if not lane['valid_verdict'] or lane['has_bias'] is True:
  neg.append({'id':'NEG-I3-'+lane['lane'].upper(),'result':'invalid_or_biased_lookahead_lane','lane':lane['lane'],'metrics':lane,'decision_effect':'blocks or limits correctness gate'})
if summary['callback_instrumentation_exact_parity'] is not True:
 neg.append({'id':'NEG-I3-CALLBACK-INSTRUMENTATION','result':'callback instrumentation parity not proven','decision_effect':'event-ledger claims blocked'})
with open('evidence/NEGATIVE_RESULTS_LEDGER.jsonl','w') as f:
 for r in neg:f.write(json.dumps(r)+'\n')
commands=[]
for p in sorted(pathlib.Path('evidence').glob('*.exit_code')):
 commands.append({'id':'RUN-'+p.stem.upper(),'exit_code':int(p.read_text().strip()),'evidence':str(p)})
pathlib.Path('evidence/COMMAND_LEDGER.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in commands))
PY

# Report and next prompt.
python - <<'PY'
import json,pathlib
s=json.load(open('evidence/FINAL_ITERATION3_SUMMARY.json'))
lines=['# FQT V2.4 Iteration 3 Native Lookahead and Callback Report','',f"**Decision:** {s['decision']}",'',f"- Classification: `{s['classification']}`",f"- Lookahead gate: `{s['lookahead_gate']}`",f"- V10↔V14 parity: `{s['v14_v10_exact_parity']}`",f"- Callback instrumentation parity: `{s['callback_instrumentation_exact_parity']}`",f"- Recursive: `{s['recursive'].get('status')}`",'- Fresh OOS: `UNTOUCHED_NOT_OPENED`','- Dry-run: `BLOCKED`','- Live: `FORBIDDEN`','', '## Native lanes','']
for r in s['lookahead_lanes']:
 lines.append(f"- {r['lane']}: valid={r['valid_verdict']} bias={r['has_bias']} checked={r['checked_signals']} found={r['found_trades_from_log']} rc={r['exit_code']}")
lines += ['', '## Next action', '', s['next_action']]
pathlib.Path('reports/ITERATION3_REPORT.md').write_text('\n'.join(lines)+'\n')
pathlib.Path('reports/NEXT_ITERATION_PROMPT.md').write_text('''PLSGO FQT-RND-V2.4 NEXT | MODE=FAIL_CLOSED | CHAMPION=M4PioneerValidationV14 | WIP_LIMIT=1 | READ=evidence/FINAL_ITERATION3_SUMMARY.json+receipts/LOOKAHEAD_AND_CALLBACK_EVALUATION_RECEIPT.json | IF_LOOKAHEAD_PASS=execute full recursive reconciliation then instrument raw_signal→gate→capital→slot→order→fill funnel | IF_LOOKAHEAD_NOT_PASS=isolate exact helper/callback mismatch with event-ledger replay and no alpha change | OOS=DO_NOT_OPEN | DRY_RUN=DO_NOT_START | LIVE=FORBIDDEN | OUTPUT=receipts+raw logs+negative results+three final downloads\n''')
PY

# Hash manifest for the raw return.
find evidence receipts reports tables logs configs user_data/strategies fqt_v24 -type f -print0 | sort -z | xargs -0 sha256sum > evidence/SHA256SUMS_ITERATION3.txt

# Do not fail artifact publication merely because a research gate failed.
exit 0
