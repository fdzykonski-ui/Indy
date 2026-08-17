#!/usr/bin/env python3
"""Detect credential-bearing fields while never emitting credential values."""

from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_KEYS = {
    "key",
    "secret",
    "password",
    "jwt_secret_key",
    "ws_token",
    "token",
    "api_key",
    "api_secret",
}
TEXT_PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "aws_access_key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
}


def populated_sensitive_paths(value: Any, prefix: str = "$") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{prefix}.{key}"
            if key.lower() in SENSITIVE_KEYS and child not in (None, "", [], {}):
                findings.append(child_path)
            findings.extend(populated_sensitive_paths(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(populated_sensitive_paths(child, f"{prefix}[{index}]"))
    return findings


def scan_json(path: Path) -> list[str]:
    try:
        return populated_sensitive_paths(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return []


def scan_archive(path: Path) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            if not member.endswith("_config.json"):
                continue
            try:
                config = json.loads(archive.read(member))
            except Exception:
                continue
            fields = populated_sensitive_paths(config)
            if fields:
                findings.append({"member": member, "populated_sensitive_fields": sorted(fields)})
    return findings


def main() -> int:
    publishable_json = sorted(
        path
        for path in ROOT.rglob("*.json")
        if "reconstruction" not in path.parts and not (
            "evidence" in path.parts and "backtests" in path.parts
        )
    )
    publishable_findings = [
        {"path": path.relative_to(ROOT).as_posix(), "populated_sensitive_fields": fields}
        for path in publishable_json
        if (fields := scan_json(path))
    ]
    text_findings: list[dict[str, Any]] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(part in {".git", "reconstruction"} for part in path.parts):
            continue
        if path.suffix.lower() in {".zip", ".parquet", ".feather", ".pkl", ".pyc"}:
            continue
        if path.stat().st_size > 5_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            continue
        matches = [name for name, pattern in TEXT_PATTERNS.items() if pattern.search(text)]
        if matches:
            text_findings.append({"path": path.relative_to(ROOT).as_posix(), "pattern_names": matches})

    raw_archives = sorted((ROOT / "evidence").glob("**/backtests/*.zip"))
    raw_archive_findings = [
        {
            "path": path.relative_to(ROOT).as_posix(),
            "findings": scan_archive(path),
            "publication_policy": "EXCLUDE",
        }
        for path in raw_archives
    ]
    report = {
        "schema_version": 1,
        "publishable_tree": {
            "truth_status": "VERIFIZIERT"
            if not publishable_findings and not text_findings
            else "NICHT VERIFIZIERT",
            "json_files_scanned": len(publishable_json),
            "populated_sensitive_json_findings": publishable_findings,
            "high_confidence_text_findings": text_findings,
        },
        "raw_historical_backtest_archives": {
            "truth_status": "BLOCKIERT",
            "archives": raw_archive_findings,
            "reason": "embedded configs contain populated credential fields; values intentionally omitted",
        },
        "guarantee_limit": "Pattern scanning reduces risk but cannot prove absence of every possible secret.",
    }
    target = ROOT / "audit/secret_scan.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"publishable_status": report["publishable_tree"]["truth_status"], "raw_archives": len(raw_archives)}))
    return 0 if report["publishable_tree"]["truth_status"] == "VERIFIZIERT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
