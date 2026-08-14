#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

mkdir -p evidence receipts reports tables logs configs user_data/strategies user_data/backtest_results

python - <<'PY'
import datetime,hashlib,json,pathlib
plan={
 'contract':'FQT_V24_REGISTERED_ANALYSIS_PLAN_ITERATION3B_V1',
 'utc_frozen':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'rq_id':'RQ-I3B-LOOKAHEAD-DOUBLE-SIGNAL-001',
 'claim':'The invalid native lookahead baseline is caused by double application of ft_advise_signals to a strategy that compacts its dataframe in populate_exit_trend; applying signals exactly once restores native trade coverage without changing strategy alpha.',
 'estimand':{'primary':'native checked signals and bias verdict after version-bound analysis-only repair','unit':'checked completed trade signal','target':'both pair-count and production lanes have explicit has_bias=false and at least 10 checked signals'},
 'population':'31 frozen Binance Spot USDC pairs, 1m, development [2026-01-01,2026-05-01)',
 'intervention_comparator':'analysis helper before versus after single-signal-pass repair; strategy source unchanged except appended diagnostic classes',
 'primary_endpoint':'valid native no-bias verdict in both native lanes',
 'secondary_endpoints':['V10↔V14 semantic ledger parity after analysis patch','signal-harness diagnostic verdict','31-pair recursive matrix if native predecessor passes'],
 'falsification':['normal V14 ledger changes','native baseline remains below 10 trades','any bias flag','recursive material drift'],
 'alternatives':['max_open_trades sentinel remains causal','portfolio callbacks alone suppress trades','genuine future-data leakage','memory patch interaction'],
 'decision_rule':'PASS only if both native lanes have explicit has_bias=false and >=10 checked signals; otherwise fail closed',
 'fresh_oos':'forbidden/not opened','dry_run':'forbidden/not started','live':'forbidden',
}
pathlib.Path('receipts/REGISTERED_ANALYSIS_PLAN_I3B.json').write_text(json.dumps(plan,indent=2)+'\n')
PY

chmod +x fqt_ip04a/run_ip04a_v2.sh
fqt_ip04a/run_ip04a_v2.sh 2>&1 | tee logs/ip04a_setup_and_baseline_i3b.log
python fqt_v24/append_diagnostic_classes.py | tee logs/append_diagnostic_classes_i3b.log
python fqt_v24/patch_lookahead_contract.py | tee logs/patch_lookahead_contract_i3b.log
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py

python - <<'PY'
import json,pathlib
base=json.loads(pathlib.Path('config_ip04.json').read_text())
base['datadir']='user_data/data/binance'; base['user_data_dir']='user_data'; base['lookahead_allow_limit_orders']=True
for name,preserve in [('paircount',False),('production',True)]:
 c=json.loads(json.dumps(base)); c['lookahead_preserve_portfolio_contract']=preserve
 pathlib.Path(f'configs/i3b_{name}.json').write_text(json.dumps(c,indent=2)+'\n')
h=json.loads(json.dumps(base)); h['lookahead_allow_limit_orders']=False; h['lookahead_preserve_portfolio_contract']=True
h['order_types']={'entry':'market','exit':'market','stoploss':'market','stoploss_on_exchange':False}
h.setdefault('entry_pricing',{})['price_side']='other'; h.setdefault('exit_pricing',{})['price_side']='other'
pathlib.Path('configs/i3b_signal_harness.json').write_text(json.dumps(h,indent=2)+'\n')
PY

run_bt() {
  local label="$1" strategy="$2" config="$3" timerange="$4"
  set +e
  /usr/bin/time -v -o "evidence/time_${label}.txt" \
    python fqt_ip04a/seed/freqtrade_offline.py backtesting \
      -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m \
      --timerange "$timerange" --fee 0.001 --export trades --breakdown month --cache none --no-color \
      2>&1 | tee "evidence/${label}.log"
  rc=${PIPESTATUS[0]}; set -e; echo "$rc" > "evidence/${label}.exit_code"
  if [ "$rc" -ne 0 ]; then return "$rc"; fi
  newest=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  test -n "$newest"; cp "$newest" "evidence/${label}.zip"
}

run_bt I3B_V14_CONTINUOUS_MAIN M4PioneerValidationV14 configs/i3b_production.json 20260101-20260501

run_lookahead() {
  local label="$1" strategy="$2" config="$3"
  rm -f "evidence/i3b_lookahead_${label}.csv"
  set +e
  /usr/bin/time -v -o "evidence/time_i3b_lookahead_${label}.txt" \
    python fqt_ip04a/seed/freqtrade_offline.py lookahead-analysis \
      -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m \
      --timerange 20260101-20260501 --fee 0.001 \
      --minimum-trade-amount 10 --targeted-trade-amount 10 \
      --lookahead-analysis-exportfilename "evidence/i3b_lookahead_${label}.csv" --no-color \
      2>&1 | tee "evidence/i3b_lookahead_${label}.log"
  rc=${PIPESTATUS[0]}; set -e; echo "$rc" > "evidence/i3b_lookahead_${label}.exit_code"
}

run_lookahead paircount M4PioneerValidationV14 configs/i3b_paircount.json
run_lookahead production M4PioneerValidationV14 configs/i3b_production.json
run_lookahead signal_harness M4PioneerValidationV14SignalHarness configs/i3b_signal_harness.json

python - <<'PY'
import csv,hashlib,json,pathlib,re,zipfile
E=pathlib.Path('evidence')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def result(path):
 with zipfile.ZipFile(path) as z:
  n=[x for x in z.namelist() if x.endswith('.json') and not x.endswith('_config.json')]
  o=json.loads(z.read(n[0])); r=next(iter(o['strategy'].values())); t=r['trades']
 keys=['pair','open_timestamp','close_timestamp','enter_tag','exit_reason','stake_amount','amount','open_rate','close_rate','profit_ratio','profit_abs']
 h=hashlib.sha256(json.dumps([{k:x.get(k) for k in keys} for x in t],sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return {'trades':r['total_trades'],'wins':r['wins'],'losses':r['losses'],'profit_pct':r['profit_total']*100,'profit_usdc':r['profit_total_abs'],'profit_factor':r['profit_factor'],'ledger_sha256':h,'result_sha256':sha(path)}
def lane(name):
 cp=E/f'i3b_lookahead_{name}.csv'; lp=E/f'i3b_lookahead_{name}.log'; rc=int((E/f'i3b_lookahead_{name}.exit_code').read_text())
 rows=list(csv.DictReader(cp.open())) if cp.exists() and cp.stat().st_size else []; log=lp.read_text(errors='replace')
 vals=[]; checked=0
 for r in rows:
  v=str(r.get('has_bias','')).strip().lower()
  if v in ('true','yes','1'): vals.append(True)
  elif v in ('false','no','0'): vals.append(False)
  try: checked=max(checked,int(float(r.get('total_signals',0))))
  except: pass
 found=None
 for pat in (r'Found\s+(\d+)\s+trades',r'found\s+(\d+)\s+trades'):
  m=re.findall(pat,log,re.I)
  if m: found=int(m[-1]); break
 valid=rc==0 and bool(rows) and bool(vals) and checked>=10
 return {'lane':name,'exit_code':rc,'row_count':len(rows),'checked_signals':checked,'found_trades':found,'valid_verdict':valid,'has_bias':any(vals) if vals else None,'single_signal_patch_logged':'indicator comparison retains signalled frames' in log,'csv_sha256':sha(cp) if cp.exists() else None,'log_sha256':sha(lp)}
v10=result(E/'IP04A_CONTINUOUS_RUN1.zip'); v14=result(E/'I3B_V14_CONTINUOUS_MAIN.zip')
lanes=[lane(x) for x in ('paircount','production','signal_harness')]; native=lanes[:2]
parity=v10['ledger_sha256']==v14['ledger_sha256'] and v10['trades']==v14['trades']
pass_native=all(x['valid_verdict'] and x['has_bias'] is False for x in native)
out={'contract':'FQT_V24_ITERATION3B_DOUBLE_SIGNAL_ROOT_CAUSE_V1','classification':'PASS_NATIVE_NO_BIAS' if pass_native and parity else 'FAIL_OR_INCOMPLETE','v10':v10,'v14':v14,'v10_v14_exact_parity':parity,'lanes':lanes,'lookahead_gate':'PASS' if pass_native else 'INVALID','root_cause_supported':all(x['single_signal_patch_logged'] and (x['found_trades'] or 0)>=10 for x in native),'decision':'PROCEED_RECURSIVE' if pass_native and parity else 'KEEP_CHAMPION_BLOCKED','oos':'UNTOUCHED_NOT_OPENED','dry_run':'BLOCKED','live':'FORBIDDEN'}
E.joinpath('I3B_FINAL_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps(out,indent=2))
PY

if python - <<'PY'
import json,sys
s=json.load(open('evidence/I3B_FINAL_SUMMARY.json')); sys.exit(0 if s['lookahead_gate']=='PASS' and s['v10_v14_exact_parity'] else 1)
PY
then
  mkdir -p evidence/i3b_recursive31
  while IFS= read -r pair; do
    safe=${pair//\//_}
    set +e
    python fqt_ip04a/seed/freqtrade_offline.py recursive-analysis \
      -c configs/i3b_production.json --strategy-path user_data/strategies \
      -s M4PioneerValidationV14 -i 1m --timerange 20260401-20260501 \
      -p "$pair" --startup-candle 200 400 800 1100 1600 --no-color \
      2>&1 | tee "evidence/i3b_recursive31/${safe}.log"
    rc=${PIPESTATUS[0]}; set -e; echo "$rc" > "evidence/i3b_recursive31/${safe}.exit_code"
  done < <(python - <<'PY'
import json
print('\n'.join(json.load(open('configs/i3b_production.json'))['exchange']['pair_whitelist']))
PY
)
  python - <<'PY'
import json,pathlib,re
root=pathlib.Path('evidence/i3b_recursive31'); rows=[]
for lp in sorted(root.glob('*.log')):
 pair=lp.stem.replace('_','/',1); log=lp.read_text(errors='replace'); rc=int(lp.with_suffix('.exit_code').read_text())
 section=log.split('Recursive Analysis')[-1]; vals=[abs(float(x)) for x in re.findall(r'(-?\d+\.\d+)%',section)]; no_bias='No lookahead bias on indicators found.' in log; maxdev=max(vals) if vals else None
 rows.append({'pair':pair,'exit_code':rc,'no_indicator_lookahead':no_bias,'max_abs_deviation_pct':maxdev,'pass':rc==0 and no_bias and maxdev is not None and maxdev<=0.001})
out={'contract':'FQT_V24_I3B_RECURSIVE_31PAIR_V1','status':'PASS' if len(rows)==31 and all(r['pass'] for r in rows) else 'FAIL','pair_count':len(rows),'passed_pairs':sum(r['pass'] for r in rows),'tolerance_pct':0.001,'rows':rows}
pathlib.Path('evidence/I3B_RECURSIVE_31PAIR_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n'); print(json.dumps({'status':out['status'],'pairs':len(rows),'passed':out['passed_pairs']},indent=2))
PY
else
  echo 'NOT_RUN: native lookahead predecessor did not PASS.' > evidence/I3B_RECURSIVE_NOT_RUN.txt
fi

python - <<'PY'
import json,pathlib,datetime
s=json.load(open('evidence/I3B_FINAL_SUMMARY.json')); recp=pathlib.Path('evidence/I3B_RECURSIVE_31PAIR_SUMMARY.json'); rec=json.load(recp.open()) if recp.exists() else {'status':'NOT_RUN'}
receipt={'id':'EVAL-I3B-001','status':'PASS' if s['lookahead_gate']=='PASS' and s['v10_v14_exact_parity'] else 'FAIL','utc_started':None,'utc_finished':datetime.datetime.now(datetime.timezone.utc).isoformat(),'inputs':[{'artifact_id':'ART-I3B-V10','sha256':s['v10']['result_sha256']},{'artifact_id':'ART-I3B-V14','sha256':s['v14']['result_sha256']}],'command':'see native logs and command ledger','exit_code':0,'primary_metrics':{'v10_v14_exact_parity':s['v10_v14_exact_parity'],'lookahead_gate':s['lookahead_gate'],'root_cause_supported':s['root_cause_supported'],'recursive_status':rec['status']},'uncertainty_or_tolerance':{'minimum_checked_signals':10,'limit_order_false_positive_risk':True,'analysis_patch_version_bound':True},'evidence':['I3B_FINAL_SUMMARY','LOOKAHEAD_CONTRACT_PATCH_RECEIPT','native logs'],'decision':'KEEP_CHAMPION','blocker_or_next_action':'Proceed to funnel/WF only if lookahead and recursive PASS; OOS remains sealed.'}
pathlib.Path('receipts/I3B_EVALUATION_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+'\n')
pathlib.Path('reports/I3B_REPORT.md').write_text(f"# FQT V2.4 Iteration 3B\n\n- V10↔V14 parity: `{s['v10_v14_exact_parity']}`\n- Lookahead: `{s['lookahead_gate']}`\n- Root cause supported: `{s['root_cause_supported']}`\n- Recursive: `{rec['status']}`\n- Decision: `KEEP_CHAMPION`\n- OOS: `UNTOUCHED_NOT_OPENED`\n- Dry-run: `BLOCKED`\n- Live: `FORBIDDEN`\n")
PY

find evidence receipts reports logs configs user_data/strategies fqt_v24 -type f -print0 | sort -z | xargs -0 sha256sum > evidence/I3B_SHA256SUMS.txt
exit 0
