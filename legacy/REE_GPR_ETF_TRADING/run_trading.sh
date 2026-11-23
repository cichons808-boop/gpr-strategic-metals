#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  echo 'Missing .venv; run ./run.sh first.' >&2
  exit 1
fi
if [[ ! -f output/tables/panel_monthly.csv ]]; then
  echo 'Missing output/tables/panel_monthly.csv. Run ./run.sh first.' >&2
  exit 1
fi
.venv/bin/python src/ree_trading.py "$@"
