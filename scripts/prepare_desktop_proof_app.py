#!/usr/bin/env python3
"""Copy an unsigned Electron app and pin it to an isolated acceptance-test data root."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-app", type=Path, required=True)
    parser.add_argument("--destination-app", type=Path, required=True)
    parser.add_argument("--data-home", type=Path, required=True)
    options = parser.parse_args()
    source = options.source_app.expanduser().resolve()
    destination = options.destination_app.expanduser().resolve()
    data_home = options.data_home.expanduser().resolve()
    if source.suffix != ".app" or not source.is_dir():
        parser.error("--source-app must name an existing .app bundle")
    if destination.suffix != ".app":
        parser.error("--destination-app must end in .app")
    if destination.exists():
        parser.error("--destination-app must not already exist")
    if data_home.exists() and (not data_home.is_dir() or any(data_home.iterdir())):
        parser.error("--data-home must be absent or empty")
    destination.parent.mkdir(parents=True, exist_ok=True)
    data_home.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination, symlinks=True)
    config = destination / "Contents" / "Resources" / "desktop-launch.json"
    config.write_text(json.dumps({"schema_version": 1, "data_home": str(data_home)}, indent=2) + "\n")
    config.chmod(0o600)
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
