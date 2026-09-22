#!/usr/bin/env python3
"""Clone an existing verified model set into an isolated three-component proof set."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "src" / "hebrew_live"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            value.update(block)
    return value.hexdigest()


def clone_or_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["/bin/cp", "-c", str(source), str(destination)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        shutil.copy2(source, destination)


def prepare(source: Path, destination: Path) -> dict:
    source = source.expanduser().resolve()
    destination = destination.expanduser().resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"source model directory does not exist: {source}")
    if destination.exists():
        raise FileExistsError(f"destination already exists: {destination}")

    inventory = json.loads((PACKAGE / "desktop_models.json").read_text())
    spec = json.loads((PACKAGE / "models.json").read_text())
    destination.mkdir(parents=True)
    files: dict[str, str] = {}
    for component in inventory["components"]:
        folder = component.get("folder")
        for item in component["files"]:
            relative = Path(folder, item["path"]) if folder else Path(item["path"])
            source_file = source / relative
            if not source_file.is_file():
                raise FileNotFoundError(f"required desktop model file is missing: {relative}")
            actual = digest(source_file)
            if source_file.stat().st_size != item["bytes"] or actual != item["sha256"]:
                raise RuntimeError(f"existing model file does not match the pinned desktop inventory: {relative}")
            destination_file = destination / relative
            clone_or_copy(source_file, destination_file)
            if digest(destination_file) != actual:
                raise RuntimeError(f"isolated model copy failed verification: {relative}")
            files[str(relative)] = actual

    assets = [component["key"] for component in inventory["components"]]
    manifest = {
        "schema_version": 2,
        "assets": assets,
        "spec": {key: spec[key] for key in assets},
        "files": files,
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"assets": assets, "files": len(files), "bytes": inventory["total_bytes"], "destination": str(destination)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-models", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.source_models, args.destination), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
