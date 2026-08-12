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
p=pathlib.Path('config_ip04.json'); c=json.loads(p.read_text()); c['datadir']='user_data/data/binance'; c['user_data_dir']='user_data'; c['evidence_status']='IP04A_EXTERNAL_HIGH_MEMORY_CONTINUOUS_PARITY_V2'; p.write_text(json.dumps(c,indent=2)+'\n')
PY
sha256sum user_data/strategies/M4PioneerStableExposureV10.py config_ip04.json > evidence/strategy_config_hashes.sha256

python fqt_ip04a/prepare_main_data.py --config config_ip04.json --datadir user_data/data/binance --raw raw --manifest evidence/MAIN_DATA_MANIFEST.json | tee evidence/data_materialization.log
python fqt_ip04a/seed/freqtrade_offline.py list-data --userdir user_data --datadir user_data/data/binance --data-format-ohlcv parquet | tee evidence/list_data.log
python -m py_compile user_data/strategies/M4PioneerStableExposureV10.py
python fqt_ip04a/seed/freqtrade_offline.py list-strategies --userdir user_data --strategy-path user_data/strategies | tee evidence/list_strategies.log
python fqt_ip04a/seed/freqtrade_offline.py show-config -c config_ip04.json | tee evidence/show_config.log

/usr/bin/time -v -o evidence/time_continuous.txt \
python fqt_ip04a/seed/freqtrade_offline.py backtesting -c config_ip04.json --strategy-path user_data/strategies -s M4PioneerStableExposureV10 -i 1m --timerange 20260101-20260501 --fee 0.001 --export trades --export-filename user_data/backtest_results/ip04a_continuous --breakdown month --cache none 2>&1 | tee evidence/continuous_backtest.log
RESULT=$(find user_data/backtest_results -maxdepth 1 -type f -name 'ip04a_continuous*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$RESULT"
cp "$RESULT" evidence/IP04A_CONTINUOUS_RESULT.zip
python fqt_ip04a/summarize_ip04a.py --result evidence/IP04A_CONTINUOUS_RESULT.zip --out evidence/IP04A_CONTINUOUS_SUMMARY.json
python fqt_ip04a/seed/compare_trade_ledgers.py fqt_ip04a/seed/V10_REFERENCE_LEDGER.csv evidence/IP04A_CONTINUOUS_RESULT.zip | tee evidence/IP04A_SCHEDULE_PARITY.json
