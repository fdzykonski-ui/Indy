#!/usr/bin/env bash
set -euo pipefail
export PYTHONHASHSEED=0 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUMEXPR_NUM_THREADS=1
chmod +x fqt_ip04a/run_ip04a_v2.sh
fqt_ip04a/run_ip04a_v2.sh
mkdir -p evidence/recursive
for pair in BTC/USDC ETH/USDC SOL/USDC SHIB/USDC; do
  safe=${pair//\//_}
  python fqt_ip04a/seed/freqtrade_offline.py recursive-analysis \
    -c config_ip04.json \
    --strategy-path user_data/strategies \
    -s M4PioneerStableExposureV10 \
    -i 1m \
    --timerange 20260301-20260315 \
    -p "$pair" \
    --startup-candle 800 1100 1600 2400 \
    --data-format-ohlcv parquet \
    --no-color 2>&1 | tee "evidence/recursive/${safe}.log"
done
python - <<'PY'
import json,pathlib,re
rows=[]; hard=[]
for p in sorted(pathlib.Path('evidence/recursive').glob('*.log')):
    text=p.read_text(errors='replace')
    vals=[]
    for line in text.splitlines():
        if '|' not in line or '%' not in line: continue
        for x in re.findall(r'(?<![A-Za-z0-9_.-])(-?\d+(?:\.\d+)?)%',line):
            vals.append(float(x))
    nan='nan%' in text.lower()
    maxabs=max((abs(x) for x in vals),default=0.0)
    rows.append({'pair':p.stem.replace('_','/'),'numeric_percent_values':len(vals),'max_abs_percent':maxabs,'nan_present':nan,'log':str(p)})
    if nan or maxabs>0.10: hard.append({'pair':p.stem,'nan_present':nan,'max_abs_percent':maxabs})
out={'contract':'FQT_OSV4_IP06_RECURSIVE_MATRIX_V1','startup_candles':[800,1100,1600,2400],'timerange':'20260301-20260315','rows':rows,'material_drift_threshold_percent':0.10,'hard_findings':hard,'pass':not hard}
pathlib.Path('evidence/IP06_RECURSIVE_SUMMARY.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
if hard: raise SystemExit(2)
PY
