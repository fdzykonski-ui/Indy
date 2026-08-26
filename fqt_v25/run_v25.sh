#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
ROOT="$PWD"
mkdir -p evidence summaries results logs fqt_v25_results

# Reconstruct the frozen source/runtime and exact Dec-Apr data contract.
bash fqt_ip04a/run_ip04a_v2.sh 2>&1 | tee logs/ip04a_rebuild.log
python fqt_v24/append_diagnostic_classes.py
python fqt_v25/append_v16_candidates.py
python fqt_v24/patch_lookahead_contract.py
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py

# Normalize the completed Iteration-3B return before any new alpha work.
python fqt_v25/parse_iteration3b.py --artifact iteration3b_input --work iteration3b_work --out evidence/ITERATION3B_NORMALIZED_SUMMARY.json | tee logs/iteration3b_parse.log

# Enforce the requested MOT=1 contract and extend data through 2026-08-10 23:59 UTC.
python - <<'PY'
import json,pathlib,copy
p=pathlib.Path('config_ip04.json'); c=json.loads(p.read_text())
c['max_open_trades']=1;c['stake_amount']='unlimited';c['dry_run_wallet']=1000;c['tradable_balance_ratio']=0.99
c['dry_run']=True;c['initial_state']='stopped';c['force_entry_enable']=False
c.setdefault('exchange',{})['key']='';c['exchange']['secret']=''
c.setdefault('api_server',{})['enabled']=False;c.setdefault('telegram',{})['enabled']=False
c['lookahead_preserve_portfolio_contract']=True;c['lookahead_allow_limit_orders']=True
pathlib.Path('config_mot1_original.json').write_text(json.dumps(c,indent=2)+'\n')
PY
python fqt_v25/prepare_extended_data.py --config config_mot1_original.json --datadir user_data/data/binance --raw raw_extended --manifest evidence/EXTENDED_DATA_MANIFEST.json | tee logs/extended_data.log

run_bt() {
  local label="$1" strategy="$2" config="$3" timerange="$4" fee="$5" order="$6"
  local before result
  before=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' | wc -l)
  /usr/bin/time -v -o "evidence/time_${label}.txt" \
    python fqt_ip04a/freqtrade_offline.py backtesting -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m --timerange "$timerange" --fee "$fee" --export trades --breakdown month --cache none 2>&1 | tee "logs/${label}.log"
  result=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  test -n "$result"
  cp "$result" "results/${label}.zip"
  python fqt_v25/summarize_result_v2.py --result "results/${label}.zip" --out "summaries/${label}.json" --strategy "$strategy" --label "$label" --timerange "$timerange" --pair-order "$order"
  echo "$before" > "evidence/result_count_before_${label}.txt"
}

# Training-only pair priority: all 31 pairs retained.
python - <<'PY'
import json,pathlib
c=json.loads(pathlib.Path('config_mot1_original.json').read_text());c['max_open_trades']=31
pathlib.Path('config_rank_train.json').write_text(json.dumps(c,indent=2)+'\n')
PY
run_bt RANK_TRAIN M4PioneerValidationV14 config_rank_train.json 20260101-20260401 0.001 original
python fqt_v25/rank_pairs.py --summary summaries/RANK_TRAIN.json --config config_mot1_original.json --out-config config_mot1_ranked.json --out-receipt evidence/PAIR_PRIORITY_RECEIPT.json
python - <<'PY'
import json,pathlib
c=json.loads(pathlib.Path('config_mot1_ranked.json').read_text());c['exchange']['pair_whitelist']=list(reversed(c['exchange']['pair_whitelist']))
pathlib.Path('config_mot1_reversed.json').write_text(json.dumps(c,indent=2)+'\n')
PY

# Corrected native lookahead. The result is authoritative only if CSV coverage is explicit.
set +e
python fqt_ip04a/freqtrade_offline.py lookahead-analysis -c config_mot1_ranked.json --strategy-path user_data/strategies -s M4PioneerValidationV14 -i 1m --timerange 20260101-20260501 --fee 0.001 --minimum-trade-amount 10 --targeted-trade-amount 20 --allow-limit-orders --lookahead-analysis-exportfilename evidence/V25_LOOKAHEAD.csv --no-color 2>&1 | tee logs/V25_LOOKAHEAD.log
la_rc=${PIPESTATUS[0]}
set -e
echo "$la_rc" > evidence/V25_LOOKAHEAD_EXIT_CODE.txt
python fqt_v25/parse_lookahead.py --csv evidence/V25_LOOKAHEAD.csv --log logs/V25_LOOKAHEAD.log --exit-code evidence/V25_LOOKAHEAD_EXIT_CODE.txt --out evidence/V25_LOOKAHEAD_SUMMARY.json

# Combine current native lookahead with the completed Iteration-3B recursive receipt.
python - <<'PY'
import json,pathlib
it=json.loads(pathlib.Path('evidence/ITERATION3B_NORMALIZED_SUMMARY.json').read_text())
la=json.loads(pathlib.Path('evidence/V25_LOOKAHEAD_SUMMARY.json').read_text())
rec=it.get('recursive') or {'pass':False,'status':'NOT_FOUND'}
out={'contract':'FQT_V25_CORRECTNESS_PREDECESSORS_V1','lookahead':la,'recursive':rec,'pass':bool(la.get('pass') and rec.get('pass')),'decision':'PASS' if la.get('pass') and rec.get('pass') else 'BLOCKED'}
pathlib.Path('evidence/CORRECTNESS_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
PY

# Preregistered Apr-Jun22 validation matrix. OOS remains unopened.
declare -A STRAT DELAY
STRAT[BASE_RANKED]=M4PioneerValidationV14; DELAY[BASE_RANKED]=M4PioneerValidationV14Delay1
STRAT[V16_PRUNE]=M4PioneerOOS50V16VwapPrune; DELAY[V16_PRUNE]=M4PioneerOOS50V16VwapPruneDelay1
STRAT[V16_VWAPQ]=M4PioneerOOS50V16VwapQuality; DELAY[V16_VWAPQ]=M4PioneerOOS50V16VwapQualityDelay1
STRAT[V16_TRENDQ]=M4PioneerOOS50V16TrendQuality; DELAY[V16_TRENDQ]=M4PioneerOOS50V16TrendQualityDelay1
for system in BASE_RANKED V16_PRUNE V16_VWAPQ V16_TRENDQ; do
  run_bt "${system}__known" "${STRAT[$system]}" config_mot1_ranked.json 20260401-20260623 0.001 ranked
  run_bt "${system}__fee15" "${STRAT[$system]}" config_mot1_ranked.json 20260401-20260623 0.0015 ranked
  run_bt "${system}__delay1" "${DELAY[$system]}" config_mot1_ranked.json 20260401-20260623 0.001 ranked
  run_bt "${system}__reversed" "${STRAT[$system]}" config_mot1_reversed.json 20260401-20260623 0.001 reversed
done
python fqt_v25/select_candidate.py --summaries summaries --correctness evidence/CORRECTNESS_SUMMARY.json --out evidence/SELECTION_RECEIPT.json | tee logs/selection.log

selection_pass=$(python -c "import json;print('1' if json.load(open('evidence/SELECTION_RECEIPT.json'))['selection_pass'] else '0')")
preauth=$(python -c "import json;print('1' if json.load(open('evidence/SELECTION_RECEIPT.json'))['oos_pre_authorized'] else '0')")
if [[ "$selection_pass" != 1 || "$preauth" != 1 ]]; then
  python - <<'PY'
import json,pathlib,shutil
sel=json.loads(pathlib.Path('evidence/SELECTION_RECEIPT.json').read_text());corr=json.loads(pathlib.Path('evidence/CORRECTNESS_SUMMARY.json').read_text())
out={'contract':'FQT_V25_FINAL_SUMMARY_V1','decision':'KEEP_CHAMPION_BLOCK_OOS','selected_system':sel.get('chosen_system'),'selected_strategy':sel.get('chosen_strategy'),'correctness':corr,'selection':sel,'oos_opened':False,'dry_run_started':False,'live_allowed':False}
pathlib.Path('fqt_v25_results/summary.json').write_text(json.dumps(out,indent=2)+'\n')
shutil.copy2('user_data/strategies/M4PioneerStableExposureV10.py','fqt_v25_results/M4PioneerValidationV14_V25_RESEARCH.py')
shutil.copy2('config_mot1_ranked.json','fqt_v25_results/config_M4PioneerValidationV14_V25.json')
PY
  exit 0
fi

chosen_system=$(python -c "import json;print(json.load(open('evidence/SELECTION_RECEIPT.json'))['chosen_system'])")
chosen_strategy=$(python -c "import json;print(json.load(open('evidence/SELECTION_RECEIPT.json'))['chosen_strategy'])")

# Full known-period confirmation and fee20 gate.
run_bt BASE_FULL_KNOWN M4PioneerValidationV14 config_mot1_ranked.json 20260101-20260623 0.001 ranked
run_bt CANDIDATE_FULL_KNOWN "$chosen_strategy" config_mot1_ranked.json 20260101-20260623 0.001 ranked
run_bt CANDIDATE_FEE20 "$chosen_strategy" config_mot1_ranked.json 20260401-20260623 0.002 ranked
python fqt_v25/authorize_oos.py --selection evidence/SELECTION_RECEIPT.json --baseline summaries/BASE_FULL_KNOWN.json --candidate summaries/CANDIDATE_FULL_KNOWN.json --fee20 summaries/CANDIDATE_FEE20.json --out evidence/OOS_AUTHORIZATION.json | tee logs/oos_authorization.log
authorized=$(python -c "import json;print('1' if json.load(open('evidence/OOS_AUTHORIZATION.json'))['authorized'] else '0')")
if [[ "$authorized" != 1 ]]; then
  python - <<'PY'
import json,pathlib,shutil
sel=json.loads(pathlib.Path('evidence/SELECTION_RECEIPT.json').read_text());auth=json.loads(pathlib.Path('evidence/OOS_AUTHORIZATION.json').read_text())
out={'contract':'FQT_V25_FINAL_SUMMARY_V1','decision':'KEEP_CHAMPION_BLOCK_OOS','selected_system':sel.get('chosen_system'),'selected_strategy':sel.get('chosen_strategy'),'selection':sel,'authorization':auth,'oos_opened':False,'dry_run_started':False,'live_allowed':False}
pathlib.Path('fqt_v25_results/summary.json').write_text(json.dumps(out,indent=2)+'\n')
shutil.copy2('user_data/strategies/M4PioneerStableExposureV10.py','fqt_v25_results/M4PioneerValidationV14_V25_RESEARCH.py')
shutil.copy2('config_mot1_ranked.json','fqt_v25_results/config_M4PioneerValidationV14_V25.json')
PY
  exit 0
fi

# One-shot frozen OOS: no code/config revision after this point.
run_bt BASE_OOS M4PioneerValidationV14 config_mot1_ranked.json 20260623-20260811 0.001 ranked
run_bt CANDIDATE_OOS "$chosen_strategy" config_mot1_ranked.json 20260623-20260811 0.001 ranked
run_bt BASE_FULL_PERIOD M4PioneerValidationV14 config_mot1_ranked.json 20260101-20260811 0.001 ranked
run_bt CANDIDATE_FULL_PERIOD "$chosen_strategy" config_mot1_ranked.json 20260101-20260811 0.001 ranked

python - <<'PY'
import json,pathlib,shutil,hashlib
load=lambda n:json.loads(pathlib.Path(n).read_text())
sel=load('evidence/SELECTION_RECEIPT.json');auth=load('evidence/OOS_AUTHORIZATION.json')
bo=load('summaries/BASE_OOS.json');co=load('summaries/CANDIDATE_OOS.json');bf=load('summaries/BASE_FULL_PERIOD.json');cf=load('summaries/CANDIDATE_FULL_PERIOD.json')
checks={
'oos_profit_gt50':float(co['profit_pct'])>50.0,
'oos_wr_gt80':float(co['winrate_pct'])>80.0,
'oos_pf_gt1_5':(co.get('profit_factor') or 0)>1.5,
'oos_mdd_lt5':float(co['max_drawdown_pct'])<5.0,
'full_trades_gt500':int(cf['trades'])>500,
'full_wr_gt80':float(cf['winrate_pct'])>80.0,
'beats_baseline_oos':float(co['profit_usdc'])>float(bo['profit_usdc']),
}
decision='PROMOTE_RESEARCH_CANDIDATE_TO_DRYRUN_PREFLIGHT' if all(checks.values()) else 'KEEP_CHAMPION_OOS_TARGET_NOT_MET'
out={'contract':'FQT_V25_FINAL_SUMMARY_V1','decision':decision,'selected_system':sel['chosen_system'],'selected_strategy':sel['chosen_strategy'],'selection':sel,'authorization':auth,'baseline_oos':bo,'candidate_oos':co,'baseline_full_period':bf,'candidate_full_period':cf,'promotion_checks':checks,'oos_opened':True,'oos_opened_once':True,'dry_run_started':False,'live_allowed':False}
out['summary_sha256']=hashlib.sha256(json.dumps(out,sort_keys=True,separators=(',',':')).encode()).hexdigest()
pathlib.Path('fqt_v25_results/summary.json').write_text(json.dumps(out,indent=2)+'\n')
shutil.copy2('user_data/strategies/M4PioneerStableExposureV10.py','fqt_v25_results/M4PioneerOOS50V16_FINAL.py')
c=json.loads(pathlib.Path('config_mot1_ranked.json').read_text());c['strategy']=sel['chosen_strategy'];c['evidence_status']=decision;c['dry_run']=True;c['initial_state']='stopped';c['max_open_trades']=1;c['stake_amount']='unlimited';c['dry_run_wallet']=1000
pathlib.Path('fqt_v25_results/config_M4PioneerOOS50V16_FINAL.json').write_text(json.dumps(c,indent=2)+'\n')
PY

# Copy compact evidence for the return artifact.
cp evidence/*.json fqt_v25_results/ 2>/dev/null || true
cp summaries/*.json fqt_v25_results/ 2>/dev/null || true
sha256sum fqt_v25_results/* > fqt_v25_results/SHA256SUMS.txt
