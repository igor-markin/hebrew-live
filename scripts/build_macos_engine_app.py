#!/usr/bin/env python3
"""Reproducibly build the stage-one PyInstaller onedir application."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "experiments" / "publication-ui-preview"
SPEC = ROOT / "desktop" / "engine" / "HebrewLive.spec"
BUILD_ROOT = ROOT / "build" / "desktop-engine"
DIST_ROOT = ROOT / "dist" / "desktop-engine"


def checked_path(value: Path, *, directory: bool = True) -> Path:
    path = value.expanduser().resolve()
    if directory and not path.is_dir():
        raise argparse.ArgumentTypeError(f"directory does not exist: {path}")
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-web-build", action="store_true", help="Use the already generated bundled web UI")
    parser.add_argument("--proof-models", type=Path, help="Embed a local stage-one model path (never copies model files)")
    parser.add_argument("--proof-home", type=Path, help="Embed an isolated stage-one data root for settings and recordings")
    args = parser.parse_args()
    if bool(args.proof_models) != bool(args.proof_home):
        parser.error("--proof-models and --proof-home must be provided together")
    return args


def main() -> int:
    args = parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("The engine app must be built natively on Apple Silicon macOS")
    if sys.version_info[:2] != (3, 12):
        raise SystemExit(f"The engine app requires Python 3.12; got {platform.python_version()}")

    if not args.skip_web_build:
        subprocess.run(["npm", "ci"], cwd=FRONTEND, check=True)
        subprocess.run(["npm", "run", "build"], cwd=FRONTEND, check=True)
    elif not (ROOT / "src" / "hebrew_live" / "web" / "live.html").is_file():
        raise SystemExit("The bundled web UI is missing; rerun without --skip-web-build")

    BUILD_ROOT.mkdir(parents=True, exist_ok=True)
    DIST_ROOT.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    if args.proof_models:
        models = checked_path(args.proof_models)
        home = args.proof_home.expanduser().resolve()
        config = BUILD_ROOT / "desktop-launch.json"
        config.write_text(json.dumps({
            "data_home": str(home),
            "models": str(models),
            "logs": str(home / "logs"),
        }, indent=2) + "\n")
        environment["HEBREW_LIVE_PROOF_CONFIG"] = str(config)

    subprocess.run([
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(BUILD_ROOT / "work"),
        "--distpath",
        str(DIST_ROOT),
        str(SPEC),
    ], cwd=ROOT, env=environment, check=True)
    app = DIST_ROOT / "Hebrew Live.app"
    if not app.is_dir():
        raise SystemExit(f"PyInstaller finished without the expected app: {app}")
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
