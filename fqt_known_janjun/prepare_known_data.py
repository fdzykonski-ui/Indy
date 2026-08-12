#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,pathlib,re,shutil,statistics,time,urllib.request,zipfile
import pandas as pd
CHECKSUM_RE=re.compile(r'^([0-9a-fA-F]{64})\s+\*?(.+?)\s*$')
MONTHS=['2025-12','2026-01','2026-02','2026-03','2026-04','2026-05','2026-06']
EXPECTED={'2025-12':44640,'2026-01':44640,'2026-02':40320,'2026-03':44640,'2026-04':43200,'2026-05':44640,'2026-06':43200}
def sha256(p):
 h=hashlib.sha256()
 with pathlib.Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def download(url,out,retries=5):
 out=pathlib.Path(out);out.parent.mkdir(parents=True,exist_ok=True)
 if out.exists() and out.stat().st_size:return
 last=None
 for n in range(retries):
  tmp=out.with_suffix(out.suffix+'.part')
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'FQT-KNOWN-JANJUN/1.0'})
   with urllib.request.urlopen(req,timeout=60) as r,tmp.open('wb') as f:shutil.copyfileobj(r,f,1<<20)
   if not tmp.stat().st_size:raise RuntimeError('empty')
   tmp.replace(out);return
  except Exception as e:last=e;tmp.unlink(missing_ok=True);time.sleep(min(2**n,16))
 raise RuntimeError(f'download failed {url}: {last!r}')
def ck(path,name):
 lines=[x for x in pathlib.Path(path).read_text().splitlines() if x.strip()]
 if len(lines)!=1 or not (m:=CHECKSUM_RE.match(lines[0])):raise RuntimeError(f'bad checksum {path}')
 if pathlib.Path(m.group(2)).name!=name:raise RuntimeError(f'checksum name {path}')
 return m.group(1).lower()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--config',type=pathlib.Path,required=True);ap.add_argument('--datadir',type=pathlib.Path,required=True);ap.add_argument('--raw',type=pathlib.Path,required=True);ap.add_argument('--manifest',type=pathlib.Path,required=True);a=ap.parse_args()
 cfg=json.loads(a.config.read_text());pairs=cfg['exchange']['pair_whitelist'];a.datadir.mkdir(parents=True,exist_ok=True);records=[]
 for pair in pairs:
  sym=pair.replace('/','');parts=[];ar=[]
  for month in MONTHS:
   name=f'{sym}-1m-{month}.zip';url=f'https://data.binance.vision/data/spot/monthly/klines/{sym}/1m/{name}';d=a.raw/sym;zp=d/name;cp=d/(name+'.CHECKSUM')
   download(url+'.CHECKSUM',cp);download(url,zp);official=ck(cp,name);actual=sha256(zp)
   if actual!=official:raise RuntimeError(f'hash mismatch {name}')
   with zipfile.ZipFile(zp) as z:
    if (bad:=z.testzip()) is not None:raise RuntimeError(f'crc {name}:{bad}')
    ms=[x for x in z.namelist() if not x.endswith('/')]
    if len(ms)!=1:raise RuntimeError(f'members {name}:{ms}')
    with z.open(ms[0]) as f:df=pd.read_csv(f,header=None,names=['open_time','open','high','low','close','volume','close_time','quote_volume','trades','taker_base','taker_quote','ignore'])
   if len(df)!=EXPECTED[month]:raise RuntimeError(f'rows {name} {len(df)}')
   for c in ['open','high','low','close','volume','quote_volume']:df[c]=pd.to_numeric(df[c],errors='raise')
   df['open_time']=pd.to_numeric(df['open_time'],errors='raise').astype('int64');parts.append(df[['open_time','open','high','low','close','volume','quote_volume']]);ar.append({'month':month,'sha256':actual,'bytes':zp.stat().st_size,'rows':len(df)})
  x=pd.concat(parts,ignore_index=True).sort_values('open_time').drop_duplicates('open_time',keep='last')
  if len(x)!=sum(EXPECTED.values()):raise RuntimeError(f'total rows {pair} {len(x)}')
  ots=x.open_time.to_numpy();gaps=int(((ots[1:]-ots[:-1])!=60_000_000).sum());dups=int(len(ots)-len(set(map(int,ots))))
  if gaps or dups:raise RuntimeError(f'invariant {pair} gaps={gaps} dups={dups}')
  out=pd.DataFrame({'date':pd.to_datetime(x.open_time,unit='us',utc=True),'open':x.open.astype(float),'high':x.high.astype(float),'low':x.low.astype(float),'close':x.close.astype(float),'volume':x.volume.astype(float)})
  fp=a.datadir/f"{pair.replace('/','_')}-1m.parquet";out.to_parquet(fp,index=False)
  r={'pair':pair,'rows':len(out),'first':out.date.iloc[0].isoformat(),'last':out.date.iloc[-1].isoformat(),'gaps':0,'duplicates':0,'zero_volume_ratio':float((out.volume==0).mean()),'median_quote_volume':float(statistics.median(x.quote_volume)),'parquet':str(fp),'parquet_sha256':sha256(fp),'archives':ar};records.append(r);print(json.dumps({'pair':pair,'rows':r['rows'],'sha256':r['parquet_sha256']}),flush=True)
 manifest={'contract':'FQT_KNOWN_JAN_JUN22_DATA_V1','classification':'KNOWN_REPEATEDLY_INSPECTED_NOT_PRISTINE_OOS','source':'official Binance monthly klines + CHECKSUM','months':MONTHS,'pair_count':len(pairs),'records':records};manifest['dataset_root_sha256']=hashlib.sha256(json.dumps([{'pair':r['pair'],'sha256':r['parquet_sha256'],'rows':r['rows']} for r in records],sort_keys=True,separators=(',',':')).encode()).hexdigest();a.manifest.parent.mkdir(parents=True,exist_ok=True);a.manifest.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n');print(json.dumps({'pair_count':len(records),'dataset_root_sha256':manifest['dataset_root_sha256']},indent=2))
if __name__=='__main__':main()
