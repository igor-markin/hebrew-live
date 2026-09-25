"""Versioned JSON control channel used by the Electron desktop shell."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import signal
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

from .desktop_download import DesktopDownloadError, DownloadCancelled, prepare_models, verify_accurate_asr
from .desktop_locations import resolve_model_locations
from .desktop_preflight import accurate_inventory, bundled_models, check_computer, load_inventory


PROTOCOL_VERSION = 1


class ProtocolError(ValueError):
    pass


def parse_message(line: bytes) -> dict[str, Any]:
    if len(line) > 1024 * 1024:
        raise ProtocolError("message_too_large")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("invalid_json") from exc
    if not isinstance(value, dict) or value.get("v") != PROTOCOL_VERSION:
        raise ProtocolError("unsupported_protocol")
    if not isinstance(value.get("id"), str) or not value["id"] or len(value["id"]) > 128:
        raise ProtocolError("invalid_id")
    if not isinstance(value.get("command"), str):
        raise ProtocolError("invalid_command")
    payload = value.get("payload", {})
    if not isinstance(payload, dict):
        raise ProtocolError("invalid_payload")
    value["payload"] = payload
    return value


class ProtocolWriter:
    def __init__(self, descriptor: int = 1):
        self.stream = os.fdopen(os.dup(descriptor), "wb", buffering=0)
        self.lock = threading.Lock()

    def _write(self, value: dict[str, Any]) -> None:
        data = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf8") + b"\n"
        with self.lock:
            self.stream.write(data)

    def event(self, event: str, data: dict[str, Any] | None = None) -> None:
        self._write({"v": PROTOCOL_VERSION, "kind": "event", "event": event, "data": data or {}})

    def response(self, identity: str, result: dict[str, Any] | None = None) -> None:
        self._write({"v": PROTOCOL_VERSION, "kind": "response", "id": identity,
                     "ok": True, "result": result or {}})

    def error(self, identity: str, code: str, message: str) -> None:
        self._write({"v": PROTOCOL_VERSION, "kind": "response", "id": identity,
                     "ok": False, "error": {"code": code, "message": message}})

    def close(self) -> None:
        self.stream.close()


class _WarmupLog:
    def __init__(self, writer: ProtocolWriter):
        self.writer = writer
        self.peak_memory = 0

    def event(self, event: str, **data: Any) -> None:
        if event == "warmup_finished":
            self.peak_memory = int(data.get("peak_memory") or 0)
        if event in ("translation_loaded", "warmup_finished"):
            safe = {key: value for key, value in data.items() if key in ("seconds", "peak_memory")}
            self.writer.event("warmup_progress", {"event": event, **safe})

    def error(self, exc: BaseException) -> None:
        self.writer.event("warmup_error", {"type": type(exc).__name__})


def desktop_asr_backend(models: Path, selected: str = "fast") -> str:
    """Only the two supported desktop modes may reach the worker."""
    if selected not in ("fast", "turbo"):
        raise DesktopDownloadError("unsupported_mode", "Unsupported recognition mode.")
    return selected


def desktop_inventory(models: Path) -> dict[str, Any]:
    """One pinned inventory describes bundled and external desktop assets."""
    return load_inventory()


def warmup_models(models: Path, writer: ProtocolWriter, cancel: threading.Event,
                  backend: str = "fast") -> dict[str, Any]:
    writer.event("preparation_phase", {"phase": "warming"})
    from .cli import VAD
    import numpy as np
    vad = VAD(models / "silero.onnx")
    vad(np.zeros(512, dtype=np.float32))
    if cancel.is_set():
        raise DownloadCancelled()
    from .remote_engine import RemoteEngine
    log = _WarmupLog(writer)
    engine = RemoteEngine(models, log, language="he", direction="he-en",
                          backend=desktop_asr_backend(models, backend),
                          stop=cancel, cancel=cancel)
    try:
        if cancel.is_set():
            engine.interrupt()
            raise DownloadCancelled()
        return {"mlx_peak_bytes": engine.mx.get_peak_memory() or log.peak_memory}
    finally:
        engine.close()


def _source_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "hebrew_live.desktop_entry"]


class DesktopController:
    def __init__(self, data_home: Path, models: Path, writer: ProtocolWriter):
        self.data_home = data_home.expanduser().resolve()
        self.bundled = bundled_models()
        if getattr(sys, "frozen", False) and self.bundled is None:
            raise RuntimeError("The packaged app is missing its bundled models")
        self.locations = resolve_model_locations(self.data_home, models, bundled=self.bundled)
        self.models = self.locations.external
        self.writer = writer
        self.inventory = desktop_inventory(self.models)
        self.cancel_prepare = threading.Event()
        self.prepare_thread: threading.Thread | None = None
        self.backend: subprocess.Popen[bytes] | None = None
        self.backend_url: str | None = None
        self.backend_expected_exit = False
        self.backend_log = None
        self.backend_parent_watch: int | None = None
        self.lock = threading.RLock()
        self.last_preflight: dict[str, Any] | None = None

    @property
    def preparing(self) -> bool:
        return bool(self.prepare_thread and self.prepare_thread.is_alive())

    def preflight(self) -> dict[str, Any]:
        self.writer.event("preflight_phase", {"phase": "checking"})
        result = check_computer(self.models, inventory=self.inventory, bundled_root=self.bundled)
        self.last_preflight = result
        self.writer.event("preflight_complete", result)
        return result

    def accurate_status(self) -> dict[str, Any]:
        optional = next(item for item in accurate_inventory()["components"] if item["key"] == "asr")
        info = {"total_bytes": sum(item["bytes"] for item in optional["files"]),
                "terms_url": optional["terms_url"]}
        try:
            verify_accurate_asr(self.models)
        except DesktopDownloadError:
            return {**info, "ready": False}
        return {**info, "ready": True}

    def start_preparation(self, backend: str = "fast") -> None:
        desktop_asr_backend(self.models, backend)
        with self.lock:
            if self.preparing:
                raise DesktopDownloadError("busy", "Model preparation is already running.")
            if self.backend and self.backend.poll() is None:
                raise DesktopDownloadError("busy", "The live backend is running.")
            self.cancel_prepare = threading.Event()
            self.prepare_thread = threading.Thread(target=self._prepare, args=(backend,),
                                                   name="desktop-model-preparation", daemon=True)
            self.prepare_thread.start()

    def _prepare(self, backend: str) -> None:
        try:
            inventory = accurate_inventory() if backend == "turbo" else self.inventory
            result = prepare_models(
                self.models,
                cancelled=self.cancel_prepare.is_set,
                emit=self.writer.event,
                inventory=inventory,
                bundled_root=self.bundled,
            )
            if backend == "turbo":
                verify_accurate_asr(self.models)
            result.update(warmup_models(self.models, self.writer, self.cancel_prepare, backend))
            if self.cancel_prepare.is_set():
                raise DownloadCancelled()
            self.writer.event("preparation_complete", {**result, "asr_backend": backend})
        except DownloadCancelled:
            self.writer.event("preparation_paused", {"code": "cancelled"})
        except DesktopDownloadError as exc:
            self.writer.event("preparation_paused", {"code": exc.code, "message": str(exc)})
        except BaseException as exc:
            self.writer.event("preparation_failed", {"code": "runtime", "type": type(exc).__name__,
                                                       "message": "Model preparation failed."})

    def save_preferences(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = {key: values[key] for key in ("ui_locale", "target_language", "save_raw_audio") if key in values}
        if set(values) - set(allowed):
            raise ProtocolError("unsupported_preference")
        if allowed.get("ui_locale") not in (None, "en", "ru"):
            raise ProtocolError("unsupported_interface_language")
        from .preferences import save
        folder = self.data_home / ".local-settings"
        self.data_home.mkdir(parents=True, exist_ok=True)
        save(folder, **allowed)
        return self.read_preferences()

    def read_preferences(self) -> dict[str, Any]:
        from .preferences import read
        saved = read(self.data_home / ".local-settings")
        return {key: saved[key] for key in ("ui_locale", "target_language", "save_raw_audio") if key in saved}

    def _backend_event_reader(self, descriptor: int) -> None:
        try:
            with os.fdopen(descriptor, "rb") as stream:
                for line in stream:
                    try:
                        event = json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if event.get("v") != PROTOCOL_VERSION or event.get("event") != "backend_ready":
                        continue
                    url = event.get("url")
                    if isinstance(url, str) and url.startswith("http://127.0.0.1:"):
                        with self.lock:
                            self.backend_url = url
                        self.writer.event("backend_ready", {"url": url})
        finally:
            pass

    def _backend_monitor(self, process: subprocess.Popen[bytes], parent_watch: int) -> None:
        code = process.wait()
        try:
            os.close(parent_watch)
        except OSError:
            pass
        with self.lock:
            expected = self.backend_expected_exit
            self.backend_url = None
            if self.backend is process:
                self.backend = None
            if self.backend_parent_watch == parent_watch:
                self.backend_parent_watch = None
            if self.backend_log is not None:
                self.backend_log.close()
                self.backend_log = None
        self.writer.event("backend_exit", {"code": code, "expected": expected})

    def start_backend(self, backend: str = "fast") -> None:
        desktop_asr_backend(self.models, backend)
        with self.lock:
            if self.preparing:
                raise DesktopDownloadError("busy", "Model preparation is still running.")
            if self.backend and self.backend.poll() is None:
                if self.backend_url:
                    self.writer.event("backend_ready", {"url": self.backend_url})
                return
            from .desktop_download import file_verified, iter_model_files, verify_desktop_external
            verify_desktop_external(self.models, self.inventory)
            if backend == "fast":
                if any(not file_verified((self.bundled or self.models) / item.relative, item)
                       for item in iter_model_files(self.inventory) if item.component == "fast_asr"):
                    raise DesktopDownloadError("corrupt_file", "The fast recognition model must be prepared again.")
            else:
                verify_accurate_asr(self.models)
            desktop_folder = self.data_home / "desktop"
            desktop_folder.mkdir(parents=True, exist_ok=True)
            log_path = desktop_folder / "backend.log"
            descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            self.backend_log = os.fdopen(descriptor, "ab", buffering=0)
            read_fd, write_fd = os.pipe()
            parent_read_fd, parent_write_fd = os.pipe()
            environment = dict(os.environ)
            environment.update({
                "HEBREW_LIVE_HOME": str(self.data_home),
                "HEBREW_LIVE_DESKTOP_MANAGED": "1",
                "HEBREW_LIVE_DESKTOP_EVENT_FD": str(write_fd),
                "HEBREW_LIVE_DESKTOP_PARENT_FD": str(parent_read_fd),
                "HF_HUB_OFFLINE": "1",
                "TRANSFORMERS_OFFLINE": "1",
                "HF_DATASETS_OFFLINE": "1",
                "TOKENIZERS_PARALLELISM": "false",
            })
            command = [*_source_command(), "--models", str(self.models), "--log-dir", str(self.data_home / "logs"),
                       "listen", "--ui", "browser", "--start-paused", "--no-open-browser"]
            command.extend(("--asr-backend", backend))
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=self.backend_log,
                    env=environment,
                    pass_fds=(write_fd, parent_read_fd),
                    close_fds=True,
                    start_new_session=True,
                )
            except BaseException:
                os.close(read_fd);os.close(write_fd)
                os.close(parent_read_fd);os.close(parent_write_fd)
                self.backend_log.close();self.backend_log = None
                raise
            os.close(write_fd)
            os.close(parent_read_fd)
            self.backend = process
            self.backend_parent_watch = parent_write_fd
            self.backend_url = None
            self.backend_expected_exit = False
            threading.Thread(target=self._backend_event_reader, args=(read_fd,), daemon=True,
                             name="desktop-backend-events").start()
            threading.Thread(target=self._backend_monitor, args=(process, parent_write_fd), daemon=True,
                             name="desktop-backend-monitor").start()
            self.writer.event("backend_starting", {"pid": process.pid, "asr_backend": backend})

    def backend_state(self) -> dict[str, Any]:
        with self.lock:
            url = self.backend_url
            process = self.backend
        if process is None or process.poll() is not None:
            return {"running": False}
        if not url:
            return {"running": True, "ready": False}
        try:
            with urllib.request.urlopen(url.removesuffix("live/") + "state", timeout=3) as response:
                state = json.loads(response.read())
        except (OSError, ValueError, urllib.error.URLError):
            return {"running": True, "ready": True, "reachable": False}
        allowed = ("phase", "paused", "finished", "stopping", "cancelling", "status_code",
                   "recording_started", "capture_active")
        return {"running": True, "ready": True, "reachable": True,
                **{key: state.get(key) for key in allowed}}

    def backend_action(self, action: str) -> dict[str, Any]:
        if action not in ("quit", "stop", "cancel_processing"):
            raise ProtocolError("unsupported_backend_action")
        with self.lock:
            url = self.backend_url
            process = self.backend
            if action == "quit":
                self.backend_expected_exit = True
        if process is None or process.poll() is not None:
            return {"running": False}
        if not url:
            raise DesktopDownloadError("backend_starting", "The backend has not published its local URL yet.")
        host = urllib.parse.urlparse(url).netloc
        request = urllib.request.Request(
            url.removesuffix("live/") + "action",
            data=json.dumps({"action": action}).encode("utf8"),
            headers={"Content-Type": "application/json", "Origin": "http://" + host},
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return {"running": True, "status": response.status}
        except urllib.error.HTTPError as exc:
            raise DesktopDownloadError("backend_action", f"The backend rejected {action} (HTTP {exc.code}).") from exc

    def diagnostics(self) -> dict[str, Any]:
        system = (self.last_preflight or {}).get("system", {})
        with self.lock:
            process = self.backend
        return {
            "protocol_version": PROTOCOL_VERSION,
            "python": platform.python_version(),
            "frozen": bool(getattr(sys, "frozen", False)),
            "backend_running": bool(process and process.poll() is None),
            "preparing": self.preparing,
            "system": system,
        }

    def close(self) -> None:
        self.cancel_prepare.set()
        preparation = self.prepare_thread
        if preparation and preparation.is_alive():
            preparation.join(timeout=35)
        with self.lock:
            process = self.backend
            self.backend_expected_exit = True
        if process and process.poll() is None:
            if self.backend_url:
                try:
                    self.backend_action("quit")
                    process.wait(timeout=120)
                    return
                except (DesktopDownloadError, OSError, subprocess.TimeoutExpired):
                    try:self.backend_action("cancel_processing")
                    except (DesktopDownloadError, OSError):pass
                    try:
                        process.wait(timeout=5)
                        return
                    except subprocess.TimeoutExpired:pass
            try:os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:return
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:pass
                process.wait(timeout=5)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--desktop-control", action="store_true", required=True)
    parser.add_argument("--data-home", type=Path, required=True)
    parser.add_argument("--models", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    os.environ["HEBREW_LIVE_HOME"] = str(args.data_home.expanduser().resolve())
    writer = ProtocolWriter()
    controller = DesktopController(args.data_home, args.models, writer)
    reader = os.fdopen(os.dup(0), "rb")
    writer.event("control_ready", {"protocol_version": PROTOCOL_VERSION})
    try:
        for line in reader:
            identity = "unknown"
            try:
                message = parse_message(line)
                identity = message["id"]
                command = message["command"]
                payload = message["payload"]
                if command == "preflight":
                    writer.response(identity, controller.preflight())
                elif command == "inventory":
                    writer.response(identity, controller.inventory)
                elif command == "languages":
                    from .languages import target_language_options
                    writer.response(identity, {"source": "he", "targets": target_language_options()})
                elif command == "prepare":
                    backend = payload.get("asr_backend", "fast")
                    controller.start_preparation(backend);writer.response(identity, {"started": True})
                elif command == "accurate_status":
                    writer.response(identity, controller.accurate_status())
                elif command == "cancel_prepare":
                    controller.cancel_prepare.set();writer.response(identity, {"cancelled": True})
                elif command == "preferences":
                    writer.response(identity, controller.read_preferences())
                elif command == "save_preferences":
                    writer.response(identity, controller.save_preferences(payload))
                elif command == "start_backend":
                    backend = payload.get("asr_backend", "fast")
                    controller.start_backend(backend);writer.response(identity, {"started": True})
                elif command == "backend_state":
                    writer.response(identity, controller.backend_state())
                elif command == "backend_action":
                    writer.response(identity, controller.backend_action(str(payload.get("action", ""))))
                elif command == "diagnostics":
                    writer.response(identity, controller.diagnostics())
                elif command == "shutdown":
                    writer.response(identity, {"shutting_down": True})
                    break
                else:
                    writer.error(identity, "unsupported_command", "The requested desktop command is not supported.")
            except ProtocolError as exc:
                writer.error(identity, str(exc), "Invalid desktop control message.")
            except DesktopDownloadError as exc:
                writer.error(identity, exc.code, str(exc))
            except BaseException as exc:
                writer.error(identity, "runtime", f"Desktop command failed: {type(exc).__name__}")
    finally:
        controller.close();reader.close();writer.close()
    return 0
