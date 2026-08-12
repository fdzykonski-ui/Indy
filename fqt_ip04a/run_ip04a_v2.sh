#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p evidence user_data/strategies user_data/data/binance user_data/backtest_results raw fqt_ip04a/seed fqt_ip04a/normalized
python - <<'PY'
import base64,hashlib,json,pathlib
expected={
'00':'ecc251174a150348a925e50d2f04980a1ad93a478708f655e4824a2eaba3f377',
'01':'041b6711e2778ffc4adbe20c7bcc81a07d983ac87709f1b60496d3b3e46376b3',
'02':'4f7abb0865a4ab4e909255b2eea1c1c6248542d984d4e1f4a866d1763ca78990',
'03':'18290818f25e441d6acf4fe5d8d2b8a875b3be772fa9abccbe2954217bbfe4f4',
'04':'93cbe43e53472b1b728b2a8c778c1ef4522f262c6542c1e5602c72ab92b9c140',
'05':'52857c3bc29f3d7d872e4c0d29d331e2dc811135f1951b58abf752d48213e8c6',
'06':'81cb1d0d642a6318ba435752e8a401b5cdab684d0e99418353e0309a643f3304'}
rows=[]; chunks=[]
for n,want in expected.items():
 p=pathlib.Path(f'fqt_ip04a/payload.b64.{n}'); s=''.join(p.read_text().split()); before=hashlib.sha256(s.encode()).hexdigest(); repair='none'
 if n=='02' and before!=want:
  if len(s)==12001 and s[10400]=='y' and s[11933:11937]=='Vlyw':
   s=s[:10400]+'Y'+s[10401:]; s=s[:11933]+'elw'+s[11937:]; repair='verified_transport_repair_y_to_Y_and_Vlyw_to_elw'
 if len(s)>12000 and n!='06' and hashlib.sha256(s[:12000].encode()).hexdigest()==want:
  s=s[:12000]; repair='trimmed_trailing_transport_byte'
 got=hashlib.sha256(s.encode()).hexdigest(); rows.append({'chunk':n,'chars':len(s),'sha256_before':before,'sha256_after':got,'expected':want,'repair':repair})
 if got!=want: raise SystemExit(f'chunk {n} mismatch: {got} != {want}')
 pathlib.Path(f'fqt_ip04a/normalized/{n}').write_text(s); chunks.append(s)
pathlib.Path('evidence/payload_chunk_reconstruction.json').write_text(json.dumps(rows,indent=2)+'\n')
z=base64.b64decode(''.join(chunks),validate=True); p=pathlib.Path('fqt_ip04a/FQT_G05_SEED.reconstructed.zip'); p.write_bytes(z)
got=hashlib.sha256(z).hexdigest(); want='8dc2804e3aca7cd616b3c0ce6839b0c58c6bfcd18b5962fe0e454e33d1b8ed3f'
if got!=want: raise SystemExit(f'seed mismatch {got} != {want}')
PY
unzip -t fqt_ip04a/FQT_G05_SEED.reconstructed.zip | tee evidence/seed_zip_test.log
unzip -q -o fqt_ip04a/FQT_G05_SEED.reconstructed.zip -d fqt_ip04a/seed
find fqt_ip04a/seed -maxdepth 1 -type f -printf '%f\t%s\n' | sort | tee evidence/seed_file_inventory.tsv

git clone --filter=blob:none https://github.com/freqtrade/freqtrade.git freqtrade_src
git -C freqtrade_src checkout --detach 77cabd291fa656ec6a1d237cfa524ee792133d89
python fqt_ip04a/verify_source.py fqt_ip04a/FREQTRADE_PROJECT_SOURCE_RECEIPT.json freqtrade_src
{
 echo '--- a/freqtrade/optimize/backtesting.py'; echo '+++ b/freqtrade/optimize/backtesting.py'; tail -n +3 fqt_ip04a/seed/backtesting_memory_patch_v3.diff
} > evidence/backtesting_memory_patch_v3.relative.diff
patch -d freqtrade_src -p1 < evidence/backtesting_memory_patch_v3.relative.diff
git -C freqtrade_src diff --check
git -C freqtrade_src diff -- freqtrade/optimize/backtesting.py > evidence/backtesting_memory_patch_v3.applied.diff
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-cache-dir -e ./freqtrade_src
python fqt_ip04a/seed/freqtrade_offline.py --version | tee evidence/freqtrade_version.log
cp fqt_ip04a/seed/M4PioneerStableExposureV10.py user_data/strategies/
cp fqt_ip04a/seed/config_ip04_v10_continuous.json config_ip04.json
python - <<'PY'
import json,pathlib
p=pathlib.Path('config_ip04.json'); c=json.loads(p.read_text()); c['datadir']='user_data/data/binance'; c['user_data_dir']='user_data'; c['evidence_status']='IP04A_EXTERNAL_DETERMINISTIC_CONTINUOUS_PARITY'; p.write_text(json.dumps(c,indent=2)+'\n')
PY
sha256sum user_data/strategies/M4PioneerStableExposureV10.py config_ip04.json > evidence/strategy_config_hashes.sha256

python fqt_ip04a/prepare_main_data.py --config config_ip04.json --datadir user_data/data/binance --raw raw --manifest evidence/MAIN_DATA_MANIFEST.json | tee evidence/data_materialization.log
python fqt_ip04a/seed/freqtrade_offline.py list-data --userdir user_data --datadir user_data/data/binance --data-format-ohlcv parquet | tee evidence/list_data.log
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py
python fqt_ip04a/seed/freqtrade_offline.py list-strategies --userdir user_data --strategy-path user_data/strategies | tee evidence/list_strategies.log
python fqt_ip04a/seed/freqtrade_offline.py show-config -c config_ip04.json | tee evidence/show_config.log

run_bt() {
  local label="$1"
  local before
  before=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' | wc -l)
  /usr/bin/time -v -o "evidence/time_${label}.txt" \
  python fqt_ip04a/seed/freqtrade_offline.py backtesting -c config_ip04.json --strategy-path user_data/strategies -s M4PioneerStableExposureV10 -i 1m --timerange 20260101-20260501 --fee 0.001 --export trades --breakdown month --cache none 2>&1 | tee "evidence/continuous_${label}.log"
  local result
  result=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
  test -n "$result"
  cp "$result" "evidence/IP04A_CONTINUOUS_${label^^}.zip"
  python fqt_ip04a/summarize_ip04a.py --result "evidence/IP04A_CONTINUOUS_${label^^}.zip" --out "evidence/IP04A_CONTINUOUS_${label^^}_SUMMARY.json"
  echo "$before" > "evidence/result_count_before_${label}.txt"
}

run_bt run1
sleep 2
run_bt run2

python - <<'PY'
import hashlib,json,math,pathlib,zipfile
A=pathlib.Path('evidence/IP04A_CONTINUOUS_RUN1.zip'); B=pathlib.Path('evidence/IP04A_CONTINUOUS_RUN2.zip')

def load(path):
    with zipfile.ZipFile(path) as z:
        names=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
        if len(names)!=1: raise SystemExit(f'{path}: result json count {len(names)}')
        obj=json.loads(z.read(names[0]))
    if len(obj['strategy'])!=1: raise SystemExit(f'{path}: strategy count')
    return next(iter(obj['strategy'].values()))

def trade_norm(t):
    keys=['pair','open_timestamp','close_timestamp','enter_tag','exit_reason','is_short','leverage','stake_amount','amount','open_rate','close_rate','profit_ratio','profit_abs','fee_open','fee_close','trade_duration','min_rate','max_rate']
    return {k:t.get(k) for k in keys}

def eq(a,b):
    if isinstance(a,float) or isinstance(b,float):
        try:return math.isclose(float(a),float(b),rel_tol=0,abs_tol=1e-12)
        except:return False
    return a==b

a,b=load(A),load(B)
ta=[trade_norm(x) for x in a['trades']]; tb=[trade_norm(x) for x in b['trades']]
diffs=[]
if len(ta)!=len(tb): diffs.append({'field':'trade_count','run1':len(ta),'run2':len(tb)})
for i,(x,y) in enumerate(zip(ta,tb)):
    for k in x:
        if not eq(x[k],y[k]):
            diffs.append({'trade_index':i,'field':k,'run1':x[k],'run2':y[k]})
            if len(diffs)>=100: break
    if len(diffs)>=100: break
summary_keys=['total_trades','wins','draws','losses','winrate','profit_total','profit_total_abs','final_balance','profit_factor','max_drawdown_account','max_drawdown_abs','rejected_signals','market_change']
summary_diffs=[]
for k in summary_keys:
    if not eq(a.get(k),b.get(k)): summary_diffs.append({'field':k,'run1':a.get(k),'run2':b.get(k)})
canon=lambda x: hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
out={'contract':'FQT_OSV4_IP04A_CONTINUOUS_DETERMINISM_V1','run1_zip_sha256':hashlib.sha256(A.read_bytes()).hexdigest(),'run2_zip_sha256':hashlib.sha256(B.read_bytes()).hexdigest(),'run1_trade_ledger_sha256':canon(ta),'run2_trade_ledger_sha256':canon(tb),'trade_count_run1':len(ta),'trade_count_run2':len(tb),'semantic_trade_differences':diffs,'summary_differences':summary_diffs,'deterministic_pass':not diffs and not summary_diffs}
pathlib.Path('evidence/IP04A_CONTINUOUS_DETERMINISM.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
if not out['deterministic_pass']: raise SystemExit(2)
PY

python - <<'PY'
import csv,json,pathlib,zipfile
ref=pathlib.Path('fqt_ip04a/seed/V10_REFERENCE_LEDGER.csv')
with ref.open(newline='') as f: rr=list(csv.DictReader(f))
with zipfile.ZipFile('evidence/IP04A_CONTINUOUS_RUN1.zip') as z:
    n=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')][0]
    o=json.loads(z.read(n)); s=next(iter(o['strategy'].values())); tr=s['trades']
forced=[r for r in rr if (r.get('exit_reason') or r.get('exit_reason_full'))=='force_exit']
out={'contract':'FQT_OSV4_IP04A_MONTHLY_RESET_BOUNDARY_AUDIT_V1','reference_monthly_reset_trade_count':len(rr),'continuous_trade_count':len(tr),'trade_count_delta':len(tr)-len(rr),'reference_force_exit_count':len(forced),'reference_force_exit_rows':[{'pair':r.get('pair'),'open_date':r.get('open_date'),'close_date':r.get('close_date'),'enter_tag':r.get('enter_tag')} for r in forced],'strict_ledger_parity_applicable':False,'reason':'Monthly reference resets wallet and force-closes at month boundaries; continuous run preserves cross-month positions, compounding and slot state.'}
pathlib.Path('evidence/IP04A_MONTHLY_RESET_BOUNDARY_AUDIT.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
PY
