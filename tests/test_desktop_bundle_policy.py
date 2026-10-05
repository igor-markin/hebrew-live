import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from scripts.desktop_bundle_policy import public_bundle_datas, verify_source_manifest


class DesktopBundlePolicyTests(unittest.TestCase):
    def test_private_installer_metadata_and_excluded_runtime_do_not_ship(self):
        entries = [(name, "source", "DATA") for name in (
            "hebrew_live_cli-0.1.0a2.dist-info/direct_url.json",
            "tokenizers-0.23.2.dist-info/sboms/tokenizers.cyclonedx.json",
            "torch-2.14.0.dist-info/licenses/LICENSE",
            "some.dist-info/RECORD",
            "some.dist-info/METADATA",
            "some.dist-info/licenses/COPYING.LESSER",
            "certifi/cacert.pem",
        )]
        kept = {item[0] for item in public_bundle_datas(entries)}
        self.assertEqual(kept, {"some.dist-info/METADATA",
                                "some.dist-info/licenses/COPYING.LESSER", "certifi/cacert.pem"})

    def test_source_identity_detects_changed_input_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "source.py"
            path.write_text("value = 1\n")
            manifest = {"schema_version": 1, "candidate_version": "0.1.0-alpha.2",
                        "base_commit": "a" * 40, "uncommitted": True,
                        "source_tree_sha256": "b" * 64,
                        "files": [{"path": "source.py", "bytes": path.stat().st_size,
                                   "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
            manifest["source_tree_sha256"] = hashlib.sha256(json.dumps(
                manifest["files"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            self.assertTrue(verify_source_manifest(root, manifest)["uncommitted"])
            path.write_text("value = 2\n")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                verify_source_manifest(root, manifest)
            manifest["files"][0]["path"] = "../source.py"
            with self.assertRaisesRegex(ValueError, "inside the snapshot"):
                verify_source_manifest(root, manifest)
