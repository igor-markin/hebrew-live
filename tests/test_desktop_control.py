import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

from hebrew_live.desktop_control import DesktopController, ProtocolError, ProtocolWriter, parse_message


class DesktopControlTests(unittest.TestCase):
    def test_protocol_requires_version_identity_command_and_object_payload(self):
        valid = parse_message(b'{"v":1,"id":"one","command":"preflight"}')
        self.assertEqual(valid["payload"], {})
        for line, reason in (
            (b'{}', "unsupported_protocol"),
            (b'{"v":1,"id":"","command":"preflight"}', "invalid_id"),
            (b'{"v":1,"id":"one","command":2}', "invalid_command"),
            (b'{"v":1,"id":"one","command":"x","payload":[]}', "invalid_payload"),
            (b'not-json', "invalid_json"),
        ):
            with self.subTest(reason=reason), self.assertRaisesRegex(ProtocolError, reason):
                parse_message(line)

    def test_protocol_writer_emits_only_versioned_json_lines(self):
        read_fd, write_fd = os.pipe()
        writer = ProtocolWriter(write_fd)
        os.close(write_fd)
        writer.event("ready", {"value": 1})
        writer.response("request", {"ok": True})
        writer.close()
        with os.fdopen(read_fd, "rb") as stream:
            values = [json.loads(line) for line in stream]
        self.assertEqual([item["v"] for item in values], [1, 1])
        self.assertEqual(values[0]["kind"], "event")
        self.assertEqual(values[1]["id"], "request")

    def test_preferences_write_existing_cli_settings_not_desktop_onboarding_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = Mock()
            with patch("hebrew_live.desktop_control.load_inventory", return_value={"components": []}):
                controller = DesktopController(root / "data", root / "models", writer)
            saved = controller.save_preferences({
                "ui_locale": "en", "target_language": "ru", "save_raw_audio": True,
            })
            self.assertEqual(saved["target_language"], "ru")
            self.assertTrue((root / ".local-settings" / "preferences.json").is_file())
            self.assertFalse((root / "data" / "desktop" / "preferences.json").exists())

    def test_diagnostics_excludes_paths_tokens_and_conversation_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = Mock()
            with patch("hebrew_live.desktop_control.load_inventory", return_value={"components": []}):
                controller = DesktopController(root / "private-data", root / "private-models", writer)
            report = json.dumps(controller.diagnostics())
            self.assertNotIn(str(root), report)
            self.assertNotIn("token", report.lower())
            self.assertNotIn("conversation", report.lower())

    def test_backend_state_exposes_capture_lifecycle_without_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch("hebrew_live.desktop_control.load_inventory", return_value={"components": []}):
                controller = DesktopController(root / "data", root / "models", Mock())
            controller.backend = Mock(poll=Mock(return_value=None))
            controller.backend_url = "http://127.0.0.1:1234/private/live/"
            response = MagicMock()
            response.__enter__.return_value = response
            response.read.return_value = json.dumps({
                "phase": "paused", "paused": True, "recording_started": True,
                "capture_active": True, "groups": [{"private": "speech"}],
            }).encode()
            with patch("hebrew_live.desktop_control.urllib.request.urlopen", return_value=response):
                state = controller.backend_state()
            self.assertTrue(state["recording_started"])
            self.assertTrue(state["capture_active"])
            self.assertNotIn("groups", state)


if __name__ == "__main__":
    unittest.main()
