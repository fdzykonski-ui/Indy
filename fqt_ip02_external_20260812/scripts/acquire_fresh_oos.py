#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,json,os,pathlib,re,shutil,socket,statistics,sys,time,urllib.error,urllib.request,zipfile
from decimal import Decimal,InvalidOperation

PAIRS=['BTC/USDC','ETH/USDC','SOL/USDC','XRP/USDC','BNB/USDC','DOGE/USDC','ENA/USDC','HBAR/USDC','LTC/USDC','AAVE/USDC','XPL/USDC','LINK/USDC','BCH/USDC','DOT/USDC','PUMP/USDC','TRX/USDC','AVAX/USDC','UNI/USDC','ARB/USDC','PENDLE/USDC','SYRUP/USDC','ALGO/USDC','ZK/USDC','WLFI/USDC','FIL/USDC','ASTER/USDC','SHIB/USDC','SEI/USDC','DASH/USDC','2Z/USDC','ATOM/USDC']
COLS=['pair','symbol','date_utc','interval','archive_url','checksum_url','expected_rows','timestamp_unit','status','sha256','rows_actual','gaps','duplicates','zero_volume_ratio','quote_notional_median']
RESULT=['attempt_index','pair','symbol','date_utc','interval','archive_url','checksum_url','status','phase','error_class','error_message','official_sha256','sha256','archive_bytes','csv_member','rows_actual','gaps','duplicates','non_monotonic','schema_columns','header_present','impossible_ohlc','negative_volume','open_time_first','open_time_last','zero_volume_ratio','quote_notional_median','validated_at_utc']
EXPECTED_MANIFEST_SHA='5b39baa54a6321bcb825040270df99673792c155a678b599c25d229d0df379c7'
EXPECTED_RECEIPT_SHA='1734ba67e10e9a6cd98997f471deb1197da77b64f68235f2f49fdab1f1b88411'
CHECKSUM_RE=re.compile(r'^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$')

class Gate(RuntimeError):
    def __init__(self,phase,code,msg): super().__init__(msg); self.phase=phase; self.code=code; self.msg=msg

def now(): return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def shab(b): return hashlib.sha256(b).hexdigest()
def shap(p):
    h=hashlib.sha256()
    with pathlib.Path(p).open('rb') as f:
        for x in iter(lambda:f.read(1<<20),b''): h.update(x)
    return h.hexdigest()
def canon(o): return shab(json.dumps(o,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode())
def wjson(p,o): p=pathlib.Path(p); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(o,indent=2,sort_keys=True,ensure_ascii=False)+'\n')

def generate_inputs(root,parent):
    data=root/'data'; ev=root/'evidence'; data.mkdir(parents=True,exist_ok=True); ev.mkdir(parents=True,exist_ok=True)
    pu={'pairs':PAIRS,'count':31,'source_config_sha256':'f01184cc63f865d3532ac53202c3c19c2b3659a197b43768c75aadfebf471929','roles':{'research_universe':'all pairs retained','execution_universe':'must pass PIT, prebuffer, liquidity gates'}}
    (data/'PAIR_UNIVERSE.json').write_text(json.dumps(pu,indent=2)+'\n')
    start=dt.date(2026,6,23); end=dt.date(2026,8,10)
    with (data/'FRESH_OOS_ACQUISITION_MANIFEST.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=COLS,lineterminator='\r\n'); w.writeheader()
        for pair in PAIRS:
            sym=pair.replace('/','')
            d=start
            while d<=end:
                ds=d.isoformat(); name=f'{sym}-1m-{ds}.zip'; base=f'https://data.binance.vision/data/spot/daily/klines/{sym}/1m/{name}'
                w.writerow({'pair':pair,'symbol':sym,'date_utc':ds,'interval':'1m','archive_url':base,'checksum_url':base+'.CHECKSUM','expected_rows':1440,'timestamp_unit':'microseconds','status':'TO_ACQUIRE'})
                d+=dt.timedelta(days=1)
    manifest=data/'FRESH_OOS_ACQUISITION_MANIFEST.csv'
    if shap(manifest)!=EXPECTED_MANIFEST_SHA: raise Gate('manifest','MANIFEST_HASH_MISMATCH',f'{shap(manifest)}')
    receipt={'checkpoint_parent':parent,'files':{'acquisition_script':{'bytes':19658,'path':'scripts/acquire_fresh_oos.py','sha256':'77ce3f5de64ee5a1f33f0341711b2cd5216ea4cc55a55159df7668a7bd263e17'},'anchor_config':{'bytes':5763,'path':'config/config_anchor_v10_unlimited.json','sha256':'5057a9fe28a308b19cb2b6a3324c96b2a67b306109218faff5d554ec3b5fcc87'},'anchor_strategy':{'bytes':114580,'path':'strategies/M4PioneerStableExposureV10.py','sha256':'42f89e05378f10869bc3a882191e67852c6d4b661cc12f6570a027e167b6fac8'},'data_contract':{'bytes':972,'path':'data/DATA_CONTRACT.md','sha256':'1fd1975ee4f810c79e7fddf56e0d9a98e82c1e9e0ab42276b21c8cb353c471ca'},'manifest':{'bytes':387659,'path':'data/FRESH_OOS_ACQUISITION_MANIFEST.csv','sha256':EXPECTED_MANIFEST_SHA},'pair_universe':{'bytes':776,'path':'data/PAIR_UNIVERSE.json','sha256':'5def6411d338e1246c697d763e2325ae1fef48a8e8436b129c293befb5448e5b'}},'fresh_oos_opened':False,'frozen_at_utc':'2026-08-11T22:29:23Z','no_alpha_change':True,'range_inclusive':['2026-06-23','2026-08-10'],'source':'BINANCE_PUBLIC_DAILY_KLINES+CHECKSUMS','timeframe':'1m'}
    if canon(receipt)!=EXPECTED_RECEIPT_SHA: raise Gate('freeze','FREEZE_RECEIPT_HASH_MISMATCH',canon(receipt))
    receipt['receipt_sha256']=EXPECTED_RECEIPT_SHA; wjson(ev/'IP02_INPUT_FREEZE.json',receipt)
    return manifest

def download(url,out,timeout,retries):
    out.parent.mkdir(parents=True,exist_ok=True)
    if out.exists() and out.stat().st_size: return
    last=None
    for n in range(retries):
        tmp=out.with_suffix(out.suffix+'.part')
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'FQT-OSV4-IP02/1.0 research-data-acquisition','Accept':'*/*'})
            with urllib.request.urlopen(req,timeout=timeout) as r,tmp.open('wb') as f:
                if getattr(r,'status',200)!=200: raise Gate('download',f'HTTP_{r.status}',url)
                shutil.copyfileobj(r,f,1<<20)
            if not tmp.stat().st_size: raise Gate('download','EMPTY_REMOTE_OBJECT',url)
            tmp.replace(out); return
        except urllib.error.HTTPError as e:
            last=e
            if e.code in (403,404): raise Gate('download',f'HTTP_{e.code}',url)
        except urllib.error.URLError as e:
            last=e
            if isinstance(getattr(e,'reason',None),socket.gaierror): raise Gate('download','NETWORK_DNS_UNAVAILABLE',f'{url}: {e.reason}')
        except Gate: raise
        except Exception as e: last=e
        tmp.unlink(missing_ok=True)
        if n+1<retries: time.sleep(min(2**n,16))
    raise Gate('download','NETWORK_DOWNLOAD_FAILED',f'{url}: {last!r}')

def checksum(p,name):
    lines=[x for x in p.read_text().splitlines() if x.strip()]
    if len(lines)!=1 or not (m:=CHECKSUM_RE.match(lines[0])): raise Gate('checksum','CHECKSUM_SCHEMA',str(p))
    if pathlib.Path(m.group(2)).name!=name: raise Gate('checksum','CHECKSUM_FILENAME_MISMATCH',lines[0])
    return m.group(1).lower()

def dec(x,i,c):
    try: d=Decimal(x)
    except InvalidOperation as e: raise Gate('schema','NON_NUMERIC_VALUE',f'row={i} col={c}') from e
    if not d.is_finite(): raise Gate('schema','NON_FINITE_VALUE',f'row={i} col={c}')
    return d

def validate(zp,meta):
    try:
        with zipfile.ZipFile(zp) as z:
            if (bad:=z.testzip()) is not None: raise Gate('zip','ZIP_CRC_ERROR',bad)
            ms=[x for x in z.namelist() if not x.endswith('/')]
            if len(ms)!=1: raise Gate('zip','ZIP_MEMBER_COUNT',repr(ms))
            member=ms[0]; expected=zp.stem+'.csv'
            if pathlib.PurePosixPath(member).name!=expected: raise Gate('zip','ZIP_MEMBER_NAME',f'{member} != {expected}')
            rows=list(csv.reader(line.decode() for line in z.open(member)))
    except zipfile.BadZipFile as e: raise Gate('zip','BAD_ZIP',str(e))
    header=False
    if rows and not rows[0][0].strip().lstrip('-').isdigit(): header=True; rows=rows[1:]
    if len(rows)!=1440: raise Gate('invariant','ROW_COUNT',f'expected=1440 actual={len(rows)}')
    ots=[]; qvs=[]; zero=impossible=negative=0
    for i,r in enumerate(rows,1):
        if len(r)!=12: raise Gate('schema','COLUMN_COUNT',f'row={i} actual={len(r)}')
        try: ot=int(r[0]); ct=int(r[6]); nt=int(r[8])
        except ValueError as e: raise Gate('schema','INTEGER_PARSE',f'row={i}: {e}')
        o,h,l,c,v,qv,tb,tq=[dec(r[j],i,str(j)) for j in (1,2,3,4,5,7,9,10)]
        impossible += int(min(o,h,l,c)<=0 or h<max(o,l,c) or l>min(o,h,c))
        negative += int(min(v,qv,tb,tq)<0 or nt<0); zero += int(v==0)
        if ct!=ot+59_999_999: raise Gate('invariant','CLOSE_TIME',f'row={i}')
        ots.append(ot); qvs.append(float(qv))
    if impossible: raise Gate('invariant','IMPOSSIBLE_OHLC',str(impossible))
    if negative: raise Gate('invariant','NEGATIVE_VOLUME_OR_TRADES',str(negative))
    dup=len(ots)-len(set(ots)); nonmono=sum(b<=a for a,b in zip(ots,ots[1:])); gaps=sum(b-a!=60_000_000 for a,b in zip(ots,ots[1:]))
    if dup: raise Gate('invariant','DUPLICATE_TIMESTAMP',str(dup))
    if nonmono: raise Gate('invariant','NON_MONOTONIC_TIMESTAMP',str(nonmono))
    if gaps: raise Gate('invariant','TIMESTAMP_GAP',str(gaps))
    day=dt.date.fromisoformat(meta['date_utc']); first=int(dt.datetime.combine(day,dt.time(),tzinfo=dt.timezone.utc).timestamp()*1_000_000); last=first+1439*60_000_000
    if ots[0]!=first or ots[-1]!=last: raise Gate('invariant','DAY_BOUNDARY',f'{ots[0]}..{ots[-1]}')
    return {'csv_member':member,'rows_actual':1440,'gaps':0,'duplicates':0,'non_monotonic':0,'schema_columns':12,'header_present':header,'impossible_ohlc':0,'negative_volume':0,'open_time_first':ots[0],'open_time_last':ots[-1],'zero_volume_ratio':zero/1440,'quote_notional_median':statistics.median(qvs)}

def main():
    a=argparse.ArgumentParser(); a.add_argument('--root',type=pathlib.Path,required=True); a.add_argument('--parent',default='FQT-OSV4-IP01-20260811'); a.add_argument('--timeout',type=int,default=120); a.add_argument('--retries',type=int,default=5); x=a.parse_args(); root=x.root.resolve(); ev=root/'evidence'; logs=root/'logs'; ev.mkdir(parents=True,exist_ok=True); logs.mkdir(parents=True,exist_ok=True)
    manifest=generate_inputs(root,x.parent); rows=list(csv.DictReader(manifest.open(newline=''))); results=[]; hard=None
    with (logs/'ip02_acquisition_events.jsonl').open('a') as log:
      log.write(json.dumps({'time':now(),'event':'INPUTS_FROZEN','receipt_sha256':EXPECTED_RECEIPT_SHA})+'\n'); log.flush()
      for idx,r in enumerate(rows,1):
        base={k:r[k] for k in ('pair','symbol','date_utc','interval','archive_url','checksum_url')}; base['attempt_index']=idx
        d=root/'raw'/r['symbol']/'1m'/r['date_utc']; z=d/pathlib.Path(r['archive_url']).name; c=d/(z.name+'.CHECKSUM')
        try:
            download(r['checksum_url'],c,x.timeout,x.retries); official=checksum(c,z.name); download(r['archive_url'],z,x.timeout,x.retries); actual=shap(z)
            if actual!=official: raise Gate('checksum','SHA256_MISMATCH',f'{official} != {actual}')
            m=validate(z,r); base.update(status='VERIFIED',phase='complete',official_sha256=official,sha256=actual,archive_bytes=z.stat().st_size,validated_at_utc=now(),**m); results.append(base)
            log.write(json.dumps({'time':now(),'event':'VERIFIED','index':idx,'symbol':r['symbol'],'date':r['date_utc'],'sha256':actual})+'\n'); log.flush()
        except Gate as e:
            hard=e; base.update(status='HARD_GATE',phase=e.phase,error_class=e.code,error_message=e.msg,validated_at_utc=now()); results.append(base)
            for j,rr in enumerate(rows[idx:],idx+1):
                q={k:rr[k] for k in ('pair','symbol','date_utc','interval','archive_url','checksum_url')}; q.update(attempt_index=j,status='NOT_ATTEMPTED_AFTER_HARD_GATE',phase='scheduler',error_class=e.code); results.append(q)
            break
    matrix=ev/'IP02_RESULT_MATRIX.csv'
    with matrix.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=RESULT,extrasaction='ignore'); w.writeheader(); w.writerows([{k:r.get(k,'') for k in RESULT} for r in results])
    verified=[r for r in results if r.get('status')=='VERIFIED']
    summary={'run_at_utc':now(),'parent':x.parent,'checkpoint':'FQT-OSV4-IP02-BLOCKED-20260811T222834Z','manifest_sha256':shap(manifest),'freeze_receipt_canonical_sha256':EXPECTED_RECEIPT_SHA,'manifest_rows':1519,'verified':len(verified),'hard_gate':None if hard is None else {'phase':hard.phase,'code':hard.code,'message':hard.msg},'result_matrix_sha256':shap(matrix),'fresh_oos_opened':False,'oos_content_inspected_for_alpha':False,'no_alpha_change':True}
    wjson(ev/'IP02_ACQUISITION_SUMMARY.json',summary)
    if not hard and len(verified)==1519:
        leaves=[{'pair':r['pair'],'symbol':r['symbol'],'date_utc':r['date_utc'],'sha256':r['sha256'],'rows':1440,'gaps':0,'duplicates':0} for r in verified]
        freeze={'contract':'FQT-OSV4-IP02_COMPLETE_DATASET_FREEZE_V1','created_at_utc':now(),'parent':x.parent,'checkpoint':'FQT-OSV4-IP02-BLOCKED-20260811T222834Z','manifest_rows':1519,'verified':1519,'manifest_sha256':shap(manifest),'input_freeze_receipt_sha256':EXPECTED_RECEIPT_SHA,'dataset_leaf_manifest_sha256':canon(leaves),'raw_archive_total_bytes':sum(int(r['archive_bytes']) for r in verified),'oos_content_inspected_for_alpha':False,'no_alpha_change':True}
        freeze['receipt_sha256']=canon(freeze); wjson(ev/'IP02_COMPLETE_DATASET_FREEZE.json',freeze)
        print('PASS verified=1519 manifest_rows=1519 dataset='+freeze['dataset_leaf_manifest_sha256']); return 0
    print(f'HARD_GATE {hard.phase} {hard.code}: {hard.msg}',file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
