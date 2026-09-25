"""Pinned, resumable desktop model preparation.

The desktop downloader intentionally does not use Hugging Face's retry stack: the
application owns one finite retry budget and can therefore report a terminal
"paused" state instead of waiting forever inside nested retries.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import time
from typing import Any, Callable, Iterable
import urllib.error
import urllib.parse
import urllib.request

from .desktop_preflight import DOWNLOAD_TEMP_BYTES, RESERVE_BYTES, load_inventory
from .model_store import atomic_json, file_digest, preparation_lock


CHUNK_BYTES = 1024 * 1024
READ_TIMEOUT_SECONDS = 30
RETRY_DELAYS_SECONDS = (2, 5, 15)


class DesktopDownloadError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class DownloadCancelled(DesktopDownloadError):
    def __init__(self):
        super().__init__("cancelled", "Model preparation was cancelled.")


@dataclass(frozen=True)
class ModelFile:
    component: str
    label: str
    relative: Path
    bytes: int
    sha256: str
    url: str


def iter_model_files(inventory: dict[str, Any] | None = None) -> Iterable[ModelFile]:
    inventory = inventory or load_inventory()
    for component in inventory["components"]:
        folder = component.get("folder")
        for item in component["files"]:
            relative = Path(folder, item["path"]) if folder else Path(item["path"])
            if component.get("repo"):
                quoted_path = "/".join(urllib.parse.quote(part, safe="") for part in Path(item["path"]).parts)
                url = (f"https://huggingface.co/{component['repo']}/resolve/"
                       f"{component['revision']}/{quoted_path}?download=true")
            else:
                url = item.get("url") or component.get("url", "")
            yield ModelFile(component["key"], component["label"], relative,
                            int(item["bytes"]), item["sha256"], url)


def file_verified(path: Path, item: ModelFile) -> bool:
    return path.is_file() and path.stat().st_size == item.bytes and file_digest(path) == item.sha256


def _existing_parent(path: Path) -> Path:
    current = path.expanduser().resolve()
    while not current.exists():
        if current.parent == current:
            raise FileNotFoundError(path)
        current = current.parent
    return current


def _space_required(models: Path, files: Iterable[ModelFile]) -> int:
    remaining = 0
    for item in files:
        target = models / item.relative
        if file_verified(target, item):
            continue
        partial = target.with_name(target.name + ".part")
        size = partial.stat().st_size if partial.is_file() else 0
        if size == item.bytes and file_digest(partial) == item.sha256:
            continue
        remaining += item.bytes - size if 0 < size < item.bytes else item.bytes
    return remaining + DOWNLOAD_TEMP_BYTES + RESERVE_BYTES if remaining else 0


def ensure_free_space(models: Path, files: Iterable[ModelFile]) -> None:
    required = _space_required(models, files)
    available = shutil.disk_usage(_existing_parent(models)).free
    if available < required:
        raise DesktopDownloadError(
            "disk_space",
            "The target disk does not have enough free space for the remaining files, temporary data, and the 2 GiB reserve.",
        )


def _response_status(response: Any) -> int:
    value = getattr(response, "status", None)
    if value is None and hasattr(response, "getcode"):
        value = response.getcode()
    return int(value or 200)


def _content_range(response: Any) -> tuple[int, int, int] | None:
    headers = getattr(response, "headers", None)
    value = headers.get("Content-Range") if headers is not None else None
    if value is None and hasattr(response, "getheader"):
        value = response.getheader("Content-Range")
    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", value or "")
    return tuple(map(int, match.groups())) if match else None


def _classify_http(error: urllib.error.HTTPError) -> DesktopDownloadError:
    if error.code in (401, 403):
        return DesktopDownloadError("access_denied", "The model server refused access to a pinned file.")
    if error.code == 404:
        return DesktopDownloadError("file_unavailable", "A pinned model file is no longer available at its expected revision.")
    if error.code in (408, 429) or 500 <= error.code <= 599:
        return DesktopDownloadError("network", f"Temporary model server error (HTTP {error.code}).", retryable=True)
    return DesktopDownloadError("network", f"Model download failed (HTTP {error.code}).")


def _classify_os(error: BaseException) -> DesktopDownloadError:
    if isinstance(error, PermissionError):
        return DesktopDownloadError("permission_denied", "Hebrew Live cannot write to the selected model folder.")
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return DesktopDownloadError("disk_full", "The disk became full while downloading models.")
    if isinstance(error, (TimeoutError, socket.timeout, ConnectionError, urllib.error.URLError)):
        return DesktopDownloadError("network", "The model download stopped making progress.", retryable=True)
    if isinstance(error, OSError):
        return DesktopDownloadError("filesystem", "A filesystem error interrupted model preparation.")
    return DesktopDownloadError("network", "A temporary network error interrupted model preparation.", retryable=True)


def _open(request: urllib.request.Request, timeout: int):
    return urllib.request.urlopen(request, timeout=timeout)


def _activate_download(partial: Path, target: Path, item: ModelFile) -> None:
    # An optional CLI ASR file may belong to an earlier setup. Keep its bytes
    # intact until a replacement has passed the pinned checksum.
    if item.component == "asr" and target.exists():
        preserved = target.with_name(f"{target.name}.previous-invalid-{time.time_ns()}")
        os.replace(target, preserved)
    os.replace(partial, target)


def download_one(
    models: Path,
    item: ModelFile,
    *,
    cancelled: Callable[[], bool],
    progress: Callable[[int], None],
    opener: Callable[[urllib.request.Request, int], Any] = _open,
) -> int:
    """Download one pinned file and return bytes transferred in this call."""
    if not item.url:
        raise DesktopDownloadError("bundled_only", "This model is supplied by the application bundle.")
    target = models / item.relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if file_verified(target, item):
        return 0
    if target.exists() and item.component != "asr":
        try:
            target.unlink()
        except OSError as exc:
            raise _classify_os(exc) from exc
    partial = target.with_name(target.name + ".part")
    partial_size = partial.stat().st_size if partial.is_file() else 0
    if partial_size == item.bytes and file_digest(partial) == item.sha256:
        _activate_download(partial, target, item)
        return 0
    if partial_size >= item.bytes:
        partial.replace(partial.with_name(partial.name + ".corrupt"))
        partial_size = 0

    transferred = 0
    try:
        for restart in range(2):
            headers = {"User-Agent": "Hebrew-Live-Desktop/0.1"}
            if partial_size:
                headers["Range"] = f"bytes={partial_size}-"
            request = urllib.request.Request(item.url, headers=headers)
            try:
                response = opener(request, READ_TIMEOUT_SECONDS)
            except urllib.error.HTTPError as exc:
                if exc.code == 416 and partial_size and restart == 0:
                    partial.unlink()
                    partial_size = 0
                    continue
                raise
            with response:
                status = _response_status(response)
                if status == 416 and partial_size and restart == 0:
                    partial.unlink()
                    partial_size = 0
                    continue
                if status == 206:
                    content_range = _content_range(response)
                    if (content_range is None or content_range[0] != partial_size
                            or content_range[1] < content_range[0]
                            or content_range[1] >= item.bytes
                            or content_range[2] != item.bytes):
                        if partial_size and restart == 0:
                            partial.unlink()
                            partial_size = 0
                            continue
                        raise DesktopDownloadError("invalid_range", "The model server returned an invalid Content-Range.")
                elif status != 200:
                    raise DesktopDownloadError("network", f"Unexpected model server response (HTTP {status}).")
                mode = "ab" if status == 206 and partial_size else "wb"
                with partial.open(mode) as destination:
                    while True:
                        if cancelled():
                            raise DownloadCancelled()
                        block = response.read(CHUNK_BYTES)
                        if not block:
                            break
                        destination.write(block)
                        destination.flush()
                        transferred += len(block)
                        progress(len(block))
                    destination.flush()
                    os.fsync(destination.fileno())
            break
        actual = partial.stat().st_size if partial.is_file() else 0
        if actual != item.bytes:
            raise DesktopDownloadError(
                "network", f"The server ended {item.relative} before all bytes arrived.", retryable=True
            )
        if file_digest(partial) != item.sha256:
            partial.replace(partial.with_name(partial.name + ".corrupt"))
            raise DesktopDownloadError(
                "corrupt_download", f"The checksum for {item.relative} does not match the pinned inventory."
            )
        _activate_download(partial, target, item)
        return transferred
    except DownloadCancelled:
        raise
    except urllib.error.HTTPError as exc:
        raise _classify_http(exc) from exc
    except DesktopDownloadError:
        raise
    except BaseException as exc:
        raise _classify_os(exc) from exc


def _valid_manifest_entry(models: Path, name: str, digest: str) -> bool:
    if not isinstance(name, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        return False
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        return False
    path = models / relative
    if not path.resolve().is_relative_to(models.resolve()):
        return False
    return path.is_file() and not path.is_symlink() and file_digest(path) == digest


def write_manifest(models: Path, inventory: dict[str, Any]) -> None:
    """Merge verified CLI records with required desktop records.

    Callers hold ``preparation_lock`` while inspecting files and committing.
    """
    from .cli import SPEC, manifest_assets, required_model_files

    desktop_items = [item for item in iter_model_files(inventory)
                     if item.component in ("translation", "vad", "asr")]
    if any(not file_verified(models / item.relative, item) for item in desktop_items):
        raise DesktopDownloadError("corrupt_file", "A required model file failed verification.")
    desktop_files = {str(item.relative): item.sha256 for item in desktop_items}
    files = dict(desktop_files)
    assets = ["translation", "vad"]
    if any(item.component == "asr" for item in iter_model_files(inventory)):
        assets.append("asr")
    previous_path = models / "manifest.json"
    if previous_path.exists():
        try:
            previous = json.loads(previous_path.read_text())
            declared, legacy = manifest_assets(previous)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise DesktopDownloadError("incompatible_cache", "The shared model manifest is incompatible.") from exc
        previous_files = previous.get("files")
        if not isinstance(previous_files, dict):
            raise DesktopDownloadError("incompatible_cache", "The shared model manifest is invalid.")
        previous_assets = ("asr", "translation", "vad") if legacy else previous["assets"]
        for asset in previous_assets:
            if asset in assets or asset not in (*SPEC, "fast_asr"):
                continue
            folder = "fast-asr" if asset == "fast_asr" else SPEC[asset].get("folder", asset)
            entries = {name: digest for name, digest in previous_files.items()
                       if isinstance(name, str) and name.startswith(folder + "/")}
            if not entries or any(not _valid_manifest_entry(models, name, digest)
                                  for name, digest in entries.items()):
                continue
            if asset == "fast_asr":
                pinned = json.loads(Path(__file__).with_name("fast_asr_manifest.json").read_text())["files"]
                if any(entries.get("fast-asr/" + name) != item["sha256"]
                       for name, item in pinned.items()):
                    continue
            else:
                exact, alternatives = required_model_files(asset)
                if not exact.issubset(entries) or (alternatives and not any(name in entries for name in alternatives)):
                    continue
            files.update(entries)
            assets.append(asset)
    atomic_json(previous_path, {"schema_version": 2, "assets": assets, "spec": SPEC, "files": files})


def verify_accurate_asr(models: Path) -> None:
    """Verify the optional pinned Whisper files without inspecting unrelated CLI assets."""
    from .cli import manifest_assets
    from .desktop_preflight import accurate_inventory

    try:
        manifest = json.loads((models / "manifest.json").read_text())
        declared, _legacy = manifest_assets(manifest)
        hashes = manifest["files"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise DesktopDownloadError("accurate_model_missing", "Accurate recognition needs model preparation.") from exc
    if "asr" not in declared or not isinstance(hashes, dict):
        raise DesktopDownloadError("accurate_model_missing", "Accurate recognition needs model preparation.")
    for item in iter_model_files(accurate_inventory()):
        if item.component == "asr" and (
            hashes.get(str(item.relative)) != item.sha256 or not file_verified(models / item.relative, item)
        ):
            raise DesktopDownloadError("accurate_model_missing", "Accurate recognition needs model preparation.")


def verify_desktop_external(models: Path, inventory: dict[str, Any]) -> None:
    """Check only required desktop files, against the pinned inventory."""
    from .cli import manifest_assets

    try:
        manifest = json.loads((models / "manifest.json").read_text())
        declared, _legacy = manifest_assets(manifest)
        hashes = manifest["files"]
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise DesktopDownloadError("corrupt_file", "The desktop model manifest is missing or invalid.") from exc
    if not {"translation", "vad"}.issubset(declared) or not isinstance(hashes, dict):
        raise DesktopDownloadError("corrupt_file", "The desktop model manifest is incomplete.")
    for item in iter_model_files(inventory):
        if item.component not in ("translation", "vad"):
            continue
        if hashes.get(str(item.relative)) != item.sha256 or not file_verified(models / item.relative, item):
            raise DesktopDownloadError("corrupt_file", f"Model verification failed for {item.relative}.")


def copy_bundled_vad(models: Path, bundled: Path, item: ModelFile) -> None:
    source = bundled / item.relative
    if not file_verified(source, item):
        raise DesktopDownloadError("corrupt_bundle", "The bundled voice detector failed verification.")
    target = models / item.relative
    if file_verified(target, item):
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".copy", dir=target.parent)
    try:
        with source.open("rb") as origin, os.fdopen(descriptor, "wb") as destination:
            shutil.copyfileobj(origin, destination, CHUNK_BYTES)
            destination.flush()
            os.fsync(destination.fileno())
        temporary = Path(name)
        if not file_verified(temporary, item):
            raise DesktopDownloadError("corrupt_file", "The voice detector copy failed verification.")
        os.replace(temporary, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def prepare_models(
    models: Path,
    *,
    cancelled: Callable[[], bool],
    emit: Callable[[str, dict[str, Any]], None],
    inventory: dict[str, Any] | None = None,
    bundled_root: Path | None = None,
    opener: Callable[[urllib.request.Request, int], Any] = _open,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    inventory = inventory or load_inventory()
    models = models.expanduser().resolve()
    try:
        with preparation_lock(models, cancelled):
            return _prepare_models_locked(models, inventory, bundled_root, cancelled, emit, opener, sleep, clock)
    except InterruptedError as exc:
        raise DownloadCancelled() from exc


def _prepare_models_locked(
    models: Path,
    inventory: dict[str, Any],
    bundled_root: Path | None,
    cancelled: Callable[[], bool],
    emit: Callable[[str, dict[str, Any]], None],
    opener: Callable[[urllib.request.Request, int], Any],
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> dict[str, Any]:
    files = tuple(iter_model_files(inventory))
    bundled = tuple(item for item in files if bundled_root is not None
                    and item.component in ("fast_asr", "vad"))
    downloads = tuple(item for item in files if item not in bundled)
    verified: set[Path] = set()
    emit("preparation_phase", {"phase": "verifying"})
    for item in bundled:
        if cancelled():
            raise DownloadCancelled()
        emit("verification_file", {"component": item.component, "file": str(item.relative)})
        if not file_verified(bundled_root / item.relative, item):
            raise DesktopDownloadError("corrupt_bundle", "A bundled model file failed verification.")
    for item in downloads:
        if cancelled():
            raise DownloadCancelled()
        emit("verification_file", {"component": item.component, "file": str(item.relative)})
        if file_verified(models / item.relative, item):
            verified.add(item.relative)

    vad_copy = next((item for item in bundled if item.component == "vad"), None)
    ensure_free_space(models, (*downloads, *((vad_copy,) if vad_copy else ())))
    if vad_copy is not None:
        try:
            copy_bundled_vad(models, bundled_root, vad_copy)
        except OSError as exc:
            raise _classify_os(exc) from exc
    missing_total = 0
    for item in downloads:
        if item.relative in verified:
            continue
        part = (models / item.relative).with_name(item.relative.name + ".part")
        size = part.stat().st_size if part.is_file() else 0
        if size == item.bytes and file_digest(part) == item.sha256:
            continue
        missing_total += item.bytes - size if 0 < size < item.bytes else item.bytes
    transferred_total = 0
    started = clock()
    total_bytes = sum(item.bytes for item in downloads)

    def progress_data(item: ModelFile) -> dict[str, int]:
        part = (models / item.relative).with_name(item.relative.name + ".part")
        staged = min(item.bytes, part.stat().st_size) if part.is_file() else 0
        return {"transferred_bytes": transferred_total,
                "staged_bytes": staged,
                "verified_bytes": sum(file.bytes for file in downloads if file.relative in verified),
                "total_bytes": total_bytes,
                "downloaded_bytes": transferred_total, "download_bytes": missing_total,
                "bundle_bytes": inventory["total_bytes"]}

    for item in downloads:
        if item.relative in verified:
            emit("download_file_complete", {
                "component": item.component, "file": str(item.relative), "reused": True,
                **progress_data(item),
            })
            continue
        ensure_free_space(models, downloads)
        emit("download_file_started", {
            "component": item.component, "label": item.label, "file": str(item.relative),
            "expected_bytes": item.bytes, **progress_data(item),
        })

        def on_progress(delta: int) -> None:
            nonlocal transferred_total
            transferred_total += delta
            elapsed = max(0.001, clock() - started)
            emit("download_progress", {
                "component": item.component, "file": str(item.relative),
                **progress_data(item), "bytes_per_second": int(transferred_total / elapsed),
            })

        for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
            try:
                download_one(models, item, cancelled=cancelled, progress=on_progress, opener=opener)
                break
            except DesktopDownloadError as exc:
                if isinstance(exc, DownloadCancelled):
                    raise
                if not exc.retryable or attempt >= len(RETRY_DELAYS_SECONDS):
                    if exc.retryable:
                        raise DesktopDownloadError("network_exhausted", str(exc)) from exc
                    raise
                delay = RETRY_DELAYS_SECONDS[attempt]
                emit("download_retry", {
                    "component": item.component, "file": str(item.relative),
                    "attempt": attempt + 1, "delay_seconds": delay,
                })
                deadline = clock() + delay
                while clock() < deadline:
                    if cancelled():
                        raise DownloadCancelled()
                    sleep(min(0.1, max(0.0, deadline - clock())))
        verified.add(item.relative)
        emit("download_file_complete", {
            "component": item.component, "file": str(item.relative), "reused": False,
            **progress_data(item),
        })

    emit("preparation_phase", {"phase": "verifying"})
    for item in downloads:
        if not file_verified(models / item.relative, item):
            raise DesktopDownloadError("corrupt_file", f"Model verification failed for {item.relative}.")
    write_manifest(models, inventory)
    verify_desktop_external(models, inventory)
    return {
        "downloaded_bytes": transferred_total, "transferred_bytes": transferred_total,
        "bundle_bytes": inventory["total_bytes"],
        "files": len(files),
    }
