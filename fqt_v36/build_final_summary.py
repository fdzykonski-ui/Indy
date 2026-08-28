#!/usr/bin/env python3
"""Build the fail-closed M6R36 native/OOS decision from executed summaries."""
from __future__ import annotations
import argparse, hashlib, json
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def main() -> None:
    ap=argparse.ArgumentParser(); ap.add_argument('--summaries',type=Path,required=True); ap.add_argument('--evidence',type=Path,required=True); ap.add_argument('--out',type=Path,required=True)
    a=ap.parse_args(); a.out.parent.mkdir(parents=True,exist_ok=True)
    summaries={p.stem:load(p) for p in sorted(a.summaries.glob('*.json'))}
    required=[
        'V10_MAIN_M1_F001','V11_MAIN_M1_F001','V11_MAIN_M1_F003',
        'V11_TRAIN_M1_F001','V11_VAL_M1_F001','V11_HOLD_M1_F001',
        'V10_OOS_M1_F001','V11_OOS_M1_F001','V11_OOS_M1_F003',
        'V11_OOS_DELAY1_M1_F003','V11_OOS_DELAY2_M1_F003',
        'V11_FULL_M1_F001','V11_FULL_M1_F003'
    ]
    missing=[x for x in required if x not in summaries]
    la=load(a.evidence/'LOOKAHEAD_SUMMARY.json') or {'pass':False,'status':'NOT_AVAILABLE'}
    rec=load(a.evidence/'RECURSIVE_SUMMARY.json') or {'pass':False,'status':'NOT_AVAILABLE'}
    correctness=bool(la.get('pass') and rec.get('pass'))
    if missing:
        decision='BLOCKED_INCOMPLETE_EXECUTION'
        checks={'required_summaries_complete':False,'correctness':correctness}
    else:
        oos=summaries['V11_OOS_M1_F001']; oos3=summaries['V11_OOS_M1_F003']; full=summaries['V11_FULL_M1_F001']; full3=summaries['V11_FULL_M1_F003']
        delays=[summaries['V11_OOS_DELAY1_M1_F003'],summaries['V11_OOS_DELAY2_M1_F003']]
        checks={
            'required_summaries_complete':True,
            'correctness':correctness,
            'oos_profit_gt50':float(oos['profit_pct'])>50.0,
            'oos_wr_gt80':float(oos['winrate_pct'])>80.0,
            'oos_pf_gt5':float(oos.get('profit_factor') or 0)>5.0,
            'oos_dd_lt5':float(oos['max_drawdown_pct'])<5.0,
            'oos_trades_ge100':int(oos['trades'])>=100,
            'oos_fee003_positive':float(oos3['profit_pct'])>0 and float(oos3.get('profit_factor') or 0)>1 and float(oos3['max_drawdown_pct'])<5,
            'oos_delay1_positive':float(delays[0]['profit_pct'])>0,
            'oos_delay2_positive':float(delays[1]['profit_pct'])>0,
            'full_trades_gt500':int(full['trades'])>500,
            'full_wr_gt80':float(full['winrate_pct'])>80.0,
            'full_profit_gt80':float(full['profit_pct'])>80.0,
            'full_pf_gt5':float(full.get('profit_factor') or 0)>5.0,
            'full_dd_lt5':float(full['max_drawdown_pct'])<5.0,
            'full_fee003_positive':float(full3['profit_pct'])>0 and float(full3.get('profit_factor') or 0)>1,
        }
        if all(checks.values()):
            decision='PROMOTE_TO_DRYRUN_PREFLIGHT'
        elif float(oos['profit_pct'])>0 and float(oos.get('profit_factor') or 0)>1 and float(oos['max_drawdown_pct'])<5:
            decision='QUARANTINE_POSITIVE_OOS_TARGETS_MISSED'
        else:
            decision='REJECT_OOS_RETAIN_ROLLBACK_CHAMPION'
    obj={
        'contract':'FQT_M6R36_V11_NATIVE_ONE_SHOT_OOS_V1',
        'decision':decision,
        'live_allowed':False,
        'dry_run_started':False,
        'oos_opened':not missing,
        'oos_opened_once':not missing,
        'no_oos_tuning':True,
        'missing_summaries':missing,
        'correctness':{'lookahead':la,'recursive':rec,'pass':correctness},
        'checks':checks,
        'summaries':summaries,
    }
    canonical=json.dumps(obj,sort_keys=True,separators=(',',':')).encode(); obj['summary_sha256']=hashlib.sha256(canonical).hexdigest()
    a.out.write_text(json.dumps(obj,indent=2,sort_keys=True)+'\n')
    compact={'decision':decision,'checks':checks,'missing':missing}
    print(json.dumps(compact,indent=2))

if __name__=='__main__': main()
