"""Finder-facing launcher for the stage-one bundled Python engine."""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
import traceback
from collections.abc import Callable


def _bundled_launch_config() -> dict[str, str]:
    """Read an optional local proof configuration embedded at build time."""
    path = Path(__file__).with_name("desktop-launch.json")
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError, TypeError) as exc:
        raise RuntimeError("The bundled desktop launch configuration is unreadable") from exc
    if not isinstance(value, dict) or any(not isinstance(key, str) or not isinstance(item, str) for key, item in value.items()):
        raise RuntimeError("The bundled desktop launch configuration is invalid")
    return value


def desktop_arguments(config: dict[str, str] | None = None) -> list[str]:
    config = config if config is not None else _bundled_launch_config()
    home = Path(config.get("data_home") or os.environ.get("HEBREW_LIVE_HOME") or
                Path.home() / "Library" / "Application Support" / "Hebrew Live CLI").expanduser().resolve()
    from .desktop_preflight import bundled_models
    packaged = bundled_models()
    if getattr(sys, "frozen", False) and packaged is None:
        raise RuntimeError("The packaged app is missing its bundled models")
    if config.get("models"):
        models = Path(config["models"]).expanduser().resolve()
    else:
        from .desktop_locations import resolve_model_locations
        models = resolve_model_locations(home, home / "models", bundled=packaged).external
    logs = Path(config.get("logs") or home / "logs").expanduser().resolve()
    os.environ["HEBREW_LIVE_HOME"] = str(home)
    if packaged and not config.get("models"):
        os.environ["HEBREW_LIVE_DESKTOP_MANAGED"] = "1"
    result = ["--models", str(models), "--log-dir", str(logs), "listen", "--ui", "browser", "--start-paused"]
    if packaged and not config.get("models"):
        result += ["--asr-backend", "fast"]
    return result


def _bootstrap_event(event: str, **data) -> None:
    """Append a privacy-filtered desktop bootstrap event with owner-only access."""
    home = Path(os.environ["HEBREW_LIVE_HOME"])
    home.mkdir(parents=True, exist_ok=True)
    path = home / "desktop-bootstrap.jsonl"
    record = dict(event=event, timestamp=round(time.time(), 3), **data)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf8") as destination:
        destination.write(json.dumps(record, ensure_ascii=False) + "\n")


def _terminate_desktop_process_group() -> None:
    """Stop the managed backend and every spawned inference/audio child."""
    try:
        os.killpg(os.getpgrp(), signal.SIGTERM)
    except ProcessLookupError:
        pass


def _start_parent_watchdog(descriptor: int, on_disconnect: Callable[[], None]) -> threading.Thread:
    """Run *on_disconnect* when the Electron controller side of a pipe closes."""
    def watch() -> None:
        try:
            while os.read(descriptor, 1):
                pass
        except OSError:
            pass
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
        on_disconnect()

    thread = threading.Thread(target=watch, daemon=True, name="desktop-parent-watchdog")
    thread.start()
    return thread


def _install_parent_watchdog() -> None:
    raw = os.environ.pop("HEBREW_LIVE_DESKTOP_PARENT_FD", None)
    if raw is None:
        return
    try:
        descriptor = int(raw)
    except ValueError as exc:
        raise RuntimeError("Invalid desktop parent watchdog descriptor") from exc
    _start_parent_watchdog(descriptor, _terminate_desktop_process_group)


def main() -> int:
    _install_parent_watchdog()
    # Arguments supplied directly to the executable are useful for a packaged
    # `doctor` probe. Finder launches have no CLI arguments and use desktop mode.
    if len(sys.argv) == 1:
        sys.argv[:] = [sys.argv[0], *desktop_arguments()]
        # PortAudio may ask for TCC permission from its source thread. A UI-less
        # Finder launch has no app event loop there, so make the one-time system
        # request explicitly on the main thread before any audio stream opens.
        _bootstrap_event("microphone_authorization_started")
        try:
            from .desktop_microphone import request_microphone_access
            authorization = request_microphone_access(observer=lambda event, **data:
                _bootstrap_event("microphone_" + event, **data))
        except BaseException as exc:
            authorization = "error"
            _bootstrap_event("microphone_authorization_failed", type=type(exc).__name__,
                stack=[dict(file=Path(frame.filename).name, line=frame.lineno, function=frame.name)
                       for frame in traceback.extract_tb(exc.__traceback__)])
        else:
            _bootstrap_event("microphone_authorization_finished", status=authorization)
        os.environ["HEBREW_LIVE_MICROPHONE_AUTHORIZATION"] = authorization
    from . import cli
    return cli.main()
