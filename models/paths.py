"""Project directories shared by the model scripts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
RESULTS = ROOT / "results"

for name in ["baseline", "materials", "market"]:
    (PROCESSED / name).mkdir(parents=True, exist_ok=True)

for name in ["baseline", "materials", "legacy", "long_history", "main"]:
    (RESULTS / name).mkdir(parents=True, exist_ok=True)
