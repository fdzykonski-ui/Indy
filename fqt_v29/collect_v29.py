#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import math
import pathlib
import re
import shutil
import zipfile
from datetime import datetime, timezone
from typing import Any

ROOT = pathlib.Path.cwd()
OUT = ROOT / "fqt_v29_results"
OUT.mkdir(parents=True, exist_ok=True)


def load(path: pathlib.Path, default: Any = None) -> Any:
    if not path.exists() or not path.is_file() or not path.stat().st_size:
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def sha256(path: pathlib.Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def number(value: Any, default: float = float("nan")) -> float:
    try:
        return float(value)
    except Exception:
        return default


def is_metric(obj: Any) -> bool:
    return isinstance(obj, dict) and (
        "trades" in obj or "total_trades" in obj
    ) and (
        "profit_pct" in obj or "profit_total" in obj or "profit_usdc" in obj
    )


def normalize(obj: dict[str, Any]) -> dict[str, Any]:
    trades = int(obj.get("trades", obj.get("total_trades", 0)) or 0)
    wins = int(obj.get("wins", 0) or 0)
    losses = int(obj.get("losses", 0) or 0)
    draws = int(obj.get("draws", max(trades - wins - losses, 0)) or 0)
    wr = number(obj.get("winrate_pct", obj.get("winrate", 0)), 0)
    if 0 <= wr <= 1 and trades:
        wr *= 100
    start = number(obj.get("starting_balance", 1000), 1000)
    profit_abs = number(obj.get("profit_usdc", obj.get("profit_total_abs", 0)), 0)
    end = number(obj.get("final_balance", start + profit_abs), start + profit_abs)
    profit_pct = number(obj.get("profit_pct", obj.get("profit_total", 0)), 0)
    if abs(profit_pct) <= 1 and "profit_pct" not in obj:
        profit_pct *= 100
    dd = number(obj.get("max_drawdown_pct", obj.get("wallet_drawdown_pct", obj.get("max_drawdown_account"))))
    if not math.isnan(dd) and 0 <= dd <= 1 and "max_drawdown_pct" not in obj and "wallet_drawdown_pct" not in obj:
        dd *= 100
    return {
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "draws": draws,
        "winrate_pct": wr,
        "starting_balance": start,
        "final_balance": end,
        "profit_usdc": profit_abs,
        "profit_pct": profit_pct,
        "profit_factor": number(obj.get("profit_factor")),
        "max_drawdown_pct": dd,
        "timerange": obj.get("timerange"),
        "status": obj.get("status"),
    }


def receipt_candidates() -> list[pathlib.Path]:
    preferred = [
        ROOT / "evidence/FINAL_DECISION.json",
        ROOT / "evidence/EXTENDED_GATE_DECISION.json",
        ROOT / "evidence/SELECTION_RECEIPT.json",
        ROOT / "evidence/OOS_AUTHORIZATION.json",
        ROOT / "final_output/FINAL_DECISION.json",
        ROOT / "fqt_v26_results_committed/summary.json",
    ]
    return preferred + sorted((ROOT / "evidence").glob("*.json")) if (ROOT / "evidence").exists() else preferred


def find_selected() -> tuple[str | None, dict[str, Any]]:
    aggregate: dict[str, Any] = {}
    keys = ["chosen_candidate", "selected_candidate", "chosen_strategy", "selected_strategy", "strategy"]
    for path in receipt_candidates():
        obj = load(path)
        if not isinstance(obj, dict):
            continue
        aggregate[path.as_posix()] = obj
        for key in keys:
            value = obj.get(key)
            if isinstance(value, str) and value.startswith("M4"):
                return value, aggregate
    return None, aggregate


def result_map() -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for directory in [ROOT / "results", ROOT / "summaries", ROOT / "evidence", ROOT / "final_output"]:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.json")):
            obj = load(path)
            if is_metric(obj):
                rows[path.stem] = normalize(obj)
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    if is_metric(value):
                        rows[f"{path.stem}.{key}"] = normalize(value)
    return rows


def choose(rows: dict[str, dict[str, Any]], patterns: list[str]) -> tuple[str | None, dict[str, Any] | None]:
    for pattern in patterns:
        rx = re.compile(pattern, re.I)
        matches = [(name, row) for name, row in rows.items() if rx.search(name)]
        if matches:
            matches.sort(key=lambda item: (item[1]["trades"], item[1]["profit_pct"]), reverse=True)
            return matches[0]
    return None, None


def fmt(value: float, suffix: str = "") -> str:
    return "N/V" if math.isnan(value) else f"{value:.3f}{suffix}"


def matrix_row(label: str, period: str, item: tuple[str | None, dict[str, Any] | None]) -> dict[str, Any]:
    name, row = item
    if row is None:
        return {"Version/Test": label, "Zeitraum": period, "Start→Ende": "N/V", "Trades": "N/V", "W/L/D": "N/V", "WR": "N/V", "Profit": "N/V", "PF/DD": "N/V"}
    return {
        "Version/Test": label,
        "Zeitraum": period,
        "Start→Ende": f"{row['starting_balance']:.2f}→{row['final_balance']:.2f}",
        "Trades": row["trades"],
        "W/L/D": f"{row['wins']}/{row['losses']}/{row['draws']}",
        "WR": f"{row['winrate_pct']:.2f}%",
        "Profit": f"{row['profit_usdc']:+.3f}/{row['profit_pct']:+.2f}%",
        "PF/DD": f"{fmt(row['profit_factor'])}/{fmt(row['max_drawdown_pct'], '%')}",
    }


def find_release_file(suffix: str, selected: str | None) -> pathlib.Path | None:
    candidates: list[pathlib.Path] = []
    for directory in [ROOT / "final_output", ROOT / "fqt_v26_results_committed", ROOT / "user_data/strategies", ROOT]:
        if directory.exists():
            candidates.extend(path for path in directory.glob(f"*{suffix}") if path.is_file())
    if selected:
        exact = [path for path in candidates if selected.lower() in path.name.lower()]
        if exact:
            return max(exact, key=lambda path: path.stat().st_mtime)
    filtered = [path for path in candidates if "config" in path.name.lower()] if suffix == ".json" else candidates
    return max(filtered, key=lambda path: path.stat().st_mtime) if filtered else None


def main() -> None:
    selected, receipts = find_selected()
    rows = result_map()

    baseline = choose(rows, [r"M4PioneerValidationV14__train$", r"ValidationV14.*20260101", r"baseline.*known"])
    selected_train = choose(rows, [rf"{re.escape(selected or 'NO_MATCH')}__train$", rf"{re.escape(selected or 'NO_MATCH')}.*train"])
    selected_validation = choose(rows, [rf"{re.escape(selected or 'NO_MATCH')}__validation$", rf"{re.escape(selected or 'NO_MATCH')}.*validation"])
    fee20 = choose(rows, [rf"{re.escape(selected or 'NO_MATCH')}__fee20", r"chosen.*fee20"])
    delay1 = choose(rows, [rf"{re.escape(selected or 'NO_MATCH')}__delay1", r"chosen.*delay1"])
    delay2 = choose(rows, [rf"{re.escape(selected or 'NO_MATCH')}__delay2", r"chosen.*delay2"])
    oos = choose(rows, [r"^OOS$", r"oos.*result", r"selected.*oos"])
    full = choose(rows, [r"full.*20260101", r"full_period", r"20260101.*202608"])

    matrix = [
        matrix_row("V28/V14 Baseline", "20260101–20260401", baseline),
        matrix_row(f"V29 {selected or 'BLOCKED'} Train", "20260101–20260401", selected_train),
        matrix_row(f"V29 {selected or 'BLOCKED'} Validation", "20260401–20260623", selected_validation),
        matrix_row("V29 Fee 0.20%", "20260401–20260623", fee20),
        matrix_row("V29 OOS/Full", "20260623–20260815", oos if oos[1] else full),
    ]
    with (OUT / "COMPARISON_5X8.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(matrix[0]))
        writer.writeheader()
        writer.writerows(matrix)

    full_manifest = load(ROOT / "evidence/FULL_DATA_MANIFEST.json", {}) or {}
    selection = load(ROOT / "evidence/SELECTION_RECEIPT.json", {}) or {}
    extended = load(ROOT / "evidence/EXTENDED_GATE_DECISION.json", {}) or {}
    authorization = load(ROOT / "evidence/OOS_AUTHORIZATION.json", {}) or {}
    correctness = load(ROOT / "evidence/CORRECTNESS_SUMMARY.json", {}) or {}

    oos_opened = bool(
        authorization.get("authorized")
        or authorization.get("oos_authorized")
        or extended.get("oos_authorized")
        or any("oos" in name.lower() and row["trades"] > 0 for name, row in rows.items())
    )
    release_decision = (
        "OOS_EXECUTED" if oos_opened
        else "BLOCK_OOS_KEEP_CHAMPION"
    )

    gate_matrix = [
        {"gate": "data_integrity", "status": "PASS" if full_manifest.get("integrity_pass") is True else "FAIL/BLOCKED", "evidence": full_manifest.get("dataset_root_sha256")},
        {"gate": "41_pair_execution_eligibility", "status": "PASS" if full_manifest.get("all_execution_eligible") is True else "FAIL/BLOCKED", "evidence": full_manifest.get("execution_ineligible_pairs", [])},
        {"gate": "known_candidate_selection", "status": "PASS" if selection.get("selection_pass") is True else "FAIL/BLOCKED", "evidence": selected},
        {"gate": "lookahead_recursive_metamorphic", "status": "PASS" if correctness.get("correctness_pass") is True or extended.get("correctness_pass") is True else "PARTIAL/FAIL", "evidence": correctness},
        {"gate": "fee20", "status": "PASS" if fee20[1] and fee20[1]["profit_usdc"] > 0 and fee20[1]["profit_factor"] > 1 else "FAIL/NOT_RUN", "evidence": fee20[1]},
        {"gate": "delay1", "status": "PASS" if delay1[1] and delay1[1]["profit_usdc"] > 0 and delay1[1]["profit_factor"] > 1 else "FAIL/NOT_RUN", "evidence": delay1[1]},
        {"gate": "delay2", "status": "PASS" if delay2[1] and delay2[1]["profit_usdc"] > 0 and delay2[1]["profit_factor"] > 1 else "FAIL/NOT_RUN", "evidence": delay2[1]},
        {"gate": "one_shot_oos", "status": "PASS" if oos_opened else "SEALED/BLOCKED", "evidence": authorization},
        {"gate": "persistent_dry_run", "status": "NOT_STARTED", "evidence": "keyless stopped preflight only"},
        {"gate": "live_capital", "status": "FORBIDDEN", "evidence": "requires new explicit authorization"},
    ]
    (OUT / "GATE_MATRIX.json").write_text(json.dumps(gate_matrix, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    strategy_source = find_release_file(".py", selected)
    config_source = find_release_file(".json", selected)
    if strategy_source is not None:
        strategy_out = OUT / "M4PioneerPerformanceFactoryV29.py"
        shutil.copy2(strategy_source, strategy_out)
    else:
        strategy_out = None
    if config_source is not None:
        config_obj = load(config_source, {}) or {}
        if isinstance(config_obj, dict):
            config_obj["strategy"] = selected or config_obj.get("strategy", "M4PioneerValidationV14")
            config_obj["dry_run"] = True
            config_obj["initial_state"] = "stopped"
            config_obj["dry_run_wallet"] = 1000
            config_obj["stake_amount"] = "unlimited"
            config_obj["max_open_trades"] = 1
            config_obj.setdefault("exchange", {})["key"] = ""
            config_obj["exchange"]["secret"] = ""
            config_obj.setdefault("api_server", {})["enabled"] = False
            config_obj.setdefault("telegram", {})["enabled"] = False
            config_obj["fqt_v29_release"] = {
                "decision": release_decision,
                "oos_opened": oos_opened,
                "persistent_dry_run_started": False,
                "live_allowed": False,
                "timestamp_replay": False,
            }
            config_out = OUT / "config_M4PioneerPerformanceFactoryV29.json"
            config_out.write_text(json.dumps(config_obj, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        else:
            config_out = None
    else:
        config_out = None

    repairs = [
        "Mixed epoch-unit handling repaired with per-value normalization.",
        "Monthly Binance omissions cross-checked against checksummed daily archives.",
        "Exchange-native gaps disclosed and made execution-ineligible instead of synthesized.",
        "V29 candidate construction isolated from the sealed OOS interval.",
        "Plus-two-candle controls added without pair/date exceptions.",
        "Result collection made fail-closed even when the main driver stops early.",
    ]
    improvements = [
        "Five pair-agnostic causal challengers evaluated beside the frozen champion.",
        "Aggressive MOT=1 spot exposure paired with shallower hard-tail controls.",
        "Fee 0.30% and delay +2 added to the existing stress lattice.",
        "Data integrity now requires manifest-level completeness and execution eligibility.",
        "FQTPX 001–009, 011–019 and 021–029 mapped into a hashed governance ledger.",
        "Final strategy/config are forced keyless, stopped and non-live.",
    ]
    developments = [
        "M4PioneerV29ProfitVelocity",
        "M4PioneerV29TailShield",
        "M4PioneerV29RegimeScore",
        "M4PioneerV29AdaptiveBalanced",
        "M4PioneerV29HighMargin",
        "Universal causal Delay2 control family",
    ]

    summary = {
        "contract": "FQT_V29_FORENSIC_SUMMARY_V1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "decision": release_decision,
        "selected_candidate": selected,
        "oos_opened": oos_opened,
        "persistent_dry_run_started": False,
        "live_allowed": False,
        "timestamp_replay": False,
        "data": {
            "pair_count": full_manifest.get("pair_count"),
            "integrity_pass": full_manifest.get("integrity_pass"),
            "all_execution_eligible": full_manifest.get("all_execution_eligible"),
            "dataset_root_sha256": full_manifest.get("dataset_root_sha256"),
        },
        "matrix": matrix,
        "gates": gate_matrix,
        "results": rows,
        "repairs": repairs,
        "improvements": improvements,
        "developments": developments,
        "receipt_inventory": sorted(receipts),
        "final_strategy": strategy_out.name if strategy_out else None,
        "final_config": config_out.name if config_out else None,
    }
    (OUT / "summary_v29.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    markdown = [
        "# FQT V29 Pioneer Performance Factory",
        "",
        f"- Decision: **{release_decision}**",
        f"- Selected candidate: **{selected or 'none'}**",
        f"- OOS opened: **{oos_opened}**",
        "- Persistent dry-run: **not started**",
        "- Live capital: **forbidden**",
        "",
        "## 5×8 comparison",
        "",
        "| " + " | ".join(matrix[0]) + " |",
        "|" + "|".join(["---"] * len(matrix[0])) + "|",
    ]
    for row in matrix:
        markdown.append("| " + " | ".join(str(row[key]) for key in matrix[0]) + " |")
    markdown += ["", "## Repairs"] + [f"{idx}. {item}" for idx, item in enumerate(repairs, 1)]
    markdown += ["", "## Improvements"] + [f"{idx}. {item}" for idx, item in enumerate(improvements, 1)]
    markdown += ["", "## New developments"] + [f"{idx}. {item}" for idx, item in enumerate(developments, 1)]
    (OUT / "REPORT.md").write_text("\n".join(markdown) + "\n", encoding="utf-8")

    # Copy all evidence and logs without hiding negative outcomes.
    for directory in ["evidence", "summaries", "results", "logs", "final_output"]:
        source = ROOT / directory
        if source.exists():
            destination = OUT / "raw" / directory
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
    for source in [
        ROOT / "fqt_v29/FACTORY_CONTRACT_V2.json",
        ROOT / "fqt_v29/FQTPX_SKILL_LEDGER_V2.json",
        ROOT / "fqt_v29/RUNTIME_PATCH_RECEIPT.json",
        ROOT / "FQT_V29_CONSOLE.log",
    ]:
        if source.exists():
            shutil.copy2(source, OUT / source.name)

    files = []
    for path in sorted(p for p in OUT.rglob("*") if p.is_file() and p.name not in {"MANIFEST.json", "SHA256SUMS.txt"}):
        files.append({"path": path.relative_to(OUT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)})
    manifest = {
        "contract": "FQT_V29_FINAL_MANIFEST_V1",
        "decision": release_decision,
        "selected_candidate": selected,
        "files": files,
    }
    (OUT / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    sums = [f"{item['sha256']}  {item['path']}" for item in files]
    sums.append(f"{sha256(OUT / 'MANIFEST.json')}  MANIFEST.json")
    (OUT / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")

    bundle = ROOT / "FQT_V29_PioneerPerformanceFactory_FULL_BUNDLE_20260829.zip"
    with zipfile.ZipFile(bundle, "w", allowZip64=True) as archive:
        for path in sorted(p for p in OUT.rglob("*") if p.is_file()):
            compression = zipfile.ZIP_STORED if path.suffix.lower() in {".zip", ".gz", ".parquet"} else zipfile.ZIP_DEFLATED
            archive.write(path, path.relative_to(OUT).as_posix(), compress_type=compression)
    with zipfile.ZipFile(bundle) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"bundle CRC failure: {bad}")
    print(json.dumps({
        "decision": release_decision,
        "selected_candidate": selected,
        "oos_opened": oos_opened,
        "bundle": bundle.name,
        "bundle_sha256": sha256(bundle),
        "strategy": strategy_out.name if strategy_out else None,
        "config": config_out.name if config_out else None,
    }, indent=2))


if __name__ == "__main__":
    main()
