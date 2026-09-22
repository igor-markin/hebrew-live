"""Desktop hardware and model-storage checks shared by the future Electron shell."""
from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import asdict, dataclass
import hashlib
import importlib
import json
import os
from pathlib import Path
import platform
import shutil
from typing import Any, Iterable


REFERENCE_MEMORY_BYTES = 16 * 1024**3
RESERVE_BYTES = 2 * 1024**3
DOWNLOAD_TEMP_BYTES = 64 * 1024**2
MINIMUM_MACOS = (26, 2)


@dataclass(frozen=True)
class FileState:
    component: str
    path: str
    expected_bytes: int
    present_bytes: int
    state: str


@dataclass(frozen=True)
class SpacePlan:
    files: tuple[FileState, ...]
    download_bytes: int
    temporary_bytes: int
    reserve_bytes: int
    required_free_bytes: int
    available_bytes: int
    resumable_credit_applied: bool


def load_inventory(path: Path | None = None) -> dict[str, Any]:
    source = path or Path(__file__).with_name("desktop_models.json")
    value = json.loads(source.read_text())
    if value.get("schema_version") != 1 or not isinstance(value.get("components"), list):
        raise ValueError("Unsupported desktop model inventory")
    return value


def _requirements(inventory: dict[str, Any]) -> Iterable[tuple[str, Path, dict[str, Any]]]:
    for component in inventory["components"]:
        folder = component.get("folder")
        for item in component["files"]:
            relative = Path(folder, item["path"]) if folder else Path(item["path"])
            yield component["key"], relative, item


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            value.update(block)
    return value.hexdigest()


def _existing_parent(path: Path) -> Path:
    value = path.expanduser().resolve()
    while not value.exists():
        if value.parent == value:
            raise FileNotFoundError(f"no existing parent for {path}")
        value = value.parent
    return value


def plan_model_space(models: Path, inventory: dict[str, Any] | None = None, *,
                     resumable_confirmed: bool = False, verify_hashes: bool = True,
                     temporary_bytes: int = DOWNLOAD_TEMP_BYTES,
                     reserve_bytes: int = RESERVE_BYTES) -> SpacePlan:
    inventory = inventory or load_inventory()
    models = models.expanduser().resolve()
    states: list[FileState] = []
    download_bytes = 0
    for component, relative, expected in _requirements(inventory):
        target = models / relative
        size = target.stat().st_size if target.is_file() else 0
        verified = size == expected["bytes"] and (not verify_hashes or _digest(target) == expected["sha256"])
        if verified:
            states.append(FileState(component, str(relative), expected["bytes"], size, "verified"))
            continue
        partial = target.with_name(target.name + ".part")
        partial_size = partial.stat().st_size if partial.is_file() else 0
        if 0 < partial_size < expected["bytes"]:
            state = "partial"
            needed = expected["bytes"] - partial_size if resumable_confirmed else expected["bytes"]
            present = partial_size
        else:
            state = "corrupt" if target.is_file() else "missing"
            needed = expected["bytes"]
            present = size
        states.append(FileState(component, str(relative), expected["bytes"], present, state))
        download_bytes += needed
    available = shutil.disk_usage(_existing_parent(models)).free
    required = download_bytes + temporary_bytes + reserve_bytes
    return SpacePlan(tuple(states), download_bytes, temporary_bytes, reserve_bytes, required, available,
                     resumable_confirmed)


def _version(value: str) -> tuple[int, ...]:
    result = []
    for part in value.split("."):
        digits = "".join(character for character in part if character.isdigit())
        if not digits:
            break
        result.append(int(digits))
    return tuple(result)


def _sysctl_uint64(name: str) -> int | None:
    library_name = ctypes.util.find_library("c")
    if not library_name:
        return None
    library = ctypes.CDLL(library_name)
    size = ctypes.c_size_t(ctypes.sizeof(ctypes.c_uint64))
    value = ctypes.c_uint64()
    if library.sysctlbyname(name.encode(), ctypes.byref(value), ctypes.byref(size), None, 0):
        return None
    return value.value


def _memory_pressure_level() -> int | None:
    library_name = ctypes.util.find_library("c")
    if not library_name:
        return None
    library = ctypes.CDLL(library_name)
    size = ctypes.c_size_t(ctypes.sizeof(ctypes.c_int))
    value = ctypes.c_int()
    if library.sysctlbyname(b"kern.memorystatus_vm_pressure_level", ctypes.byref(value), ctypes.byref(size), None, 0):
        return None
    return value.value


def metal_available() -> bool:
    try:
        mx = importlib.import_module("mlx.core")
        if not mx.metal.is_available():
            return False
        mx.set_default_device(mx.gpu)
        value = mx.array([0], dtype=mx.int32)
        mx.eval(value)
        return True
    except Exception:
        return False


def check_computer(models: Path, *, inventory: dict[str, Any] | None = None,
                   verify_hashes: bool = True) -> dict[str, Any]:
    system = platform.system()
    machine = platform.machine()
    macos = platform.mac_ver()[0]
    memory = _sysctl_uint64("hw.memsize")
    pressure = _memory_pressure_level()
    logical_cpus = os.cpu_count() or 1
    load = os.getloadavg()[0]
    high_load = load >= logical_cpus * 0.75 or pressure in (2, 4)
    metal = metal_available() if system == "Darwin" and machine == "arm64" else False
    space = plan_model_space(models, inventory, verify_hashes=verify_hashes)
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    if system != "Darwin" or machine != "arm64":
        blockers.append({"code": "unsupported_architecture", "message": "Hebrew Live requires native Apple Silicon macOS."})
    if system == "Darwin" and _version(macos) < MINIMUM_MACOS:
        blockers.append({"code": "unsupported_macos", "message": "This build requires macOS 26.2 or later because of its pinned MLX binaries."})
    if not metal:
        blockers.append({"code": "metal_unavailable", "message": "MLX could not use Apple Metal."})
    if space.available_bytes < space.required_free_bytes:
        blockers.append({"code": "disk_space", "message": "The target disk does not have enough free space for models, temporary data, and the 2 GiB reserve."})
    if memory is not None and memory < REFERENCE_MEMORY_BYTES:
        warnings.append({"code": "memory_below_reference", "message": "16 GiB is the tested reference, not a proven minimum. Continue only by explicit choice."})
    if high_load:
        warnings.append({"code": "current_load_high", "message": "Current memory pressure or CPU load is high. Close other applications and check again."})
    return {
        "schema_version": 1,
        "compatible": not blockers,
        "system": {
            "macos": macos,
            "machine": machine,
            "memory_bytes": memory,
            "memory_reference_bytes": REFERENCE_MEMORY_BYTES,
            "memory_pressure_level": pressure,
            "load_average_1m": load,
            "logical_cpu_count": logical_cpus,
            "high_current_load": high_load,
            "metal_available": metal,
            "minimum_macos": ".".join(map(str, MINIMUM_MACOS)),
        },
        "storage": {**asdict(space), "files": [asdict(item) for item in space.files]},
        "blockers": blockers,
        "warnings": warnings,
    }
