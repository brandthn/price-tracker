#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}${PYTHONPATH:+:${PYTHONPATH}}"
PYTHON="${PYTHON:-python3}"
"$PYTHON" -m pip install -q pytest
"$PYTHON" -m pytest shared/tests/ -v
