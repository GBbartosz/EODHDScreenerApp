"""Refresh the whole data pipeline, from the download to the app's cache.

    .venv\\Scripts\\python.exe update_data.py             free prices + rebuild everything
    .venv\\Scripts\\python.exe update_data.py --eodhd     also the paid EODHD download first
    .venv\\Scripts\\python.exe update_data.py --no-download   rebuild from the files on disk
    .venv\\Scripts\\python.exe update_data.py --dry-run   print the steps, run nothing

Steps, each in its own project and with that project's own venv:

1. 0_EODHD_download/1_download_eodhd.py  (only with --eodhd: needs an active subscription)
2. 0_EODHD_download/2_download_free.py   yfinance prices up to yesterday, FRED series
3. 0_EODHD_download/3_build_outputs.py   raw files -> data/3_output
4. copy data/3_output -> 1_FeaturesBuilder/input_data (what used to be done by hand)
5. 1_FeaturesBuilder: features build      input_data -> data/features/v1 (validated)
6. ScreenerApp: screenerapp.cache         the start-up cache for the new build

A step that fails stops the run, so a later step never works on half-updated input.
Restart a running app afterwards: its in-memory caches belong to the old build.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
PROJECTS_DIR = PROJECT_ROOT.parent
DOWNLOAD_DIR = PROJECTS_DIR / "0_EODHD_download"
FEATURES_DIR = PROJECTS_DIR / "1_FeaturesBuilder"

DOWNLOAD_OUTPUT = DOWNLOAD_DIR / "data" / "3_output"
FEATURES_INPUT = FEATURES_DIR / "input_data"


def venv_python(project: Path) -> Path:
    return project / ".venv" / "Scripts" / "python.exe"


def run(title: str, project: Path, args: list[str], dry_run: bool) -> None:
    """Run `python <args>` in `project` with its venv; exit on failure."""
    command = [str(venv_python(project)), *args]
    print(f"\n=== {title}\n    {project}> {' '.join(args)}", flush=True)
    if dry_run:
        return
    start = time.time()
    # Unbuffered, so the child's progress shows as it happens.
    env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    result = subprocess.run(command, cwd=project, env=env)
    if result.returncode != 0:
        sys.exit(f"\n!!! {title} failed (exit code {result.returncode}). Later steps were not run.")
    print(f"=== {title}: done in {time.time() - start:.0f} s", flush=True)


def copy_outputs(dry_run: bool) -> None:
    """data/3_output -> input_data, file by file, each replaced in one move."""
    print(f"\n=== Copy the download outputs\n    {DOWNLOAD_OUTPUT} -> {FEATURES_INPUT}", flush=True)
    files = [p for p in DOWNLOAD_OUTPUT.rglob("*") if p.is_file()]
    if not files:
        sys.exit(f"\n!!! {DOWNLOAD_OUTPUT} is empty. Later steps were not run.")
    if dry_run:
        return
    for source in files:
        target = FEATURES_INPUT / source.relative_to(DOWNLOAD_OUTPUT)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy next to the target first, so an interrupted copy never leaves a half file.
        partial = target.with_name(target.name + ".partial")
        shutil.copy2(source, partial)
        os.replace(partial, target)
    print(f"=== Copied {len(files)} files", flush=True)


def check_projects() -> None:
    missing = [str(p) for p in (venv_python(DOWNLOAD_DIR), venv_python(FEATURES_DIR)) if not p.exists()]
    if missing:
        sys.exit("Missing Python environments:\n  " + "\n  ".join(missing))


def main() -> None:
    parser = argparse.ArgumentParser(description="Download the data, build the features and the app cache.")
    parser.add_argument("--eodhd", action="store_true",
                        help="run the paid EODHD download first (needs an active subscription)")
    parser.add_argument("--no-download", action="store_true",
                        help="skip both downloads, rebuild from the files already on disk")
    parser.add_argument("--dry-run", action="store_true", help="print the steps without running them")
    args = parser.parse_args()
    if args.eodhd and args.no_download:
        parser.error("--eodhd and --no-download exclude each other")

    check_projects()
    start = time.time()
    if args.eodhd:
        run("EODHD download", DOWNLOAD_DIR, ["1_download_eodhd.py"], args.dry_run)
    if not args.no_download:
        run("Free download (yfinance, FRED)", DOWNLOAD_DIR, ["2_download_free.py"], args.dry_run)
    run("Build the download outputs", DOWNLOAD_DIR, ["3_build_outputs.py"], args.dry_run)
    copy_outputs(args.dry_run)
    run("Build the features", FEATURES_DIR, ["-m", "features", "build"], args.dry_run)
    run("Build the app cache", PROJECT_ROOT, ["-m", "screenerapp.cache"], args.dry_run)

    if args.dry_run:
        return
    print(f"\nAll steps done in {(time.time() - start) / 60:.1f} min. Restart the app if it is running.")
    print("Reminder: 0_EODHD_download_summary.md is now out of date (see the !!! box above).")


if __name__ == "__main__":
    main()
