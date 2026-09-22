import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PublicExportTests(unittest.TestCase):
    def test_desktop_sources_pass_the_public_tree_allowlist(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "public"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts" / "build_public_export.py"),
                    "--output",
                    str(destination),
                ],
                cwd=ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            result = json.loads(completed.stdout)
            self.assertGreater(result["files"], 0)
            self.assertTrue((destination / "desktop" / "electron" / "src" / "main.ts").is_file())


if __name__ == "__main__":
    unittest.main()
