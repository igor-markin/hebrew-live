import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import patch

from hebrew_live.cli import desktop_model_download_keys
from hebrew_live.desktop_runtime import _bootstrap_event, _start_parent_watchdog, desktop_arguments
from hebrew_live.desktop_microphone import request_microphone_access
from scripts.prepare_desktop_proof_models import prepare


ROOT = Path(__file__).resolve().parents[1]


class DesktopPackagingTests(unittest.TestCase):
    def test_parent_watchdog_fires_when_controller_pipe_closes(self):
        read_fd, write_fd = os.pipe()
        disconnected = threading.Event()
        thread = _start_parent_watchdog(read_fd, disconnected.set)
        os.close(write_fd)
        self.assertTrue(disconnected.wait(1))
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_bootstrap_log_is_owner_only_and_privacy_filtered(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"HEBREW_LIVE_HOME": tmp}):
            _bootstrap_event("microphone_authorization_finished", status="authorized")
            path = Path(tmp) / "desktop-bootstrap.jsonl"
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(json.loads(path.read_text())["status"], "authorized")
            self.assertNotIn(str(Path(tmp)), path.read_text())

    def test_desktop_microphone_request_is_explicit_and_does_not_open_audio(self):
        class Device:
            status = 0
            requests = 0

            @classmethod
            def authorizationStatusForMediaType_(cls, media_type):
                self.assertEqual(media_type, "audio")
                return cls.status

            @classmethod
            def requestAccessForMediaType_completionHandler_(cls, media_type, completion):
                self.assertEqual(media_type, "audio")
                cls.requests += 1
                completion(True)

        api = type("AV", (), {
            "AVMediaTypeAudio": "audio",
            "AVCaptureDevice": Device,
            "AVAuthorizationStatusNotDetermined": 0,
            "AVAuthorizationStatusRestricted": 1,
            "AVAuthorizationStatusDenied": 2,
            "AVAuthorizationStatusAuthorized": 3,
        })
        self.assertEqual(request_microphone_access(api=api), "authorized")
        self.assertEqual(Device.requests, 1)
        Device.status = 2
        self.assertEqual(request_microphone_access(api=api), "denied")
        self.assertEqual(Device.requests, 1)

    def test_entry_calls_freeze_support_before_importing_runtime(self):
        entry = ROOT / "src" / "hebrew_live" / "desktop_entry.py"
        tree = ast.parse(entry.read_text())
        guarded = next(node for node in tree.body if isinstance(node, ast.If))
        freeze_index = next(index for index, node in enumerate(guarded.body)
                            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                            and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "freeze_support")
        imports = [node for node in ast.walk(guarded)
                   if isinstance(node, ast.ImportFrom)
                   and node.module in ("hebrew_live.desktop_runtime", "hebrew_live.desktop_control")]
        self.assertEqual({node.module for node in imports},
                         {"hebrew_live.desktop_runtime", "hebrew_live.desktop_control"})
        self.assertTrue(all(guarded.body[freeze_index].lineno < node.lineno for node in imports))

    def test_desktop_arguments_use_isolated_config_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            models = root / "models"; models.mkdir()
            home = root / "desktop-home"
            with patch.dict(os.environ, {}, clear=False):
                arguments = desktop_arguments({"data_home": str(home), "models": str(models), "logs": str(home / "records")})
                self.assertEqual(os.environ["HEBREW_LIVE_HOME"], str(home.resolve()))
            self.assertEqual(arguments[:4], ["--models", str(models.resolve()), "--log-dir", str((home / "records").resolve())])
            self.assertEqual(arguments[4:], ["listen", "--ui", "browser", "--start-paused"])
            self.assertFalse(home.exists())

    def test_desktop_inventory_is_exactly_three_pinned_components(self):
        path = ROOT / "src" / "hebrew_live" / "desktop_models.json"
        inventory = json.loads(path.read_text())
        self.assertEqual(desktop_model_download_keys(), [item["key"] for item in inventory["components"]])
        files = [item for component in inventory["components"] for item in component["files"]]
        self.assertEqual(inventory["total_bytes"], sum(item["bytes"] for item in files))
        self.assertEqual(len({(component["key"], item["path"])
                              for component in inventory["components"] for item in component["files"]}), len(files))
        for item in files:
            self.assertGreater(item["bytes"], 0)
            self.assertEqual(len(item["sha256"]), hashlib.sha256().digest_size * 2)

    def test_spec_bundles_prompt_source_required_by_retranslation(self):
        spec = (ROOT / "desktop" / "engine" / "HebrewLive.spec").read_text()
        self.assertIn('PACKAGE_ROOT / "translation.py"', spec)

    def test_proof_model_preparation_refuses_an_existing_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(FileExistsError, "destination already exists"):
                prepare(root, root)


if __name__ == "__main__":
    unittest.main()
