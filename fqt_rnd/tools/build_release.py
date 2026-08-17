#!/usr/bin/env python3
"""Build and verify the deterministic, secret-free research handoff bundle."""

from __future__ import annotations

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from scan_secrets import TEXT_PATTERNS, populated_sensitive_paths


ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = ROOT / "release"
RELEASE_NAME = "FQT_RnD_V741_Audit_20260817.zip"
FIXED_ZIP_TIME = (2026, 8, 17, 0, 0, 0)

ROOT_FILES = [".gitattributes", ".gitignore", "Makefile", "README.md"]
INCLUDED_TREES = [
    "audit",
    "champion",
    "configs",
    "contracts",
    "decisions",
    "hypotheses",
    "logs",
    "notebooks",
    "report",
    "results/summaries",
    "scripts",
    "strategies",
    "tests",
    "tools",
]


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def eligible(path: Path) -> bool:
    relative = path.relative_to(ROOT)
    if not path.is_file():
        return False
    if any(part in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"} for part in relative.parts):
        return False
    if path.suffix in {".pyc", ".zip"}:
        return False
    if path.name.endswith(".meta.json") or path.name == ".last_result.json":
        return False
    if relative.as_posix() == "audit/release_verification.json":
        return False
    return True


def collect_files() -> list[Path]:
    paths = [ROOT / name for name in ROOT_FILES]
    for tree in INCLUDED_TREES:
        paths.extend((ROOT / tree).rglob("*"))
    unique = {path.resolve(): path for path in paths if eligible(path)}
    return sorted(unique.values(), key=lambda item: item.relative_to(ROOT).as_posix())


def assert_preconditions() -> None:
    secret_scan = json.loads((ROOT / "audit/secret_scan.json").read_text(encoding="utf-8"))
    verification = json.loads((ROOT / "audit/verification_results.json").read_text(encoding="utf-8"))
    receipt = json.loads((ROOT / "report/delivery_receipt.json").read_text(encoding="utf-8"))
    decision = json.loads((ROOT / "decisions/promotion_decision.json").read_text(encoding="utf-8"))
    if secret_scan["publishable_tree"]["truth_status"] != "VERIFIZIERT":
        raise RuntimeError("publishable secret scan is not verified")
    if verification["failed"] != 0:
        raise RuntimeError("project verification has failures")
    if not receipt.get("ok"):
        raise RuntimeError("portable report delivery did not pass")
    if decision["all_targets_pass"] or "NO OOS" not in decision["decision"]:
        raise RuntimeError("unexpected promotion/OOS state")
    if (ROOT / "results/oos").exists():
        raise RuntimeError("frozen OOS output unexpectedly exists")


def manifest_for(files: list[Path]) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "bundle": RELEASE_NAME,
        "scope": "Binance Spot; USDC; long-only; 1m; research-only; no live orders",
        "decision": "RETAIN_HISTORICAL_CHAMPION; NO PROMOTION; NO OOS; NO CANARY",
        "reproducibility": "ZIP timestamps and member order are fixed; hashes cover every bundled file.",
        "excluded": [
            "reconstruction/ (3.8 GB immutable supplied checkout and market data)",
            "evidence/ (supplied inputs, including secret-bearing historical ZIP configs)",
            "results/**/*.zip and runtime/ (large locally reproducible engine archives)",
            "release/*.zip (prevents recursive bundles)",
        ],
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in files
        ],
    }


def zip_member(name: str, payload: bytes) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def write_archive(
    archive_path: Path,
    manifest_payload: bytes,
    files: list[Path],
) -> None:
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(zip_member("MANIFEST.json", manifest_payload), manifest_payload)
        for path in files:
            name = path.relative_to(ROOT).as_posix()
            payload = path.read_bytes()
            archive.writestr(zip_member(name, payload), payload)


def scan_bundle(archive_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    expected = {item["path"]: item for item in manifest["files"]}
    sensitive_json: list[dict[str, Any]] = []
    text_findings: list[dict[str, Any]] = []
    hash_mismatches: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        expected_names = ["MANIFEST.json", *expected]
        if names != expected_names:
            raise RuntimeError("release member order/content differs from manifest")
        embedded_manifest = json.loads(archive.read("MANIFEST.json"))
        if embedded_manifest != manifest:
            raise RuntimeError("embedded manifest mismatch")
        for name, metadata in expected.items():
            payload = archive.read(name)
            if sha256_bytes(payload) != metadata["sha256"]:
                hash_mismatches.append(name)
            suffix = Path(name).suffix.lower()
            if suffix == ".json":
                try:
                    fields = populated_sensitive_paths(json.loads(payload.decode("utf-8")))
                except Exception:
                    fields = []
                if fields:
                    sensitive_json.append({"path": name, "populated_sensitive_fields": fields})
            if suffix not in {".sqlite", ".png", ".jpg", ".jpeg", ".gif", ".parquet", ".feather"} and len(payload) <= 5_000_000:
                try:
                    text = payload.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                matches = [label for label, pattern in TEXT_PATTERNS.items() if pattern.search(text)]
                if matches:
                    text_findings.append({"path": name, "pattern_names": matches})
    return {
        "schema_version": 1,
        "bundle": f"release/{RELEASE_NAME}",
        "bundle_bytes": archive_path.stat().st_size,
        "bundle_sha256": sha256_file(archive_path),
        "members": len(expected) + 1,
        "hash_mismatches": hash_mismatches,
        "populated_sensitive_json_findings": sensitive_json,
        "high_confidence_text_findings": text_findings,
        "truth_status": "VERIFIZIERT"
        if not hash_mismatches and not sensitive_json and not text_findings
        else "NICHT VERIFIZIERT",
        "guarantee_limit": "Pattern scanning reduces risk but cannot prove absence of every possible secret.",
    }


def main() -> int:
    assert_preconditions()
    files = collect_files()
    manifest = manifest_for(files)
    RELEASE_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = RELEASE_DIR / "MANIFEST.json"
    manifest_payload = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    manifest_path.write_bytes(manifest_payload)
    archive_path = RELEASE_DIR / RELEASE_NAME
    write_archive(archive_path, manifest_payload, files)
    with tempfile.TemporaryDirectory(prefix="fqt-release-check-") as temporary:
        rebuilt = Path(temporary) / RELEASE_NAME
        write_archive(rebuilt, manifest_payload, files)
        deterministic_rebuild_sha256 = sha256_file(rebuilt)
    verification = scan_bundle(archive_path, manifest)
    verification["deterministic_rebuild_sha256"] = deterministic_rebuild_sha256
    verification["deterministic_rebuild_verified"] = (
        deterministic_rebuild_sha256 == verification["bundle_sha256"]
    )
    if not verification["deterministic_rebuild_verified"]:
        verification["truth_status"] = "NICHT VERIFIZIERT"
    (ROOT / "audit/release_verification.json").write_text(
        json.dumps(verification, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(verification, ensure_ascii=False))
    return 0 if verification["truth_status"] == "VERIFIZIERT" else 1


if __name__ == "__main__":
    raise SystemExit(main())
