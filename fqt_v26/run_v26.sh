#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
ROOT="${1:-$PWD/fqt_v26_work}"
mkdir -p "$ROOT"/{evidence/{capa,data,correctness,results,skills,statistics,stress,validation},logs,raw,user_data/{strategies,data/binance,backtest_results},seed,summaries,release,tmp}
cd "$ROOT"
REPO_ROOT="${GITHUB_WORKSPACE:-$PWD/..}"

# Optional swap for the 41-pair matrix. Failure does not silently change the test contract.
if command -v sudo >/dev/null 2>&1; then
  set +e
  sudo fallocate -l 8G /swapfile 2>/dev/null && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo $? > evidence/swap_setup.rc
  set -e
fi
free -h > evidence/memory_before.txt || true
df -h > evidence/disk_before.txt || true

# Skill registry / contract freeze.
cp "$REPO_ROOT/fqt_v26/skills/FQTPX_SKILL_REGISTRY_V1.md" evidence/skills/
cp "$REPO_ROOT/fqt_v26/skills/skill_contracts.json" evidence/skills/
python - <<'PY'
import hashlib,json,pathlib
p=pathlib.Path('evidence/skills/skill_contracts.json')
o=json.loads(p.read_text())
assert [x['id'] for x in o['skills']]==[f'fqtpx{i:03d}' for i in range(1,10)]
pathlib.Path('evidence/skills/FQTPX_INSTALL_RECEIPT.json').write_text(json.dumps({
 'contract':'FQT_PROJECT_LOCAL_SKILL_INSTALL_V1','status':'PASS','skill_count':9,
 'skills':[x['id'] for x in o['skills']], 'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),
 'registry_type':'project-local; no external plugin registry package was available',
},indent=2)+'\n')
PY

# Last-iteration CAPA first: retrieve and normalize the completed Iteration-3B return.
set +e
curl -fL --retry 3 --connect-timeout 20 \
  -H "Authorization: Bearer ${GITHUB_TOKEN:-}" -H 'Accept: application/vnd.github+json' \
  'https://api.github.com/repos/fdzykonski-ui/Indy/actions/artifacts/9612713371/zip' \
  -o raw/FQT_V24_Iteration3B_GitHubArtifact.zip
CAPA_DL_RC=$?
set -e
echo "$CAPA_DL_RC" > evidence/capa/iteration3b_download.rc
if [[ "$CAPA_DL_RC" == "0" ]]; then
  python "$REPO_ROOT/fqt_v26/normalize_iteration3b.py" \
    --artifact raw/FQT_V24_Iteration3B_GitHubArtifact.zip \
    --out evidence/capa/ITERATION3B_CAPA_FINAL.json | tee logs/iteration3b_normalize.log
else
  python - <<'PY'
import json,pathlib
pathlib.Path('evidence/capa/ITERATION3B_CAPA_FINAL.json').write_text(json.dumps({
 'contract':'FQT_V26_ITERATION3B_CAPA_NORMALIZATION_V1','lookahead':{'status':'BLOCKED','valid_verdict':False,'has_bias':None,'row_count':0},
 'recursive':{'status':'BLOCKED','pass':False},'decision':'CAPA_ARTIFACT_UNAVAILABLE_RERUN_REQUIRED'
},indent=2)+'\n')
PY
fi

# Deterministic project seed reconstruction.
python "$REPO_ROOT/fqt_v26/reconstruct_seed.py" \
  --chunks-dir "$REPO_ROOT/fqt_ip04a" \
  --out-zip tmp/FQT_G05_SEED.reconstructed.zip \
  --extract-dir seed \
  --receipt evidence/SEED_RECONSTRUCTION.json | tee logs/seed_reconstruction.log

# Freqtrade source/runtime freeze and version-bound patches.
git clone --filter=blob:none https://github.com/freqtrade/freqtrade.git freqtrade_src
git -C freqtrade_src checkout --detach 77cabd291fa656ec6a1d237cfa524ee792133d89
python "$REPO_ROOT/fqt_ip04a/verify_source.py" "$REPO_ROOT/fqt_ip04a/FREQTRADE_PROJECT_SOURCE_RECEIPT.json" freqtrade_src
{
  echo '--- a/freqtrade/optimize/backtesting.py'
  echo '+++ b/freqtrade/optimize/backtesting.py'
  tail -n +3 "$REPO_ROOT/fqt_ip04a/backtesting_memory_patch_v3.diff"
} > evidence/backtesting_memory_patch_v3.relative.diff
patch -d freqtrade_src -p1 < evidence/backtesting_memory_patch_v3.relative.diff
python "$REPO_ROOT/fqt_v24/patch_lookahead_contract.py" | tee logs/lookahead_patch.log
git -C freqtrade_src diff --check
git -C freqtrade_src rev-parse HEAD > evidence/FREQTRADE_GIT_HEAD.txt
git -C freqtrade_src diff > evidence/FREQTRADE_PATCHSET.diff
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-cache-dir -e ./freqtrade_src
python -m freqtrade --version | tee evidence/freqtrade_version.log

# Strategy/config construction and 41-pair selection without performance labels.
cp seed/M4PioneerStableExposureV10.py user_data/strategies/M4PioneerStableExposureV10.py
cp seed/config_ip04_v10_continuous.json config_base31.json
curl -fsSL --retry 5 --retry-delay 2 --connect-timeout 20 \
  'https://data-api.binance.vision/api/v3/exchangeInfo?permissions=SPOT&showPermissionSets=true' \
  -o evidence/data/exchangeInfo.json
sha256sum evidence/data/exchangeInfo.json > evidence/data/exchangeInfo.sha256
python "$REPO_ROOT/fqt_v26/select_universe_41.py" \
  --base-config config_base31.json --out-config config41.json \
  --receipt evidence/data/UNIVERSE_41_SELECTION.json --raw raw | tee logs/universe_selection.log
python - <<'PY'
import json,pathlib
p=pathlib.Path('config41.json'); c=json.loads(p.read_text())
c['datadir']='user_data/data/binance'; c['user_data_dir']='user_data'; c['max_open_trades']=1
c['stake_amount']='unlimited'; c['dry_run_wallet']=1000; c['tradable_balance_ratio']=0.99
c['dry_run']=True; c['initial_state']='stopped'; c['force_entry_enable']=False
c.setdefault('api_server',{})['enabled']=False; c.setdefault('telegram',{})['enabled']=False
c['exchange']['key']=''; c['exchange']['secret']=''
c['lookahead_allow_limit_orders']=True; c['lookahead_preserve_portfolio_contract']=True
p.write_text(json.dumps(c,indent=2)+'\n')
r=pathlib.Path('config41_reverse.json'); d=json.loads(json.dumps(c)); d['exchange']['pair_whitelist']=list(reversed(d['exchange']['pair_whitelist'])); r.write_text(json.dumps(d,indent=2)+'\n')
PY
python "$REPO_ROOT/fqt_v26/build_candidate_strategies.py" \
  --source user_data/strategies/M4PioneerStableExposureV10.py \
  --out user_data/strategies/M4PioneerV26Factory.py \
  --receipt evidence/CANDIDATE_REGISTRY.json | tee logs/candidate_build.log
python "$REPO_ROOT/fqt_v26/append_v14_delay.py"
python "$REPO_ROOT/fqt_v26/append_baseline_controls.py"
python -m py_compile user_data/strategies/M4PioneerV26Factory.py

# Data contract: Dec 2025 warmup, Jan-Jul monthly and Aug 1-14 daily archives.
python "$REPO_ROOT/fqt_ip04a/prepare_main_data.py" \
  --config config41.json --datadir user_data/data/binance --raw raw \
  --manifest evidence/data/MAIN_DEC_APR_MANIFEST.json | tee logs/data_dec_apr.log
python "$REPO_ROOT/fqt_v26/prepare_full_data_20260814.py" \
  --config config41.json --datadir user_data/data/binance --raw raw \
  --manifest evidence/data/FULL_DATA_MANIFEST.json | tee logs/data_full.log

export FQT_EXCHANGE_INFO_PATH="$ROOT/evidence/data/exchangeInfo.json"
export FQT_CONFIG_PATH="$ROOT/config41.json"
python "$REPO_ROOT/fqt_v26/freqtrade_offline_dynamic.py" list-data \
  --userdir user_data --datadir user_data/data/binance --data-format-ohlcv parquet --no-color | tee evidence/data/list_data.log
python "$REPO_ROOT/fqt_v26/freqtrade_offline_dynamic.py" list-strategies \
  --userdir user_data --strategy-path user_data/strategies --no-color | tee evidence/list_strategies.log
python "$REPO_ROOT/fqt_v26/freqtrade_offline_dynamic.py" show-config -c config41.json --no-color | tee evidence/show_config.log
sha256sum config41.json config41_reverse.json user_data/strategies/M4PioneerV26Factory.py > evidence/FREEZE_HASHES.sha256

run_bt() {
  local label="$1" strategy="$2" timerange="$3" fee="$4" config="$5"
  local log="logs/${label}.log" rcfile="logs/${label}.rc" outzip="evidence/results/${label}.zip" outjson="summaries/${label}.json"
  local before latest
  before=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2- || true)
  set +e
  FQT_CONFIG_PATH="$ROOT/$config" /usr/bin/time -v -o "logs/${label}.time" \
    python "$REPO_ROOT/fqt_v26/freqtrade_offline_dynamic.py" backtesting \
      -c "$config" --strategy-path user_data/strategies -s "$strategy" -i 1m \
      --timerange "$timerange" --fee "$fee" --export trades --breakdown month --cache none --no-color \
      >"$log" 2>&1
  local rc=$?
  set -e
  echo "$rc" > "$rcfile"
  if [[ "$rc" != "0" ]]; then
    python - "$outjson" "$strategy" "$label" "$rc" <<'PY'
import json,pathlib,sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({'status':'FAILED','strategy':sys.argv[2],'label':sys.argv[3],'exit_code':int(sys.argv[4])},indent=2)+'\n')
PY
    return 0
  fi
  latest=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  if [[ -z "$latest" || "$latest" == "$before" ]]; then
    echo 'No new result archive' >> "$log"
    python - "$outjson" "$strategy" "$label" <<'PY'
import json,pathlib,sys
pathlib.Path(sys.argv[1]).write_text(json.dumps({'status':'FAILED_NO_NEW_RESULT','strategy':sys.argv[2],'label':sys.argv[3]},indent=2)+'\n')
PY
    return 0
  fi
  cp "$latest" "$outzip"
  python "$REPO_ROOT/fqt_v26/summarize_result.py" --result "$outzip" --strategy "$strategy" --timerange "$timerange" --out "$outjson" >> "$log" 2>&1
}

# fqtpx004 controls and fqtpx005 preregistered candidate screen.
CANDIDATES=(M4PioneerValidationV14 M4PioneerV26FullStake M4PioneerV26VWAPPrune M4PioneerV26CausalQuality M4PioneerV26PathQuality M4PioneerV26TailBrake M4PioneerV26Balanced)
for s in "${CANDIDATES[@]}"; do
  run_bt "${s}__train" "$s" 20260101-20260401 0.001 config41.json
  run_bt "${s}__validation" "$s" 20260401-20260623 0.001 config41.json
done
run_bt 'FQTV26EMABaseline__train' FQTV26EMABaseline 20260101-20260401 0.001 config41.json
run_bt 'FQTV26ReverseEMANegativeControl__train' FQTV26ReverseEMANegativeControl 20260101-20260401 0.001 config41.json
run_bt 'FQTV26PeriodicNegativeControl__train' FQTV26PeriodicNegativeControl 20260101-20260401 0.001 config41.json

python - <<'PY'
import json,pathlib,math
candidates=['M4PioneerValidationV14','M4PioneerV26FullStake','M4PioneerV26VWAPPrune','M4PioneerV26CausalQuality','M4PioneerV26PathQuality','M4PioneerV26TailBrake','M4PioneerV26Balanced']
rows=[]
def f(v,d=-1e99):
 try:
  x=float(v); return x if math.isfinite(x) else d
 except:return d
for c in candidates:
 p=pathlib.Path('summaries')/f'{c}__validation.json'
 t=pathlib.Path('summaries')/f'{c}__train.json'
 if not p.exists() or not t.exists():continue
 v=json.loads(p.read_text()); tr=json.loads(t.read_text())
 if v.get('status')!='EXECUTED' or tr.get('status')!='EXECUTED':continue
 monthly=v.get('monthly',{}); mp=sum(f((monthly.get(m) or {}).get('profit_usdc'))>0 for m in ['2026-04','2026-05','2026-06'])
 score=(mp, f(v.get('profit_factor'),0), f(v.get('profit_usdc')), f(v.get('winrate_pct')), f(tr.get('profit_usdc')))
 rows.append({'candidate':c,'score':score,'validation':v,'train':tr})
rows=sorted(rows,key=lambda r:tuple(r['score']),reverse=True)
out={'contract':'FQT_V26_PRELIMINARY_TOP3_V1','rows':rows,'top3':[r['candidate'] for r in rows[:3]]}
pathlib.Path('evidence/validation/PRELIMINARY_TOP3.json').write_text(json.dumps(out,indent=2)+'\n')
pathlib.Path('evidence/validation/top3.txt').write_text('\n'.join(out['top3'])+'\n')
print(json.dumps(out,indent=2))
PY

while IFS= read -r s; do
  [[ -n "$s" ]] || continue
  run_bt "${s}__fee15" "$s" 20260401-20260623 0.0015 config41.json
  run_bt "${s}__fee20" "$s" 20260401-20260623 0.002 config41.json
  if [[ "$s" == 'M4PioneerValidationV14' ]]; then delay='M4PioneerValidationV14Delay1'; else delay="${s}Delay1"; fi
  run_bt "${delay}__delay1" "$delay" 20260401-20260623 0.001 config41.json
  run_bt "${s}__reverse" "$s" 20260401-20260623 0.001 config41_reverse.json
done < evidence/validation/top3.txt

# Preliminary choice (correctness placeholder only identifies the candidate; it does not authorize OOS).
cat > evidence/correctness/CORRECTNESS_PLACEHOLDER.json <<'JSON'
{"lookahead":{"status":"PASS","has_bias":false},"recursive":{"status":"PASS"}}
JSON
python "$REPO_ROOT/fqt_v26/select_candidate.py" --summaries summaries \
  --correctness evidence/correctness/CORRECTNESS_PLACEHOLDER.json \
  --out evidence/validation/SELECTION_PRELIMINARY.json | tee logs/selection_preliminary.log
SELECTED=$(python - <<'PY'
import json
print(json.load(open('evidence/validation/SELECTION_PRELIMINARY.json')).get('chosen_candidate') or 'M4PioneerValidationV14')
PY
)
echo "$SELECTED" | tee evidence/validation/SELECTED_CANDIDATE.txt

# Current corrected native lookahead for the exact selected class.
set +e
FQT_CONFIG_PATH="$ROOT/config41.json" python "$REPO_ROOT/fqt_v26/freqtrade_offline_dynamic.py" lookahead-analysis \
  -c config41.json --strategy-path user_data/strategies -s "$SELECTED" -i 1m \
  --timerange 20260101-20260623 --fee 0.001 --minimum-trade-amount 10 --targeted-trade-amount 50 \
  --lookahead-analysis-exportfilename "$ROOT/evidence/correctness/lookahead_selected.csv" --no-color \
  > logs/lookahead_selected.log 2>&1
LOOK_RC=$?
set -e
echo "$LOOK_RC" > evidence/correctness/lookahead_selected.rc

# Native recursive representative matrix. Syntax is frozen and failures are evidence, not hidden.
NEW_PAIR=$(python - <<'PY'
import json
print(json.load(open('evidence/data/UNIVERSE_41_SELECTION.json'))['additions'][0])
PY
)
mkdir -p logs/recursive
for pair in 'BTC/USDC' 'ETH/USDC' 'SHIB/USDC' "$NEW_PAIR"; do
  token=$(echo "$pair" | tr '/:' '__')
  set +e
  FQT_CONFIG_PATH="$ROOT/config41.json" python "$REPO_ROOT/fqt_v26/freqtrade_offline_dynamic.py" recursive-analysis \
    -c config41.json --strategy-path user_data/strategies -s "$SELECTED" -i 1m \
    --timerange 20260101-20260401 -p "$pair" --startup-candle 200 400 800 1100 1600 --no-color \
    > "logs/recursive/recursive_${token}.log" 2>&1
  rc=$?
  set -e
  echo "$rc" > "logs/recursive/recursive_${token}.rc"
done
set +e
python "$REPO_ROOT/fqt_v26/summarize_recursive.py" --logs-dir logs/recursive \
  --out evidence/correctness/RECURSIVE_REPRESENTATIVE.json | tee logs/recursive_summary.log
RECUR_SUM_RC=$?
set -e

set +e
python "$REPO_ROOT/fqt_v26/metamorphic_full_universe.py" \
  --strategy-file user_data/strategies/M4PioneerV26Factory.py --strategy "$SELECTED" \
  --config config41.json --datadir user_data/data/binance \
  --out evidence/correctness/METAMORPHIC_41PAIR.json | tee logs/metamorphic_41pair.log
META_RC=$?
set -e
echo "$META_RC" > evidence/correctness/metamorphic_41pair.rc
python "$REPO_ROOT/fqt_v26/parse_correctness.py" \
  --lookahead-csv evidence/correctness/lookahead_selected.csv \
  --lookahead-rc evidence/correctness/lookahead_selected.rc \
  --recursive-receipt evidence/correctness/RECURSIVE_REPRESENTATIVE.json \
  --metamorphic-receipt evidence/correctness/METAMORPHIC_41PAIR.json \
  --iteration3b evidence/capa/ITERATION3B_CAPA_FINAL.json \
  --out evidence/correctness/CORRECTNESS_SUMMARY.json | tee logs/correctness_summary.log

# Select again with real correctness evidence.
python "$REPO_ROOT/fqt_v26/select_candidate.py" --summaries summaries \
  --correctness evidence/correctness/CORRECTNESS_SUMMARY.json \
  --out evidence/validation/SELECTION_CORRECTNESS.json | tee logs/selection_correctness.log
SELECTED=$(python - <<'PY'
import json
print(json.load(open('evidence/validation/SELECTION_CORRECTNESS.json')).get('chosen_candidate') or 'M4PioneerValidationV14')
PY
)
echo "$SELECTED" > evidence/validation/SELECTED_CANDIDATE.txt

# Determinism on the selected validation ledger.
run_bt "${SELECTED}__validation_rerun" "$SELECTED" 20260401-20260623 0.001 config41.json
python - <<'PY'
import json,pathlib
s=json.load(open(f'summaries/{pathlib.Path("evidence/validation/SELECTED_CANDIDATE.txt").read_text().strip()}__validation.json'))
r=json.load(open(f'summaries/{pathlib.Path("evidence/validation/SELECTED_CANDIDATE.txt").read_text().strip()}__validation_rerun.json'))
out={'contract':'FQT_V26_DETERMINISM_V1','run1_hash':s.get('semantic_trade_ledger_sha256'),'run2_hash':r.get('semantic_trade_ledger_sha256'),'trades1':s.get('trades'),'trades2':r.get('trades')}
out['pass']=out['run1_hash']==out['run2_hash'] and out['trades1']==out['trades2'] and s.get('status')=='EXECUTED' and r.get('status')=='EXECUTED'
pathlib.Path('evidence/validation/DETERMINISM.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
PY

# Five representative LOPO runs and same-candle audit.
for pair in 'BTC/USDC' 'ETH/USDC' 'SOL/USDC' 'XRP/USDC' 'BNB/USDC'; do
  token=$(echo "$pair" | tr '/:' '__')
  python - "$pair" "$token" <<'PY'
import json,pathlib,sys
pair,token=sys.argv[1],sys.argv[2]
c=json.load(open('config41.json')); c['exchange']['pair_whitelist']=[x for x in c['exchange']['pair_whitelist'] if x!=pair]
pathlib.Path(f'config_lopo_{token}.json').write_text(json.dumps(c,indent=2)+'\n')
PY
  run_bt "${SELECTED}__lopo_${token}" "$SELECTED" 20260401-20260623 0.001 "config_lopo_${token}.json"
done
python - <<'PY'
import json,pathlib
selected=pathlib.Path('evidence/validation/SELECTED_CANDIDATE.txt').read_text().strip(); rows=[]
for p in sorted(pathlib.Path('summaries').glob(f'{selected}__lopo_*.json')):
 o=json.load(open(p)); ok=o.get('status')=='EXECUTED' and float(o.get('profit_usdc',-1))>0 and float(o.get('profit_factor') or 0)>1 and float(o.get('winrate_pct',0))>=75 and float(o.get('max_drawdown_pct',99))<7
 rows.append({'file':p.name,'pass':ok,'trades':o.get('trades'),'profit_usdc':o.get('profit_usdc'),'profit_factor':o.get('profit_factor'),'winrate_pct':o.get('winrate_pct')})
out={'contract':'FQT_V26_REPRESENTATIVE_LOPO_V1','rows':rows,'pass_count':sum(r['pass'] for r in rows),'pass':len(rows)==5 and sum(r['pass'] for r in rows)>=4}
pathlib.Path('evidence/validation/LOPO_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n')
PY
python - <<'PY'
import json,pathlib,zipfile
selected=pathlib.Path('evidence/validation/SELECTED_CANDIDATE.txt').read_text().strip(); zp=pathlib.Path(f'evidence/results/{selected}__validation.zip')
with zipfile.ZipFile(zp) as z:
 n=[x for x in z.namelist() if x.endswith('.json') and not x.endswith('_config.json')][0]; root=json.loads(z.read(n)); s=root['strategy'][selected]
tr=s.get('trades',[]); same=sum((t.get('open_timestamp')==t.get('close_timestamp')) or int(t.get('trade_duration') or 0)==0 for t in tr)
out={'contract':'FQT_V26_SAME_CANDLE_AUDIT_V1','trades':len(tr),'same_candle_trades':same,'pass':same==0}
pathlib.Path('evidence/validation/SAME_CANDLE_AUDIT.json').write_text(json.dumps(out,indent=2)+'\n')
PY

# Data fault-injection contract: validator must detect duplicate, gap and negative-volume corruptions.
python - <<'PY'
import json,pathlib,pandas as pd
p=pathlib.Path('user_data/data/binance/BTC_USDC-1m.parquet'); df=pd.read_parquet(p).iloc[:5000].copy()
def validate(x):
 t=pd.to_datetime(x.date,utc=True).astype('int64').to_numpy(); return {'duplicates':int(len(t)-len(set(map(int,t)))),'gaps':int(((t[1:]-t[:-1])!=60_000_000_000).sum()),'negative_volume':int((x.volume<0).sum())}
base=validate(df); dup=validate(pd.concat([df,df.iloc[[100]]],ignore_index=True)); gap=validate(df.drop(index=100).reset_index(drop=True)); neg=df.copy();neg.loc[100,'volume']=-1;negative=validate(neg)
out={'contract':'FQT_V26_FAULT_INJECTION_V1','base':base,'duplicate_case':dup,'gap_case':gap,'negative_case':negative,'pass':base=={'duplicates':0,'gaps':0,'negative_volume':0} and dup['duplicates']>0 and gap['gaps']>0 and negative['negative_volume']>0}
pathlib.Path('evidence/validation/FAULT_INJECTION.json').write_text(json.dumps(out,indent=2)+'\n')
PY

# Training-only multi-seed Hyperopt diagnostic (no parameter adoption, no OOS access).
mkdir -p evidence/hyperopt
for seed in 11 29 47; do
  set +e
  FQT_CONFIG_PATH="$ROOT/config41.json" python "$REPO_ROOT/fqt_v26/freqtrade_offline_dynamic.py" hyperopt \
    -c config41.json --strategy-path user_data/strategies -s "$SELECTED" -i 1m \
    --timerange 20260101-20260301 --fee 0.001 --spaces roi stoploss \
    --epochs 8 --random-state "$seed" --min-trades 50 --hyperopt-loss SharpeHyperOptLossDaily --no-color \
    > "logs/hyperopt_seed_${seed}.log" 2>&1
  rc=$?
  set -e
  echo "$rc" > "evidence/hyperopt/seed_${seed}.rc"
done
python - <<'PY'
import json,pathlib
rows=[]
for p in sorted(pathlib.Path('evidence/hyperopt').glob('seed_*.rc')):
 rc=int(p.read_text().strip()); rows.append({'seed':p.stem.split('_')[-1],'exit_code':rc,'pass':rc==0})
out={'contract':'FQT_V26_MULTI_SEED_HYPEROPT_DIAGNOSTIC_V1','epochs_per_seed':8,'spaces':['roi','stoploss'],'training_range':'[2026-01-01,2026-03-01)','rows':rows,'pass':bool(rows and all(r['pass'] for r in rows)),'adopted_parameters':False,'reason':'Diagnostic only; no stable plateau proof and no OOS peeking.'}
pathlib.Path('evidence/hyperopt/HYPEROPT_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n')
PY

# Extended predecessor gates and final OOS authorization.
python - <<'PY'
import json,pathlib
manifest=json.load(open('evidence/data/FULL_DATA_MANIFEST.json')); det=json.load(open('evidence/validation/DETERMINISM.json')); lopo=json.load(open('evidence/validation/LOPO_SUMMARY.json')); same=json.load(open('evidence/validation/SAME_CANDLE_AUDIT.json')); fault=json.load(open('evidence/validation/FAULT_INJECTION.json'))
out={'contract':'FQT_V26_EXTENDED_PREDECESSOR_GATES_V1','data_integrity_pass':manifest.get('pair_count')==41 and all(r.get('gaps')==0 and r.get('duplicates')==0 for r in manifest.get('records',[])),'determinism_pass':bool(det.get('pass')),'lopo_pass':bool(lopo.get('pass')),'same_candle_pass':bool(same.get('pass')),'fault_injection_pass':bool(fault.get('pass')),'hyperopt_diagnostic':json.load(open('evidence/hyperopt/HYPEROPT_SUMMARY.json'))}
pathlib.Path('evidence/validation/EXTENDED_GATES.json').write_text(json.dumps(out,indent=2)+'\n')
PY
python "$REPO_ROOT/fqt_v26/apply_extended_gates.py" \
  --selection evidence/validation/SELECTION_CORRECTNESS.json \
  --extended evidence/validation/EXTENDED_GATES.json \
  --out evidence/validation/SELECTION_FINAL.json | tee logs/selection_final.log

AUTHORIZED=$(python - <<'PY'
import json
print('true' if json.load(open('evidence/validation/SELECTION_FINAL.json')).get('oos_authorized') else 'false')
PY
)
SELECTED=$(python - <<'PY'
import json
print(json.load(open('evidence/validation/SELECTION_FINAL.json')).get('chosen_candidate') or 'M4PioneerValidationV14')
PY
)

# One-shot OOS batch: no reruns, no threshold revision, only if every predecessor passed.
if [[ "$AUTHORIZED" == "true" ]]; then
  touch evidence/validation/OOS_OPENED_ONCE.lock
  run_bt 'M4PioneerValidationV14__oos' M4PioneerValidationV14 20260623-20260815 0.001 config41.json
  run_bt "${SELECTED}__oos" "$SELECTED" 20260623-20260815 0.001 config41.json
  run_bt "${SELECTED}__oos_fee15" "$SELECTED" 20260623-20260815 0.0015 config41.json
  run_bt 'M4PioneerValidationV14__full' M4PioneerValidationV14 20260101-20260815 0.001 config41.json
  run_bt "${SELECTED}__full" "$SELECTED" 20260101-20260815 0.001 config41.json
else
  echo 'OOS_NOT_OPENED_PREDECESSOR_GATE' > evidence/validation/OOS_BLOCKED.txt
fi

python "$REPO_ROOT/fqt_v26/finalize_v26.py" \
  --selection evidence/validation/SELECTION_FINAL.json \
  --correctness evidence/correctness/CORRECTNESS_SUMMARY.json \
  --summaries summaries --factory-strategy user_data/strategies/M4PioneerV26Factory.py \
  --config config41.json --out-dir release | tee logs/finalize.log
python -m py_compile release/M4PioneerV26Final.py

# Skill execution receipts.
python - <<'PY'
import json,pathlib,hashlib
sel=json.load(open('evidence/validation/SELECTION_FINAL.json')); cor=json.load(open('evidence/correctness/CORRECTNESS_SUMMARY.json')); summ=json.load(open('release/summary.json')); ext=json.load(open('evidence/validation/EXTENDED_GATES.json'))
skills={
'fqtpx001':('PASS',{'freeze':'evidence/FREEZE_HASHES.sha256'}),
'fqtpx002':('PASS' if ext['data_integrity_pass'] else 'FAIL',{'manifest':'evidence/data/FULL_DATA_MANIFEST.json'}),
'fqtpx003':('PASS' if cor.get('pass') else 'FAIL',cor),
'fqtpx004':('PASS' if ext['determinism_pass'] else 'FAIL',{'determinism':'evidence/validation/DETERMINISM.json','controls':['EMA','ReverseEMA','Periodic']}),
'fqtpx005':('PASS_DIAGNOSTIC' if ext['hyperopt_diagnostic'].get('pass') else 'BLOCKED',ext['hyperopt_diagnostic']),
'fqtpx006':('PASS' if ext['lopo_pass'] else 'FAIL',{'lopo':'evidence/validation/LOPO_SUMMARY.json'}),
'fqtpx007':('PASS' if sel.get('selection_pass') else 'FAIL',{'selection':sel.get('chosen_candidate'),'checks':sel.get('authorization_checks')}),
'fqtpx008':('PASS' if summ.get('oos_opened') and summ.get('promotion_pass') else ('FAIL' if summ.get('oos_opened') else 'NOT_RUN'),{'oos_opened':summ.get('oos_opened'),'promotion_checks':summ.get('promotion_checks')}),
'fqtpx009':('BLOCKED',{'dry_run_started':False,'live_allowed':False}),
}
for sid,(status,evidence) in skills.items():
 pathlib.Path(f'evidence/skills/{sid}_RECEIPT.json').write_text(json.dumps({'skill':sid,'status':status,'evidence':evidence},indent=2,default=str)+'\n')
PY

# Compact chat extract and complete return package (no raw OHLCV archives/parquets).
python - <<'PY'
import json,pathlib
s=json.load(open('release/summary.json'))
lines=['FQT V26 NATIVE EXECUTION EXTRACT',f"decision={s.get('decision')}",f"selected={s.get('selected_system')}",f"oos_opened={s.get('oos_opened')}",f"promotion_pass={s.get('promotion_pass')}"]
for key in ['baseline_oos','candidate_oos','candidate_oos_fee15','baseline_full_period','candidate_full_period']:
 o=s.get(key)
 if isinstance(o,dict):lines.append(f"{key}|trades={o.get('trades')}|WR={o.get('winrate_pct')}|profit_pct={o.get('profit_pct')}|PF={o.get('profit_factor')}|DD={o.get('max_drawdown_pct')}")
pathlib.Path('release/CHAT_LOG_BLOCK.txt').write_text('\n'.join(lines)+'\n')
PY
find evidence summaries release logs -type f -print0 | sort -z | xargs -0 sha256sum > release/SHA256SUMS.txt
python - <<'PY'
import json,pathlib,zipfile
root=pathlib.Path('.');out=pathlib.Path('FQT_V26_PIONEER_FACTORY_RETURN.zip')
with zipfile.ZipFile(out,'w',allowZip64=True) as z:
 for base in ['evidence','summaries','release','logs']:
  for p in sorted(pathlib.Path(base).rglob('*')):
   if not p.is_file():continue
   if 'raw' in p.parts or p.suffix=='.parquet':continue
   method=zipfile.ZIP_STORED if p.suffix=='.zip' else zipfile.ZIP_DEFLATED
   z.write(p,p.as_posix(),compress_type=method)
 z.write('config41.json','inputs/config41.json',compress_type=zipfile.ZIP_DEFLATED)
 z.write('user_data/strategies/M4PioneerV26Factory.py','inputs/M4PioneerV26Factory.py',compress_type=zipfile.ZIP_DEFLATED)
with zipfile.ZipFile(out) as z:
 bad=z.testzip()
 if bad:raise SystemExit(f'CRC {bad}')
print(json.dumps({'return_zip':str(out),'bytes':out.stat().st_size},indent=2))
PY
sha256sum FQT_V26_PIONEER_FACTORY_RETURN.zip > FQT_V26_PIONEER_FACTORY_RETURN.zip.sha256
free -h > evidence/memory_after.txt || true
df -h > evidence/disk_after.txt || true
