#!/usr/bin/env bash
set -euo pipefail
SCENARIO=${1:?scenario required}
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
mkdir -p evidence user_data/strategies user_data/data/binance user_data/backtest_results raw fqt_ip04a/seed fqt_ip04a/normalized
python - <<'PY'
import base64,hashlib,pathlib
expected={'00':'ecc251174a150348a925e50d2f04980a1ad93a478708f655e4824a2eaba3f377','01':'041b6711e2778ffc4adbe20c7bcc81a07d983ac87709f1b60496d3b3e46376b3','02':'4f7abb0865a4ab4e909255b2eea1c1c6248542d984d4e1f4a866d1763ca78990','03':'18290818f25e441d6acf4fe5d8d2b8a875b3be772fa9abccbe2954217bbfe4f4','04':'93cbe43e53472b1b728b2a8c778c1ef4522f262c6542c1e5602c72ab92b9c140','05':'52857c3bc29f3d7d872e4c0d29d331e2dc811135f1951b58abf752d48213e8c6','06':'81cb1d0d642a6318ba435752e8a401b5cdab684d0e99418353e0309a643f3304'}
chunks=[]
for n,want in expected.items():
 p=pathlib.Path(f'fqt_ip04a/payload.b64.{n}');s=''.join(p.read_text().split())
 if n=='02' and hashlib.sha256(s.encode()).hexdigest()!=want and len(s)==12001 and s[10400]=='y' and s[11933:11937]=='Vlyw':
  s=s[:10400]+'Y'+s[10401:];s=s[:11933]+'elw'+s[11937:]
 if len(s)>12000 and n!='06' and hashlib.sha256(s[:12000].encode()).hexdigest()==want:s=s[:12000]
 if hashlib.sha256(s.encode()).hexdigest()!=want:raise SystemExit(f'chunk {n} mismatch')
 chunks.append(s)
z=base64.b64decode(''.join(chunks),validate=True)
if hashlib.sha256(z).hexdigest()!='8dc2804e3aca7cd616b3c0ce6839b0c58c6bfcd18b5962fe0e454e33d1b8ed3f':raise SystemExit('seed mismatch')
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
cp fqt_ip04a/seed/M4PioneerStableExposureV10.py user_data/strategies/V15TailRepair.py
cat >> user_data/strategies/V15TailRepair.py <<'PY'

class M4PioneerStableExposureV15SL25(M4PioneerStableExposureV10):
    stoploss = -0.025
    @staticmethod
    def version() -> str: return '15.30-v10-exposure-static-stop-2p5pct'

class M4PioneerStableExposureV15SL25_DELAY1(M4PioneerStableExposureV15SL25):
    @staticmethod
    def version() -> str: return '15.30-v10-exposure-static-stop-2p5pct-delay1'
    def populate_entry_trend(self, dataframe, metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(1).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(1).fillna('').astype(str)
        return df.copy()

class M4PioneerStableExposureV15Emergency2(M4PioneerStableExposureV10):
    stoploss = -0.03
    sell_emergency_loss_floor = DecimalParameter(-0.05,-0.005,default=-0.02,decimals=3,space='sell',optimize=False)
    @staticmethod
    def version() -> str: return '15.31-v10-exposure-stop3-emergency2'

class M4PioneerStableExposureV15Emergency2_DELAY1(M4PioneerStableExposureV15Emergency2):
    @staticmethod
    def version() -> str: return '15.31-v10-exposure-stop3-emergency2-delay1'
    def populate_entry_trend(self, dataframe, metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(1).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(1).fillna('').astype(str)
        return df.copy()

class M4PioneerStableExposureV15CSL(M4PioneerStableExposureV10):
    use_custom_stoploss = True
    @staticmethod
    def version() -> str: return '15.32-v10-exposure-causal-custom-stoploss'

class M4PioneerStableExposureV15CSL_DELAY1(M4PioneerStableExposureV15CSL):
    @staticmethod
    def version() -> str: return '15.32-v10-exposure-causal-custom-stoploss-delay1'
    def populate_entry_trend(self, dataframe, metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(1).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(1).fillna('').astype(str)
        return df.copy()
PY
cp fqt_ip04a/seed/config_ip04_v10_continuous.json config_tail.json
python - <<'PY'
import json,pathlib
p=pathlib.Path('config_tail.json');c=json.loads(p.read_text());c['datadir']='user_data/data/binance';c['user_data_dir']='user_data';c['evidence_status']='V15_TAIL_REPAIR_KNOWN_DEVELOPMENT_ONLY';p.write_text(json.dumps(c,indent=2)+'\n')
PY
python fqt_ip04a/prepare_main_data.py --config config_tail.json --datadir user_data/data/binance --raw raw --manifest evidence/MAIN_DATA_MANIFEST.json > evidence/data_materialization.log
python -m py_compile user_data/strategies/V15TailRepair.py

STRATEGY='';FEE=0.001
case "$SCENARIO" in
 sl25_fee001) STRATEGY=M4PioneerStableExposureV15SL25;FEE=0.001 ;;
 sl25_fee002) STRATEGY=M4PioneerStableExposureV15SL25;FEE=0.002 ;;
 sl25_delay1_fee001) STRATEGY=M4PioneerStableExposureV15SL25_DELAY1;FEE=0.001 ;;
 sl25_delay1_fee002) STRATEGY=M4PioneerStableExposureV15SL25_DELAY1;FEE=0.002 ;;
 emergency2_fee001) STRATEGY=M4PioneerStableExposureV15Emergency2;FEE=0.001 ;;
 emergency2_fee002) STRATEGY=M4PioneerStableExposureV15Emergency2;FEE=0.002 ;;
 emergency2_delay1_fee001) STRATEGY=M4PioneerStableExposureV15Emergency2_DELAY1;FEE=0.001 ;;
 csl_fee001) STRATEGY=M4PioneerStableExposureV15CSL;FEE=0.001 ;;
 csl_fee002) STRATEGY=M4PioneerStableExposureV15CSL;FEE=0.002 ;;
 csl_delay1_fee001) STRATEGY=M4PioneerStableExposureV15CSL_DELAY1;FEE=0.001 ;;
 *) echo "unknown scenario $SCENARIO" >&2;exit 2 ;;
esac
/usr/bin/time -v -o "evidence/time_${SCENARIO}.txt" python fqt_ip04a/seed/freqtrade_offline.py backtesting -c config_tail.json --strategy-path user_data/strategies -s "$STRATEGY" -i 1m --timerange 20260101-20260501 --fee "$FEE" --export trades --export-filename "user_data/backtest_results/${SCENARIO}" --breakdown month --cache none 2>&1 | tee "evidence/${SCENARIO}.log"
RESULT=$(find user_data/backtest_results -maxdepth 1 -type f -name "${SCENARIO}*.zip" -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$RESULT";cp "$RESULT" "evidence/${SCENARIO}_RESULT.zip"
python - "$SCENARIO" "$STRATEGY" "$FEE" "$RESULT" <<'PY'
import hashlib,json,pathlib,sys,zipfile
scenario,strategy,fee,path=sys.argv[1],sys.argv[2],float(sys.argv[3]),pathlib.Path(sys.argv[4])
with zipfile.ZipFile(path) as z:
 names=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')];o=json.loads(z.read(names[0]));s=o['strategy'][strategy];tr=s['trades']
w=sum(float(x['profit_ratio'])>0 for x in tr);l=sum(float(x['profit_ratio'])<0 for x in tr);d=len(tr)-w-l
out={'contract':'FQT_V15_TAIL_REPAIR_EXACT_CONTINUOUS_V1','scenario':scenario,'strategy':strategy,'fee_per_side':fee,'timerange':'20260101-20260501','trades':len(tr),'wins':w,'draws':d,'losses':l,'winrate_pct':100*w/len(tr) if tr else 0,'profit_usdc':s.get('profit_total_abs'),'profit_pct':100*s.get('profit_total',0),'profit_factor':s.get('profit_factor'),'max_drawdown_abs':s.get('max_drawdown_abs'),'max_drawdown_pct':100*s.get('max_drawdown_account',0),'starting_balance':s.get('starting_balance'),'final_balance':s.get('final_balance'),'result_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'fresh_oos_opened':False,'status':'EXECUTED_KNOWN_DEVELOPMENT'}
pathlib.Path(f'evidence/{scenario}_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
PY
