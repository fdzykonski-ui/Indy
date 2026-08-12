#!/usr/bin/env python3
import argparse,hashlib,json,pathlib,zipfile
ap=argparse.ArgumentParser();ap.add_argument('--result',type=pathlib.Path,required=True);ap.add_argument('--out',type=pathlib.Path,required=True);a=ap.parse_args()
with zipfile.ZipFile(a.result) as z:
 names=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')];obj=json.loads(z.read(names[0]))
s=obj['strategy']['M4PioneerStableExposureV10'];tr=s['trades'];wins=sum(float(x['profit_ratio'])>0 for x in tr);losses=sum(float(x['profit_ratio'])<0 for x in tr);draws=len(tr)-wins-losses
out={'contract':'FQT_OSV4_IP04A_CONTINUOUS_RESULT_V1','trades':len(tr),'wins':wins,'draws':draws,'losses':losses,'winrate_pct':100*wins/len(tr) if tr else 0,'profit_usdc':s.get('profit_total_abs'),'profit_pct':100*s.get('profit_total',0),'profit_factor':s.get('profit_factor'),'max_drawdown_abs':s.get('max_drawdown_abs'),'max_drawdown_pct':100*s.get('max_drawdown_account',0),'starting_balance':s.get('starting_balance'),'final_balance':s.get('final_balance'),'result_sha256':hashlib.sha256(a.result.read_bytes()).hexdigest(),'status':'EXECUTED'};a.out.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(out,indent=2))
