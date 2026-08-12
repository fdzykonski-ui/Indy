#!/usr/bin/env python3
from __future__ import annotations
import csv,json,sys,pathlib,zipfile,hashlib,math
refp=pathlib.Path(sys.argv[1]); curp=pathlib.Path(sys.argv[2])

def load_result(p):
    if p.exists() and zipfile.is_zipfile(p):
        with zipfile.ZipFile(p) as z:
            names=[n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json')]
            if len(names)!=1: raise SystemExit(f'expected one result json in {p}: {names}')
            return json.loads(z.read(names[0]))
    if p.exists(): return json.loads(p.read_text())
    candidates=sorted(p.parent.glob(p.stem+'*.zip'),key=lambda x:x.stat().st_mtime,reverse=True)
    if candidates:return load_result(candidates[0])
    raise SystemExit(f'missing current result {p}')

with refp.open(newline='') as f: ref=list(csv.DictReader(f))
obj=load_result(curp)
strategies=obj.get('strategy',{})
if 'M4PioneerStableExposureV10' not in strategies: raise SystemExit(strategies.keys())
cur=strategies['M4PioneerStableExposureV10']['trades']
fields=['pair','open_date','close_date','enter_tag','exit_reason','is_short']
float_fields=['profit_ratio','open_rate','close_rate']
def key(x):return (x.get('open_date'),x.get('pair'),x.get('close_date'),x.get('enter_tag'),x.get('exit_reason'))
ref=sorted(ref,key=key);cur=sorted(cur,key=key)
changes=[]
if len(ref)!=len(cur):changes.append({'field':'trade_count','reference':len(ref),'current':len(cur)})
for i,(a,b) in enumerate(zip(ref,cur)):
    for f in fields:
        av=a.get(f);bv=b.get(f)
        if f=='is_short': av=str(av).lower() in ('true','1');bv=bool(bv)
        if av!=bv:changes.append({'row':i,'field':f,'reference':av,'current':bv})
    for f in float_fields:
        av=float(a[f]);bv=float(b[f])
        if not math.isclose(av,bv,rel_tol=0,abs_tol=1e-10):changes.append({'row':i,'field':f,'reference':av,'current':bv,'abs_delta':abs(av-bv)})
max_profit=max((abs(float(a['profit_ratio'])-float(b['profit_ratio'])) for a,b in zip(ref,cur)),default=0)
out={'contract':'FQT_G05_CONTINUOUS_SCHEDULE_PARITY_V1','reference_method':'monthly reset ledgers concatenated; stake_amount excluded because continuous unlimited-wallet compounding is not comparable to monthly resets','reference_sha256':hashlib.sha256(refp.read_bytes()).hexdigest(),'reference_trades':len(ref),'current_trades':len(cur),'changed_fields':len(changes),'max_profit_ratio_abs_delta':max_profit,'status':'PASS_SCHEDULE_PARITY' if not changes and len(ref)==len(cur) else 'FAIL','first_changes':changes[:100]}
print(json.dumps(out,indent=2))
if out['status']!='PASS_SCHEDULE_PARITY':raise SystemExit(2)
