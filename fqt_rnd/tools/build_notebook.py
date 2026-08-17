#!/usr/bin/env python3
"""Build a Colab-compatible, no-hidden-state audit notebook."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def markdown(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code(source: str, *, smoke: bool = True) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {"smoke_test": smoke},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def main() -> int:
    cells = [
        markdown(
            """# Freqtrade Spot/USDC 1m — reproduzierbares R&D-Audit

Dieses Notebook liest ausschließlich gespeicherte Artefakte und startet OOS oder Dry-run nicht automatisch. Harte Grenzen: Binance Spot, USDC, Long-only, 1m, kein Futures/Short/Grid/DCA. V741 bleibt bytegenau eingefroren; Promotionsziele sind keine Ergebnisgarantie.
"""
        ),
        code(
            """from pathlib import Path
import json
import pandas as pd

def find_root(start=Path.cwd()):
    for candidate in [start, *start.parents]:
        if (candidate / 'contracts/research_contract_v1.json').exists():
            return candidate
    raise FileNotFoundError('Projektwurzel nicht gefunden; Bundle zuerst entpacken.')

ROOT = find_root()
print(ROOT)
"""
        ),
        code(
            """contract = json.loads((ROOT / 'contracts/research_contract_v1.json').read_text())
decision = json.loads((ROOT / 'decisions/promotion_decision.json').read_text())
verification = json.loads((ROOT / 'audit/verification_results.json').read_text())
assert contract['hard_constraints']['timeframe'] == '1m'
assert contract['hard_constraints']['trading_mode'] == 'spot'
assert verification['failed'] == 0
assert decision['all_targets_pass'] is False
print(decision['decision'])
"""
        ),
        markdown("## Identischer Trainingsvertrag: Champion gegen Challenger\n"),
        code(
            """training = decision['identical_training_comparison']
comparison = pd.DataFrame({
    'Champion V741': training['champion'],
    'Challenger H001': training['challenger_h001'],
    'Challenger H002': training['challenger_h002'],
}).T
print(training['contract'])
print(comparison[['total_trades', 'winrate_pct', 'profit_pct', 'profit_factor', 'wallet_max_drawdown_pct']].to_string())
"""
        ),
        markdown("## Simulierte tägliche Equity — V741 gegen Cash und Buy-and-Hold\n"),
        code(
            """equity = pd.read_csv(ROOT / 'results/summaries/daily_equity.csv')
pivot = equity.pivot(index='date', columns='strategy', values='equity_usdc')
assert len(pivot) == 121
print(pivot.iloc[[0, -1]].to_string())
"""
        ),
        markdown("## Gate-Matrix\n"),
        code(
            """gates = pd.DataFrame(json.loads((ROOT / 'audit/gate_matrix.json').read_text())['gates'])
print(gates.groupby('status').size().to_string())
print(gates.loc[gates['status'] != 'VERIFIZIERT', ['gate', 'status', 'decision']].to_string(index=False))
"""
        ),
        markdown(
            """## Optionaler vollständiger Entwicklungs-Lauf

In Colab zuerst das Release-Bundle entpacken und den rekonstruierten Freqtrade-Checkout bereitstellen. Dann `RUN_FULL_ENGINE=True` setzen. Der Lauf enthält Backtests, Baselines, Negativkontrollen, Gebühren, Delay, Ablationen, Lookahead und Recursive — aber absichtlich **kein** OOS und keinen Trading-Prozess.
"""
        ),
        code(
            """RUN_FULL_ENGINE = False
if RUN_FULL_ENGINE:
    import subprocess
    subprocess.run(['bash', str(ROOT / 'scripts/run_engine_suite.sh')], check=True, cwd=ROOT)
else:
    print('Engine-Suite nicht gestartet. Zum expliziten Start RUN_FULL_ENGINE=True setzen.')
"""
        ),
        markdown("## OOS- und Canary-Sperre\n"),
        code(
            """assert not (ROOT / 'results/oos').exists(), 'OOS wurde entgegen dem Vertrag geöffnet.'
assert decision['all_targets_pass'] is False
print('BLOCKIERT: Frozen OOS und Dry-run-Canary bleiben geschlossen.')
"""
        ),
    ]
    notebook = {
        "cells": cells,
        "metadata": {
            "accelerator": "CPU",
            "colab": {"name": "FQT_RnD_Audit.ipynb", "provenance": []},
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "version": "3.12"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    target = ROOT / "notebooks/FQT_RnD_Audit.ipynb"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(notebook, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": target.relative_to(ROOT).as_posix(), "cells": len(cells)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
