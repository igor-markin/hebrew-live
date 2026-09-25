#!/usr/bin/env python3
"""Reproducibly build the stage-one PyInstaller onedir application."""
from __future__ import annotations

import argparse
import hashlib
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
    parser.add_argument("--bundle-models", type=Path, default=ROOT / "models",
                        help="Verified GigaAM-He and Silero build assets; MiLMMT stays external")
    parser.add_argument("--build-root", type=Path, help="Use a separate PyInstaller work directory")
    parser.add_argument("--dist-root", type=Path, help="Use a separate output directory")
    parser.add_argument("--build-log", type=Path, help="Keep complete PyInstaller output for build diagnosis")
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
    build_root = (args.build_root or BUILD_ROOT).expanduser().resolve()
    dist_root = (args.dist_root or DIST_ROOT).expanduser().resolve()

    if not args.skip_web_build:
        subprocess.run(["npm", "ci"], cwd=FRONTEND, check=True)
        subprocess.run(["npm", "run", "build"], cwd=FRONTEND, check=True)
    elif not (ROOT / "src" / "hebrew_live" / "web" / "live.html").is_file():
        raise SystemExit("The bundled web UI is missing; rerun without --skip-web-build")

    build_root.mkdir(parents=True, exist_ok=True)
    dist_root.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    model_root = checked_path(args.bundle_models)
    inventory = json.loads((ROOT / "src" / "hebrew_live" / "desktop_models.json").read_text())
    hashes: dict[str, str] = {}
    for component in inventory["components"]:
        if component["key"] not in ("fast_asr", "vad"):
            continue
        for item in component["files"]:
            relative = Path(component.get("folder", "")) / item["path"]
            source = model_root / relative
            if not source.is_file() or source.stat().st_size != item["bytes"]:
                raise SystemExit(f"Bundled model missing or wrong size: {relative}")
            with source.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if digest != item["sha256"]:
                raise SystemExit(f"Bundled model checksum mismatch: {relative}")
            hashes[str(relative)] = digest
    if sum(item["bytes"] for part in inventory["components"] for item in part["files"]) != inventory["total_bytes"]:
        raise SystemExit("Bundled model inventory total is inconsistent")
    bundle_manifest = build_root / "manifest.json"
    bundle_manifest.write_text(json.dumps({
        "schema_version": 1,
        "assets": ["fast_asr", "vad"],
        "files": hashes,
    }, indent=2, sort_keys=True) + "\n")
    environment["HEBREW_LIVE_BUNDLE_MODELS"] = str(model_root)
    environment["HEBREW_LIVE_BUNDLE_MANIFEST"] = str(bundle_manifest)
    # PyInstaller --clean otherwise tries to remove the user's global cache,
    # which is outside an isolated build workspace.
    environment["PYINSTALLER_CONFIG_DIR"] = str(build_root / "pyinstaller-config")
    if args.proof_models:
        models = checked_path(args.proof_models)
        home = args.proof_home.expanduser().resolve()
        config = build_root / "desktop-launch.json"
        config.write_text(json.dumps({
            "data_home": str(home),
            "models": str(models),
            "logs": str(home / "logs"),
        }, indent=2) + "\n")
        environment["HEBREW_LIVE_PROOF_CONFIG"] = str(config)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--workpath",
        str(build_root / "work"),
        "--distpath",
        str(dist_root),
        str(SPEC),
    ]
    if args.build_log:
        path = args.build_log.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as output:
            subprocess.run(command, cwd=ROOT, env=environment, check=True,
                           stdout=output, stderr=subprocess.STDOUT)
    else:
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
    app = dist_root / "Hebrew Live.app"
    if not app.is_dir():
        raise SystemExit(f"PyInstaller finished without the expected app: {app}")
    packaged_models = dist_root / "Hebrew Live" / "_internal" / "hebrew_live" / "bundled_models"
    packaged_manifest = packaged_models / "manifest.json"
    if not packaged_manifest.is_file() or json.loads(packaged_manifest.read_text()).get("files") != hashes:
        raise SystemExit("PyInstaller omitted or changed the bundled model manifest")
    for relative, digest in hashes.items():
        packaged_file = packaged_models / relative
        if not packaged_file.is_file():
            raise SystemExit(f"PyInstaller omitted a bundled model: {relative}")
        with packaged_file.open("rb") as stream:
            packaged_digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if packaged_digest != digest:
            raise SystemExit(f"PyInstaller omitted or changed a bundled model: {relative}")
    if (packaged_models / "milmmt-4b-4bit").exists():
        raise SystemExit("MiLMMT must not be included in the application bundle")
    print(app)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
