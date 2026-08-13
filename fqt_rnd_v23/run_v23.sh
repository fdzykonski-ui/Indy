#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1 TZ=UTC
mkdir -p evidence/v23 user_data/strategies user_data/backtest_results

# Reconstruct the frozen project source, install exact Freqtrade commit, materialize
# the full Dec-2025 through Apr-2026 31-pair data and execute the deterministic V10 anchor.
chmod +x fqt_ip04a/run_ip04a_v2.sh
fqt_ip04a/run_ip04a_v2.sh 2>&1 | tee evidence/v23/setup_and_v10_baseline.log

cp fqt_rnd_v23/M4PioneerContractCleanV15.py user_data/strategies/
python -m py_compile user_data/strategies/M4PioneerContractCleanV15.py

python - <<'PY'
import json, pathlib
base=json.loads(pathlib.Path('config_ip04.json').read_text())
base['dry_run']=True
base['dry_run_wallet']=1000
base['stake_currency']='USDC'
base['stake_amount']='unlimited'
base['max_open_trades']=2
base['timeframe']='1m'
base['trading_mode']='spot'
base['initial_state']='stopped'
base.setdefault('api_server',{})['enabled']=False
base.setdefault('telegram',{})['enabled']=False
base.setdefault('exchange',{})['key']=''
base['exchange']['secret']=''
base['exchange']['enable_ws']=False
base['force_entry_enable']=False
base['governance_v23']={
  'live_trading_forbidden':True,
  'fresh_oos_opened':False,
  'known_evaluation_integrity':'CONTAMINATED',
  'wip_limit':1,
  'champion':'M4PioneerValidationV14',
  'challenger':'M4PioneerContractCleanV15',
  'development_surface':'Portfolio/Capital'
}
for name,strategy in [
 ('config_v14.json','M4PioneerValidationV14'),
 ('config_v15.json','M4PioneerContractCleanV15'),
 ('config_v15_delay1.json','M4PioneerContractCleanV15_DELAY1'),
 ('config_v15_delay2.json','M4PioneerContractCleanV15_DELAY2')]:
 c=json.loads(json.dumps(base)); c['strategy']=strategy
 pathlib.Path(name).write_text(json.dumps(c,indent=2,sort_keys=True)+'\n')
look=json.loads(json.dumps(base)); look['strategy']='M4PioneerContractCleanV15'
look.setdefault('entry_pricing',{})['price_side']='other'
look.setdefault('exit_pricing',{})['price_side']='other'
look.pop('order_types',None)
pathlib.Path('config_v15_lookahead.json').write_text(json.dumps(look,indent=2,sort_keys=True)+'\n')
PY

python fqt_ip04a/seed/freqtrade_offline.py list-strategies \
  -c config_v15.json --userdir user_data --strategy-path user_data/strategies \
  2>&1 | tee evidence/v23/list_strategies.log
if grep -Eq 'DUPLICATE NAME|LOAD FAILED' evidence/v23/list_strategies.log; then
  echo 'Strategy resolution failed closed' >&2; exit 20
fi
python fqt_ip04a/seed/freqtrade_offline.py show-config -c config_v15.json \
  2>&1 | tee evidence/v23/show_config_v15.log

# Contract defect reproducer and target verification.
python - <<'PY' | tee evidence/v23/pairguard_target_test.json
import datetime as dt, importlib.util, json, pathlib
p=pathlib.Path('user_data/strategies/M4PioneerContractCleanV15.py')
spec=importlib.util.spec_from_file_location('v15overlay',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
tag='btcp_v6971|trend_pullback|tier_B|score_69|risk_NORMAL_STAKE|policy_TEST|regime_clean_uptrend|fp_trend_pullback'
a,b='2Z/USDC','AAVE/USDC'
v14=m.M4PioneerValidationV14({}); v15=m.M4PioneerContractCleanV15({})
kw=dict(current_time=dt.datetime(2026,1,2,tzinfo=dt.timezone.utc),current_rate=1.0,proposed_stake=100.0,min_stake=5.0,max_stake=500.0,leverage=1.0,entry_tag=tag,side='long')
out={
 'contract':'FQT_RND_V23_PAIRGUARD_TARGET_TEST_V1',
 'v14':{'factor_a':m.M4PioneerValidationV14._portfolio_factor(a,tag),'factor_b':m.M4PioneerValidationV14._portfolio_factor(b,tag),'stake_a':v14.custom_stake_amount(pair=a,**kw),'stake_b':v14.custom_stake_amount(pair=b,**kw)},
 'v15':{'factor_a':m.M4PioneerContractCleanV15._portfolio_factor(a,tag),'factor_b':m.M4PioneerContractCleanV15._portfolio_factor(b,tag),'stake_a':v15.custom_stake_amount(pair=a,**kw),'stake_b':v15.custom_stake_amount(pair=b,**kw)},
}
out['v14_pair_dependency_reproduced']=out['v14']['stake_a']!=out['v14']['stake_b']
out['v15_pair_independence_verified']=out['v15']['stake_a']==out['v15']['stake_b']
out['status']='PASS' if out['v14_pair_dependency_reproduced'] and out['v15_pair_independence_verified'] else 'FAIL'
print(json.dumps(out,indent=2,sort_keys=True))
if out['status']!='PASS': raise SystemExit(21)
PY

# Full 31-pair lookahead gate. Freqtrade supplies the complete market-order contract;
# config only changes compatible price sides and intentionally omits partial order_types.
set +e
python fqt_ip04a/seed/freqtrade_offline.py lookahead-analysis \
  -c config_v15_lookahead.json \
  --strategy-path user_data/strategies \
  -s M4PioneerContractCleanV15 -i 1m \
  --timerange 20260101-20260501 --fee 0.001 \
  --minimum-trade-amount 10 --targeted-trade-amount 50 \
  --lookahead-analysis-exportfilename evidence/v23/lookahead_v15_31pair.csv \
  --no-color 2>&1 | tee evidence/v23/lookahead_v15_31pair.log
look_rc=${PIPESTATUS[0]}
set -e
python - "$look_rc" <<'PY' | tee evidence/v23/LOOKAHEAD_V15_SUMMARY.json
import csv,json,pathlib,sys
rc=int(sys.argv[1]); p=pathlib.Path('evidence/v23/lookahead_v15_31pair.csv')
rows=list(csv.DictReader(p.open())) if p.exists() else []
vals=[]
for r in rows:
 v=str(r.get('has_bias','')).strip().lower()
 if v in ('yes','true','1'): vals.append(True)
 elif v in ('no','false','0'): vals.append(False)
out={'contract':'FQT_RND_V23_LOOKAHEAD_V15_31PAIR_V1','command_exit_code':rc,'csv_exists':p.exists(),'row_count':len(rows),'valid_verdict':bool(vals),'has_bias':any(vals) if vals else None}
out['status']='PASS' if rc==0 and out['valid_verdict'] and not out['has_bias'] else 'FAIL'
print(json.dumps(out,indent=2,sort_keys=True))
if out['status']!='PASS': raise SystemExit(22)
PY

summarize() {
  local src="$1"; local strategy="$2"; local out="$3"
  python - "$src" "$strategy" "$out" <<'PY'
import hashlib,json,math,pathlib,sys,zipfile
p=pathlib.Path(sys.argv[1]); strategy=sys.argv[2]; outp=pathlib.Path(sys.argv[3])
with zipfile.ZipFile(p) as z:
 names=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
 if len(names)!=1: raise SystemExit(f'result json count={len(names)}')
 obj=json.loads(z.read(names[0]))
 if strategy not in obj['strategy']: raise SystemExit(f'{strategy} absent: {list(obj["strategy"])}')
 s=obj['strategy'][strategy]
tr=s['trades']; wins=sum(float(t['profit_ratio'])>0 for t in tr); draws=sum(float(t['profit_ratio'])==0 for t in tr); losses=sum(float(t['profit_ratio'])<0 for t in tr); profit=sum(float(t['profit_abs']) for t in tr)
checks={
 'trade_count':len(tr)==int(s['total_trades']),
 'wins':wins==int(s['wins']), 'draws':draws==int(s['draws']), 'losses':losses==int(s['losses']),
 'profit_abs':math.isclose(profit,float(s['profit_total_abs']),rel_tol=0,abs_tol=1e-8),
 'balance':math.isclose(float(s['starting_balance'])+float(s['profit_total_abs']),float(s['final_balance']),rel_tol=0,abs_tol=1e-8),
}
ws=s.get('wallet_stats') or {}
out={
 'contract':'FQT_RND_V23_BACKTEST_SUMMARY_V1','status':'PASS' if all(checks.values()) else 'INVALID','strategy':strategy,
 'result_zip':str(p),'result_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'reconciliation':checks,
 'timerange':s.get('timerange'),'backtest_start':s.get('backtest_start'),'backtest_end':s.get('backtest_end'),
 'starting_balance':s.get('starting_balance'),'final_balance':s.get('final_balance'),'total_trades':s.get('total_trades'),
 'wins':s.get('wins'),'draws':s.get('draws'),'losses':s.get('losses'),'winrate_pct':100*float(s.get('winrate',0)),
 'profit_usdc':s.get('profit_total_abs'),'profit_pct':100*float(s.get('profit_total',0)),'profit_factor':s.get('profit_factor'),
 'closed_trade_drawdown_pct':100*float(s.get('max_drawdown_account',0)),
 'wallet_drawdown_pct':100*float(ws.get('max_drawdown_account',float('nan'))),
 'trades_per_day':s.get('trades_per_day'),'expectancy':s.get('expectancy'),'expectancy_ratio':s.get('expectancy_ratio'),
 'market_change_pct':100*float(s.get('market_change',0)), 'rejected_signals':s.get('rejected_signals'),
 'left_open_trades':len(s.get('left_open_trades') or []),
}
outp.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n'); print(json.dumps(out,indent=2,sort_keys=True))
if out['status']!='PASS': raise SystemExit(23)
PY
}

run_bt() {
  local label="$1"; local strategy="$2"; local config="$3"; local fee="$4"
  local marker="evidence/v23/.marker_${label}"
  touch "$marker"
  python fqt_ip04a/seed/freqtrade_offline.py backtesting \
    -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m \
    --timerange 20260101-20260501 --fee "$fee" --cache none --export trades \
    --breakdown month --no-color 2>&1 | tee "evidence/v23/${label}.log"
  local result
  result=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -newer "$marker" -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  test -n "$result"
  cp "$result" "evidence/v23/${label}_RESULT.zip"
  summarize "evidence/v23/${label}_RESULT.zip" "$strategy" "evidence/v23/${label}_SUMMARY.json" | tee "evidence/v23/${label}_summary_console.log"
}

run_bt V15_MAIN M4PioneerContractCleanV15 config_v15.json 0.001
run_bt V15_FEE020 M4PioneerContractCleanV15 config_v15.json 0.002
run_bt V15_FEE030 M4PioneerContractCleanV15 config_v15.json 0.003
run_bt V15_DELAY1 M4PioneerContractCleanV15_DELAY1 config_v15_delay1.json 0.001
run_bt V15_DELAY2 M4PioneerContractCleanV15_DELAY2 config_v15_delay2.json 0.001

# Baseline V10 was executed twice by the frozen setup. Reconcile and expose it as V14's
# alpha-equivalent previous champion.
cp evidence/IP04A_CONTINUOUS_RUN1.zip evidence/v23/V14_ALPHA_EQUIV_BASELINE_RESULT.zip
summarize evidence/v23/V14_ALPHA_EQUIV_BASELINE_RESULT.zip M4PioneerStableExposureV10 evidence/v23/V14_ALPHA_EQUIV_BASELINE_SUMMARY.json | tee evidence/v23/V14_baseline_summary_console.log
cp evidence/IP04A_CONTINUOUS_DETERMINISM.json evidence/v23/
cp evidence/IP04A_CONTINUOUS_RUN1_SUMMARY.json evidence/v23/
cp evidence/IP04A_CONTINUOUS_RUN2_SUMMARY.json evidence/v23/
cp evidence/MAIN_DATA_MANIFEST.json evidence/v23/
cp evidence/SOURCE_PARITY.json evidence/v23/
cp evidence/freqtrade_version.log evidence/v23/

python - <<'PY' | tee evidence/v23/V15_GATE_MATRIX.json
import json,pathlib
load=lambda n:json.loads(pathlib.Path('evidence/v23/'+n).read_text())
b=load('V14_ALPHA_EQUIV_BASELINE_SUMMARY.json'); m=load('V15_MAIN_SUMMARY.json'); f2=load('V15_FEE020_SUMMARY.json'); f3=load('V15_FEE030_SUMMARY.json'); d1=load('V15_DELAY1_SUMMARY.json'); d2=load('V15_DELAY2_SUMMARY.json'); la=load('LOOKAHEAD_V15_SUMMARY.json')
gates=[
 {'id':'G-LOOKAHEAD','pass':la['status']=='PASS','actual':la},
 {'id':'G-TRADES','pass':m['total_trades']>500,'actual':m['total_trades'],'target':'>500'},
 {'id':'G-WR','pass':m['winrate_pct']>80,'actual':m['winrate_pct'],'target':'>80%'},
 {'id':'G-PROFIT','pass':m['profit_pct']>80,'actual':m['profit_pct'],'target':'>80%'},
 {'id':'G-PF','pass':m['profit_factor']>5,'actual':m['profit_factor'],'target':'>5'},
 {'id':'G-MDD','pass':m['wallet_drawdown_pct']<=5,'actual':m['wallet_drawdown_pct'],'target':'<=5%'},
 {'id':'G-FEE020','pass':f2['profit_usdc']>0 and f2['profit_factor']>1,'actual':{'profit_usdc':f2['profit_usdc'],'pf':f2['profit_factor']}},
 {'id':'G-FEE030','pass':f3['profit_usdc']>0 and f3['profit_factor']>1,'actual':{'profit_usdc':f3['profit_usdc'],'pf':f3['profit_factor']}},
 {'id':'G-DELAY1','pass':d1['profit_usdc']>0 and d1['profit_factor']>1,'actual':{'profit_usdc':d1['profit_usdc'],'pf':d1['profit_factor']}},
 {'id':'G-DELAY2','pass':d2['profit_usdc']>0 and d2['profit_factor']>1,'actual':{'profit_usdc':d2['profit_usdc'],'pf':d2['profit_factor']}},
]
out={'contract':'FQT_RND_V23_GATE_MATRIX_V1','baseline':b,'main':m,'gates':gates,'hard_target_pass':all(x['pass'] for x in gates),'decision':'PROMOTE' if all(x['pass'] for x in gates) else 'KEEP_CHAMPION'}
print(json.dumps(out,indent=2,sort_keys=True))
PY

sha256sum user_data/strategies/M4PioneerContractCleanV15.py config_v15.json config_v15_lookahead.json > evidence/v23/V15_INPUT_HASHES.sha256
find evidence/v23 -type f -printf '%P\t%s\n' | sort > evidence/v23/ARTIFACT_INVENTORY.tsv
tar -czf FQT_RND_V23_CONTRACT_CLEAN_RETURN_20260813.tar.gz evidence/v23 user_data/strategies/M4PioneerContractCleanV15.py config_v15.json config_v15_lookahead.json
sha256sum FQT_RND_V23_CONTRACT_CLEAN_RETURN_20260813.tar.gz > FQT_RND_V23_CONTRACT_CLEAN_RETURN_20260813.tar.gz.sha256
