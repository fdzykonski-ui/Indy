#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
chmod +x fqt_ip04a/run_ip04a_v2.sh
fqt_ip04a/run_ip04a_v2.sh
python - <<'PY'
import json,pathlib
p=pathlib.Path('config_ip04.json')
c=json.loads(p.read_text())
# Config precedence replaces the strategy order_types dictionary as a whole.
# The lookahead market-order override must therefore carry every required key.
c['order_types']={
    'entry':'market',
    'exit':'market',
    'stoploss':'market',
    'stoploss_on_exchange':False,
    'emergency_exit':'market',
    'force_entry':'market',
    'force_exit':'market',
}
c.setdefault('entry_pricing',{})['price_side']='other'
c.setdefault('exit_pricing',{})['price_side']='other'
p.write_text(json.dumps(c,indent=2)+'\n')
PY
python fqt_ip04a/seed/freqtrade_offline.py show-config -c config_ip04.json | tee evidence/lookahead_show_config.log
python fqt_ip04a/seed/freqtrade_offline.py lookahead-analysis \
  -c config_ip04.json \
  --strategy-path user_data/strategies \
  -s M4PioneerStableExposureV10 \
  -i 1m \
  --timerange 20260101-20260501 \
  --fee 0.001 \
  --minimum-trade-amount 10 \
  --targeted-trade-amount 50 \
  --lookahead-analysis-exportfilename evidence/lookahead_full_31pair.csv \
  --no-color 2>&1 | tee evidence/lookahead_full_31pair.log
python - <<'PY'
import csv,json,pathlib
p=pathlib.Path('evidence/lookahead_full_31pair.csv')
rows=list(csv.DictReader(p.open())) if p.exists() else []
out={'contract':'FQT_OSV4_IP05_LOOKAHEAD_FULL_V3','csv_exists':p.exists(),'rows':rows,'row_count':len(rows),'valid_verdict':False,'has_bias':None}
if rows:
    vals=[]
    for r in rows:
        v=str(r.get('has_bias','')).strip().lower()
        if v in ('yes','true','1'): vals.append(True)
        elif v in ('no','false','0'): vals.append(False)
    if vals:
        out['valid_verdict']=True
        out['has_bias']=any(vals)
pathlib.Path('evidence/IP05_LOOKAHEAD_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
if not out['valid_verdict'] or out['has_bias']:
    raise SystemExit(2)
PY
