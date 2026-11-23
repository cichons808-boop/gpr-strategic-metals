"""Restore the selected GPR packages after explicit approval of the one-time job.

This script restores files and checks their integrity. It does not change
repository permissions, create workflows, or push commits.
"""
from pathlib import Path, PurePosixPath
from zipfile import ZipFile
import ast
import csv
import hashlib
import importlib.metadata
import json
import os
import platform
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[2]
STAGING = ROOT / ".github" / "import"
CACHE = Path(os.environ.get("RUNNER_TEMP", tempfile.gettempdir())) / "gpr-source-import"
CONTEXT = CACHE / "context.json"
PRIMARY = "gpr-strategic-metals-data-models.zip"

SELECTED_SOURCES = {
    PRIMARY: "libfile_16444a9fc30881919ecd817b09145a2e",
    "GPR_Rare_Earths_Replication_EN.zip": "libfile_232d0a4e61a881919783c2a2034aeb75",
    "GPR_Rare_Earths_LaTeX_Source.zip": "libfile_e59c7e5291048191968f42049ede9dff",
    "REE_GPR_ETF.zip": "libfile_09b2e446109c8191b45542979b4ab4d4",
    "REE_GPR_ETF_VAR.zip": "libfile_2d737c9cfef08191a7fa82e5b7ed744d",
    "REE_GPR_ETF_TRADING.zip": "libfile_3290a10c48c4819183eb95ef47f47dfe",
    "REE_GPR_SIGN_STRATEGY.zip": "libfile_48554230f28c8191b4c34f3f1a77a896",
    "REE_GPR_MA200.zip": "libfile_2015a438deb081919be70ca177b3bd5b",
    "SPY_GPR_EXCESS.zip": "libfile_2db0c638931c8191a632eb796983bd49",
    "SPY_GPR_EXCESS_FIX.zip": "libfile_73dcb57d4a188191bf9e874f754d9c31",
    "ETF_GPR_FORECAST.zip": "libfile_1b091b71ad1481919cd7fa79800e79b8",
    "GPR_surowce_strategiczne_praca-2.pdf": "libfile_83dd769da98c8191806a39d898d78165",
    "GPR_Rare_Earths_Research_Article_EN.pdf": "libfile_9b711504654881918dce6e2d95315993",
    "GPR_Rare_Earths_Research_Article_EN(1).pdf": "libfile_a697a18e4a108191bf8724fa67441265",
    "ree_gpr.py": "libfile_4df3e95432a881918fc77ead5e3a3989",
    "ree_var.py": "libfile_09ceaac4d9bc819195da93f8deb07f9f",
    "ree_trading.py": "libfile_bbf95d1e973081919fa045ece2ef36bb",
    "spy_gpr_excess.py": "libfile_afb2c54587648191bc00d6cdc0671c6a",
    "etf_gpr_forecast.py": "libfile_4a89d3fd652c81919e9f3cb1eeaef2bf",
    "README_SPY_GPR.md": "libfile_c137fa82c1f48191899b57b94adfbb68",
    "README_ETF_GPR_FORECAST.md": "libfile_6fb82ac950888191a6af55b416cbd28f",
}
PACKAGES = [
    (PRIMARY, "", "gpr-strategic-metals", 402),
    ("GPR_Rare_Earths_Replication_EN.zip", "replication", None, 459),
    ("GPR_Rare_Earths_LaTeX_Source.zip", "paper/latex", None, 26),
    ("REE_GPR_ETF.zip", "legacy/REE_GPR_ETF", "REE_GPR_ETF", 7),
    ("REE_GPR_ETF_VAR.zip", "legacy/REE_GPR_ETF_VAR", "REE_GPR_ETF", 11),
    ("REE_GPR_ETF_TRADING.zip", "legacy/REE_GPR_ETF_TRADING", "REE_GPR_ETF", 15),
    ("REE_GPR_SIGN_STRATEGY.zip", "legacy/REE_GPR_SIGN_STRATEGY", "REE_GPR_ETF", 4),
    ("REE_GPR_MA200.zip", "legacy/REE_GPR_MA200", "REE_GPR_ETF", 4),
    ("SPY_GPR_EXCESS.zip", "legacy/SPY_GPR_EXCESS", "REE_GPR_ETF", 4),
    ("SPY_GPR_EXCESS_FIX.zip", "legacy/SPY_GPR_EXCESS_FIX", "REE_GPR_ETF", 3),
    ("ETF_GPR_FORECAST.zip", "legacy/ETF_GPR_FORECAST", "REE_GPR_ETF", 6),
]

NAVIGATION = """
## Articles, replication and earlier code

| Path | Contents |
| --- | --- |
| [paper/](paper/) | Polish article and both saved English article versions |
| [paper/latex/](paper/latex/) | English LaTeX source, tables, figures and compilation instructions |
| [replication/](replication/) | Complete original English replication package with its original directory structure |
| [legacy/](legacy/) | Earlier ETF, VAR, trading, GPR direction, MA200, SPY excess-return and forecasting projects |
| [docs/IMPORT_NOTES.md](docs/IMPORT_NOTES.md) | Import scope and validation notes |
| [docs/IMPORT_MANIFEST.csv](docs/IMPORT_MANIFEST.csv) | Source archive, original member, destination, byte size and SHA-256 for every imported file |

The root-level models and data directories are the reorganised data-and-model
snapshot. The original replication and earlier projects retain their own
instructions, dependencies and historical assumptions. Adding these materials
to GitHub does not update the underlying data or produce new research results.
"""


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_source(path, data):
    path = ROOT / path
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError("Destination escapes the repository")
    if path.exists() and path != ROOT / "README.md" and path.read_bytes() != data:
        raise ValueError(f"Existing file differs from the selected source: {path.relative_to(ROOT)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if path.suffix == ".sh":
        path.chmod(0o755)


def record(rows, source, member, destination, data):
    rows.append({
        "archive": source,
        "member": member,
        "path": str(destination),
        "size_bytes": len(data),
        "sha256": digest(data),
    })


def restore_package(name, destination, strip, expected_count, rows):
    count = 0
    with ZipFile(CACHE / name) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            path = PurePosixPath(info.filename)
            if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
                raise ValueError("Unsafe archive member")
            if ".git" in path.parts or ".github" in path.parts:
                raise ValueError("Unexpected repository-control directory in a source archive")
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError("Symbolic links are not accepted in source archives")
            if strip:
                if not path.parts or path.parts[0] != strip:
                    raise ValueError("Unexpected archive root")
                path = PurePosixPath(*path.parts[1:])
            target = PurePosixPath(destination) / path
            data = archive.read(info)
            write_source(target, data)
            record(rows, name, info.filename, target, data)
            count += 1
    if count != expected_count:
        raise ValueError(f"Unexpected member count for {name}: {count}")


def mask_transfer(transfer):
    values = [transfer.get("download_url"), transfer.get("completion_token")]
    values += list((transfer.get("headers") or {}).values())
    for value in values:
        if value:
            safe = str(value).replace("\r", "").replace("\n", "")
            print(f"::add-mask::{safe}", flush=True)


def prepare_sources():
    launch = json.loads((STAGING / "launch.json").read_text())
    items = launch["source_files"]
    by_name = {item["name"]: item for item in items}
    if set(by_name) != set(SELECTED_SOURCES) or len(items) != len(by_name):
        raise ValueError("The launch manifest does not match the 21 selected sources")
    CACHE.mkdir(parents=True, exist_ok=True)
    helper_dir = CACHE / "helpers"
    helper_dir.mkdir(exist_ok=True)
    for filename in ["library_file_transfer.py", "library_hosted_apps.py"]:
        (helper_dir / filename).write_bytes((STAGING / filename).read_bytes())
    source_digests = []
    for name, library_id in SELECTED_SOURCES.items():
        item = by_name[name]
        transfer = item["transfer"]
        if item["library_file_id"] != library_id or transfer.get("library_file_id") != library_id:
            raise ValueError("Library identity mismatch")
        if not transfer.get("download_url") or transfer.get("workspace_path"):
            raise ValueError("The file was not prepared for external delivery")
        headers = transfer.get("headers") or {}
        if any(key.lower() in {"authorization", "cookie", "proxy-authorization"} for key in headers):
            raise ValueError("Account-wide authentication headers may not be forwarded")
        mask_transfer(transfer)
        command = [sys.executable, str(helper_dir / "library_file_transfer.py"), "materialize", str(CACHE / name)]
        result = subprocess.run(command, input=json.dumps(transfer), capture_output=True, text=True)
        if result.returncode:
            print(result.stderr, file=sys.stderr)
            raise RuntimeError(f"Source materialization failed: {name}")
        data = (CACHE / name).read_bytes()
        if len(data) != transfer["size_bytes"]:
            raise ValueError("Source byte count differs from the prepared transfer")
        source_digests.append({"name": name, "size_bytes": len(data), "sha256": digest(data)})
        print(f"Restored source: {name}", flush=True)
    return source_digests


def assemble():
    source_digests = prepare_sources()
    rows = []
    for name, destination, strip, count in PACKAGES:
        restore_package(name, destination, strip, count, rows)
    for name in SELECTED_SOURCES:
        if name.endswith(".zip"):
            continue
        destination = PurePosixPath("paper" if name.endswith(".pdf") else "legacy/standalone") / name
        data = (CACHE / name).read_bytes()
        write_source(destination, data)
        record(rows, name, "", destination, data)
    if len(rows) != 951 or len({row["path"] for row in rows}) != 951:
        raise ValueError("The complete source import must have 951 distinct destination files")
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    original_readme = (ROOT / "README.md").read_bytes()
    (docs / "README_data_models_snapshot.md").write_bytes(original_readme)
    for row in rows:
        if row["path"] == "README.md":
            row["path"] = "docs/README_data_models_snapshot.md"
    with (docs / "IMPORT_MANIFEST.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    marker = "Scripts can also be run separately as " + chr(96) + "python models/<script>.py" + chr(96) + ".\n"
    readme = original_readme.decode("utf-8")
    if marker not in readme:
        raise ValueError("The saved root README has changed")
    (ROOT / "README.md").write_text(readme.replace(marker, marker + NAVIGATION, 1))
    (docs / "IMPORT_NOTES.md").write_text(
        "# Saved GPR project import\n\n"
        "Imported from the existing research packages on 23 November 2026.\n"
        "The underlying data retain the snapshot dates recorded in the original packages.\n\n"
        "The reorganised project is at the repository root. The complete original\n"
        "English replication is in replication/, the LaTeX source is in paper/latex/,\n"
        "the three article PDFs are in paper/, and all eight earlier projects plus\n"
        "the standalone files are in legacy/.\n\n"
        "IMPORT_MANIFEST.csv records all 951 source files and their SHA-256 digests.\n"
        "README_data_models_snapshot.md preserves the unedited original root README.\n"
        "Identical data retain both original paths; Git deduplicates identical contents.\n\n"
        "The import does not refresh the datasets or rerun the full model search.\n"
        "The existing independent checks are run with python run.py --check.\n"
        "Results and source integrity are recorded in checks/github_import_validation.json.\n"
    )
    CONTEXT.write_text(json.dumps({"rows": rows, "source_archives": source_digests}))
    check_sources(rows)
    print("Assembled and checked all 951 original source files.", flush=True)


def check_sources(rows):
    for row in rows:
        data = (ROOT / row["path"]).read_bytes()
        if len(data) != row["size_bytes"] or digest(data) != row["sha256"]:
            raise ValueError("Source-integrity mismatch: " + row["path"])
    python_files = [ROOT / row["path"] for row in rows if row["path"].endswith(".py")]
    for path in python_files:
        ast.parse(path.read_bytes(), filename=str(path.relative_to(ROOT)))
    if len(python_files) != 74:
        raise ValueError("Unexpected number of source Python files")
    return len(python_files)


def finalize():
    context = json.loads(CONTEXT.read_text())
    validation = json.loads((ROOT / "checks/verification.json").read_text())
    if validation.get("status") != "PASS":
        raise ValueError("The existing independent model checks did not pass")
    with ZipFile(CACHE / PRIMARY) as archive:
        saved = archive.read("gpr-strategic-metals/checks/verification.json")
    (ROOT / "checks/verification.json").write_bytes(saved)
    python_count = check_sources(context["rows"])
    report = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "source_files_checked": len(context["rows"]),
        "source_integrity": "PASS",
        "python_syntax_files_checked": python_count,
        "python_syntax": "PASS",
        "main_check_command": "python run.py --check",
        "main_checks_status": validation["status"],
        "main_checks": validation["checks"],
        "validation_runtime": {
            "python": platform.python_version(),
            **{name: importlib.metadata.version(name) for name in
               ["numpy", "pandas", "scipy", "statsmodels", "openpyxl", "xlrd"]},
        },
        "saved_source_files_preserved": True,
        "full_model_search_rerun": False,
        "new_research_data_downloaded": False,
        "source_packages": context["source_archives"],
    }
    (ROOT / "checks/github_import_validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Independent checks passed and all original source bytes are preserved.", flush=True)


if __name__ == "__main__":
    if sys.argv[1:] == ["--finalize"]:
        finalize()
    elif not sys.argv[1:]:
        assemble()
    else:
        raise SystemExit("Usage: import_gpr.py [--finalize]")
