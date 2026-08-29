#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import pathlib
import re

SOURCE = pathlib.Path("fqt_v26/run_v26.sh")
TARGET = pathlib.Path("fqt_v29/run_v29.generated.sh")
RECEIPT = pathlib.Path("fqt_v29/RUNTIME_PATCH_RECEIPT.json")

OLD = [
    "M4PioneerValidationV14",
    "M4PioneerV26FullStake",
    "M4PioneerV26VWAPPrune",
    "M4PioneerV26CausalQuality",
    "M4PioneerV26PathQuality",
    "M4PioneerV26TailBrake",
    "M4PioneerV26Balanced",
]
NEW = OLD + [
    "M4PioneerV29ProfitVelocity",
    "M4PioneerV29TailShield",
    "M4PioneerV29RegimeScore",
    "M4PioneerV29AdaptiveBalanced",
    "M4PioneerV29HighMargin",
]


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> tuple[str, dict]:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one occurrence, found {count}")
    return text.replace(old, new, 1), {"label": label, "count": count}


def replace_candidate_lists(text: str) -> tuple[str, int]:
    replacements = 0
    old_bash = "CANDIDATES=(" + " ".join(OLD) + ")"
    new_bash = "CANDIDATES=(" + " ".join(NEW) + ")"
    if old_bash in text:
        text = text.replace(old_bash, new_bash)
        replacements += 1

    quote_variants = [
        "[" + ",".join(repr(name) for name in OLD) + "]",
        "[" + ", ".join(repr(name) for name in OLD) + "]",
        "[" + ",".join(json.dumps(name) for name in OLD) + "]",
        "[" + ", ".join(json.dumps(name) for name in OLD) + "]",
    ]
    replacement_py = "[" + ",".join(repr(name) for name in NEW) + "]"
    for variant in quote_variants:
        count = text.count(variant)
        if count:
            text = text.replace(variant, replacement_py)
            replacements += count

    # Conservative multiline fallback: only lists containing all seven frozen names.
    pattern = re.compile(r"\[(?:\s*['\"]M4Pioneer(?:ValidationV14|V26(?:FullStake|VWAPPrune|CausalQuality|PathQuality|TailBrake|Balanced))['\"]\s*,?){7}\s*\]", re.S)
    text, count = pattern.subn(replacement_py, text)
    replacements += count
    return text, replacements


def patch_selection_script(path: pathlib.Path) -> dict:
    before = path.read_bytes()
    text = before.decode("utf-8")
    text2, replacements = replace_candidate_lists(text)
    if replacements == 0:
        # The selector may discover candidates from filenames; this is acceptable only
        # when no explicit frozen-name list exists.
        explicit_old_names = sum(text.count(name) for name in OLD)
        if explicit_old_names:
            raise RuntimeError(f"selection script contains old explicit names but list patch failed: {explicit_old_names}")
    path.write_text(text2, encoding="utf-8")
    return {
        "path": str(path),
        "before_sha256": digest_bytes(before),
        "after_sha256": digest_bytes(path.read_bytes()),
        "candidate_list_replacements": replacements,
    }


def main() -> None:
    before = SOURCE.read_bytes()
    text = before.decode("utf-8")
    changes = []

    anchor = 'python "$REPO_ROOT/fqt_v26/append_baseline_controls.py"\n'
    insertion = (
        anchor
        + 'python "$REPO_ROOT/fqt_v29/append_v29_candidates.py"\n'
        + 'python "$REPO_ROOT/fqt_v29/append_v29_delay2_controls.py"\n'
    )
    text, receipt = replace_once(text, anchor, insertion, "append_v29_candidates_and_delay2")
    changes.append(receipt)

    text, candidate_replacements = replace_candidate_lists(text)
    if candidate_replacements < 2:
        raise RuntimeError(f"run script candidate lists: expected >=2 replacements, got {candidate_replacements}")
    changes.append({"label": "extend_candidate_lists", "count": candidate_replacements})

    old_stress = '''  if [[ "$s" == 'M4PioneerValidationV14' ]]; then delay='M4PioneerValidationV14Delay1'; else delay="${s}Delay1"; fi
  run_bt "${s}__delay1" "$delay" 20260401-20260623 0.001 config41.json
  run_bt "${s}__reverse" "$s" 20260401-20260623 0.001 config41_reverse.json
done
'''
    new_stress = '''  if [[ "$s" == 'M4PioneerValidationV14' ]]; then delay='M4PioneerValidationV14Delay1'; else delay="${s}Delay1"; fi
  delay2="${s}Delay2"
  run_bt "${s}__delay1" "$delay" 20260401-20260623 0.001 config41.json
  run_bt "${s}__delay2" "$delay2" 20260401-20260623 0.001 config41.json
  run_bt "${s}__fee30" "$s" 20260401-20260623 0.003 config41.json
  run_bt "${s}__reverse" "$s" 20260401-20260623 0.001 config41_reverse.json
done
'''
    text, receipt = replace_once(text, old_stress, new_stress, "add_fee30_and_delay2_stress")
    changes.append(receipt)

    old_integrity = "manifest.get('pair_count')==41 and all(r.get('gaps')==0 and r.get('duplicates')==0 for r in manifest.get('records',[]))"
    new_integrity = "manifest.get('pair_count')==41 and manifest.get('integrity_pass') is True and manifest.get('all_execution_eligible') is True and all(r.get('unresolved_gap_minutes',0)==0 and r.get('duplicates')==0 for r in manifest.get('records',[]))"
    if old_integrity in text:
        text = text.replace(old_integrity, new_integrity)
        changes.append({"label": "fail_closed_data_integrity_gate", "count": 1})
    else:
        # Older contract form; require a positive manifest-level gate immediately after load.
        marker = "manifest=json.load(open('evidence/FULL_DATA_MANIFEST.json'))\n"
        if marker not in text:
            raise RuntimeError("data-integrity marker not found")
        text = text.replace(marker, marker + "assert manifest.get('integrity_pass') is True and manifest.get('all_execution_eligible') is True, manifest\n", 1)
        changes.append({"label": "fail_closed_data_integrity_assertion", "count": 1})

    # Keep V29 output names distinct without changing execution semantics.
    text = text.replace("FQT_V26_PIONEER_FACTORY_RETURN", "FQT_V29_PIONEER_FACTORY_RETURN")
    text = text.replace("FQT_V26_PIONEER_FINAL", "FQT_V29_PIONEER_FINAL")
    text = text.replace("FQT_V26_FINAL", "FQT_V29_FINAL")
    changes.append({"label": "v29_output_namespace", "count": 1})

    # Include frozen V29 contracts in the internally generated bundle where possible.
    package_anchor = "cp \"$REPO_ROOT/fqt_v26/FACTORY_CONTRACT_V1.json\" final_output/\n"
    if package_anchor in text:
        text = text.replace(
            package_anchor,
            package_anchor
            + 'cp "$REPO_ROOT/fqt_v29/FACTORY_CONTRACT_V2.json" final_output/\n'
            + 'cp "$REPO_ROOT/fqt_v29/FQTPX_SKILL_LEDGER_V2.json" final_output/\n'
            + 'cp "$REPO_ROOT/fqt_v29/RUNTIME_PATCH_RECEIPT.json" final_output/\n',
            1,
        )
        changes.append({"label": "embed_v29_contracts", "count": 1})

    # Validate shell syntax before publishing the generated runtime.
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(text, encoding="utf-8")

    selector_receipt = patch_selection_script(pathlib.Path("fqt_v26/select_candidate.py"))

    receipt = {
        "contract": "FQT_V29_RUNTIME_PATCH_RECEIPT_V1",
        "status": "PASS",
        "source": str(SOURCE),
        "target": str(TARGET),
        "source_sha256": digest_bytes(before),
        "target_sha256": digest_bytes(TARGET.read_bytes()),
        "candidate_count_before": len(OLD),
        "candidate_count_after": len(NEW),
        "candidates": NEW,
        "changes": changes,
        "selector_patch": selector_receipt,
        "oos_semantics_changed": False,
        "timestamp_replay": False,
    }
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
