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
cp fqt_ip04a/seed/M4PioneerStableExposureV10.py user_data/strategies/V15CausalLossRepair.py
cat >> user_data/strategies/V15CausalLossRepair.py <<'PY'

class M4PioneerV15NoVWAP(M4PioneerStableExposureV10):
    @staticmethod
    def version(): return '15.50-v10-causal-no-vwap-path-development'
    def populate_entry_trend(self,dataframe,metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        tag=df.get('enter_tag','').fillna('').astype(str)
        veto=(df.get('enter_long',0).fillna(0).astype(int)>0)&tag.str.contains('|vwap_reclaim|',regex=False,na=False)
        df.loc[veto,'enter_long']=0;df.loc[veto,'enter_tag']=''
        return df.copy()

class _V15TrialTimeoutBase(M4PioneerStableExposureV10):
    TIMEOUT_MODE='none'
    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        minutes=self._trade_minutes_open(trade,current_time)
        low_stake=float(getattr(trade,'stake_amount',0.0) or 0.0)<=25.0
        if low_stake:
            if self.TIMEOUT_MODE=='360_m1pct' and minutes>=360 and current_profit<=-0.010:
                return 'protective_exit|trial_timeout_360_m1pct|v15'
            if self.TIMEOUT_MODE=='720_nonpos' and minutes>=720 and current_profit<=0.0:
                return 'protective_exit|trial_timeout_720_nonpos|v15'
            if self.TIMEOUT_MODE=='combo' and ((minutes>=360 and current_profit<=-0.010) or (minutes>=720 and current_profit<=0.0)):
                return 'protective_exit|trial_timeout_combo|v15'
            if self.TIMEOUT_MODE=='1440_nonpos' and minutes>=1440 and current_profit<=0.0:
                return 'protective_exit|trial_timeout_1440_nonpos|v15'
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)

class M4PioneerV15Timeout360(_V15TrialTimeoutBase):
    TIMEOUT_MODE='360_m1pct'
    @staticmethod
    def version(): return '15.51-v10-lowstake-timeout360-m1pct'

class M4PioneerV15Timeout720(_V15TrialTimeoutBase):
    TIMEOUT_MODE='720_nonpos'
    @staticmethod
    def version(): return '15.52-v10-lowstake-timeout720-nonpositive'

class M4PioneerV15TimeoutCombo(_V15TrialTimeoutBase):
    TIMEOUT_MODE='combo'
    @staticmethod
    def version(): return '15.53-v10-lowstake-timeout-combo'

class M4PioneerV15Timeout1440(_V15TrialTimeoutBase):
    TIMEOUT_MODE='1440_nonpos'
    @staticmethod
    def version(): return '15.54-v10-lowstake-timeout1440-nonpositive'

class M4PioneerV15NoVWAPCombo(M4PioneerV15TimeoutCombo):
    @staticmethod
    def version(): return '15.55-v10-no-vwap-plus-lowstake-timeout-combo'
    def populate_entry_trend(self,dataframe,metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        tag=df.get('enter_tag','').fillna('').astype(str)
        veto=(df.get('enter_long',0).fillna(0).astype(int)>0)&tag.str.contains('|vwap_reclaim|',regex=False,na=False)
        df.loc[veto,'enter_long']=0;df.loc[veto,'enter_tag']=''
        return df.copy()

class M4PioneerV15NoVWAP_DELAY1(M4PioneerV15NoVWAP):
    @staticmethod
    def version(): return '15.50-v10-no-vwap-delay1'
    def populate_entry_trend(self,dataframe,metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(1).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(1).fillna('').astype(str)
        return df.copy()

class M4PioneerV15NoVWAPCombo_DELAY1(M4PioneerV15NoVWAPCombo):
    @staticmethod
    def version(): return '15.55-v10-no-vwap-timeout-combo-delay1'
    def populate_entry_trend(self,dataframe,metadata):
        df=super().populate_entry_trend(dataframe,metadata)
        df['enter_long']=df.get('enter_long',0).shift(1).fillna(0).astype(int)
        df['enter_tag']=df.get('enter_tag','').shift(1).fillna('').astype(str)
        return df.copy()
PY
cp fqt_ip04a/seed/config_ip04_v10_continuous.json config_loss.json
python - <<'PY'
import json,pathlib
p=pathlib.Path('config_loss.json');c=json.loads(p.read_text());c['datadir']='user_data/data/binance';c['user_data_dir']='user_data';c['evidence_status']='V15_CAUSAL_LOSS_REPAIR_KNOWN_DEVELOPMENT_ONLY';p.write_text(json.dumps(c,indent=2)+'\n')
PY
python fqt_ip04a/prepare_main_data.py --config config_loss.json --datadir user_data/data/binance --raw raw --manifest evidence/MAIN_DATA_MANIFEST.json > evidence/data_materialization.log
python -m py_compile user_data/strategies/V15CausalLossRepair.py
STRATEGY='';FEE=0.001
case "$SCENARIO" in
 no_vwap_fee001) STRATEGY=M4PioneerV15NoVWAP ;;
 no_vwap_fee002) STRATEGY=M4PioneerV15NoVWAP;FEE=0.002 ;;
 no_vwap_delay1_fee001) STRATEGY=M4PioneerV15NoVWAP_DELAY1 ;;
 timeout360_fee001) STRATEGY=M4PioneerV15Timeout360 ;;
 timeout720_fee001) STRATEGY=M4PioneerV15Timeout720 ;;
 timeoutcombo_fee001) STRATEGY=M4PioneerV15TimeoutCombo ;;
 timeout1440_fee001) STRATEGY=M4PioneerV15Timeout1440 ;;
 timeoutcombo_fee002) STRATEGY=M4PioneerV15TimeoutCombo;FEE=0.002 ;;
 no_vwap_combo_fee001) STRATEGY=M4PioneerV15NoVWAPCombo ;;
 no_vwap_combo_delay1_fee001) STRATEGY=M4PioneerV15NoVWAPCombo_DELAY1 ;;
 *) echo "unknown scenario $SCENARIO" >&2;exit 2 ;;
esac
BEFORE=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' | wc -l)
/usr/bin/time -v -o "evidence/time_${SCENARIO}.txt" python fqt_ip04a/seed/freqtrade_offline.py backtesting -c config_loss.json --strategy-path user_data/strategies -s "$STRATEGY" -i 1m --timerange 20260101-20260501 --fee "$FEE" --export trades --breakdown month --cache none 2>&1 | tee "evidence/${SCENARIO}.log"
RESULT=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' -printf '%T@ %p\n' | sort -nr | head -1 | cut -d' ' -f2-)
test -n "$RESULT"
AFTER=$(find user_data/backtest_results -maxdepth 1 -type f -name 'backtest-result-*.zip' | wc -l)
test "$AFTER" -gt "$BEFORE"
cp "$RESULT" "evidence/${SCENARIO}_RESULT.zip"
python - "$SCENARIO" "$STRATEGY" "$FEE" "$RESULT" <<'PY'
import hashlib,json,pathlib,sys,zipfile
scenario,strategy,fee,path=sys.argv[1],sys.argv[2],float(sys.argv[3]),pathlib.Path(sys.argv[4])
with zipfile.ZipFile(path) as z:
 names=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')];o=json.loads(z.read(names[0]));s=o['strategy'][strategy];tr=s['trades']
w=sum(float(x['profit_ratio'])>0 for x in tr);l=sum(float(x['profit_ratio'])<0 for x in tr);d=len(tr)-w-l
out={'contract':'FQT_V15_CAUSAL_LOSS_REPAIR_EXACT_CONTINUOUS_V1','scenario':scenario,'strategy':strategy,'fee_per_side':fee,'timerange':'20260101-20260501','trades':len(tr),'wins':w,'draws':d,'losses':l,'winrate_pct':100*w/len(tr) if tr else 0,'profit_usdc':s.get('profit_total_abs'),'profit_pct':100*s.get('profit_total',0),'profit_factor':s.get('profit_factor'),'max_drawdown_abs':s.get('max_drawdown_abs'),'max_drawdown_pct':100*s.get('max_drawdown_account',0),'starting_balance':s.get('starting_balance'),'final_balance':s.get('final_balance'),'result_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'fresh_oos_opened':False,'status':'EXECUTED_KNOWN_DEVELOPMENT'}
pathlib.Path(f'evidence/{scenario}_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
PY
