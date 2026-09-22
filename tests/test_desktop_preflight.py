import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from hebrew_live.desktop_preflight import REFERENCE_MEMORY_BYTES, check_computer, plan_model_space


def inventory(payload: bytes = b"model"):
    return {
        "schema_version": 1,
        "components": [{
            "key": "test",
            "folder": "component",
            "files": [{"path": "weights.bin", "bytes": len(payload),
                       "sha256": hashlib.sha256(payload).hexdigest()}],
        }],
    }


class DesktopPreflightTests(unittest.TestCase):
    def test_less_than_16_gib_is_a_warning_not_a_blocker(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch("hebrew_live.desktop_preflight.platform.system", return_value="Darwin"), \
             patch("hebrew_live.desktop_preflight.platform.machine", return_value="arm64"), \
             patch("hebrew_live.desktop_preflight.platform.mac_ver", return_value=("27.0", ("", "", ""), "")), \
             patch("hebrew_live.desktop_preflight._sysctl_uint64", return_value=REFERENCE_MEMORY_BYTES - 1), \
             patch("hebrew_live.desktop_preflight._memory_pressure_level", return_value=1), \
             patch("hebrew_live.desktop_preflight.os.getloadavg", return_value=(0.1, 0.1, 0.1)), \
             patch("hebrew_live.desktop_preflight.metal_available", return_value=True), \
             patch("hebrew_live.desktop_preflight.shutil.disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            result = check_computer(Path(tmp) / "models", inventory=inventory(), verify_hashes=False)
        self.assertTrue(result["compatible"])
        self.assertIn("memory_below_reference", {item["code"] for item in result["warnings"]})

    def test_current_load_warning_is_independent_of_installed_memory(self):
        with tempfile.TemporaryDirectory() as tmp, \
             patch("hebrew_live.desktop_preflight.platform.system", return_value="Darwin"), \
             patch("hebrew_live.desktop_preflight.platform.machine", return_value="arm64"), \
             patch("hebrew_live.desktop_preflight.platform.mac_ver", return_value=("27.0", ("", "", ""), "")), \
             patch("hebrew_live.desktop_preflight._sysctl_uint64", return_value=REFERENCE_MEMORY_BYTES), \
             patch("hebrew_live.desktop_preflight._memory_pressure_level", return_value=2), \
             patch("hebrew_live.desktop_preflight.os.getloadavg", return_value=(0.1, 0.1, 0.1)), \
             patch("hebrew_live.desktop_preflight.metal_available", return_value=True), \
             patch("hebrew_live.desktop_preflight.shutil.disk_usage", return_value=SimpleNamespace(free=100 * 1024**3)):
            result = check_computer(Path(tmp) / "models", inventory=inventory(), verify_hashes=False)
        self.assertIn("current_load_high", {item["code"] for item in result["warnings"]})

    def test_missing_verified_and_corrupt_files_change_required_download(self):
        payload = b"verified-model"
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / "models"
            missing = plan_model_space(models, inventory(payload), temporary_bytes=7, reserve_bytes=11)
            self.assertEqual(missing.download_bytes, len(payload))
            self.assertEqual(missing.required_free_bytes, len(payload) + 18)
            target = models / "component" / "weights.bin";target.parent.mkdir(parents=True)
            target.write_bytes(payload)
            verified = plan_model_space(models, inventory(payload), temporary_bytes=7, reserve_bytes=11)
            self.assertEqual(verified.download_bytes, 0)
            self.assertEqual(verified.files[0].state, "verified")
            target.write_bytes(b"broken")
            corrupt = plan_model_space(models, inventory(payload), temporary_bytes=7, reserve_bytes=11)
            self.assertEqual(corrupt.download_bytes, len(payload))
            self.assertEqual(corrupt.files[0].state, "corrupt")

    def test_partial_file_gets_credit_only_after_resume_is_confirmed(self):
        payload = b"0123456789"
        with tempfile.TemporaryDirectory() as tmp:
            models = Path(tmp) / "models"
            part = models / "component" / "weights.bin.part";part.parent.mkdir(parents=True);part.write_bytes(payload[:4])
            conservative = plan_model_space(models, inventory(payload), resumable_confirmed=False,
                                             temporary_bytes=0, reserve_bytes=0)
            resumed = plan_model_space(models, inventory(payload), resumable_confirmed=True,
                                        temporary_bytes=0, reserve_bytes=0)
            self.assertEqual(conservative.download_bytes, len(payload))
            self.assertEqual(resumed.download_bytes, len(payload) - 4)
            self.assertEqual(resumed.files[0].state, "partial")


if __name__ == "__main__":
    unittest.main()
