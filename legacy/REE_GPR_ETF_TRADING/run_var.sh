#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -d .venv ]]; then
  echo 'Missing .venv; run ./run.sh --offline first to set up dependencies.' >&2
  exit 1
fi
if [[ ! -f output/tables/panel_monthly.csv ]]; then
  echo 'Missing panel_monthly.csv; run ./run.sh --offline first.' >&2
  exit 1
fi
.venv/bin/python src/ree_var.py "$@"
