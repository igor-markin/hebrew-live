import hashlib
import json
import multiprocessing
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from hebrew_live.cli import SPEC
from hebrew_live.desktop_download import DesktopDownloadError, verify_accurate_asr, verify_desktop_external, write_manifest
from hebrew_live.desktop_preflight import accurate_inventory, load_inventory
from hebrew_live.desktop_locations import resolve_model_locations
from hebrew_live.model_store import preparation_lock


def _hold_lock(folder: str, ready, release):
    with preparation_lock(Path(folder)):
        ready.set()
        release.wait(5)


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _tiny_inventory():
    return {"schema_version": 1, "total_bytes": 4, "components": [
        {"key": "translation", "label": "Translation", "folder": "milmmt-4b-4bit", "files": [
            {"path": "config.json", "bytes": 1, "sha256": _digest(b"a")},
            {"path": "model.safetensors", "bytes": 1, "sha256": _digest(b"b")},
        ]},
        {"key": "vad", "label": "VAD", "files": [{"path": "silero.onnx", "bytes": 2, "sha256": _digest(b"cd")}]},
    ]}


class DesktopModelStoreTests(unittest.TestCase):
    def test_optional_inventory_does_not_change_default_download(self):
        default = load_inventory()
        combined = accurate_inventory()
        self.assertEqual([item["key"] for item in default["components"]],
                         ["fast_asr", "translation", "vad"])
        self.assertEqual([item["key"] for item in combined["components"]][-1], "asr")
        self.assertEqual(combined["total_bytes"] - default["total_bytes"], 1613977880)
        self.assertEqual(combined["components"][-1]["revision"], SPEC["asr"]["revision"])

    def test_accurate_verification_is_pinned_and_ignores_unrelated_cli_damage(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            (models / "asr").mkdir()
            (models / "asr/config.json").write_bytes(b"config")
            (models / "asr/weights.safetensors").write_bytes(b"weights")
            optional = {"schema_version": 1, "total_bytes": 13, "components": [
                {"key": "asr", "label": "Whisper", "folder": "asr", "files": [
                    {"path": "config.json", "bytes": 6, "sha256": _digest(b"config")},
                    {"path": "weights.safetensors", "bytes": 7, "sha256": _digest(b"weights")},
                ]},
            ]}
            (models / "manifest.json").write_text(json.dumps({
                "schema_version": 2, "assets": ["translation", "vad", "asr", "asr_multilingual"], "spec": SPEC,
                "files": {"asr/config.json": _digest(b"config"),
                          "asr/weights.safetensors": _digest(b"weights"),
                          "asr-multilingual/broken.safetensors": _digest(b"missing")},
            }))
            with patch("hebrew_live.desktop_preflight.accurate_inventory", return_value=optional):
                verify_accurate_asr(models)
                (models / "asr/weights.safetensors").write_bytes(b"corrupt")
                with self.assertRaises(DesktopDownloadError):
                    verify_accurate_asr(models)

    def test_accurate_manifest_adds_only_verified_optional_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            inventory = _tiny_inventory()
            inventory["components"].append({"key": "asr", "label": "Whisper", "folder": "asr", "files": [
                {"path": "config.json", "bytes": 1, "sha256": _digest(b"x")},
                {"path": "weights.safetensors", "bytes": 1, "sha256": _digest(b"y")},
            ]})
            for name, value in (("milmmt-4b-4bit/config.json", b"a"),
                                ("milmmt-4b-4bit/model.safetensors", b"b"),
                                ("silero.onnx", b"cd"), ("asr/config.json", b"x"),
                                ("asr/weights.safetensors", b"y")):
                target = models / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
            with preparation_lock(models):
                write_manifest(models, inventory)
            saved = json.loads((models / "manifest.json").read_text())
            self.assertEqual(saved["assets"], ["translation", "vad", "asr"])
            self.assertEqual(saved["files"]["asr/weights.safetensors"], _digest(b"y"))

    def test_manifest_keeps_valid_cli_asr_and_ignores_corrupt_optional_asr(self):
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp)
            for name, value in (("milmmt-4b-4bit/config.json", b"a"),
                                ("milmmt-4b-4bit/model.safetensors", b"b"),
                                ("silero.onnx", b"cd"),
                                ("asr/config.json", b"e"),
                                ("asr/weights.safetensors", b"f")):
                target = models / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
            old = {"schema_version": 2, "assets": ["asr", "translation", "vad"],
                   "spec": SPEC, "files": {"asr/config.json": _digest(b"e"),
                                             "asr/weights.safetensors": _digest(b"f")}}
            (models / "manifest.json").write_text(json.dumps(old))
            with preparation_lock(models):
                write_manifest(models, _tiny_inventory())
            merged = json.loads((models / "manifest.json").read_text())
            self.assertIn("asr", merged["assets"])
            self.assertEqual(merged["files"]["asr/weights.safetensors"], _digest(b"f"))
            verify_desktop_external(models, _tiny_inventory())

            (models / "asr/weights.safetensors").write_bytes(b"broken")
            with preparation_lock(models):
                write_manifest(models, _tiny_inventory())
            merged = json.loads((models / "manifest.json").read_text())
            self.assertNotIn("asr", merged["assets"])
            self.assertNotIn("asr/weights.safetensors", merged["files"])
            self.assertEqual((models / "asr/weights.safetensors").read_bytes(), b"broken")
            verify_desktop_external(models, _tiny_inventory())

    def test_incompatible_shared_root_selects_persisted_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            shared = home / "models"
            shared.mkdir()
            (shared / "manifest.json").write_text('{"schema_version":99}')
            first = resolve_model_locations(home, shared, bundled=home / "bundle")
            self.assertEqual(first.external, home / "desktop" / "models")
            (shared / "manifest.json").write_text(json.dumps({
                "schema_version": 2, "assets": ["translation", "vad"], "spec": SPEC,
                "files": {"silero.onnx": _digest(b"cd")},
            }))
            second = resolve_model_locations(home, shared, bundled=home / "bundle")
            self.assertEqual(second.external, first.external)

    def test_corrupt_optional_cli_file_does_not_select_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            shared = home / "models"
            shared.mkdir()
            (shared / "manifest.json").write_text(json.dumps({
                "schema_version": 2, "assets": ["asr", "translation", "vad"], "spec": SPEC,
                "files": {"asr/weights.safetensors": _digest(b"expected")},
            }))
            selected = resolve_model_locations(home, shared, bundled=home / "bundle")
            self.assertEqual(selected.external, shared)

    def test_interrupted_download_resumes_in_selected_shared_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            shared = home / "models"
            first = resolve_model_locations(home, shared, bundled=home / "bundle")
            self.assertEqual(first.external, shared)
            partial = shared / "milmmt-4b-4bit" / "model.safetensors.part"
            partial.parent.mkdir(parents=True)
            partial.write_bytes(b"partial")
            again = resolve_model_locations(home, shared, bundled=home / "bundle")
            self.assertEqual(again.external, shared)
            self.assertEqual(partial.read_bytes(), b"partial")

            # A newly discovered, unclaimed model folder remains incompatible.
            other_home = home / "other"
            new = resolve_model_locations(other_home, shared, bundled=home / "bundle")
            self.assertEqual(new.external, other_home / "desktop" / "models")

    def test_cli_and_desktop_preparation_use_same_process_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            context = multiprocessing.get_context("spawn")
            ready, release = context.Event(), context.Event()
            child = context.Process(target=_hold_lock, args=(tmp, ready, release))
            child.start()
            try:
                self.assertTrue(ready.wait(5))
                cancelled = threading.Event()
                timer = threading.Timer(0.2, cancelled.set)
                timer.start()
                started = time.monotonic()
                with self.assertRaises(InterruptedError):
                    with preparation_lock(Path(tmp), cancelled.is_set):
                        self.fail("a second writer acquired the lock")
                self.assertGreaterEqual(time.monotonic() - started, 0.18)
                timer.join()
            finally:
                release.set()
                child.join(5)
                if child.is_alive():
                    child.terminate()
                    child.join(5)
            self.assertEqual(child.exitcode, 0)


if __name__ == "__main__":
    unittest.main()
