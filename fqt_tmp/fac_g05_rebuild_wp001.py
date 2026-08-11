#!/usr/bin/env python3
from __future__ import annotations
import concurrent.futures, hashlib, io, json, pathlib, re, time, urllib.error, urllib.request, zipfile
import pandas as pd

BASE='https://data.binance.vision/data/spot/monthly/klines'
MONTHS=[f'{y:04d}-{m:02d}' for y,m in [(2025,m) for m in range(1,13)]+[(2026,m) for m in range(1,5)]]
EXPECTED={"BTC/USDC":"9ed4ac23eff272dab6c604754c9be275ef2ce54f7cf58a195228c5a5b9a66df9","STX/USDC":"2e16483babc184db7efe97eed616f936e77aec5d9fb4e946f362286ac3600f81","SOLV/USDC":"7f778fcaf22c39e0df0b8abd2d4cedf3375fb5836182b31be6f75c36eb2b7763","ETH/USDC":"b83b0767d377169faa965715dc14bc16bb9f6f5fc47f43d29f13a3241ccf81d4","MITO/USDC":"e18dd24ede2999787123fc2a4aa97e4e3224dd8ceb816ad3bbabb1d866954d37","A/USDC":"d29b3d5401af9310908593b715ceb5ab84319c5732ae45d77fc85537a85e7ea2","SOPH/USDC":"4f45132ac471ca6779635c36068fa03dd47f88dd7955e8037ec3cbdd0ee8f4e3","1INCH/USDC":"f5ba7e171a8c4606e73fd58b0253f97167c857ff96556d55fd5d78f6b82d5ce7","1MBABYDOGE/USDC":"ce0d4b015d041babe7cf4594ad44b64089373cd425330f430c31d1212e2878b1","2Z/USDC":"d65a883099d347b27fd0e9403b016af2405aa3d1e05db20034a5ca1b58e55875","ACH/USDC":"805d169d898009bddb5367656123fb3b3e0b59e520e25a505382230e0dda6f52","ALLO/USDC":"0e406756542a68db4d1f063539abc52fcc48835c7013900f80603ad7952bec6c","ASTER/USDC":"c957201d9533d566456cdde1834b4bb551a2580ea05f0621c9918c9f09ff4775","AT/USDC":"6a74b181072bef5493ed0d1b0b370f91fef2a93f56fee7e5a6bba070358f89a1","AVNT/USDC":"b109fdf33c54bb86c7652d38625e736f04a0e47732ce4e6c7c7d178234a2d57f","BANANAS31/USDC":"11cb9a89d45d74b3fb945c1ade3676727e825f4382da27f64827ac5093ea02d3","BERA/USDC":"6a9b35b9e887751f2ae9a0f965694301466862ec37c57d39595c0158d6cd4ed5","BIO/USDC":"f0c9cb493c21060f2664903cc64dc282913f42ee46d5334f5da12e740c301234","CATI/USDC":"2c951cd336e66b12a5ac5a7f1811ad6bf6d4e12b9a635131d077e3d37b899164","CETUS/USDC":"b076ae90278cb8b14e295522003616f000b4e65b9c6abff1fdb7586d341ab819","CGPT/USDC":"9bc314a843e8d55f25ffc471a40a94086178936156fc754029f4f25c73028576","CHIP/USDC":"583f90e4f2b9ab252acc71affc11c602eb0a08c2f9d15b8e9cf7d968c5013571","COW/USDC":"1210a264cc59520977a17a23d04f9c96ffb53ef49a7ec2b7ff8fcf744da84df1","CVX/USDC":"4c69afbfe87887e0f0d159e04fc63c4fe01b6c02b53c2e892de9c8ec35d73e49","DASH/USDC":"f1f4cee449bd8f1782edb88108bf2abbb895b3709683c573ff3a0c6e8b55170c","DOGS/USDC":"c9bfb1983a6013c4b2e1642642c2c4608dbe3c6d8ce3a7f4168872d1a3758e64","DOLO/USDC":"f61eeb1bc986a7bb7bcf20506dabaf0dedf6888e29f497e8ab8dd7b5eea2a529","DYM/USDC":"8f8d3ea04d4029b6a4f2392dc1d5f39a71767049ea840be80cac19de8c51687e","EIGEN/USDC":"fad3181552175dcad9a6b662f3a2180e85636aab9174f1c5a50dcf6acfaa6a14","ERA/USDC":"d052d4aa35288fd5339c3dd22851fe643a3567cd961f23c029e0513aad3c99c0","ETHFI/USDC":"7f84c721df0a6ca6021f5612a6b9b5c857d94424e2817d299887bd275ecd6eee","FORM/USDC":"4336b344cc2855cf7bac4be5060b4a90c796fe0664432135d347c5df21378fad","GUN/USDC":"b58f4295ae3174c65098ab39f86d02fe2da52e6b0588597242da6096fab1b991","HOLO/USDC":"48fe3d1ac0e1c01f2b9a30efb669af60d721c537897017781cfbe52608464e88","IOTA/USDC":"4250957ba877fbc9071e75352093f2670ca6a88b20280d602a0b9b75d085677d","KMNO/USDC":"92b57bab20763197c0cd3d5e5efe8521cd5fb88ca278f2ce1c6eb240490f9b6c","LUNC/USDC":"97a8b0d617fbcc9c8fe52811dea945c563a3b1568f7b2c9ffadc85ac19c25655","MINA/USDC":"5686160c94476a76c6f0b02f9f17b804770348363aa443609730a84e06dc4c43","NXPC/USDC":"985edf39bc001e83913b860efaf6d05df05d2f28498e4631056398ad3ab70fda","ORCA/USDC":"7d1f0e1566a43d1e82db873ce004d8798724f92d3299d8591fc3e4382efdb1ff","ORDI/USDC":"effd3dbc30ab09e6bfa646d65428f8b68ed1170732461e6230cb76d96aae7356","PENDLE/USDC":"507b4df828082f10458fbf9c49dc0157c82f4f05537d15aa5df59b35e51b30c9","PLUME/USDC":"cc21c5a1e369ba15f925b036e021a9d4ff792cfce23af0ae45f36c88ee8e40ea","PNUT/USDC":"12b97bb5931742dcc486568781afa3a0c11c8f9f815f1cd5636a9635a7ae748f","PUMP/USDC":"a779d836ad0001e5daaa00e07f55102d4c571a1517d90b7e57bb557323c4c83b","RED/USDC":"c643cd3e44ad841554994725347806fd39e06845a066f4a5fa60a4d1908c291c","REZ/USDC":"c1ed11a3cd549a919f3e3cf96f2ba8f45a3f5519612299ade7447e8460dca485","ROBO/USDC":"f416dc8cde41c52cc3ec3e79ab532b3ba0d56864ef98e19ea02671fbd728f837","RUNE/USDC":"c37ccc17dabb73bf9eb82c183197804cb106c907af01479831cb872744c93761","SAGA/USDC":"9ad51c8dc61d26b41bffdbad2c41024b420bad05ff0f95808dbacdc3cd1a78a0","SAHARA/USDC":"8b2127a162d8c8a8f34fe7f0de92acf6885b51e6fd63a09cb8c6c2280337890e"}
COLUMNS=['open_time','open','high','low','close','volume','close_time','quote_asset_volume','number_of_trades','taker_buy_base_asset_volume','taker_buy_quote_asset_volume','ignore']
OUT=pathlib.Path('fac_g05_wp001_rebuild/binance'); OUT.mkdir(parents=True,exist_ok=True)

def sha(b:bytes)->str: return hashlib.sha256(b).hexdigest()
def get(url:str, allow404=False):
    req=urllib.request.Request(url,headers={'User-Agent':'FQT-WP001-audit/1'})
    last=None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req,timeout=120) as r: return r.read()
        except urllib.error.HTTPError as e:
            if allow404 and e.code==404: return None
            last=e
            if e.code<500 and e.code!=429: break
        except Exception as e: last=e
        time.sleep(min(16,2**attempt))
    raise RuntimeError(f'download failed {url}: {last}')
def expected_checksum(payload:bytes,name:str)->str:
    text=payload.decode().strip(); m=re.fullmatch(r'([0-9a-fA-F]{64})\s+\*?(.+)',text)
    if not m or pathlib.Path(m.group(2)).name!=name: raise RuntimeError(f'bad checksum {name}: {text!r}')
    return m.group(1).lower()
def ts_unit(s):
    x=int(pd.to_numeric(s,errors='raise').iloc[0]); return 'us' if x>=10**14 else 'ms' if x>=10**11 else (_ for _ in ()).throw(RuntimeError(x))
def one(pair:str):
    symbol=pair.replace('/',''); frames=[]; months=[]; archives=[]
    for month in MONTHS:
        name=f'{symbol}-1m-{month}.zip'; url=f'{BASE}/{symbol}/1m/{name}'
        c=get(url+'.CHECKSUM',True)
        if c is None: continue
        exp=expected_checksum(c,name); b=get(url)
        actual=sha(b)
        if actual!=exp: raise RuntimeError(f'{name} archive hash {actual} != {exp}')
        with zipfile.ZipFile(io.BytesIO(b)) as z:
            bad=z.testzip()
            if bad: raise RuntimeError(f'{name} crc {bad}')
            members=[n for n in z.namelist() if not n.endswith('/')]
            if len(members)!=1: raise RuntimeError(f'{name} members {members}')
            with z.open(members[0]) as h: f=pd.read_csv(h,header=None,names=COLUMNS)
        frames.append(f); months.append(month); archives.append({'month':month,'sha256':actual,'bytes':len(b)})
    if not frames: raise RuntimeError(f'{pair}: no archives')
    raw=pd.concat(frames,ignore_index=True); unit=ts_unit(raw['open_time'])
    dates=pd.to_datetime(pd.to_numeric(raw['open_time'],errors='raise'),unit=unit,utc=True)
    o=pd.DataFrame({'date':dates,'open':pd.to_numeric(raw['open'],errors='raise').astype(float),'high':pd.to_numeric(raw['high'],errors='raise').astype(float),'low':pd.to_numeric(raw['low'],errors='raise').astype(float),'close':pd.to_numeric(raw['close'],errors='raise').astype(float),'volume':pd.to_numeric(raw['volume'],errors='raise').astype(float)}).sort_values('date',kind='stable').reset_index(drop=True)
    path=OUT/f"{symbol[:-4]}_USDC-1m.parquet"; o.to_parquet(path,index=False)
    actual=hashlib.sha256(path.read_bytes()).hexdigest(); exp=EXPECTED[pair]
    rec={'pair':pair,'symbol':symbol,'months':months,'rows':len(o),'first':o['date'].iloc[0].isoformat(),'last':o['date'].iloc[-1].isoformat(),'parquet':str(path),'expected_sha256':exp,'actual_sha256':actual,'hash_pass':actual==exp,'archives':archives}
    print(json.dumps({k:rec[k] for k in ('pair','rows','first','last','hash_pass')},sort_keys=True),flush=True)
    return rec

rows=[]; errors=[]
with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
    fut={ex.submit(one,p):p for p in EXPECTED}
    for f in concurrent.futures.as_completed(fut):
        p=fut[f]
        try: rows.append(f.result())
        except Exception as e:
            errors.append({'pair':p,'type':type(e).__name__,'message':str(e)}); print(json.dumps(errors[-1]),flush=True)
rows.sort(key=lambda r:list(EXPECTED).index(r['pair']))
result={'schema_version':1,'python_runtime':'3.12.13','expected_pair_count':51,'completed':len(rows),'hash_pass_count':sum(r['hash_pass'] for r in rows),'errors':errors,'all_exact':len(rows)==51 and not errors and all(r['hash_pass'] for r in rows),'records':rows}
pathlib.Path('fac_g05_wp001_rebuild/FAC_G05_WP001_EXACT_REBUILD.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
if not result['all_exact']: raise SystemExit(42)
