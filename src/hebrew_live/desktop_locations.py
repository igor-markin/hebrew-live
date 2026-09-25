"""One model-location decision for desktop preflight, warmup and runtime."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .desktop_preflight import bundled_models
from .model_store import atomic_json


@dataclass(frozen=True)
class ModelLocations:
    bundled: Path | None
    external: Path

    @property
    def fast_asr(self) -> Path:
        return self.bundled or self.external

    @property
    def vad_source(self) -> Path:
        return (self.bundled or self.external) / "silero.onnx"


def _compatible_shared_root(root: Path, *, resume_desktop_partial: bool = False) -> bool:
    manifest = root / "manifest.json"
    if not manifest.exists():
        # A pre-existing CLI model directory without its manifest is not ours
        # to overwrite. An empty directory (or interrupted desktop download) is.
        reserved = ("asr", "asr-multilingual")
        if any((root / name).exists() for name in reserved):
            return False
        return resume_desktop_partial or not (root / "milmmt-4b-4bit").exists()
    try:
        from .cli import manifest_assets
        manifest_assets(json.loads(manifest.read_text()))
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return True


def resolve_model_locations(data_home: Path, shared: Path, *,
                            bundled: Path | None = None) -> ModelLocations:
    data_home = data_home.expanduser().resolve()
    shared = shared.expanduser().resolve()
    fallback = data_home / "desktop" / "models"
    preference = data_home / "desktop" / "model-location.json"
    choice = None
    saved = None
    try:
        saved = json.loads(preference.read_text())
        if isinstance(saved, dict) and saved.get("schema_version") == 1 and saved.get("shared") == str(shared):
            choice = saved.get("choice")
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    if choice not in ("shared", "fallback"):
        choice = "shared" if _compatible_shared_root(shared) else "fallback"
    elif choice == "shared" and not _compatible_shared_root(shared, resume_desktop_partial=True):
        choice = "fallback"
    external = shared if choice == "shared" else fallback
    record = {"schema_version": 1, "shared": str(shared), "choice": choice}
    if saved != record:
        atomic_json(preference, record)
    return ModelLocations(bundled if bundled is not None else bundled_models(), external)
