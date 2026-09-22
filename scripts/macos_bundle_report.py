#!/usr/bin/env python3
"""Report deployment targets and native contents of a built macOS app."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import struct

from macholib.MachO import MachO
from macholib.mach_o import LC_BUILD_VERSION, LC_VERSION_MIN_MACOSX


def decoded_version(value: int) -> str:
    return f"{value >> 16}.{(value >> 8) & 0xff}.{value & 0xff}"


def inspect(app: Path) -> dict:
    app = app.expanduser().resolve()
    if not app.is_dir() or app.suffix != ".app":
        raise FileNotFoundError(f"macOS app bundle does not exist: {app}")
    bundle_entries = [item for item in app.rglob("*") if item.is_file() or item.is_symlink()]
    logical_bytes = sum(item.lstat().st_size for item in bundle_entries)
    targets: dict[str, list[str]] = {}
    native_files = 0
    for path in sorted(item for item in bundle_entries if item.is_file() and not item.is_symlink()):
        try:
            headers = MachO(str(path)).headers
        except (ValueError, OSError, struct.error):
            continue
        native_files += 1
        versions: set[str] = set()
        for header in headers:
            for load_command, command, _data in header.commands:
                if load_command.cmd == LC_BUILD_VERSION:
                    versions.add(decoded_version(command.minos))
                elif load_command.cmd == LC_VERSION_MIN_MACOSX:
                    versions.add(decoded_version(command.version))
        for version in versions:
            targets.setdefault(version, []).append(str(path.relative_to(app)))
    ordered = sorted(targets, key=lambda value: tuple(int(part) for part in value.split(".")))
    return {
        "app": str(app),
        "bundle_entries": len(bundle_entries),
        "logical_bytes": logical_bytes,
        "native_files": native_files,
        "minimum_macos_required_by_any_binary": ordered[-1] if ordered else None,
        "deployment_targets": {key: len(targets[key]) for key in ordered},
        "highest_target_examples": targets[ordered[-1]][:12] if ordered else [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.app), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
