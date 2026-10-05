"""Public desktop bundle composition and immutable source-manifest checks."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath


EXCLUDED_RUNTIME_PACKAGES = ("torch", "torchaudio", "torchvision", "librosa")
PRIVATE_METADATA_NAMES = {"direct_url.json", "RECORD", "INSTALLER", "REQUESTED"}


def public_bundle_datas(entries):
    """Keep runtime and license data, without installer/source-host metadata."""
    result = []
    for entry in entries:
        parts = PurePosixPath(entry[0]).parts
        if parts[:2] == ("onnxruntime", "datasets"):
            continue
        if any(part == ".DS_Store" or part.startswith("__editable__") for part in parts):
            continue
        distributions = [p for p in parts if p.endswith(".dist-info")]
        if distributions:
            distribution = distributions[0].lower().replace("_", "-")
            if any(distribution.startswith(name.replace("_", "-") + "-")
                   for name in EXCLUDED_RUNTIME_PACKAGES):
                continue
            if parts[-1] in PRIVATE_METADATA_NAMES or "sboms" in parts:
                continue
        result.append(entry)
    return result


def verify_source_manifest(root: Path, manifest: dict) -> dict:
    """Verify the recorded snapshot, returning only public build identity fields."""
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("Unsupported source manifest")
    files = manifest["files"]
    for entry in files:
        relative = PurePosixPath(entry["path"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Source manifest paths must remain inside the snapshot")
        path = root / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_size != entry["bytes"]:
            raise ValueError(f"Source snapshot missing or changed: {relative}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Source snapshot hash mismatch: {relative}")
    tree_hash = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if tree_hash != manifest.get("source_tree_sha256"):
        raise ValueError("Source manifest identity does not match its file list")
    return {key: manifest[key] for key in
            ("schema_version", "candidate_version", "base_commit", "uncommitted", "source_tree_sha256")}
