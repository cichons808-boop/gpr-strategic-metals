#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then
  exec .venv/bin/python ma200_gpr_var_strategy.py "$@"
else
  exec python3 ma200_gpr_var_strategy.py "$@"
fi
