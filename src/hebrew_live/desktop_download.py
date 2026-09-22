"""Pinned, resumable desktop model preparation.

The desktop downloader intentionally does not use Hugging Face's retry stack: the
application owns one finite retry budget and can therefore report a terminal
"paused" state instead of waiting forever inside nested retries.
"""
from __future__ import annotations

from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import time
from typing import Any, Callable, Iterable
import urllib.error
import urllib.parse
import urllib.request

from .desktop_preflight import DOWNLOAD_TEMP_BYTES, RESERVE_BYTES, load_inventory


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
                url = component["url"]
            yield ModelFile(component["key"], component["label"], relative,
                            int(item["bytes"]), item["sha256"], url)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(8 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


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
        remaining += item.bytes - size if 0 < size < item.bytes else item.bytes
    return remaining + DOWNLOAD_TEMP_BYTES + RESERVE_BYTES


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


def download_one(
    models: Path,
    item: ModelFile,
    *,
    cancelled: Callable[[], bool],
    progress: Callable[[int], None],
    opener: Callable[[urllib.request.Request, int], Any] = _open,
) -> int:
    """Download one pinned file and return bytes transferred in this call."""
    target = models / item.relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if file_verified(target, item):
        return 0
    if target.exists():
        try:
            target.unlink()
        except OSError as exc:
            raise _classify_os(exc) from exc
    partial = target.with_name(target.name + ".part")
    partial_size = partial.stat().st_size if partial.is_file() else 0
    if partial_size >= item.bytes:
        partial.replace(partial.with_name(partial.name + ".corrupt"))
        partial_size = 0

    headers = {"User-Agent": "Hebrew-Live-Desktop/0.1"}
    if partial_size:
        headers["Range"] = f"bytes={partial_size}-"
    request = urllib.request.Request(item.url, headers=headers)
    transferred = 0
    try:
        response = opener(request, READ_TIMEOUT_SECONDS)
        status = _response_status(response)
        append = partial_size > 0 and status == 206
        if partial_size and not append:
            partial_size = 0
        mode = "ab" if append else "wb"
        with response, partial.open(mode) as destination:
            while True:
                if cancelled():
                    raise DownloadCancelled()
                block = response.read(CHUNK_BYTES)
                if not block:
                    break
                destination.write(block)
                transferred += len(block)
                progress(len(block))
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
        os.replace(partial, target)
        return transferred
    except DownloadCancelled:
        raise
    except urllib.error.HTTPError as exc:
        raise _classify_http(exc) from exc
    except DesktopDownloadError:
        raise
    except BaseException as exc:
        raise _classify_os(exc) from exc


def write_manifest(models: Path, inventory: dict[str, Any]) -> None:
    from .cli import SPEC

    files = {str(item.relative): item.sha256 for item in iter_model_files(inventory)}
    manifest = {
        "schema_version": 2,
        "assets": [component["key"] for component in inventory["components"]],
        "spec": SPEC,
        "files": files,
    }
    temporary = models / ".manifest.json.tmp"
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, models / "manifest.json")


def prepare_models(
    models: Path,
    *,
    cancelled: Callable[[], bool],
    emit: Callable[[str, dict[str, Any]], None],
    inventory: dict[str, Any] | None = None,
    opener: Callable[[urllib.request.Request, int], Any] = _open,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    inventory = inventory or load_inventory()
    models = models.expanduser().resolve()
    models.mkdir(parents=True, exist_ok=True)
    files = tuple(iter_model_files(inventory))
    verified: set[Path] = set()
    emit("preparation_phase", {"phase": "verifying"})
    for item in files:
        if cancelled():
            raise DownloadCancelled()
        emit("verification_file", {"component": item.component, "file": str(item.relative)})
        if file_verified(models / item.relative, item):
            verified.add(item.relative)

    ensure_free_space(models, files)
    missing_total = 0
    for item in files:
        if item.relative in verified:
            continue
        part = (models / item.relative).with_name(item.relative.name + ".part")
        size = part.stat().st_size if part.is_file() else 0
        missing_total += item.bytes - size if 0 < size < item.bytes else item.bytes
    transferred_total = 0
    started = clock()

    for item in files:
        if item.relative in verified:
            emit("download_file_complete", {
                "component": item.component, "file": str(item.relative), "reused": True,
                "downloaded_bytes": transferred_total, "download_bytes": missing_total,
                "bundle_bytes": inventory["total_bytes"],
            })
            continue
        ensure_free_space(models, files)
        emit("download_file_started", {
            "component": item.component, "label": item.label, "file": str(item.relative),
            "expected_bytes": item.bytes, "downloaded_bytes": transferred_total,
            "download_bytes": missing_total, "bundle_bytes": inventory["total_bytes"],
        })

        def on_progress(delta: int) -> None:
            nonlocal transferred_total
            transferred_total += delta
            elapsed = max(0.001, clock() - started)
            emit("download_progress", {
                "component": item.component, "file": str(item.relative),
                "downloaded_bytes": transferred_total, "download_bytes": missing_total,
                "bundle_bytes": inventory["total_bytes"], "bytes_per_second": int(transferred_total / elapsed),
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
        emit("download_file_complete", {
            "component": item.component, "file": str(item.relative), "reused": False,
            "downloaded_bytes": transferred_total, "download_bytes": missing_total,
            "bundle_bytes": inventory["total_bytes"],
        })

    emit("preparation_phase", {"phase": "verifying"})
    for item in files:
        if not file_verified(models / item.relative, item):
            raise DesktopDownloadError("corrupt_file", f"Model verification failed for {item.relative}.")
    write_manifest(models, inventory)
    from .cli import desktop_model_download_keys, verify
    verify(models, desktop_model_download_keys())
    return {
        "downloaded_bytes": transferred_total,
        "bundle_bytes": inventory["total_bytes"],
        "files": len(files),
    }
