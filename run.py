"""Run the saved-data models from the project root."""

import argparse
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent

parser = argparse.ArgumentParser(description=__doc__)
options = parser.add_mutually_exclusive_group()
options.add_argument(
    "--all",
    action="store_true",
    help="also run the earlier models and robustness search",
)
options.add_argument(
    "--check",
    action="store_true",
    help="check the saved main results without re-estimating models",
)
args = parser.parse_args()

stages = [
    "models/prepare_data.py",
    "models/baseline.py",
    "models/baseline_checks.py",
    "models/material_screen.py",
]
if args.all:
    stages += [
        "models/nonlinear.py",
        "models/candidate_validation.py",
        "models/legacy_backtest.py",
        "models/legacy_vintages.py",
        "models/long_history.py",
    ]
stages += [
    "models/price_models.py",
    "models/benchmarks.py",
    "models/sensitivity.py",
    "models/revision_attribution.py",
    "checks/verify.py",
]
if args.check:
    stages = ["checks/verify.py"]

for script in stages:
    print(script, end=" ... ", flush=True)
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, str(ROOT / script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        print("failed")
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        raise SystemExit(result.returncode)
    print(f"{time.monotonic() - start:.1f}s")
