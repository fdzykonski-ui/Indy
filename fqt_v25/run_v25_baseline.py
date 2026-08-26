#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import shutil
import zipfile
from pathlib import Path

import run_v25_oos_factory as fac


def compact(label: str, row: dict) -> dict:
    return {
        "Version/Test": label,
        "Zeitraum": row.get("timerange", ""),
        "Start-Ende": f"{row.get('starting_balance', 0):.2f}->{row.get('final_balance', 0):.2f}",
        "Trades": row.get("total_trades"),
        "W/L": f"{row.get('wins')}/{row.get('losses')}",
        "WR_pct": round(row.get("winrate_pct", 0), 2),
        "Profit": f"{row.get('profit_usdc', 0):+.2f}/{row.get('profit_pct', 0):+.2f}%",
        "PF/MDD": f"{row.get('profit_factor', 0):.2f}/{row.get('max_drawdown_pct', 0):.2f}%",
    }


def main() -> int:
    parent, config_path = fac.locate_parent()
    fac.write_candidate_strategy(parent)
    template = json.loads(config_path.read_text()) if config_path else fac.fallback_config()
    available = []
    for idx, pair in enumerate(fac.ORIGINAL_PAIRS, 1):
        ok = fac.materialize_pair(pair)
        print(f"BASELINE DATA {idx}/31 {pair} {'PASS' if ok else 'FAIL'}", flush=True)
        if ok:
            available.append(pair)
    if len(available) != 31:
        raise RuntimeError(f"Original 31-pair universe incomplete: {len(available)}/31")
    dev = fac.backtest(template, available, "M4PioneerValidationV14", fac.DEV_RANGE, "baseline_dev_mot1")
    known = fac.backtest(template, available, "M4PioneerValidationV14", fac.KNOWN_RANGE, "baseline_known_mot1")
    oos = fac.backtest(template, available, "M4PioneerValidationV14", fac.OOS_RANGE, "baseline_oos_mot1")
    full = fac.backtest(template, available, "M4PioneerValidationV14", fac.FULL_RANGE, "baseline_full_mot1")
    if not all([dev, known, oos, full]):
        raise RuntimeError("One or more baseline runs failed")
    summary = {
        "run_id": "FQT-V25-MOT1-BASELINE-20260826",
        "strategy": "M4PioneerValidationV14",
        "pairs": available,
        "max_open_trades": 1,
        "stake_amount": "unlimited",
        "wallet": 1000,
        "development": {k:v for k,v in dev.items() if k not in ["trades","results_per_pair"]},
        "known": {k:v for k,v in known.items() if k not in ["trades","results_per_pair"]},
        "one_shot_oos": {k:v for k,v in oos.items() if k not in ["trades","results_per_pair"]},
        "full": {k:v for k,v in full.items() if k not in ["trades","results_per_pair"]},
        "targets": {
            "oos_profit_gt_50": oos["profit_pct"] > 50,
            "full_trades_gt_500": full["total_trades"] > 500,
            "full_wr_gt_80": full["winrate_pct"] > 80,
        },
        "classification": "BASELINE_ONLY_NO_ALPHA_SELECTION",
        "no_live": True,
    }
    out = Path("fqt_v25_baseline_results")
    (out / "tables").mkdir(parents=True, exist_ok=True)
    (out / "final").mkdir(parents=True, exist_ok=True)
    (out / "evidence").mkdir(parents=True, exist_ok=True)
    (out / "FINAL_SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    rows = [compact("V14 Dev", dev), compact("V14 Known", known), compact("V14 OOS", oos), compact("V14 Full", full)]
    with (out / "tables/COMPARISON.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    cfg = fac.make_config(template, available, "baseline_final_mot1", max_open=1, wallet=1000, stake="unlimited")
    cfg_obj = json.loads(cfg.read_text()); cfg_obj["strategy"] = "M4PioneerValidationV14"; cfg_obj["dry_run"] = True; cfg_obj["initial_state"] = "stopped"
    (out / "final/config_M4PioneerValidationV14_MOT1_20260826.json").write_text(json.dumps(cfg_obj, indent=2) + "\n")
    shutil.copy2(parent, out / "final/M4PioneerValidationV14_MOT1_20260826.py")
    for label in ["baseline_dev_mot1", "baseline_known_mot1", "baseline_oos_mot1", "baseline_full_mot1"]:
        src = fac.EVIDDIR / "results" / f"{label}.json"
        if src.exists(): shutil.copy2(src, out / "evidence" / src.name)
    bundle = out / "FQT_V25_MOT1_BASELINE_EvidencePack_20260826.zip"
    with zipfile.ZipFile(bundle, "w", allowZip64=True) as zf:
        for p in sorted(out.rglob("*")):
            if p.is_file() and p != bundle:
                zf.write(p, p.relative_to(out).as_posix(), compress_type=zipfile.ZIP_DEFLATED)
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
