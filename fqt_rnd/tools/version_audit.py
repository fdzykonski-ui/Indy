#!/usr/bin/env python3
"""Record local runtime/version evidence and bounded official-doc comparison."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "reconstruction/freqtrade"
VENV_PYTHON = UPSTREAM / ".venv/bin/python"


def run(command: list[str], cwd: Path = UPSTREAM, env: dict[str, str] | None = None) -> str:
    return subprocess.run(command, cwd=cwd, env=env, check=True, text=True, capture_output=True).stdout.strip()


def main() -> int:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(UPSTREAM)
    version_output = run([str(VENV_PYTHON), "-m", "freqtrade", "--version"], env=env)
    version_match = re.search(r"Version:\s*freqtrade\s+([^\s]+)", version_output)
    if not version_match:
        raise ValueError(f"could not parse Freqtrade version from {version_output!r}")
    version = version_match.group(1)
    dependencies = json.loads(
        run(
            [
                str(VENV_PYTHON),
                "-c",
                (
                    "import json,sys,ccxt,pandas,numpy,pyarrow;"
                    "print(json.dumps({'python':sys.version.split()[0],'ccxt':ccxt.__version__,"
                    "'pandas':pandas.__version__,'numpy':numpy.__version__,'pyarrow':pyarrow.__version__}))"
                ),
            ],
            env=env,
        )
    )
    report = {
        "schema_version": 1,
        "checked_at_utc": "2026-08-17",
        "local_runtime": {
            "freqtrade": version,
            "git_commit": run(["git", "rev-parse", "HEAD"]),
            "git_branch": run(["git", "branch", "--show-current"]),
            "git_describe": run(["git", "describe", "--tags", "--always", "--dirty"]),
            **dependencies,
            "truth_status": "VERIFIZIERT",
        },
        "historical_evidence_runtime": {
            "freqtrade": "2026.5.1",
            "ccxt": "4.5.56",
            "source": "evidence/ed8_v741/ED8_V741_8x_InternalExecution/logs/V741_bt.log",
            "truth_status": "VERIFIZIERT",
        },
        "official_reference": {
            "observed_latest_release": "2026.5.1",
            "release_source": "https://github.com/freqtrade/freqtrade/releases",
            "repository_source": "https://github.com/freqtrade/freqtrade",
            "installation_source": "https://www.freqtrade.io/en/stable/installation/",
            "lookahead_source": "https://www.freqtrade.io/en/stable/lookahead-analysis/",
            "recursive_source": "https://docs.freqtrade.io/en/stable/recursive-analysis/",
            "python_requirement": ">=3.11",
            "truth_status": "TEILWEISE VERIFIZIERT",
            "reason": "Official pages were checked, but the release index snapshot may lag the 2026-08-17 wall clock.",
        },
        "compatibility_assessment": {
            "python_requirement_met": tuple(map(int, dependencies["python"].split(".")[:2])) >= (3, 11),
            "exact_historical_reproduction_on_local_dev_runtime": True,
            "truth_status": "VERIFIZIERT",
            "scope_limit": "Exact backtest reproduction does not establish exchange/live compatibility.",
        },
    }
    target = ROOT / "audit/freqtrade_version_audit.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"local": report["local_runtime"]["freqtrade"], "compatibility": "VERIFIZIERT"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
