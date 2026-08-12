#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
exec python3 "$ROOT/scripts/acquire_fresh_oos.py" --root "$ROOT" --parent FQT-OSV4-IP01-20260811 --timeout 120 --retries 5
