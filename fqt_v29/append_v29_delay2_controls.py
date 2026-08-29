#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import pathlib

TARGET = pathlib.Path("user_data/strategies/M4PioneerV26Factory.py")
RECEIPT = pathlib.Path("evidence/DELAY2_CONTROL_REGISTRY_V29.json")
MARKER = "# ===== FQT V29 UNIVERSAL DELAY2 CONTROLS ====="
BASES = [
    "M4PioneerValidationV14",
    "M4PioneerV26FullStake",
    "M4PioneerV26VWAPPrune",
    "M4PioneerV26CausalQuality",
    "M4PioneerV26PathQuality",
    "M4PioneerV26TailBrake",
    "M4PioneerV26Balanced",
]


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    if MARKER in text:
        raise SystemExit(0)
    available = {node.name for node in ast.parse(text).body if isinstance(node, ast.ClassDef)}
    missing = [name for name in BASES if name not in available]
    if missing:
        raise RuntimeError(f"missing base classes: {missing}")
    blocks = ["\n\n" + MARKER]
    controls = []
    for base in BASES:
        name = f"{base}Delay2"
        controls.append(name)
        blocks.append(f'''\nclass {name}({base}):
    @staticmethod
    def version() -> str:
        return "29.control-delay-plus-2"

    def populate_entry_trend(self, dataframe, metadata):
        df = super().populate_entry_trend(dataframe, metadata)
        source = df.get("enter_long", 0).fillna(0).astype(int)
        source_tag = df.get("enter_tag", _fqt_v26_pd.Series(None, index=df.index))
        df["enter_long"] = source.shift(2, fill_value=0).astype(int)
        df["enter_tag"] = source_tag.shift(2)
        return df
''')
    blocks.append("# ===== END FQT V29 UNIVERSAL DELAY2 CONTROLS =====\n")
    candidate = text + "".join(blocks)
    ast.parse(candidate)
    TARGET.write_text(candidate, encoding="utf-8")
    receipt = {
        "contract": "FQT_V29_DELAY2_CONTROL_REGISTRY_V1",
        "status": "PASS",
        "controls": controls,
        "strategy_sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
        "signal_semantics": "original entry signal and tag shifted exactly two completed 1m candles",
    }
    RECEIPT.parent.mkdir(parents=True, exist_ok=True)
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
