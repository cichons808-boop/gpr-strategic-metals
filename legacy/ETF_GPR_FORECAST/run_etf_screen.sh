#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -x .venv/bin/python ]]; then PY=.venv/bin/python; else
  python3 -m venv .venv
  PY=.venv/bin/python
fi
if ! "$PY" -c 'import numpy,pandas,matplotlib,statsmodels,yfinance,requests,xlrd' >/dev/null 2>&1; then
  "$PY" -m pip install -r requirements_etf_screen.txt
fi
"$PY" src/etf_gpr_forecast.py "$@"
