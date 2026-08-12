#!/usr/bin/env bash
set -euo pipefail
SCENARIO=${1:?scenario required}
cp fqt_ip04b/run_scenario.sh /tmp/run_slippage_scenario.sh
python - "$SCENARIO" <<'PY'
import pathlib,sys
p=pathlib.Path('/tmp/run_slippage_scenario.sh');s=p.read_text()
s=s.replace("  fee002) FEE=0.002 ;;", "  fee0012) FEE=0.0012 ;;\n  fee0015) FEE=0.0015 ;;\n  fee002) FEE=0.002 ;;")
p.write_text(s)
PY
chmod +x /tmp/run_slippage_scenario.sh
exec /tmp/run_slippage_scenario.sh "$SCENARIO"
