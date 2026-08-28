#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1

ROOT="$PWD"
mkdir -p evidence summaries results logs m6r36_results/final

# 1) Reconstruct exact project source, patched backtester and deterministic 31-pair V10 baseline.
bash fqt_ip04a/run_ip04a_v2.sh 2>&1 | tee logs/ip04a_rebuild_and_baseline.log
cp evidence/IP04A_CONTINUOUS_RUN1.zip results/V10_MAIN_F001_MAX2.zip
python fqt_m6r36/summarize_result.py --result results/V10_MAIN_F001_MAX2.zip --out summaries/V10_MAIN_F001_MAX2.json --label V10_MAIN_F001_MAX2

# 2) Append preregistered V11 risk-only classes. No alpha/exit/ROI/stoploss mutation.
python fqt_m6r36/append_v11.py
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py
python fqt_ip04a/seed/freqtrade_offline.py list-strategies --userdir user_data --strategy-path user_data/strategies | tee evidence/list_strategies_v11.log

# 3) Freeze max2 and latest-user-contract max1 configurations.
python - <<'PY'
import hashlib,json,pathlib
base=json.loads(pathlib.Path('config_ip04.json').read_text())
base['dry_run_wallet']=1000;base['stake_amount']='unlimited';base['dry_run']=True;base['initial_state']='stopped'
base.setdefault('exchange',{})['key']='';base['exchange']['secret']=''
base.setdefault('api_server',{})['enabled']=False;base.setdefault('telegram',{})['enabled']=False
for name,mot in [('config_v11_max2.json',2),('config_v11_max1.json',1)]:
    c=json.loads(json.dumps(base));c['max_open_trades']=mot;c['strategy']='M4PioneerRiskAllocatorV11Balanced75'
    c['evidence_status']='M6R36_NATIVE_RESEARCH_ONLY_NOT_PROMOTED'
    pathlib.Path(name).write_text(json.dumps(c,indent=2)+'\n')
for pair,name in [('BTC/USDC','config_v11_btc.json'),('AVAX/USDC','config_v11_avax.json')]:
    c=json.loads(json.dumps(base));c['max_open_trades']=1;c['exchange']['pair_whitelist']=[pair]
    c['strategy']='M4PioneerRiskAllocatorV11Balanced75';pathlib.Path(name).write_text(json.dumps(c,indent=2)+'\n')
for path in ['config_v11_max2.json','config_v11_max1.json','config_v11_btc.json','config_v11_avax.json','user_data/strategies/M4PioneerStableExposureV10.py']:
    p=pathlib.Path(path);print(hashlib.sha256(p.read_bytes()).hexdigest(),path)
PY
sha256sum config_v11_*.json user_data/strategies/M4PioneerStableExposureV10.py > evidence/M6R36_PRE_RUN_HASHES.sha256

run_bt() {
  local label="$1" strategy="$2" config="$3" timerange="$4" fee="$5"
  local outdir="results/${label}_raw"
  mkdir -p "$outdir"
  /usr/bin/time -v -o "evidence/time_${label}.txt" \
    python fqt_ip04a/seed/freqtrade_offline.py backtesting \
      -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m \
      --timerange "$timerange" --fee "$fee" --export trades --breakdown month \
      --backtest-directory "$outdir" --cache none 2>&1 | tee "logs/${label}.log"
  local result
  result=$(find "$outdir" -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  test -n "$result"
  cp "$result" "results/${label}.zip"
  python fqt_m6r36/summarize_result.py --result "results/${label}.zip" --out "summaries/${label}.json" --label "$label"
}

# 4) Native main-window plateau and cost/capacity/delay stress.
run_bt V11_TIER50_MAIN_F001_MAX2 M4PioneerRiskAllocatorV11Tier50 config_v11_max2.json 20260101-20260501 0.001
run_bt V11_BAL75_MAIN_F001_MAX2 M4PioneerRiskAllocatorV11Balanced75 config_v11_max2.json 20260101-20260501 0.001
run_bt V11_BAL75_MAIN_F001_MAX2_REPEAT M4PioneerRiskAllocatorV11Balanced75 config_v11_max2.json 20260101-20260501 0.001
run_bt V11_TIER100_MAIN_F001_MAX2 M4PioneerRiskAllocatorV11Tier100 config_v11_max2.json 20260101-20260501 0.001
run_bt V11_BAL75_MAIN_F002_MAX2 M4PioneerRiskAllocatorV11Balanced75 config_v11_max2.json 20260101-20260501 0.002
run_bt V11_BAL75_MAIN_F003_MAX2 M4PioneerRiskAllocatorV11Balanced75 config_v11_max2.json 20260101-20260501 0.003
run_bt V11_BAL75_MAIN_F001_MAX1 M4PioneerRiskAllocatorV11Balanced75 config_v11_max1.json 20260101-20260501 0.001
run_bt V11_BAL75_MAIN_F003_MAX1 M4PioneerRiskAllocatorV11Balanced75 config_v11_max1.json 20260101-20260501 0.003
run_bt V11_BAL75_DELAY1_F003_MAX2 M4PioneerRiskAllocatorV11Balanced75_DELAY1 config_v11_max2.json 20260101-20260501 0.003
run_bt V11_BAL75_DELAY2_F003_MAX2 M4PioneerRiskAllocatorV11Balanced75_DELAY2 config_v11_max2.json 20260101-20260501 0.003

# 5) Determinism and inheritance/callback contract before any fresh OOS is opened.
python - <<'PY'
import ast,hashlib,json,pathlib
A=json.loads(pathlib.Path('summaries/V11_BAL75_MAIN_F001_MAX2.json').read_text())
B=json.loads(pathlib.Path('summaries/V11_BAL75_MAIN_F001_MAX2_REPEAT.json').read_text())
fields=['trades','wins','draws','losses','winrate_pct','profit_usdc','profit_pct','profit_factor','max_drawdown_abs','max_drawdown_pct','starting_balance','final_balance','trade_ledger_sha256']
diff={k:{'run1':A.get(k),'run2':B.get(k)} for k in fields if A.get(k)!=B.get(k)}
out={'contract':'FQT_M6R36_NATIVE_DETERMINISM_V1','fields':fields,'differences':diff,'pass':not diff}
pathlib.Path('evidence/V11_NATIVE_DETERMINISM.json').write_text(json.dumps(out,indent=2)+'\n')
if diff: raise SystemExit(f'determinism failed: {diff}')
source=pathlib.Path('user_data/strategies/M4PioneerStableExposureV10.py').read_text();tree=ast.parse(source)
cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='M4PioneerRiskAllocatorV11Balanced75')
methods={n.name for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
forbidden={'populate_indicators','populate_entry_trend','populate_exit_trend','custom_exit','custom_stoploss','confirm_trade_entry','confirm_trade_exit'}
contract={'contract':'FQT_M6R36_RISK_ONLY_INHERITANCE_V1','declared_methods':sorted(methods),'forbidden_overrides':sorted(methods&forbidden),'pass':not(methods&forbidden),'source_sha256':hashlib.sha256(source.encode()).hexdigest()}
pathlib.Path('evidence/V11_RISK_ONLY_INHERITANCE.json').write_text(json.dumps(contract,indent=2)+'\n')
if not contract['pass']: raise SystemExit(contract)
PY

# 6) Scope-limited native lookahead and recursive checks for the selected risk-only class.
set +e
python fqt_ip04a/seed/freqtrade_offline.py lookahead-analysis \
  -c config_v11_max2.json --strategy-path user_data/strategies \
  -s M4PioneerRiskAllocatorV11Balanced75 -i 1m --timerange 20260101-20260501 \
  --fee 0.001 --minimum-trade-amount 10 --targeted-trade-amount 20 --allow-limit-orders \
  --lookahead-analysis-exportfilename evidence/V11_LOOKAHEAD.csv --no-color 2>&1 | tee logs/V11_LOOKAHEAD.log
la_rc=${PIPESTATUS[0]}
set -e
echo "$la_rc" > evidence/V11_LOOKAHEAD_EXIT_CODE.txt
python fqt_v25/parse_lookahead.py --csv evidence/V11_LOOKAHEAD.csv --log logs/V11_LOOKAHEAD.log --exit-code evidence/V11_LOOKAHEAD_EXIT_CODE.txt --out evidence/V11_LOOKAHEAD_SUMMARY.json || true

run_recursive() {
  local pairlabel="$1" config="$2"
  local help
  help=$(python fqt_ip04a/seed/freqtrade_offline.py recursive-analysis --help 2>&1 || true)
  local args=(recursive-analysis -c "$config" --strategy-path user_data/strategies -s M4PioneerRiskAllocatorV11Balanced75 -i 1m --timerange 20260101-20260501 --startup-candle 499 999 1999 --no-color)
  if grep -q -- '--recursive-analysis-exportfilename' <<<"$help"; then args+=(--recursive-analysis-exportfilename "evidence/V11_RECURSIVE_${pairlabel}.csv"); fi
  set +e
  python fqt_ip04a/seed/freqtrade_offline.py "${args[@]}" 2>&1 | tee "logs/V11_RECURSIVE_${pairlabel}.log"
  local rc=${PIPESTATUS[0]}
  set -e
  echo "$rc" > "evidence/V11_RECURSIVE_${pairlabel}_EXIT_CODE.txt"
}
run_recursive BTC config_v11_btc.json
run_recursive AVAX config_v11_avax.json

# 7) Acquire and freeze the independent official Binance OOS dataset through 2026-08-10.
python fqt_v25/prepare_extended_data.py --config config_v11_max2.json --datadir user_data/data/binance --raw raw_extended --manifest evidence/EXTENDED_DATA_MANIFEST.json 2>&1 | tee logs/extended_data.log
python - <<'PY'
import hashlib,json,pathlib
paths=[pathlib.Path('user_data/strategies/M4PioneerStableExposureV10.py'),pathlib.Path('config_v11_max2.json'),pathlib.Path('config_v11_max1.json'),pathlib.Path('evidence/EXTENDED_DATA_MANIFEST.json')]
out={'contract':'FQT_M6R36_PRE_OOS_FREEZE_V1','oos_timerange':'20260623-20260811','oos_opened':False,'files':[]}
for p in paths:
 out['files'].append({'path':str(p),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
out['freeze_sha256']=hashlib.sha256(json.dumps(out['files'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
pathlib.Path('evidence/PRE_OOS_FREEZE.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
PY

# 8) One-shot OOS. No code/config/threshold mutation is allowed after PRE_OOS_FREEZE.
run_bt V10_OOS_F001_MAX2 M4PioneerStableExposureV10 config_v11_max2.json 20260623-20260811 0.001
run_bt V11_BAL75_OOS_F001_MAX2 M4PioneerRiskAllocatorV11Balanced75 config_v11_max2.json 20260623-20260811 0.001
run_bt V11_BAL75_OOS_F003_MAX2 M4PioneerRiskAllocatorV11Balanced75 config_v11_max2.json 20260623-20260811 0.003
run_bt V11_BAL75_OOS_F001_MAX1 M4PioneerRiskAllocatorV11Balanced75 config_v11_max1.json 20260623-20260811 0.001
run_bt V11_BAL75_OOS_F003_MAX1 M4PioneerRiskAllocatorV11Balanced75 config_v11_max1.json 20260623-20260811 0.003

# 9) Final fail-closed decision and compact machine-readable return.
python - <<'PY'
import hashlib,json,pathlib,shutil
load=lambda n: json.loads(pathlib.Path(n).read_text())
base=load('summaries/V10_MAIN_F001_MAX2.json')
main=load('summaries/V11_BAL75_MAIN_F001_MAX2.json')
fee2=load('summaries/V11_BAL75_MAIN_F002_MAX2.json')
fee3=load('summaries/V11_BAL75_MAIN_F003_MAX2.json')
oos=load('summaries/V11_BAL75_OOS_F001_MAX2.json')
oos3=load('summaries/V11_BAL75_OOS_F003_MAX2.json')
look=load('evidence/V11_LOOKAHEAD_SUMMARY.json') if pathlib.Path('evidence/V11_LOOKAHEAD_SUMMARY.json').exists() else {'pass':False,'status':'MISSING'}
det=load('evidence/V11_NATIVE_DETERMINISM.json')
checks={
 'native_main_profit_improves': float(main['profit_pct'])>float(base['profit_pct']),
 'native_main_pf_gt5': float(main.get('profit_factor') or 0)>5,
 'native_main_wr_gt80': float(main['winrate_pct'])>80,
 'native_main_trades_gt500': int(main['trades'])>500,
 'native_main_dd_lt5': float(main['max_drawdown_pct'])<5,
 'fee002_positive': float(fee2['profit_pct'])>0,
 'fee003_positive': float(fee3['profit_pct'])>0,
 'oos_profit_gt50': float(oos['profit_pct'])>50,
 'oos_wr_gt80': float(oos['winrate_pct'])>80,
 'oos_pf_gt1_5': float(oos.get('profit_factor') or 0)>1.5,
 'oos_dd_lt5': float(oos['max_drawdown_pct'])<5,
 'oos_fee003_positive': float(oos3['profit_pct'])>0,
 'deterministic': bool(det.get('pass')),
 'lookahead_pass_scope_limited': bool(look.get('pass')),
}
promote=all(checks.values())
decision='PROMOTE_TO_DRYRUN_PREFLIGHT' if promote else 'QUARANTINE_V11_KEEP_V10_RESEARCH_CHAMPION'
out={'contract':'FQT_M6R36_FINAL_DECISION_V1','decision':decision,'promotion':promote,'live_allowed':False,'orders_allowed':False,'dry_run_started':False,'baseline':base,'candidate_main':main,'candidate_fee002':fee2,'candidate_fee003':fee3,'candidate_oos':oos,'candidate_oos_fee003':oos3,'checks':checks,'lookahead':look,'limits':['No live or micro-live order authorization.','OOS was opened once after PRE_OOS_FREEZE.','No post-OOS tuning is permitted.']}
out['decision_sha256']=hashlib.sha256(json.dumps(out,sort_keys=True,separators=(',',':')).encode()).hexdigest()
pathlib.Path('m6r36_results/DECISION.json').write_text(json.dumps(out,indent=2)+'\n')
pathlib.Path('m6r36_results/SUMMARY.json').write_text(json.dumps({'decision':decision,'baseline':base,'candidate_main':main,'candidate_oos':oos,'candidate_oos_fee003':oos3,'checks':checks},indent=2)+'\n')
shutil.copy2('user_data/strategies/M4PioneerStableExposureV10.py','m6r36_results/final/M4PioneerRiskAllocatorV11Balanced75.py')
# Latest explicit user contract: max_open_trades=1; research-only, stopped, no orders.
c=json.loads(pathlib.Path('config_v11_max1.json').read_text());c['strategy']='M4PioneerRiskAllocatorV11Balanced75';c['evidence_status']=decision;c['dry_run']=True;c['initial_state']='stopped';c['force_entry_enable']=False;c.setdefault('api_server',{})['enabled']=False;c.setdefault('telegram',{})['enabled']=False
pathlib.Path('m6r36_results/final/config.json').write_text(json.dumps(c,indent=2)+'\n')
PY

cp -r evidence summaries results logs m6r36_results/ 2>/dev/null || true
find m6r36_results -type f -print0 | sort -z | xargs -0 sha256sum > m6r36_results/SHA256SUMS.txt
python - <<'PY'
import hashlib,json,pathlib
root=pathlib.Path('m6r36_results');rows=[]
for p in sorted(x for x in root.rglob('*') if x.is_file() and x.name!='RETURN_MANIFEST.json'):
 h=hashlib.sha256(p.read_bytes()).hexdigest();rows.append({'path':str(p.relative_to(root)),'bytes':p.stat().st_size,'sha256':h})
(root/'RETURN_MANIFEST.json').write_text(json.dumps({'contract':'FQT_M6R36_RETURN_MANIFEST_V1','files':rows},indent=2)+'\n')
print(json.dumps({'files':len(rows)},indent=2))
PY
