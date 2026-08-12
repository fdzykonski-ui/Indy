#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p evidence user_data/strategies user_data/data/binance user_data/backtest_results raw fqt_ip04a/seed fqt_ip04a/normalized
python - <<'PY'
import base64,hashlib,pathlib
expected={'00':'ecc251174a150348a925e50d2f04980a1ad93a478708f655e4824a2eaba3f377','01':'041b6711e2778ffc4adbe20c7bcc81a07d983ac87709f1b60496d3b3e46376b3','02':'4f7abb0865a4ab4e909255b2eea1c1c6248542d984d4e1f4a866d1763ca78990','03':'18290818f25e441d6acf4fe5d8d2b8a875b3be772fa9abccbe2954217bbfe4f4','04':'93cbe43e53472b1b728b2a8c778c1ef4522f262c6542c1e5602c72ab92b9c140','05':'52857c3bc29f3d7d872e4c0d29d331e2dc811135f1951b58abf752d48213e8c6','06':'81cb1d0d642a6318ba435752e8a401b5cdab684d0e99418353e0309a643f3304'}
chunks=[]
for n,want in expected.items():
 p=pathlib.Path(f'fqt_ip04a/payload.b64.{n}'); s=''.join(p.read_text().split())
 if n=='02' and hashlib.sha256(s.encode()).hexdigest()!=want and len(s)==12001 and s[10400]=='y' and s[11933:11937]=='Vlyw':
  s=s[:10400]+'Y'+s[10401:]; s=s[:11933]+'elw'+s[11937:]
 if len(s)>12000 and n!='06' and hashlib.sha256(s[:12000].encode()).hexdigest()==want: s=s[:12000]
 if hashlib.sha256(s.encode()).hexdigest()!=want: raise SystemExit(f'chunk {n} mismatch')
 chunks.append(s)
z=base64.b64decode(''.join(chunks),validate=True)
if hashlib.sha256(z).hexdigest()!='8dc2804e3aca7cd616b3c0ce6839b0c58c6bfcd18b5962fe0e454e33d1b8ed3f': raise SystemExit('seed mismatch')
pathlib.Path('fqt_ip04a/FQT_G05_SEED.reconstructed.zip').write_bytes(z)
PY
unzip -q -o fqt_ip04a/FQT_G05_SEED.reconstructed.zip -d fqt_ip04a/seed

git clone --filter=blob:none https://github.com/freqtrade/freqtrade.git freqtrade_src
git -C freqtrade_src checkout --detach 77cabd291fa656ec6a1d237cfa524ee792133d89
python fqt_ip04a/verify_source.py fqt_ip04a/FREQTRADE_PROJECT_SOURCE_RECEIPT.json freqtrade_src
{ echo '--- a/freqtrade/optimize/backtesting.py'; echo '+++ b/freqtrade/optimize/backtesting.py'; tail -n +3 fqt_ip04a/seed/backtesting_memory_patch_v3.diff; } > evidence/backtesting_memory_patch_v3.relative.diff
patch -d freqtrade_src -p1 < evidence/backtesting_memory_patch_v3.relative.diff
python -m pip install --upgrade pip setuptools wheel
python -m pip install --no-cache-dir -e ./freqtrade_src
cp fqt_ip04a/seed/M4PioneerStableExposureV10.py user_data/strategies/
cp fqt_ip04a/seed/config_ip04_v10_continuous.json config_known.json
python - <<'PY'
import json,pathlib
p=pathlib.Path('config_known.json');c=json.loads(p.read_text());c['datadir']='user_data/data/binance';c['user_data_dir']='user_data';c['evidence_status']='KNOWN_JAN_JUN22_NOT_PRISTINE_OOS';p.write_text(json.dumps(c,indent=2)+'\n')
PY
python fqt_known_janjun/prepare_known_data.py --config config_known.json --datadir user_data/data/binance --raw raw --manifest evidence/KNOWN_JANJUN_DATA_MANIFEST.json | tee evidence/data_materialization.log
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py
/usr/bin/time -v -o evidence/time_known_janjun.txt \
python fqt_ip04a/seed/freqtrade_offline.py backtesting -c config_known.json --strategy-path user_data/strategies -s M4PioneerStableExposureV10 -i 1m --timerange 20260101-20260623 --fee 0.001 --export trades --breakdown month --cache none 2>&1 | tee evidence/known_janjun.log
RESULT=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$RESULT"
cp "$RESULT" evidence/KNOWN_JANJUN_RESULT.zip
python - "$RESULT" <<'PY'
import hashlib,json,pathlib,sys,zipfile
path=pathlib.Path(sys.argv[1])
with zipfile.ZipFile(path) as z:
 names=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
 o=json.loads(z.read(names[0]));s=next(iter(o['strategy'].values()))
keys=['total_trades','wins','draws','losses','winrate','profit_total','profit_total_abs','final_balance','profit_factor','max_drawdown_account','max_drawdown_abs','rejected_signals','market_change','backtest_start','backtest_end']
out={'contract':'FQT_KNOWN_JAN_JUN22_CONTINUOUS_V1','classification':'KNOWN_REPEATEDLY_INSPECTED_NOT_PRISTINE_OOS','result_zip_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**{k:s.get(k) for k in keys}}
pathlib.Path('evidence/KNOWN_JANJUN_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
PY
